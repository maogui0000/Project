# voice_assistant.py
"""
voice_assistant.py
小黃語音助理 — Demo 專案核心整合模組

完整流程：
  說「小黃小黃」
    → 播放「有何吩咐」（三語同步合成並播放）
    → 錄音 → 台灣話 ASR (speech_tool.audio_to_text) → MemoryController + Ollama
    → 呼叫 國/台/客 TTS (speech_tool.text_to_speech_and_play) 播放回覆
    → 繼續對話，直到說「掰掰」
    → 恢復喚醒詞監聽
"""

import asyncio
import os
import sys
import tempfile
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

# ── 路徑設定，確保可以 import Demo 內的模組 ──────────
_demo_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_demo_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

# ── 引入專案內模組 ────────────────────────────────────
from speech.wake_word import WakeWordDetector
from core.memory_controller import MemoryController

# 🎯 引入語音辨識 + TTS 模組
from speech.asr_tts import (
    audio_to_text, 
    text_to_speech_and_play, 
    stream_speak,
    synthesize_and_play_sentence,
)

# 🎯 引入串流逐句 LLM 生成器
from core.ai_chat import ask_ollama_stream_sentences, system_prompt

# ── 設定 ──────────────────────────────────────────────
GREETING        = "有何吩咐"
FAREWELL_WORDS  = ["掰掰", "再見", "結束", "拜拜", "bye", "不用了"]
SILENT_MSG      = "我沒聽清楚，可以再說一次嗎？"
IDLE_MSG        = "好的，有需要再叫我小黃小黃喔"
MAX_TURNS       = 20       # 單次對話最多輪數
SILENT_RETRY    = 2        # 連續聽不到幾次後自動結束
RECORD_SECONDS  = 6        # 每次使用者說話錄音秒數
SAMPLE_RATE     = 16000
ENERGY_THRESH   = 0.008    # 靜音門檻
# ──────────────────────────────────────────────────────


