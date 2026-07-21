"""
config.py
雲湧智生 — 智慧長照關懷系統 統一配置中心

所有路徑、模型設定、API 設定集中管理，各模組只需 import config 即可取得所有設定。
支援 .env 檔案覆寫預設值。
"""

import os
from dotenv import load_dotenv

# ── 載入 .env 環境變數 ────────────────────────────────
load_dotenv()

# ── 專案根目錄 ────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════
# 模型路徑設定
# ═══════════════════════════════════════════════════════

# Taiwan-Tongues-ASR 本地模型路徑
ASR_MODEL_PATH = os.getenv(
    "ASR_MODEL_PATH",
    os.path.join(BASE_DIR, "models", "taiwan-tongues-asr")
)

# Whisper 微調權重路徑
WHISPER_WEIGHTS_PATH = os.getenv(
    "WHISPER_WEIGHTS_PATH",
    os.path.join(BASE_DIR, "speech", "taiwan_whisper.pt")
)

# Whisper 模型大小（備援模式）
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")

# ═══════════════════════════════════════════════════════
# ASR 效能優化設定
# ═══════════════════════════════════════════════════════

# 音訊前處理：最大允許秒數（超過會截斷）
ASR_MAX_AUDIO_SECONDS = int(os.getenv("ASR_MAX_AUDIO_SECONDS", "30"))

# 模型生成最大 token 數
ASR_MAX_NEW_TOKENS = int(os.getenv("ASR_MAX_NEW_TOKENS", "64"))

# 靜音裁剪閾值（RMS 低於此值視為靜音）
ASR_SILENCE_THRESHOLD = float(os.getenv("ASR_SILENCE_THRESHOLD", "0.01"))

# 靜音裁剪窗口大小（毫秒）
ASR_SILENCE_FRAME_MS = int(os.getenv("ASR_SILENCE_FRAME_MS", "30"))

# ═══════════════════════════════════════════════════════
# Ollama AI 對話設定
# ═══════════════════════════════════════════════════════

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2")

# ═══════════════════════════════════════════════════════
# TTS 語音合成設定
# ═══════════════════════════════════════════════════════

TTS_ENGINE = os.getenv("TTS_ENGINE", "edge")

TTS_VOICES = {
    "國語 (華語)": ("zh-TW-HsiaoChenNeural", "mandarin.mp3"),
    "台語 (閩南語)": ("zh-TW-HsiaoYuNeural", "taiwanese.mp3"),
    "客語 (客家語)": ("zh-TW-YunJheNeural", "hakka.mp3"),
}

# ═══════════════════════════════════════════════════════
# 伺服器設定
# ═══════════════════════════════════════════════════════

# FastAPI 後端
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8001"))

# LINE Bot
LINE_BOT_PORT = int(os.getenv("LINE_BOT_PORT", "5000"))
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TARGET_USER_ID = os.getenv("LINE_TARGET_USER_ID", "")

# ═══════════════════════════════════════════════════════
# 檔案路徑設定
# ═══════════════════════════════════════════════════════

# 資料目錄（4 個核心 JSON）
DATA_DIR = os.path.join(BASE_DIR, "data")

# 提示詞目錄
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
SYSTEM_PROMPT_PATH = os.path.join(PROMPTS_DIR, "system_prompt.txt")
ENVIRONMENTAL_PROMPTS_PATH = os.path.join(PROMPTS_DIR, "Environmental_Prompts.txt")
LIFE_RECORDS_PROMPT_PATH = os.path.join(PROMPTS_DIR, "life_records_prompt.txt")

# 天氣 API Key
WEATHER_API_KEY_PATH = os.path.join(BASE_DIR, "api_key.txt")

# 暫存音訊
LAST_SPEECH_PATH = os.path.join(BASE_DIR, "last_elder_speech.wav")

# ═══════════════════════════════════════════════════════
# 語音助理行為設定
# ═══════════════════════════════════════════════════════

WAKE_WORDS = ["小黃小黃", "小黃", "xiaohuang"]
FAREWELL_WORDS = ["掰掰", "再見", "結束", "拜拜", "bye", "不用了"]
MAX_CONVERSATION_TURNS = 20
SILENCE_RETRY_LIMIT = 2
RECORD_SECONDS = 6
SAMPLE_RATE = 16000
ENERGY_THRESHOLD = 0.008

# ═══════════════════════════════════════════════════════
# 天氣更新間隔（秒）
# ═══════════════════════════════════════════════════════

WEATHER_UPDATE_INTERVAL = int(os.getenv("WEATHER_UPDATE_INTERVAL", "21600"))  # 預設 6 小時

# ═══════════════════════════════════════════════════════
# 靜態資源
# ═══════════════════════════════════════════════════════

IMAGES_DIR = os.path.join(BASE_DIR, "images")
WEB_DIR = os.path.join(BASE_DIR, "web")
STATIC_HTML_FILES = {
    "index": os.path.join(WEB_DIR, "index.html"),
    "dashboard": os.path.join(WEB_DIR, "dashboard.html"),
    "admin": os.path.join(WEB_DIR, "admin.html"),
}
