"""
wake_word.py
喚醒詞「小黃小黃」偵測模組

策略：
  優先使用 Taiwan-Tongues-ASR 本地 Whisper 模型（離線、高精度台灣語音）
  備援使用 Vosk 離線辨識或 Google STT
"""

import os
import sys
import json
import threading
import numpy as np
import sounddevice as sd
import torch

# ── OpenCC 延遲導入（防止 DLL 載入失敗阻斷啟動）─────
try:
    from opencc import OpenCC
    OPENCC_AVAILABLE = True
except (ImportError, OSError):
    OPENCC_AVAILABLE = False
    print("[喚醒詞] ⚠️ OpenCC 無法載入（DLL 被封鎖或未安裝），簡繁轉換將跳過")

# ── 路徑設定 ──────────────────────────────────────────
_demo_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_demo_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

# ── Vosk 可用性檢查（作為 fallback）──────────────────
try:
    from vosk import Model as VoskModel, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

# ── SpeechRecognition（作為最終 fallback）─────────────
try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

# ── 引入整合後的 ASR 模組（延遲載入，不在 import 階段就載模型）────
ASR_AVAILABLE = False
model = None
processor = None

def _ensure_asr_loaded():
    """需要 ASR 時才載入模型，避免 import 階段就阻塞 30+ 秒"""
    global model, processor, ASR_AVAILABLE
    if ASR_AVAILABLE and model is not None:
        return True
    
    try:
        import speech.asr_tts
        speech.asr_tts._lazy_init_asr()
        model = speech.asr_tts.model
        processor = speech.asr_tts.processor
        ASR_AVAILABLE = True
        print("[喚醒詞] ASR 模型已載入")
        return True
    except Exception as err:
        print(f"[喚醒詞] ⚠️ ASR 載入失敗：{err}")
        return False

# ── 設定 ──────────────────────────────────────────────
WAKE_WORDS = ["小黃小黃", "小黃", "xiaohuang"]
SAMPLE_RATE = 16000
CHUNK_SECONDS = 3
ENERGY_THRESH = 0.01

# Vosk 模型路徑
VOSK_MODEL_PATHS = [
    os.path.join(_project_dir, "vosk-model-cn"),
    os.path.join(_project_dir, "vosk-model-small-cn-0.22"),
    os.path.join(_project_dir, "model"),
]
# ──────────────────────────────────────────────────────


def _find_vosk_model():
    """尋找 Vosk 模型資料夾"""
    for path in VOSK_MODEL_PATHS:
        if os.path.isdir(path):
            return path
    return None


