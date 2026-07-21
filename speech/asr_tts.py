import asyncio
import os
import sys
import torch
import miniaudio
import numpy as np
import edge_tts
import warnings
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import transformers

# 抑制 transformers 的無害警告（max_new_tokens、SuppressTokens、tokenizer spaces）
warnings.filterwarnings("ignore", message=".*max_new_tokens.*max_length.*")
warnings.filterwarnings("ignore", message=".*custom logits processor.*")
warnings.filterwarnings("ignore", message=".*clean_up_tokenization_spaces.*")
transformers.logging.set_verbosity_error()  # 只顯示 ERROR 層級

# ── faster-whisper (CTranslate2) 加速引擎 ─────────────
try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    print("[tts_module] ⚠️ faster-whisper 未安裝，將使用 HuggingFace Transformers（較慢）")

# ── OpenCC 延遲導入（防止 DLL 載入失敗）─────────────
try:
    from opencc import OpenCC
    OPENCC_AVAILABLE = True
except (ImportError, OSError):
    OPENCC_AVAILABLE = False
    print("[tts_module] ⚠️ OpenCC 無法載入，簡繁轉換將跳過")

# 確保 Windows 輸出不亂碼
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# ==================== 全域與路徑設定 ====================
SAMPLE_RATE = 16000
VOICES = {
    "國語 (華語)": ("zh-TW-HsiaoChenNeural", "mandarin.mp3"),
    "台語 (閩南語)": ("zh-TW-HsiaoYuNeural", "taiwanese.mp3"),
    "客語 (客家語)": ("zh-TW-YunJheNeural", "hakka.mp3")
}

# 指向本地 ASR 模型目錄（從 config.py 讀取，避免硬編碼）
import sys as _sys
_tts_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_tts_dir, ".."))
if _project_dir not in _sys.path:
    _sys.path.insert(0, _project_dir)

try:
    import config
    LOCAL_MODEL_PATH = config.ASR_MODEL_PATH
except ImportError:
    LOCAL_MODEL_PATH = os.path.join(_project_dir, "models", "taiwan-tongues-asr")

# HuggingFace 模型名稱（用於 faster-whisper 自動下載 CT2 格式）
_HF_MODEL_NAME = "adi-gov-tw/Taiwan-Tongues-ASR-CE-pretrained-v2.0"

# CTranslate2 轉換後的模型存放路徑
_CT2_MODEL_PATH = os.path.join(_project_dir, "models", "taiwan-tongues-asr-ct2")

# ==================== ASR 引擎初始化 ====================

# faster-whisper 全域模型（優先使用）
_fw_model = None

# HuggingFace Transformers fallback
device = "cuda" if torch.cuda.is_available() else "cpu"
processor = None
model = None


def _convert_to_ct2():
    """將本地 HuggingFace 模型轉換為 CTranslate2 int8 格式（只需轉換一次）"""
    if os.path.exists(os.path.join(_CT2_MODEL_PATH, "model.bin")):
        return _CT2_MODEL_PATH  # 已經轉換過了

    print(f"⚙️ [faster-whisper] 首次使用，正在將模型轉換為 CTranslate2 int8 格式...")
    print(f"   來源：{LOCAL_MODEL_PATH}")
    print(f"   目標：{_CT2_MODEL_PATH}")

    try:
        from ctranslate2.converters import TransformersConverter
        converter = TransformersConverter(
            model_name_or_path=LOCAL_MODEL_PATH,
            copy_files=["tokenizer.json", "tokenizer_config.json", "processor_config.json"],
        )
        converter.convert(
            output_dir=_CT2_MODEL_PATH,
            quantization="int8",
            force=False,
        )
        print(f"✨ [成功] CTranslate2 模型轉換完成！\n")
        return _CT2_MODEL_PATH
    except Exception as e:
        print(f"⚠️ [CT2 轉換失敗]: {e}")
        return None


def _lazy_init_faster_whisper():
    """延遲載入 faster-whisper 模型（CTranslate2 int8 量化，CPU 快 4-8 倍）"""
    global _fw_model
    if _fw_model is not None:
        return True

    if not FASTER_WHISPER_AVAILABLE:
        return False

    try:
        # 先確保有 CT2 格式的模型
        ct2_path = _convert_to_ct2()
        if ct2_path is None:
            return False

        print(f"⚙️ [faster-whisper] 正在載入 CTranslate2 模型（int8 量化）...")
        print(f"   模型路徑：{ct2_path}")
        _fw_model = FasterWhisperModel(
            ct2_path,
            device="cpu",
            compute_type="int8",
            cpu_threads=os.cpu_count() or 4,
        )
        print("✨ [成功] faster-whisper 模型載入完成（int8 量化，CPU 加速）！\n")
        return True
    except Exception as e:
        print(f"⚠️ [faster-whisper] 載入失敗，將回退到 HuggingFace Transformers: {e}")
        _fw_model = None
        return False