class VoiceAssistant:
    def __init__(self):
        self.memory     = MemoryController()
        self.detector   = WakeWordDetector(callback=self._on_wake)
        self._lock      = threading.Lock()
        self._active    = False
        self.running    = False
        
        # 💡 ASR 與 TTS 模型初始化已封裝移至 speech_tool，此處不需手動載入模型
        print("[語音助理] 核心語音助理控制台初始化成功！")

    # ── 公開方法 ──────────────────────────────────────

    def start(self):
        """啟動語音助理（背景執行喚醒詞偵測）"""
        self.running = True
        self.detector.start()
        print("[語音助理] 已啟動，等待喚醒詞「小黃小黃」")

    def stop(self):
        """優雅關閉"""
        self.running = False
        self.detector.stop()
        print("[語音助理] 已關閉")

    def is_active(self) -> bool:
        """回傳是否正在對話中（供 API 查詢）"""
        return self._active

    # ── 喚醒回呼 ──────────────────────────────────────

    def _on_wake(self):
        """偵測到喚醒詞後觸發，在獨立執行緒執行對話"""
        with self._lock:
            if self._active:
                return   # 已在對話中，忽略重複觸發
            self._active = True

        print("[語音助理] 喚醒詞觸發！啟動對話模式")
        # 在獨立執行緒執行，不阻塞 FastAPI 事件迴圈
        t = threading.Thread(target=self._run_conversation, daemon=True)
        t.start()

    # ── 對話主流程 ────────────────────────────────────

    def _run_conversation(self):
        """一次完整對話：喚醒 → 多輪問答 → 結束 → 恢復監聽"""
        try:
            # 1. 喚醒回應
            self._speak(GREETING)

            silent_count = 0

            for _ in range(MAX_TURNS):
                # 2. 錄使用者語音
                audio = self._record_user()

                if audio is None or self._is_silent(audio):
                    silent_count += 1
                    if silent_count >= SILENT_RETRY:
                        self._speak(IDLE_MSG)
                        break
                    self._speak(SILENT_MSG)
                    continue

                silent_count = 0

                # 3. 呼叫 ASR
                user_text = self._transcribe(audio)
                if not user_text:
                    silent_count += 1
                    if silent_count >= SILENT_RETRY:
                        self._speak(IDLE_MSG)
                        break
                    self._speak(SILENT_MSG)
                    continue

                print(f"[使用者] {user_text}")

                # 4. 結束語檢查
                if any(w in user_text for w in FAREWELL_WORDS):
                    self._speak("好的，有需要再叫我")
                    break

                # 5. 串流對話 + 逐句 TTS 即時播放
                #    LLM 每產出一句就立即合成語音播放，不等全部生成完
                history_ctx  = self.memory.get_history_summary_text()
                full_prompt  = f"{history_ctx}長者最新說的話：{user_text}"
                
                print("[小黃] ", end="", flush=True)
                sentence_gen = ask_ollama_stream_sentences(full_prompt)
                ai_reply = stream_speak(sentence_gen)
                print()  # 換行

                # 6. 更新長短期記憶
                self.memory.update_memories(user_text, ai_reply)

        except Exception as e:
            print(f"[語音助理] 對話錯誤：{e}")
        finally:
            # 對話結束，重置狀態並恢復喚醒詞偵測
            with self._lock:
                self._active = False
            print("[語音助理] 對話結束，重新等待喚醒詞")
            if self.running:
                time.sleep(0.5)
                self.detector.resume()

    # ── 錄音 ──────────────────────────────────────────

    def _record_user(self) -> np.ndarray | None:
        """錄使用者說話，回傳 float32 numpy array"""
        try:
            print("[錄音] 請說話...")
            frames = int(SAMPLE_RATE * RECORD_SECONDS)
            audio  = sd.rec(frames, samplerate=SAMPLE_RATE,
                            channels=1, dtype="float32")
            sd.wait()
            return audio.flatten()
        except Exception as e:
            print(f"[錄音] 錯誤：{e}")
            return None

    def _is_silent(self, audio: np.ndarray) -> bool:
        return float(np.abs(audio).mean()) < ENERGY_THRESH

    # ── 語音辨識 ──────────────────────────────────────

    def _transcribe(self, audio: np.ndarray) -> str | None:
        """🎯 核心修正：將錄音暫存為 wav，並呼叫本機 ASR (防止型態衝突)"""
        try:
            # 使用 tempfile 建立一個臨時音檔
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = temp_file.name
            
            # 使用 soundfile 將錄好的 numpy array 寫入該臨時檔案
            sf.write(temp_path, audio, SAMPLE_RATE)
            
            # 呼叫整合好、防型態報錯的 ASR 辨識 Function
            transcription = audio_to_text(temp_path)
            
            # 辨識完成後，將臨時檔案刪除，保持硬碟乾淨
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            return transcription.strip() or None
            
        except Exception as e:
            print(f"[微調 ASR 推論錯誤]：{e}")
            return None

    # ── 國/台/客 三語同步合成與播放 ──────────────────

    def _speak(self, text: str):
        """短句即時播放（用於喚醒回應、錯誤提示等簡短句子）"""
        print(f"[小黃] {text}")
        try:
            # 短句直接用 stream_speak 走單句合成播放
            asyncio.run(synthesize_and_play_sentence(text, None, 0))
        except Exception as e:
            print(f"[TTS] 錯誤：{e}")

    # ── AI 對話（Ollama）──────────────────────────────

    def _ask_ollama(self, prompt: str) -> str:
        """非串流模式呼叫 Ollama（供 app.py API 使用）"""
        try:
            from ollama import chat
            from core.ai_chat import get_combined_system_prompt

            current_prompt = get_combined_system_prompt()
            response = chat(
                model="gemma2",
                messages=[
                    {"role": "system", "content": current_prompt},
                    {"role": "user",   "content": prompt},
                ],
                stream=False,
            )
            return response["message"]["content"].strip()
        except Exception as e:
            print(f"[Ollama] 錯誤：{e}")
            return "抱歉，我現在沒辦法回應，請稍後再試。"

    def _ask_ollama_streaming(self, prompt: str) -> str:
        """串流模式：LLM 逐句生成 + 即時 TTS 播放，回傳完整回覆"""
        try:
            sentence_gen = ask_ollama_stream_sentences(prompt)
            full_reply = stream_speak(sentence_gen)
            return full_reply
        except Exception as e:
            print(f"[Ollama 串流] 錯誤：{e}")
            return "抱歉，我現在沒辦法回應，請稍後再試。"


# ── 全域單例（供 app.py import）──────────────────────
_assistant_instance: VoiceAssistant | None = None

def get_assistant() -> VoiceAssistant:
    """取得全域唯一的 VoiceAssistant 實例"""
    global _assistant_instance
    if _assistant_instance is None:
        _assistant_instance = VoiceAssistant()
    return _assistant_instance


# ── 單獨測試 ──────────────────────────────────────────
if __name__ == "__main__":
    import signal

    assistant = get_assistant()
    assistant.start()

    print("\n按 Ctrl+C 結束\n")

    def _shutdown(sig, frame):
        assistant.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)

    # 讓主執行緒保持存活
    while True:
        time.sleep(1)