class WakeWordDetector:
    """
    持續錄音並偵測喚醒詞，偵測到後呼叫 callback。

    辨識引擎優先級：
    1. Taiwan-Tongues-ASR（Whisper 本地模型，離線高精度）
    2. Vosk（離線輕量）
    3. Google STT（需網路，最終備援）
    """

    def __init__(self, callback, wake_words=None):
        self.callback = callback
        self.wake_words = [w.lower() for w in (wake_words or WAKE_WORDS)]
        self._running = False
        self._thread = None
        self.cc = OpenCC('s2twp') if OPENCC_AVAILABLE else None

        # Vosk 模型初始化
        self._vosk_model = None
        self._use_vosk = False
        if not ASR_AVAILABLE and VOSK_AVAILABLE:
            vosk_path = _find_vosk_model()
            if vosk_path:
                try:
                    self._vosk_model = VoskModel(vosk_path)
                    self._use_vosk = True
                    print(f"[喚醒詞] 使用 Vosk 離線辨識（模型：{os.path.basename(vosk_path)}）")
                except Exception as e:
                    print(f"[喚醒詞] Vosk 模型載入失敗：{e}")

        if not ASR_AVAILABLE and not self._use_vosk:
            print("[喚醒詞] 將使用 Google STT 作為最終備援（需網路）")

    # ── 公開方法 ──────────────────────────────────────

    def start(self):
        """背景執行喚醒詞偵測"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        print("[喚醒詞偵測] 已啟動，說「小黃小黃」來喚醒 AI")

    def stop(self):
        """停止偵測"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        print("[喚醒詞偵測] 已停止")

    def resume(self):
        """對話結束後恢復喚醒詞偵測"""
        # 確保舊執行緒已完全結束
        if self._thread and self._thread.is_alive():
            self._running = False
            self._thread.join(timeout=5)
        self.start()

    def listen_once_blocking(self, max_retries: int = 200) -> bool:
        """
        阻塞式等待一次喚醒詞。
        回傳 True 代表偵測成功，False 代表達到重試上限或麥克風異常。
        """
        print("[喚醒詞偵測] 等待喚醒詞...")
        consecutive_errors = 0
        max_consecutive_errors = 5

        for _ in range(max_retries):
            try:
                audio = self._record_chunk()
                if self._is_silent(audio):
                    continue

                text = self._transcribe(audio)
                if text is None:
                    continue

                if text == "__ERROR__":
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print("[喚醒詞偵測] 連續多次錯誤，停止監聽")
                        return False
                    continue

                consecutive_errors = 0
                if self._contains_wake_word(text):
                    return True

            except Exception as e:
                consecutive_errors += 1
                print(f"[喚醒詞偵測] 錯誤：{e}")
                if consecutive_errors >= max_consecutive_errors:
                    return False

        print("[喚醒詞偵測] 達到最大監聽次數，停止等待")
        return False

    # ── 內部：監聽迴圈 ────────────────────────────────

    def _listen_loop(self):
        """背景執行緒持續監聽"""
        while self._running:
            try:
                audio = self._record_chunk()
                if self._is_silent(audio):
                    continue

                text = self._transcribe(audio)
                if text and text != "__ERROR__" and self._contains_wake_word(text):
                    # 偵測到喚醒詞，暫停監聽並觸發 callback
                    self._running = False
                    print("[喚醒詞偵測] 喚醒詞偵測到，暫停監聽")
                    self.callback()
                    return  # 結束執行緒
            except Exception as e:
                if not self._running:
                    return  # 被外部 stop/resume 中斷，正常退出
                print(f"[喚醒詞] 監聽迴圈錯誤：{e}")

    # ── 內部：錄音 ────────────────────────────────────

    def _record_chunk(self) -> np.ndarray:
        """錄一段固定長度的音訊"""
        frames = int(SAMPLE_RATE * CHUNK_SECONDS)
        audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        sd.wait()
        return audio.flatten()

    def _is_silent(self, audio: np.ndarray) -> bool:
        """能量低於門檻視為靜音"""
        return float(np.abs(audio).mean()) < ENERGY_THRESH

    # ── 內部：語音辨識 ────────────────────────────────

    def _transcribe(self, audio: np.ndarray) -> str | None:
        """語音 → 文字，已修正型態衝突與 attention_mask 問題"""
        # 確保 ASR 模型已載入
        _ensure_asr_loaded()
        
        # 方式一：Taiwan-Tongues-ASR 本地模型
        if ASR_AVAILABLE and model is not None and processor is not None:
            try:
                _device = "cuda" if torch.cuda.is_available() else "cpu"
                inputs = processor(
                    audio,
                    sampling_rate=SAMPLE_RATE,
                    return_tensors="pt",
                    return_attention_mask=True
                )

                target_dtype = model.dtype
                input_features = inputs.input_features.to(device=_device, dtype=target_dtype)
                attention_mask = inputs.attention_mask.to(device=_device, dtype=torch.long)

                with torch.no_grad():
                    if _device == "cuda":
                        with torch.amp.autocast(device_type="cuda"):
                            predicted_ids = model.generate(
                                input_features,
                                attention_mask=attention_mask,
                                language="zh",
                                task="transcribe",
                                max_new_tokens=128,
                                no_repeat_ngram_size=3,
                                repetition_penalty=1.2,
                                num_beams=1
                            )
                    else:
                        predicted_ids = model.generate(
                            input_features,
                            attention_mask=attention_mask,
                            language="zh",
                            task="transcribe",
                            max_new_tokens=128,
                            no_repeat_ngram_size=3,
                            repetition_penalty=1.2,
                            num_beams=1
                        )

                raw_transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
                text = self.cc.convert(raw_transcription).strip() if self.cc else raw_transcription.strip()

                if text:
                    print(f"[喚醒詞] 聽到：{text}")
                return text or None

            except Exception as e:
                print(f"[喚醒詞] ASR 推論錯誤：{e}")

        # 方式二：Google STT fallback（需網路）
        if SR_AVAILABLE:
            try:
                import io
                import soundfile as sf
                recognizer = sr.Recognizer()
                buf = io.BytesIO()
                sf.write(buf, audio, SAMPLE_RATE, format="WAV")
                buf.seek(0)
                with sr.AudioFile(buf) as source:
                    audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data, language="zh-TW")
                print(f"[喚醒詞] 聽到（Google）：{text}")
                return text.lower()
            except Exception:
                return None

        return None

    def _contains_wake_word(self, text: str) -> bool:
        """檢查是否包含喚醒詞"""
        text_lower = text.lower()
        for word in self.wake_words:
            if word in text_lower:
                print(f"[喚醒詞] ✅ 匹配成功：{word}")
                return True
        return False


# ── 單獨測試 ──────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  喚醒詞偵測模組測試")
    print("  說「小黃小黃」來測試")
    print("  按 Ctrl+C 退出")
    print("=" * 50)

    def on_detected():
        print("\n🎉 喚醒詞偵測成功！")

    detector = WakeWordDetector(callback=on_detected)
    result = detector.listen_once_blocking(max_retries=30)
    print(f"結果：{'成功' if result else '超時'}")