def _lazy_init_asr():
    """內部輔助函式：載入 HuggingFace Transformers ASR 模型（fallback）"""
    global processor, model
    if processor is not None and model is not None:
        return

    if not os.path.exists(LOCAL_MODEL_PATH):
        raise FileNotFoundError(
            f"❌ 找不到本地模型目錄：{LOCAL_MODEL_PATH}。\n"
            f"請先運行 download_model.py 將模型儲存於該路徑。"
        )

    print(f"⚙️ 正在載入本地 ASR 模型 ({device.upper()})... 路徑：{LOCAL_MODEL_PATH}")
    try:
        processor = WhisperProcessor.from_pretrained(LOCAL_MODEL_PATH)
        if device == "cuda":
            model = WhisperForConditionalGeneration.from_pretrained(
                LOCAL_MODEL_PATH,
                torch_dtype=torch.float16
            ).to(device)
        else:
            model = WhisperForConditionalGeneration.from_pretrained(LOCAL_MODEL_PATH).to(device)
        print("✨ [成功] 本地 ASR 模型載入完成！\n")
    except Exception as e:
        print(f"❌ 本地 ASR 模型載入失敗: {e}")
        sys.exit(1)


# ==================== 功能 1：語音辨識 (ASR) ====================

def _preprocess_audio(speech: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    音訊前處理優化：
    1. 轉為單聲道（如果是多聲道）
    2. 重新取樣至 16kHz
    3. 靜音裁剪（去頭尾靜音段）
    4. 截斷超長音訊（避免模型處理過多 padding）
    """
    import time as _t
    _pp_start = _t.time()

    # 1. 轉單聲道
    if speech.ndim > 1:
        speech = speech.mean(axis=1)

    # 2. 重新取樣至 16kHz
    if sample_rate != SAMPLE_RATE:
        import librosa
        speech = librosa.resample(speech, orig_sr=sample_rate, target_sr=SAMPLE_RATE)

    # 3. 靜音裁剪 (VAD trim) — 去掉頭尾低能量靜音
    frame_size = int(SAMPLE_RATE * config.ASR_SILENCE_FRAME_MS / 1000)
    threshold = config.ASR_SILENCE_THRESHOLD

    # 從前方找到第一個有聲段
    start_idx = 0
    for i in range(0, len(speech) - frame_size, frame_size):
        frame_rms = np.sqrt(np.mean(speech[i:i + frame_size] ** 2))
        if frame_rms > threshold:
            start_idx = max(0, i - frame_size)  # 保留一小段 buffer
            break

    # 從後方找到最後一個有聲段
    end_idx = len(speech)
    for i in range(len(speech) - frame_size, frame_size, -frame_size):
        frame_rms = np.sqrt(np.mean(speech[i:i + frame_size] ** 2))
        if frame_rms > threshold:
            end_idx = min(len(speech), i + 2 * frame_size)  # 保留一小段 buffer
            break

    speech = speech[start_idx:end_idx]

    # 4. 截斷超長音訊
    max_samples = config.ASR_MAX_AUDIO_SECONDS * SAMPLE_RATE
    if len(speech) > max_samples:
        print(f"⚠️ [ASR] 音訊超過 {config.ASR_MAX_AUDIO_SECONDS}s，截斷前 {config.ASR_MAX_AUDIO_SECONDS}s")
        speech = speech[:max_samples]

    duration_after = len(speech) / SAMPLE_RATE
    print(f"⏱️ [ASR 前處理] {_t.time() - _pp_start:.3f}s → 有效音訊 {duration_after:.1f}s")
    return speech


def _asr_faster_whisper(audio_path: str) -> str:
    """
    使用 faster-whisper (CTranslate2 int8) 進行 ASR。
    CPU 上比 HuggingFace Transformers 快 4-5 倍。
    """
    import soundfile as sf
    import time as _t
    _start = _t.time()

    # 先做前處理（靜音裁剪+截斷），再傳入 numpy array
    speech, sample_rate = sf.read(audio_path, dtype='float32')
    speech = _preprocess_audio(speech, sample_rate)

    # 如果裁剪後太短，可能是純靜音
    if len(speech) < int(SAMPLE_RATE * 0.1):
        print("⚠️ [faster-whisper] 音訊太短，可能是純靜音")
        return ""

    _infer_start = _t.time()
    segments, info = _fw_model.transcribe(
        speech,
        language="zh",
        task="transcribe",
        beam_size=1,
        best_of=1,
        vad_filter=False,          # 已在前處理做過靜音裁剪，不再用 VAD
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
    )

    # 收集所有 segment 文字
    texts = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            texts.append(text)

    raw_text = "".join(texts)
    print(f"⏱️ [faster-whisper 推論] {_t.time() - _infer_start:.2f}s（總計含前處理 {_t.time() - _start:.2f}s）")
    return raw_text


def _asr_hf_transformers(audio_path: str) -> str:
    """
    使用 HuggingFace Transformers Whisper 進行 ASR（fallback）。
    包含前處理優化（靜音裁剪、動態 max_tokens）。
    """
    import soundfile as sf
    import time as _t

    _lazy_init_asr()
    if model is None or processor is None:
        return ""

    _total_start = _t.time()

    # 1. 讀取音訊
    speech, sample_rate = sf.read(audio_path, dtype='float32')

    # 2. 前處理：單聲道、重取樣、靜音裁剪、截斷
    speech = _preprocess_audio(speech, sample_rate)

    # 如果裁剪後太短（< 0.1s），可能是靜音或噪音
    if len(speech) < int(SAMPLE_RATE * 0.1):
        print("⚠️ [ASR] 音訊太短，可能是純靜音")
        return ""

    # 3. 提取特徵
    _feat_start = _t.time()
    inputs = processor(
        speech,
        sampling_rate=SAMPLE_RATE,
        return_tensors="pt",
        return_attention_mask=True
    )
    print(f"⏱️ [ASR 特徵提取] {_t.time() - _feat_start:.3f}s")

    # 4. 型態對齊
    target_dtype = model.dtype
    input_features = inputs.input_features.to(device=device, dtype=target_dtype)
    attention_mask = inputs.attention_mask.to(device=device, dtype=torch.long)

    # 5. 動態 max_new_tokens
    audio_duration = len(speech) / SAMPLE_RATE
    dynamic_max_tokens = min(
        config.ASR_MAX_NEW_TOKENS,
        max(20, int(audio_duration * 3.5))
    )

    # 6. 模型推論
    _infer_start = _t.time()
    with torch.no_grad():
        if device == "cuda":
            with torch.amp.autocast(device_type="cuda"):
                predicted_ids = model.generate(
                    input_features,
                    attention_mask=attention_mask,
                    language="zh",
                    task="transcribe",
                    max_new_tokens=dynamic_max_tokens,
                    no_repeat_ngram_size=3,
                    repetition_penalty=1.2,
                    num_beams=1,
                    condition_on_prev_tokens=False,
                )
        else:
            predicted_ids = model.generate(
                input_features,
                attention_mask=attention_mask,
                language="zh",
                task="transcribe",
                max_new_tokens=dynamic_max_tokens,
                no_repeat_ngram_size=3,
                repetition_penalty=1.2,
                num_beams=1,
                condition_on_prev_tokens=False,
            )
    print(f"⏱️ [HF 模型推論] {_t.time() - _infer_start:.2f}s（max_tokens={dynamic_max_tokens}）")

    raw_text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
    print(f"⏱️ [HF ASR 總計] {_t.time() - _total_start:.2f}s")
    return raw_text


def audio_to_text(audio_path: str) -> str:
    """
    將音訊檔案轉換為文字。
    優先使用 faster-whisper (CTranslate2 int8)，僅在例外時 fallback 到 HuggingFace Transformers。
    """
    import time as _t
    _total_start = _t.time()

    raw_text = ""
    used_faster_whisper = False

    # 優先嘗試 faster-whisper（快 4-5 倍）
    if FASTER_WHISPER_AVAILABLE and _lazy_init_faster_whisper():
        try:
            raw_text = _asr_faster_whisper(audio_path)
            used_faster_whisper = True  # 即使結果為空也算成功（可能真的沒語音）
        except Exception as e:
            print(f"⚠️ [faster-whisper] 推論失敗，回退到 HF Transformers: {e}")
            used_faster_whisper = False

    # 僅在 faster-whisper 不可用或拋出例外時才 fallback
    if not used_faster_whisper:
        try:
            raw_text = _asr_hf_transformers(audio_path)
        except Exception as e:
            print(f"❌ [HF ASR] 推論失敗: {e}")
            return ""

    # 簡繁轉換
    if raw_text and OPENCC_AVAILABLE:
        cc = OpenCC('s2twp')
        raw_text = cc.convert(raw_text)

    result = raw_text.strip()
    print(f"⏱️ [ASR 總計] {_t.time() - _total_start:.2f}s → 「{result}」")
    return result

# ==================== 功能 2：多語合成與播放 (TTS) ====================

async def play_audio(file_path):
    """播放音檔的輔助函式"""
    try:
        stream = miniaudio.stream_file(file_path)
        with miniaudio.PlaybackDevice() as dev:
            dev.start(stream)
            while stream.num_frames_pending > 0:
                pass
    except Exception as e:
        print(f"⚠️ 播放 {file_path} 時發生問題：{e}")

async def synthesize_voice(text, voice_name, output_file, label):
    """單一語音合成任務"""
    try:
        print(f"⚡ 正在合成【{label}】...")
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(output_file)
        return True
    except Exception as e:
        print(f"❌ 【{label}】合成失敗: {e}")
        return False

async def text_to_speech_and_play(text: str) -> dict:
    """
    將文字並行合成國、台、客三語音檔，並自動依序播放。
    
    :param text: 要合成的文字
    :return: 包含各語言音檔路徑的字典
    """
    if not text.strip():
        print("⚠️ 輸入文字為空，取消合成。")
        return {}

    # 建立三個語言的並行合成任務
    tasks = []
    for label, (voice_name, filename) in VOICES.items():
        tasks.append(synthesize_voice(text, voice_name, filename, label))
        
    print("\n🚀 開始並行合成中...")
    await asyncio.gather(*tasks)
    print("✨ 合成完成！\n")
    
    # 依序播放
    for label, (_, filename) in VOICES.items():
        if os.path.exists(filename):
            print(f"🔊 播放【{label}】中...")
            await play_audio(filename)
            await asyncio.sleep(0.5)  # 播放完稍微停頓一下
            
    return {label: filename for label, (_, filename) in VOICES.items()}


# ==================== 功能 3：逐句即時合成與播放 (Streaming TTS) ====================

# 預設使用台語語音進行即時播放
DEFAULT_STREAM_VOICE = "zh-TW-HsiaoChenNeural"  # 國語
DEFAULT_STREAM_VOICE_TW = "zh-TW-HsiaoYuNeural"  # 台語

async def synthesize_and_play_sentence(text: str, voice_name: str = None, sentence_index: int = 0):
    """
    合成單句語音並立即播放（用於串流 TTS）。
    
    :param text: 要合成的單句文字
    :param voice_name: edge-tts 語音名稱（預設台語）
    :param sentence_index: 句子序號（用於產生不重複的暫存檔名）
    """
    if not text.strip():
        return
    
    voice = voice_name or DEFAULT_STREAM_VOICE
    # 用序號避免檔案衝突
    temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"_stream_tts_{sentence_index}.mp3")
    
    try:
        # 合成
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(temp_file)
        
        # 播放
        if os.path.exists(temp_file):
            await play_audio(temp_file)
            # 播放完成後清理暫存檔
            try:
                os.remove(temp_file)
            except OSError:
                pass
    except Exception as e:
        print(f"⚠️ [串流TTS] 句子合成播放失敗: {e}")


def stream_speak(sentence_generator, voice_name: str = None):
    """
    同步接口：接收一個逐句生成器，每產出一句就即時合成播放。
    
    適用於 voice_assistant.py 的主對話迴圈（非 async 環境）。
    
    用法：
        from AI_Chat import ask_ollama_stream_sentences
        from tts_module.main import stream_speak
        
        sentences = ask_ollama_stream_sentences("你好嗎")
        full_reply = stream_speak(sentences)
    
    :param sentence_generator: 一個 yield 句子字串的生成器
    :param voice_name: edge-tts 語音名稱
    :return: 完整的 AI 回覆文字（所有句子串接）
    """
    full_text = ""
    
    async def _run():
        nonlocal full_text
        idx = 0
        for sentence in sentence_generator:
            full_text += sentence
            print(f"[TTS 串流] 第{idx+1}句：{sentence}")
            await synthesize_and_play_sentence(sentence, voice_name, idx)
            idx += 1
    
    asyncio.run(_run())
    return full_text


async def stream_speak_async(sentence_generator, voice_name: str = None):
    """
    非同步接口：同 stream_speak 但用於 async 環境（如 FastAPI）。
    
    :param sentence_generator: 一個 yield 句子字串的生成器
    :param voice_name: edge-tts 語音名稱
    :return: 完整的 AI 回覆文字
    """
    full_text = ""
    idx = 0
    for sentence in sentence_generator:
        full_text += sentence
        await synthesize_and_play_sentence(sentence, voice_name, idx)
        idx += 1
    return full_text


async def synthesize_sentence_to_bytes(text: str, voice_name: str = None) -> bytes:
    """
    合成單句語音並回傳 bytes（用於 Web API 串流傳輸給前端）。
    
    :param text: 要合成的單句文字
    :param voice_name: edge-tts 語音名稱
    :return: MP3 音訊的 bytes 資料
    """
    if not text.strip():
        return b""
    
    voice = voice_name or DEFAULT_STREAM_VOICE
    temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"_api_tts_{id(text)}.mp3")
    
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(temp_file)
        
        if os.path.exists(temp_file):
            with open(temp_file, "rb") as f:
                audio_bytes = f.read()
            os.remove(temp_file)
            return audio_bytes
    except Exception as e:
        print(f"⚠️ [API TTS] 合成失敗: {e}")
    
    return b""