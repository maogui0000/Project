# app.py
"""
雲湧智生 — 智慧長照關懷系統 後端 API 伺服器
整合語音辨識 (ASR)、語音合成 (TTS)、AI 對話、生活摘要、LINE Bot 推播

資料層：使用 data_manager.DataManager 統一存取 4 個 JSON 檔案
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from contextlib import asynccontextmanager
import asyncio
import json
import os
import threading
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

# ── 統一配置中心 ─────────────────────────────────────
import config

# ── 統一資料存取層 ───────────────────────────────────
from core.data_manager import DataManager

# ── 引入各功能模組 ───────────────────────────────────
import services.ai_summary
from core.voice_assistant import get_assistant

# ── 語音辨識與合成 ───────────────────────────────────
import edge_tts
from speech.asr_tts import audio_to_text, VOICES, synthesize_sentence_to_bytes

# ── 語音情緒辨識 ─────────────────────────────────────
from speech.emotion_recognition import recognize_emotion, log_emotion, get_emotion_summary
from services.weather_cron import update_emotion_in_prompt

# ── 串流 LLM 逐句生成 ───────────────────────────────
from core.ai_chat import ask_ollama_stream_sentences


# ═══════════════════════════════════════════════════════
# FastAPI 初始化
# ═══════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 50)
    print("  雲湧智生 — 智慧長照關懷系統 後端已啟動")
    print(f"  API 伺服器：http://{config.API_HOST}:{config.API_PORT}")
    print(f"  AI 模型：{config.BEDROCK_MODEL_ID}")
    print(f"  資料目錄：data/")
    print("=" * 50)
    
    # 預載 ASR 模型（避免第一次請求時等太久）
    print("[啟動] 預載 ASR 語音辨識模型...")
    try:
        from speech.asr_tts import _lazy_init_faster_whisper, FASTER_WHISPER_AVAILABLE
        if FASTER_WHISPER_AVAILABLE:
            _lazy_init_faster_whisper()
        else:
            from speech.asr_tts import _lazy_init_asr
            _lazy_init_asr()
    except Exception as e:
        print(f"⚠️ ASR 預載失敗（首次請求時會再嘗試）: {e}")
    
    yield
    print("[app] 後端 API 門戶已關閉")

app = FastAPI(
    title="雲湧智生 — 智慧長照關懷系統 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全域 DataManager 實例（已移除，各 API 端點會依 elder_id 動態建立）──


# ═══════════════════════════════════════════════════════
# 🔒 安全性：elder_id 驗證（防目錄遍歷）
# ═══════════════════════════════════════════════════════
import re as _re

_VALID_ELDER_ID_PATTERN = _re.compile(r'^elder_[a-zA-Z0-9]{6,20}$')

def _validate_elder_id(elder_id: str) -> str:
    """
    驗證 elder_id 格式，防止目錄遍歷攻擊。
    合法格式：elder_ + 6~20位英數字（如 elder_ms5tr8ljjrk6）
    """
    if not elder_id or not _VALID_ELDER_ID_PATTERN.match(elder_id):
        raise HTTPException(status_code=400, detail="無效的使用者 ID")
    return elder_id


# ═══════════════════════════════════════════════════════
# 🔒 Session Token 驗證（防止未授權存取其他使用者資料）
# ═══════════════════════════════════════════════════════
import secrets
import hashlib as _hashlib

# 存儲已發出的 session token: {token_hash: elder_id}
_active_sessions: dict = {}

def _generate_session_token(elder_id: str) -> str:
    """為註冊/登入成功的使用者生成 session token"""
    token = secrets.token_hex(32)  # 64 字元隨機 token
    token_hash = _hashlib.sha256(token.encode()).hexdigest()
    _active_sessions[token_hash] = elder_id
    return token


def _verify_session(request) -> str:
    """
    從請求的 Authorization header 或 query 中驗證 session token。
    驗證通過回傳 elder_id，失敗拋出 401。
    """
    # 從 header 取得 token
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    
    # 備用：從 query 參數取得（供前端 EventSource 使用）
    if not token:
        token = request.query_params.get("token", "")
    
    if not token:
        raise HTTPException(status_code=401, detail="未提供存取憑證，請先登入")
    
    token_hash = _hashlib.sha256(token.encode()).hexdigest()
    elder_id = _active_sessions.get(token_hash)
    
    if not elder_id:
        raise HTTPException(status_code=401, detail="存取憑證無效或已過期，請重新登入")
    
    return elder_id


# ═══════════════════════════════════════════════════════
# 🔒 台灣身分證字號驗證（含檢查碼驗算）
# ═══════════════════════════════════════════════════════

def _validate_tw_id_number(id_number: str) -> bool:
    """
    驗證台灣身分證字號格式與檢查碼是否正確。
    格式：1英文字母 + 9位數字，最後一位為檢查碼。
    """
    if not id_number:
        return True  # 空值不驗證（選填）
    
    id_number = id_number.strip().upper()
    
    # 基本格式檢查
    if not _re.match(r'^[A-Z][12]\d{8}$', id_number):
        return False
    
    # 英文字母對應數值表（A=10, B=11, ..., Z=35；依縣市編碼）
    letter_map = {
        'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14, 'F': 15, 'G': 16,
        'H': 17, 'I': 34, 'J': 18, 'K': 19, 'L': 20, 'M': 21, 'N': 22,
        'O': 35, 'P': 23, 'Q': 24, 'R': 25, 'S': 26, 'T': 27, 'U': 28,
        'V': 29, 'W': 32, 'X': 30, 'Y': 31, 'Z': 33,
    }
    
    # 將英文字母轉為兩位數字
    letter_value = letter_map.get(id_number[0])
    if letter_value is None:
        return False
    
    # 計算檢查碼
    # 首位字母拆為十位和個位
    n1 = letter_value // 10
    n2 = letter_value % 10
    
    # 加權計算：n1*1 + n2*9 + d1*8 + d2*7 + d3*6 + d4*5 + d5*4 + d6*3 + d7*2 + d8*1 + d9(檢查碼)*1
    digits = [int(c) for c in id_number[1:]]
    weights = [8, 7, 6, 5, 4, 3, 2, 1, 1]
    
    total = n1 + n2 * 9
    for i, d in enumerate(digits):
        total += d * weights[i]
    
    # 檢查碼：total % 10 == 0 表示合法
    return total % 10 == 0


# ═══════════════════════════════════════════════════════
# 🔒 輸入驗證：防注入、違禁字檢查、資料清洗
# ═══════════════════════════════════════════════════════

# 違禁字/危險模式（防 SQL 注入、XSS、命令注入、路徑注入）
_DANGEROUS_PATTERNS = _re.compile(
    r'(<script|javascript:|on\w+\s*=|'       # XSS
    r';\s*(rm|cat|ls|wget|curl|bash|sh)\s|'   # 命令注入
    r'\b(DROP|DELETE|INSERT|UPDATE|SELECT|ALTER|CREATE|EXEC|UNION)\b.*\b(TABLE|FROM|INTO|SET|WHERE|DATABASE|ALL)\b|'  # SQL 注入
    r'\b(DROP\s+TABLE|DROP\s+DATABASE|DELETE\s+FROM|INSERT\s+INTO)\b|'  # SQL 直接語句
    r'\.\./|/etc/|/proc/|/dev/)',             # 路徑遍歷
    _re.IGNORECASE
)

# 允許的字元模式（中文、英數、常見標點）
_SAFE_TEXT_PATTERN = _re.compile(
    r'^[\u4e00-\u9fff\u3400-\u4dbf\uF900-\uFAFF'  # 中文
    r'a-zA-Z0-9'                                     # 英數
    r'\s，。、！？；：「」（）\-\.\,\!\?\;\:\'\"\(\)\[\]\/@\#\$\%\&\*\+\=\~'  # 常見標點
    r']*$'
)

def _sanitize_input(text: str, field_name: str = "欄位", max_length: int = 200) -> str:
    """
    清洗使用者輸入：
    1. 去除首尾空白
    2. 限制長度
    3. 檢查危險模式（注入攻擊）
    4. 移除不安全字元
    """
    if text is None:
        return ""
    
    text = str(text).strip()
    
    # 長度限制
    if len(text) > max_length:
        raise HTTPException(status_code=400, detail=f"「{field_name}」超過最大長度 {max_length} 字")
    
    # 檢查危險模式
    if _DANGEROUS_PATTERNS.search(text):
        raise HTTPException(status_code=400, detail=f"「{field_name}」包含不允許的內容")
    
    # 移除 HTML 標籤
    text = _re.sub(r'<[^>]+>', '', text)
    
    return text


def _sanitize_list_input(items: list, field_name: str = "欄位", max_items: int = 20, max_item_length: int = 50) -> list:
    """清洗列表輸入"""
    if not items:
        return []
    if len(items) > max_items:
        raise HTTPException(status_code=400, detail=f"「{field_name}」項目數超過上限 {max_items}")
    return [_sanitize_input(item, field_name, max_item_length) for item in items if item and item.strip()]


def _validate_registration_input(req) -> dict:
    """
    完整驗證註冊輸入資料，回傳清洗後的安全資料。
    確認沒有違禁字才能讓使用者通過。
    """
    errors = []
    
    # 必填欄位驗證
    name = _sanitize_input(req.name, "姓名", 20)
    if not name:
        errors.append("姓名為必填")
    
    nickname = _sanitize_input(req.nickname, "暱稱", 20)
    if not nickname:
        errors.append("暱稱為必填")
    
    gender = req.gender.strip() if req.gender else ""
    if gender not in ("male", "female"):
        errors.append("性別為必填（male 或 female）")
    
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))
    
    # 選填欄位清洗
    clean = {
        "name": name,
        "nickname": nickname,
        "gender": gender,
        "age": req.age if req.age and 0 < req.age < 150 else None,
        "location": _sanitize_input(req.location, "居住地", 50),
        "id_number": req.id_number.strip() if req.id_number else "",
        "ec_name": _sanitize_input(req.ec_name, "聯絡人姓名", 20),
        "ec_relationship": _sanitize_input(req.ec_relationship, "關係", 10),
        "ec_phone": _sanitize_input(req.ec_phone, "電話", 20),
        "chronic_diseases": _sanitize_list_input(req.chronic_diseases, "慢性疾病"),
        "current_medications": _sanitize_list_input(req.current_medications, "目前用藥"),
        "drug_allergies": _sanitize_list_input(req.drug_allergies, "藥物過敏"),
        "food_allergies": _sanitize_list_input(req.food_allergies, "食物過敏"),
        "mobility": _sanitize_input(req.mobility, "行動能力", 20),
        "dietary_restrictions": _sanitize_list_input(req.dietary_restrictions, "飲食禁忌"),
        "has_dementia": bool(req.has_dementia),
        "has_wandering_history": bool(req.has_wandering_history),
        "care_notes": _sanitize_input(req.care_notes, "照護備註", 500),
    }
    
    # 電話格式驗證（如果有填）
    if clean["ec_phone"] and not _re.match(r'^[\d\-\+\(\)\s]{7,20}$', clean["ec_phone"]):
        raise HTTPException(status_code=400, detail="聯絡人電話格式不正確")
    
    # 身分證格式驗證（台灣身分證：含檢查碼驗算）
    if clean["id_number"] and not _validate_tw_id_number(clean["id_number"]):
        raise HTTPException(status_code=400, detail="身分證字號不正確，請確認輸入無誤")
    
    return clean


# ═══════════════════════════════════════════════════════
# 📦 Session 閒置計時器（觸發背景記憶分析）
# ═══════════════════════════════════════════════════════
from core.data_manager import SESSION_IDLE_TIMEOUT_SECONDS

# 每個 elder 的閒置計時器狀態
_session_idle_timers: dict = {}  # {elder_id: asyncio.Task}
_session_pending_analysis: dict = {}  # {elder_id: [{"user": ..., "ai": ...}, ...]}
_session_analysis_running: dict = {}  # {elder_id: bool} — 背景分析是否正在執行


async def _trigger_session_end_analysis(elder_id: str):
    """
    Session 結束觸發的一次性背景記憶分析。
    依據 demo.md 規格：取消每輪立刻分析，改為 Session 結束或閒置超過 2 分鐘時異步執行。
    """
    import time as _bt
    _bg_start = _bt.time()
    
    pending = _session_pending_analysis.pop(elder_id, [])
    if not pending:
        return
    
    _session_analysis_running[elder_id] = True
    print(f"🧠 [Session 分析] 長者 {elder_id} 閒置超時/Session 結束，開始背景記憶分析（{len(pending)} 輪對話）")
    
    try:
        elder_dm = DataManager(elder_id=elder_id)
        
        # 1. 記憶分析（健康、用藥偵測）— 逐輪分析
        for turn in pending:
            try:
                assistant = get_assistant()
                # 確保 MemoryController 使用正確的 elder_id
                if assistant.memory.dm is None or assistant.memory._elder_id != elder_id:
                    assistant.memory.set_elder_id(elder_id)
                assistant.memory.update_memories(turn["user"], turn["ai"])
            except Exception as e:
                print(f"⚠️ [Session 分析] update_memories 失敗: {e}")
        
        # 2. AI 精準摘要（整合所有待分析對話，一次性生成）
        combined_chat = "\n".join([
            f"長者說：{t['user']}\nAI回覆：{t['ai']}" for t in pending
        ])
        try:
            ai_result = services.ai_summary.get_elder_daily_summary(
                current_chat=combined_chat
            )
            summary_text = ai_result.get("overallSummary", "")
            structured = ai_result.get("structuredData", {})
            metrics = {}
            if structured.get("diet"):
                metrics["diet"] = structured["diet"]
            if structured.get("sleep"):
                metrics["sleep"] = structured["sleep"]
            if structured.get("activity"):
                metrics["activity"] = structured["activity"]
            # 用藥同步：如果摘要提到了服藥，確保 metrics 也更新
            if structured.get("medication"):
                med_text = structured["medication"]
                if "服" in med_text or "吃" in med_text:
                    metrics["medication_taken"] = True
                    # 從摘要文字中提取藥名
                    _med_names = ["高血壓藥", "降血壓藥", "血壓藥", "降血糖藥", "血糖藥", "止痛藥", "安眠藥", "心臟藥", "胃藥"]
                    found_name = "藥物"
                    for mn in _med_names:
                        if mn in med_text:
                            found_name = mn
                            break
                    metrics["medication_name"] = found_name
            if summary_text:
                elder_dm.update_today_summary(summary_text, metrics)
                broadcast_event({"type": "summary_updated", "elder_id": elder_id, "summary": summary_text})
        except Exception as e:
            print(f"⚠️ [Session 分析] AI 摘要失敗: {e}")
        
        # 3. 更新環境提示詞中的情緒區塊
        try:
            update_emotion_in_prompt()
        except Exception:
            pass
        
    except Exception as e:
        print(f"🚨 [Session 分析] 整體失敗: {e}")
    finally:
        _session_analysis_running[elder_id] = False
        
        # Session 分析完成後，即時推播 LINE 通知
        try:
            _send_line_session_summary(elder_id)
        except Exception as e:
            print(f"⚠️ [LINE 即時推播] 失敗: {e}")
        
        print(f"⏱️ [Session 分析] 長者 {elder_id} 背景分析完成：{_bt.time() - _bg_start:.2f}s")


def _send_line_session_summary(elder_id: str):
    """Session 分析完成後即時推播 LINE 通知（包含 5 個項目）"""
    from services.weather_cron import _send_line_push
    
    try:
        elder_dm = DataManager(elder_id=elder_id)
        dashboard = elder_dm.get_dashboard_logs()
        summary = dashboard.get("today_summary", {})
        summary_text = summary.get("text", "")
        metrics = summary.get("metrics", {})
        
        if not summary_text and not metrics:
            return
        
        # 讀取長者名稱
        profile = elder_dm.get_profile()
        elder_name = profile.get("personal_info", {}).get("nickname") or profile.get("personal_info", {}).get("name") or elder_id
        
        # 組裝 5 個項目
        diet = metrics.get("diet", "")
        activity = metrics.get("activity", "")
        sleep = metrics.get("sleep", "")
        medication = metrics.get("medication", "")
        emotion = metrics.get("emotion", "")
        emotion_reason = metrics.get("emotion_reason", "")
        voice_emotion = metrics.get("voice_emotion", "")
        
        # 情緒顯示（文字+語音綜合）
        emotion_display = ""
        if emotion and emotion != "未檢測":
            emotion_display = f"{emotion}"
            if emotion_reason:
                emotion_display += f"（{emotion_reason[:20]}）"
        elif voice_emotion:
            emotion_display = f"{voice_emotion}（語音偵測）"
        
        message = f"📋 【{elder_name} 互動更新】\n━━━━━━━━━━━\n"
        
        if summary_text:
            message += f"📝 {summary_text}\n\n"
        
        message += f"🍚 飲食：{diet or '未提及'}\n"
        message += f"🏃 活動：{activity or '未提及'}\n"
        message += f"😴 睡眠：{sleep or '未提及'}\n"
        message += f"💊 用藥：{medication or '未提及'}\n"
        message += f"🎭 情緒：{emotion_display or '未檢測'}"
        
        _send_line_push(message)
        print(f"✅ [LINE 即時推播] 已推送 {elder_name} 的互動摘要")
    except Exception as e:
        print(f"⚠️ [LINE 即時推播] 組裝或發送失敗: {e}")


async def _session_idle_countdown(elder_id: str):
    """閒置計時器：等待 2 分鐘，若未被重置則觸發 Session 結束分析"""
    try:
        await asyncio.sleep(SESSION_IDLE_TIMEOUT_SECONDS)
        # 超時，觸發背景分析
        await _trigger_session_end_analysis(elder_id)
    except asyncio.CancelledError:
        # 被新的互動重置了，不做事
        pass


def _reset_session_idle_timer(elder_id: str):
    """每次互動時呼叫：重置該長者的閒置計時器"""
    # 取消舊的計時器
    old_task = _session_idle_timers.get(elder_id)
    if old_task and not old_task.done():
        old_task.cancel()
    
    # 建立新的計時器
    try:
        loop = asyncio.get_event_loop()
        _session_idle_timers[elder_id] = loop.create_task(_session_idle_countdown(elder_id))
    except RuntimeError:
        # 如果 event loop 尚未運行（極少見），忽略
        pass


def _enqueue_for_session_analysis(elder_id: str, user_text: str, ai_text: str):
    """將對話加入待分析佇列（Session 結束時統一分析）"""
    if elder_id not in _session_pending_analysis:
        _session_pending_analysis[elder_id] = []
    _session_pending_analysis[elder_id].append({"user": user_text, "ai": ai_text})


def is_session_analysis_running(elder_id: str = "elder_001") -> bool:
    """查詢特定長者的背景分析是否仍在執行（供 LINE Bot 推播緩衝使用）"""
    return _session_analysis_running.get(elder_id, False)


# ── 離開意圖偵測（LLM 判斷）─────────────────────────

def _detect_farewell(user_text: str) -> bool:
    """用 LLM 判斷使用者是否想結束對話"""
    try:
        from core.bedrock_client import chat as bedrock_chat
        
        # 從檔案讀取提示詞
        try:
            with open(config.FAREWELL_DETECTION_PROMPT_PATH, 'r', encoding='utf-8') as f:
                base_prompt = f.read()
        except Exception:
            base_prompt = "判斷使用者是否想結束對話。只回答 yes 或 no。"
        
        answer = bedrock_chat(
            user_text=f"{base_prompt}\n\n使用者說：「{user_text}」",
            temperature=0.0,
            max_tokens=16,
        )
        answer = answer.strip().lower()
        is_farewell = "yes" in answer
        print(f"👋 [告別偵測] 「{user_text[:30]}」→ LLM 判斷：{'結束' if is_farewell else '繼續'}")
        return is_farewell
    except Exception as e:
        print(f"⚠️ [告別偵測] LLM 判斷失敗: {e}")
        return False


# ── 對話情緒偵測（文字 + 語音綜合判斷）─────────────────
_EMOTION_KEYWORDS = {
    "開心": ["開心", "高興", "快樂", "好棒", "太好了", "哈哈", "嘻嘻", "不錯", "很好", "好開心", "真好", "好玩",
             "心情好", "好心情", "爽", "舒服", "滿足", "幸福", "愉快", "歡喜", "笑", "樂"],
    "難過": ["難過", "傷心", "哭", "不開心", "想哭", "寂寞", "孤單", "好累", "沒人", "好難受", "唉",
             "心情不好", "心情很不好", "心情超不好", "心情差", "心情很差", "不好受", "好煩", "鬱悶", "憂鬱",
             "低落", "沮喪", "無聊", "沒意思", "不想動", "不舒服", "心裡難受", "好難過", "委屈", "失落", "落寞",
             "不太好", "不太開心", "很不好", "很難過", "很傷心", "很低落"],
    "生氣": ["生氣", "氣死", "不爽", "煩", "討厭", "很火", "混蛋", "受不了", "怎麼這樣",
             "火大", "氣死了", "惱", "煩死", "很煩", "吵死", "夠了", "受夠"],
    "恐懼": ["害怕", "可怕", "嚇", "恐怖", "擔心", "不敢", "怕怕", "緊張", "焦慮", "不安", "慌"],
    "吃驚": ["天啊", "真的假的", "不會吧", "嚇到", "驚", "沒想到", "怎麼會", "太扯", "誇張"],
}

def _detect_chat_emotion(user_text: str, voice_emotion: dict = None) -> tuple:
    """
    綜合判斷對話情緒（文字為主，語音為輔）。
    回傳 (情緒, 原因) 的 tuple。
    """
    # 文字情緒判斷（主要）
    text = user_text.lower().strip()
    text_emotion = "中立"
    emotion_reason = ""
    
    # 第一層：關鍵詞精確匹配
    for emotion, keywords in _EMOTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                text_emotion = emotion
                emotion_reason = user_text.strip()[:50]
                break
        if text_emotion != "中立":
            break
    
    # 第二層：正則模糊匹配（補漏「心情X不好」「很X難過」等變體）
    if text_emotion == "中立":
        import re
        _negative_mood_patterns = [
            re.compile(r'心情.{0,3}(?:不好|差|不太好|糟|爛|低落|不佳)'),
            re.compile(r'(?:很|好|超|真|太).{0,2}(?:難過|傷心|低落|鬱悶|沮喪|煩|累)'),
            re.compile(r'(?:不想|不要).{0,3}(?:活|動|說話|理人|出門)'),
            re.compile(r'(?:活著|人生).{0,3}(?:沒意思|沒意義|好累|無聊)'),
        ]
        _positive_mood_patterns = [
            re.compile(r'心情.{0,3}(?:好|不錯|很好|超好|愉快)'),
            re.compile(r'(?:很|好|超|真|太).{0,2}(?:開心|高興|快樂|爽)'),
        ]
        for pat in _negative_mood_patterns:
            if pat.search(text):
                text_emotion = "難過"
                emotion_reason = user_text.strip()[:50]
                break
        if text_emotion == "中立":
            for pat in _positive_mood_patterns:
                if pat.search(text):
                    text_emotion = "開心"
                    emotion_reason = user_text.strip()[:50]
                    break
    
    # 語音情緒（輔助）
    voice_emo = "中立"
    voice_confidence = 0.0
    if voice_emotion and voice_emotion.get("confidence", 0) > 0.3:
        voice_emo = voice_emotion.get("emotion_zh", "中立")
        voice_confidence = voice_emotion.get("confidence", 0)
    
    # 綜合判斷：文字有明確情緒用文字，文字無情緒時以語音為主
    if text_emotion != "中立":
        return (text_emotion, emotion_reason, 1.0)
    elif voice_emo != "中立" and voice_confidence > 0.3:
        return (voice_emo, f"語音情緒偵測：{voice_emo}", voice_confidence)
    else:
        return ("未檢測", "", 0.0)


# ═══════════════════════════════════════════════════════
# 📡 即時事件廣播機制（供 Dashboard SSE 使用）
# ═══════════════════════════════════════════════════════
_event_subscribers: list = []
_latest_events: list = []

def broadcast_event(event_data: dict):
    """將事件推送給所有 SSE 訂閱者"""
    event_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _latest_events.insert(0, event_data)
    if len(_latest_events) > 50:
        _latest_events.pop()
    for queue in _event_subscribers[:]:
        try:
            queue.put_nowait(event_data)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════
# API 1: Dashboard 資料（供 dashboard.html 撈取）
# ═══════════════════════════════════════════════════════
@app.get("/api/elder/{elder_id}")
def get_elder_dashboard_data(elder_id: str, request: Request):
    """回傳整合後的完整看板資料（需要有效的 session token）"""
    elder_id = _validate_elder_id(elder_id)
    
    # 🔒 驗證 session token，確認請求者有權存取此 elder_id
    authorized_elder_id = _verify_session(request)
    if authorized_elder_id != elder_id:
        raise HTTPException(status_code=403, detail="無權存取此使用者的資料")
    
    # 確認資料存在
    elder_dir = os.path.join(config.DATA_DIR, elder_id)
    if not os.path.exists(elder_dir):
        raise HTTPException(status_code=404, detail="找不到此使用者的資料")
    try:
        elder_dm = DataManager(elder_id=elder_id)
        data = elder_dm.get_full_dashboard_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料讀取失敗: {str(e)}")


# ═══════════════════════════════════════════════════════
# API 2b: 純文字串流對話（前端已用瀏覽器 ASR 辨識完，只送文字）
# ═══════════════════════════════════════════════════════
class ChatStreamRequest(BaseModel):
    text: str
    elder_id: str

@app.post("/api/chat/stream")
async def handle_chat_stream(req: ChatStreamRequest):
    """
    前端已用瀏覽器 Web Speech API 做完 ASR，直接送文字過來。
    後端只做 LLM 串流 + TTS 合成，大幅縮短延遲。
    """
    text = req.text
    elder_id = _validate_elder_id(req.elder_id)
    import time as _t
    _total_start = _t.time()
    
    user_text = text.strip()
    if not user_text:
        user_text = "（空白輸入）"
    
    print(f"🔥 [Chat] 收到文字：{user_text}")
    
    # 為該長者建立 DataManager
    elder_dm = DataManager(elder_id=elder_id)
    
    # 組合 prompt（短期對話歷史 + 長期記憶）
    history_ctx = elder_dm.get_history_summary_text()
    long_term_ctx = elder_dm.get_long_term_summary_text()
    full_prompt = f"{long_term_ctx}{history_ctx}長者最新說的話：{user_text}"

    async def _post_chat_tasks_text(u_text: str, ai_text: str, eid: str):
        """背景後處理：即時分析 + 寫入"""
        import time as _bt
        _bg_start = _bt.time()
        
        # 1. 寫入對話記錄 + 情緒判斷
        try:
            elder_dm.record_full_interaction(u_text, ai_text)
            chat_emotion, emotion_reason, confidence = _detect_chat_emotion(u_text)
            print(f"🎭 [文字情緒] 「{u_text[:30]}」→ {chat_emotion}，信心度：{confidence:.0%}")
            elder_dm.update_today_summary("", {"latest_emotion": chat_emotion, "emotion": chat_emotion, "emotion_reason": emotion_reason})
            # 寫入情緒歷史（每次都記錄，不論是否檢測成功）
            elder_dm.add_emotion_record(chat_emotion, emotion_reason, confidence, "text")
        except Exception as e:
            print(f"⚠️ [背景] record_full_interaction: {e}")
        
        # 2. 即時執行健康分析（每輪對話都分析，不延遲）
        try:
            from core.memory_controller import MemoryController
            mc = MemoryController(elder_id=eid)
            mc.update_memories(u_text, ai_text)
        except Exception as e:
            print(f"⚠️ [背景] update_memories: {e}")
        
        # 3. 廣播給 dashboard
        broadcast_event({"type": "speech_interaction", "elder_id": eid, "user_text": u_text, "ai_reply": ai_text, "summary_updated": True})
        
        # 4. 加入待摘要佇列 + 重置計時器（Session 結束時生成 AI 摘要）
        _enqueue_for_session_analysis(eid, u_text, ai_text)
        _reset_session_idle_timer(eid)
        
        print(f"⏱️ [背景] 即時分析完成：{_bt.time() - _bg_start:.2f}s")

    async def generate():
        full_reply = ""
        sentence_index = 0

        yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        try:
            _stream_start = _t.time()
            _first = True

            for sentence in ask_ollama_stream_sentences(full_prompt, elder_id=elder_id):
                full_reply += sentence
                _elapsed = _t.time() - _stream_start

                if _first:
                    print(f"⏱️ [Chat] LLM 首句：{_elapsed:.2f}s")
                    _first = False

                print(f"⏱️ [Chat] 句子 #{sentence_index} +{_elapsed:.1f}s：{sentence[:30]}...")

                _tts_s = _t.time()
                audio_data = await synthesize_sentence_to_bytes(sentence)
                print(f"⏱️ [Chat] TTS #{sentence_index}：{_t.time()-_tts_s:.2f}s")

                if audio_data:
                    audio_path = f"_stream_audio_{sentence_index}.mp3"
                    abs_path = os.path.join(config.BASE_DIR, audio_path)
                    with open(abs_path, "wb") as af:
                        af.write(audio_data)
                    yield f"data: {json.dumps({'type': 'sentence', 'index': sentence_index, 'text': sentence, 'audioUrl': f'/{audio_path}'}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'sentence', 'index': sentence_index, 'text': sentence, 'audioUrl': ''}, ensure_ascii=False)}\n\n"

                sentence_index += 1

        except Exception as e:
            print(f"🚨 LLM 錯誤: {e}")
            if not full_reply:
                full_reply = "抱歉，我現在沒辦法回應。"
                yield f"data: {json.dumps({'type': 'sentence', 'index': 0, 'text': full_reply, 'audioUrl': ''}, ensure_ascii=False)}\n\n"

        _total = _t.time() - _total_start
        print(f"═══ ⏱️ [Chat 總結] 全程 {_total:.2f}s / {sentence_index} 句 / {len(full_reply)} 字 ═══")
        
        # 判斷使用者是否想結束對話
        end_session = _detect_farewell(user_text)
        yield f"data: {json.dumps({'type': 'done', 'full_reply': full_reply, 'end_session': end_session}, ensure_ascii=False)}\n\n"

        asyncio.ensure_future(_post_chat_tasks_text(user_text, full_reply, elder_id))
        
        # 若偵測到結束對話，立即觸發 Session 結束分析（取消閒置等待）
        if end_session:
            old_task = _session_idle_timers.get(elder_id)
            if old_task and not old_task.done():
                old_task.cancel()
            asyncio.ensure_future(_trigger_session_end_analysis(elder_id))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })


# ═══════════════════════════════════════════════════════
# API 2c: 獨立 ASR 端點（fallback，僅在瀏覽器 ASR 失敗時使用）
# ═══════════════════════════════════════════════════════
@app.post("/api/asr")
async def standalone_asr(
    file: UploadFile = File(...),
    elder_id: str = Query(..., description="長者 ID（必填）")
):
    """獨立 ASR 端點：收音檔回傳文字。僅作為 fallback。"""
    elder_id = _validate_elder_id(elder_id)
    import time as _t
    _start = _t.time()
    
    audio_bytes = await file.read()
    audio_filename = config.LAST_SPEECH_PATH
    with open(audio_filename, "wb") as f:
        f.write(audio_bytes)
    
    # 在 thread executor 中執行 ASR，避免阻塞 event loop
    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, audio_to_text, audio_filename)
    except Exception:
        text = None
    
    print(f"⏱️ [ASR fallback] {_t.time()-_start:.2f}s → {text}")
    return {"text": text or ""}
@app.post("/api/speech")
async def handle_elder_speech(
    file: UploadFile = File(...),
    elder_id: str = Query(..., description="長者 ID（必填）")
):
    """
    前端 POST 音檔 → 後端 ASR 辨識 → LLM 串流逐句生成 → 每句即時 TTS 合成
    → SSE 逐句推送 {sentence, audioUrl} 給前端 → 前端收到一句播一句
    """
    elder_id = _validate_elder_id(elder_id)
    # ═══════ 全流程計時器 ═══════
    import time as _t
    _total_start = _t.time()
    
    # 1. 儲存音檔
    _step_start = _t.time()
    audio_bytes = await file.read()
    audio_filename = config.LAST_SPEECH_PATH
    with open(audio_filename, "wb") as f:
        f.write(audio_bytes)
    print(f"⏱️ [步驟1] 接收並儲存音檔：{_t.time() - _step_start:.2f}s（大小 {len(audio_bytes)} bytes）")

    # 2. ASR 語音辨識（在 thread executor 中執行，不阻塞 event loop）
    _step_start = _t.time()
    loop = asyncio.get_event_loop()
    try:
        # 並行執行 ASR + 情緒辨識（兩者都是 CPU-bound，用 executor 避免阻塞）
        asr_task = loop.run_in_executor(None, audio_to_text, audio_filename)
        emotion_task = loop.run_in_executor(None, recognize_emotion, audio_filename)
        user_text, emotion_result = await asyncio.gather(asr_task, emotion_task)
    except Exception as asr_err:
        print(f"🚨 ASR/情緒辨識失敗: {asr_err}")
        user_text = None
        emotion_result = {"emotion_zh": "中立", "emotion_en": "neutral", "emotion_index": 4, "confidence": 0.0, "all_scores": {}}
    _asr_time = _t.time() - _step_start
    
    # 記錄情緒到當日日誌
    log_emotion(emotion_result)
    print(f"🎭 [情緒辨識] {emotion_result['emotion_zh']}({emotion_result['emotion_en']}) 信心度: {emotion_result['confidence']:.2%}")
    
    if not user_text or not user_text.strip():
        user_text = "（長輩發出了聲音，但語音識別未偵測到清晰文字）"

    print(f"⏱️ [步驟2] ASR 語音辨識：{_asr_time:.2f}s → 「{user_text}」")

    # 3. 組合 prompt
    _step_start = _t.time()
    elder_dm = DataManager(elder_id=elder_id)
    history_ctx = elder_dm.get_history_summary_text()
    full_prompt = f"{history_ctx}長者最新說的話：{user_text}"
    print(f"⏱️ [步驟3] 組合 prompt：{_t.time() - _step_start:.3f}s（歷史 {len(history_ctx)} 字）")

    # 4. SSE 串流回應
    async def _post_chat_tasks(u_text: str, ai_text: str, eid: str, emotion: dict = None):
        """背景後處理：即時分析 + 寫入"""
        import time as _bt
        _bg_start = _bt.time()
        
        # 1. 寫入對話記錄 + 情緒判斷
        try:
            elder_dm.record_full_interaction(u_text, ai_text)
            chat_emotion, emotion_reason, confidence = _detect_chat_emotion(u_text, emotion)
            # 分開顯示文字情緒和語音情緒
            print(f"🎭 [文字情緒] 「{u_text[:30]}」→ {chat_emotion}，信心度：{confidence:.0%}")
            if emotion and emotion.get("confidence", 0) > 0:
                print(f"🎭 [語音情緒] {emotion.get('emotion_zh','無')}({emotion.get('emotion_en','')})，信心度：{emotion.get('confidence',0):.0%}")
            
            # 情緒寫入 dashboard（文字+語音綜合結果）
            emotion_data = {"latest_emotion": chat_emotion, "emotion": chat_emotion, "emotion_reason": emotion_reason}
            # 語音情緒也存入用戶數據（持久化）
            if emotion and emotion.get("confidence", 0) > 0:
                emotion_data["voice_emotion"] = emotion.get("emotion_zh", "")
                emotion_data["voice_confidence"] = emotion.get("confidence", 0)
            elder_dm.update_today_summary("", emotion_data)
            # 寫入情緒歷史（每次都記錄，不論是否檢測成功）
            elder_dm.add_emotion_record(chat_emotion, emotion_reason, confidence, "text")
            if emotion and emotion.get("confidence", 0) > 0:
                elder_dm.add_emotion_record(emotion.get("emotion_zh", "中立"), "語音偵測", emotion.get("confidence", 0), "voice")
        except Exception as e:
            print(f"⚠️ [背景] record_full_interaction 失敗: {e}")

        # 2. 即時執行健康分析（每輪對話都分析，不延遲）
        try:
            from core.memory_controller import MemoryController
            mc = MemoryController(elder_id=eid)
            mc.update_memories(u_text, ai_text)
        except Exception as e:
            print(f"⚠️ [背景] update_memories: {e}")

        # 3. 廣播給 Dashboard
        try:
            broadcast_event({
                "type": "speech_interaction",
                "elder_id": eid,
                "user_text": u_text,
                "ai_reply": ai_text,
                "summary_updated": True,
            })
        except Exception as e:
            print(f"⚠️ [背景] broadcast_event 失敗: {e}")

        # 4. 加入待摘要佇列 + 重置計時器
        _enqueue_for_session_analysis(eid, u_text, ai_text)
        _reset_session_idle_timer(eid)

        # 5. 更新情緒提示詞
        if emotion and emotion.get("confidence", 0) > 0:
            try:
                update_emotion_in_prompt()
            except Exception as e:
                print(f"⚠️ [背景] 情緒提示詞更新失敗: {e}")

        print(f"⏱️ [背景] 即時分析完成：{_bt.time() - _bg_start:.2f}s")

    async def generate_stream():
        full_reply = ""
        sentence_index = 0

        # 先推送 ASR 結果
        yield f"data: {json.dumps({'type': 'asr', 'text': user_text}, ensure_ascii=False)}\n\n"

        # LLM 開始前先通知前端「思考中」
        yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        # LLM 串流逐句生成
        try:
            _stream_start = _t.time()
            _first_sentence_time = None
            print(f"⏱️ [步驟4] LLM 串流開始...")

            for sentence in ask_ollama_stream_sentences(full_prompt, elder_id=elder_id):
                full_reply += sentence
                _elapsed = _t.time() - _stream_start
                
                if _first_sentence_time is None:
                    _first_sentence_time = _elapsed
                    print(f"⏱️ [步驟4] LLM 首句到達：{_first_sentence_time:.2f}s（首 token 延遲）")
                
                print(f"⏱️ [步驟4] 句子 #{sentence_index} +{_elapsed:.1f}s：{sentence[:30]}{'...' if len(sentence)>30 else ''}")

                # TTS 合成這一句的音訊
                _tts_start = _t.time()
                audio_data = await synthesize_sentence_to_bytes(sentence)
                _tts_elapsed = _t.time() - _tts_start
                print(f"⏱️ [步驟5] TTS #{sentence_index} 合成：{_tts_elapsed:.2f}s（{len(sentence)}字 → {len(audio_data) if audio_data else 0} bytes）")

                if audio_data:
                    # 存為暫存檔供前端下載
                    audio_path = f"_stream_audio_{sentence_index}.mp3"
                    abs_path = os.path.join(config.BASE_DIR, audio_path)
                    with open(abs_path, "wb") as af:
                        af.write(audio_data)

                    yield f"data: {json.dumps({'type': 'sentence', 'index': sentence_index, 'text': sentence, 'audioUrl': f'/{audio_path}'}, ensure_ascii=False)}\n\n"
                else:
                    # TTS 失敗，只送文字
                    yield f"data: {json.dumps({'type': 'sentence', 'index': sentence_index, 'text': sentence, 'audioUrl': ''}, ensure_ascii=False)}\n\n"

                sentence_index += 1

        except Exception as llm_err:
            print(f"🚨 LLM 串流錯誤: {llm_err}")
            if not full_reply:
                full_reply = "抱歉，我現在沒辦法回應，請稍後再試。"
                yield f"data: {json.dumps({'type': 'sentence', 'index': 0, 'text': full_reply, 'audioUrl': ''}, ensure_ascii=False)}\n\n"

        # 推送完成訊號，SSE 串流到此結束
        _total_elapsed = _t.time() - _total_start
        _stream_elapsed = _t.time() - _stream_start if '_stream_start' in dir() else 0
        print(f"")
        print(f"═══════════════════════════════════════════")
        print(f"⏱️ [總結] 本次互動完整計時：")
        print(f"    全流程總耗時：{_total_elapsed:.2f}s")
        print(f"    LLM+TTS 串流：{_stream_elapsed:.2f}s（{sentence_index} 句）")
        print(f"    完整回覆：{len(full_reply)} 字")
        print(f"═══════════════════════════════════════════")
        print(f"")
        end_session = _detect_farewell(user_text)
        yield f"data: {json.dumps({'type': 'done', 'full_reply': full_reply, 'end_session': end_session}, ensure_ascii=False)}\n\n"

        # 5. 交由獨立背景 task 處理（輕量寫入 + Dashboard 廣播）
        #    記憶分析延遲到 Session 結束時統一觸發
        asyncio.ensure_future(_post_chat_tasks(user_text, full_reply, elder_id, emotion_result))
        
        # 若偵測到結束對話，立即觸發 Session 結束分析（取消閒置等待）
        if end_session:
            old_task = _session_idle_timers.get(elder_id)
            if old_task and not old_task.done():
                old_task.cancel()
            asyncio.ensure_future(_trigger_session_end_analysis(elder_id))

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ═══════════════════════════════════════════════════════
# API 3: 更新長者基本資料
# ═══════════════════════════════════════════════════════
class ElderProfileRequest(BaseModel):
    elder_id: str = ""
    name: str
    nickname: str
    gender: str
    age: Optional[int] = None
    location: str = ""
    id_number: str = ""  # 身分證字號（前端傳明文，後端加密存儲）
    # 緊急聯絡人
    ec_name: str = ""
    ec_relationship: str = ""
    ec_phone: str = ""
    # 醫療與用藥
    chronic_diseases: List[str] = []
    current_medications: List[str] = []
    drug_allergies: List[str] = []
    food_allergies: List[str] = []
    # 生理與照護
    mobility: str = ""
    dietary_restrictions: List[str] = []
    # 精神與認知
    has_dementia: bool = False
    has_wandering_history: bool = False
    care_notes: str = ""


def _hash_id_number(id_number: str) -> str:
    """將身分證字號用 SHA256 加密（不可逆），用於比對身份"""
    import hashlib
    return hashlib.sha256(id_number.strip().upper().encode('utf-8')).hexdigest()


def _find_existing_elder(name: str, id_hash: str) -> Optional[str]:
    """
    根據姓名 + 身分證 hash 查找是否已有對應的長者資料。
    若找到，回傳該 elder_id；否則回傳 None。
    """
    data_dir = os.path.join(config.BASE_DIR, "data")
    if not os.path.exists(data_dir):
        return None
    
    for elder_dir_name in os.listdir(data_dir):
        if not elder_dir_name.startswith("elder_"):
            continue
        profile_path = os.path.join(data_dir, elder_dir_name, "elder_profile.json")
        if not os.path.exists(profile_path):
            continue
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            stored_name = profile.get("personal_info", {}).get("name", "")
            stored_hash = profile.get("personal_info", {}).get("id_number_hash", "")
            # 姓名相同 + 身分證 hash 相同 → 同一個人
            if stored_name == name and stored_hash == id_hash and stored_hash:
                return elder_dir_name
        except Exception:
            continue
    return None


@app.post("/api/elder/profile")
def save_elder_profile(req: ElderProfileRequest):
    try:
        # 🔒 輸入驗證與清洗（防注入、違禁字檢查）
        clean = _validate_registration_input(req)
        
        # 如果有身分證字號，嘗試匹配已有用戶
        matched_elder_id = None
        id_hash = ""
        if clean["id_number"]:
            id_hash = _hash_id_number(clean["id_number"])
            matched_elder_id = _find_existing_elder(clean["name"], id_hash)
        
        if matched_elder_id:
            # 找到已有用戶 → 發行 session token（登入模式）
            token = _generate_session_token(matched_elder_id)
            return {
                "success": True,
                "elder_id": matched_elder_id,
                "is_existing": True,
                "token": token,
                "message": f"歡迎回來！已找到 {clean['name']} 的資料。"
            }
        
        # 新用戶註冊
        elder_id = req.elder_id if req.elder_id else f"elder_{datetime.now().strftime('%s')[:10]}{os.urandom(3).hex()}"
        # 驗證生成的 elder_id 格式
        _validate_elder_id(elder_id)
        
        elder_dm = DataManager(elder_id=elder_id)
        
        # 寫入基本資料
        elder_dm.update_profile(
            name=clean["name"],
            nickname=clean["nickname"],
            age=clean["age"],
            location=clean["location"],
            gender=clean["gender"],
        )
        
        # 寫入身分證 hash（加密存儲，不保存明文）
        if id_hash:
            profile = elder_dm.get_profile()
            profile["personal_info"]["id_number_hash"] = id_hash
            profile["meta"]["last_updated"] = datetime.now().isoformat()
            elder_dm._save(elder_dm.profile_path, profile)
        
        # 寫入緊急聯絡人
        if clean["ec_name"] or clean["ec_phone"]:
            elder_dm.update_emergency_contact(
                name=clean["ec_name"],
                relationship=clean["ec_relationship"],
                phone=clean["ec_phone"],
            )
        
        # 寫入醫療與用藥
        if clean["chronic_diseases"] or clean["drug_allergies"] or clean["food_allergies"] or clean["current_medications"]:
            elder_dm.update_medical_safety(
                chronic_diseases=clean["chronic_diseases"],
                current_medications=clean["current_medications"],
                drug_allergies=clean["drug_allergies"],
                food_allergies=clean["food_allergies"],
            )
        
        # 寫入生理照護
        if clean["mobility"] or clean["dietary_restrictions"]:
            elder_dm.update_physical_care(
                mobility=clean["mobility"],
                dietary_restrictions=clean["dietary_restrictions"],
            )
        
        # 寫入精神與認知
        if clean["has_dementia"] or clean["has_wandering_history"] or clean["care_notes"]:
            elder_dm.update_mental_cognitive(
                has_dementia=clean["has_dementia"],
                has_wandering_history=clean["has_wandering_history"],
                cognitive_notes=clean["care_notes"],
            )

        # 新用戶註冊成功，發行 session token
        token = _generate_session_token(elder_id)
        
        return {
            "success": True,
            "elder_id": elder_id,
            "is_existing": False,
            "token": token,
            "message": f"✅ 長者 {clean['name']} 基本資料已儲存！"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# API 4: 新增時間軸事件
# ═══════════════════════════════════════════════════════
class TimelineEventRequest(BaseModel):
    elder_id: str
    event_time: str
    event_type: str
    status: str
    title: str
    content: str

@app.post("/api/elder/timeline")
def add_timeline_event(req: TimelineEventRequest):
    try:
        elder_dm = DataManager(elder_id=req.elder_id)
        elder_dm.add_timeline_event(
            event_type=req.event_type,
            title=req.title,
            description=req.content,
            time_str=req.event_time,
        )
        return {"success": True, "message": f"✅ 時間軸事件【{req.title}】已新增！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# API 5: 手動對話文字 → AI 摘要
# ═══════════════════════════════════════════════════════
class ConversationRequest(BaseModel):
    elder_id: str
    conversation_text: str

@app.post("/api/elder/ai-summary")
def generate_ai_summary(req: ConversationRequest):
    try:
        elder_dm = DataManager(elder_id=req.elder_id)
        ai_result = services.ai_summary.get_elder_daily_summary(
            current_chat=req.conversation_text
        )
        summary_text = ai_result.get("overallSummary", "")
        structured = ai_result.get("structuredData", {})

        # 寫入看板
        metrics = {}
        if structured.get("diet"):
            _diet_filter_words = ["藥", "高血壓", "糖尿病", "頭痛", "痛", "暈", "維他命", "胰島素"]
            diet_val = structured["diet"]
            if not any(w in diet_val for w in _diet_filter_words):
                metrics["diet"] = diet_val
        if structured.get("sleep"):
            metrics["sleep"] = structured["sleep"]
        if structured.get("medication"):
            metrics["medication_taken"] = True
        elder_dm.update_today_summary(summary_text, metrics)

        # timeline 事件
        if "timeline" in ai_result:
            for event in ai_result["timeline"]:
                elder_dm.add_timeline_event(
                    event_type=event.get("type", "interaction"),
                    title=event.get("title", "AI 分析事件"),
                    description=event.get("content", ""),
                    time_str=event.get("time"),
                )

        return {
            "success": True,
            "message": "✅ AI 摘要已生成並寫入！",
            "summary": {"overallSummary": summary_text, "structuredData": structured}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# API 6: Dashboard 即時事件串流 (SSE) + 最新事件查詢
# ═══════════════════════════════════════════════════════
@app.get("/api/elder/events/stream")
async def event_stream():
    """SSE 端點：Dashboard 訂閱後即時收到互動事件"""
    queue = asyncio.Queue()
    _event_subscribers.append(queue)

    async def generate():
        try:
            yield f"data: {json.dumps({'type': 'connected'}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _event_subscribers:
                _event_subscribers.remove(queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.get("/api/elder/events/latest")
def get_latest_events(limit: int = 10):
    return {"events": _latest_events[:limit]}


# ═══════════════════════════════════════════════════════
# API 7: TTS 語音合成
# ═══════════════════════════════════════════════════════
@app.get("/api/tts")
async def text_to_speech(
    text: str,
    lang: str = Query(default="台語 (閩南語)")
):
    try:
        if not text.strip():
            raise HTTPException(status_code=400, detail="語音合成文字不可為空")

        if lang not in VOICES:
            lang = "台語 (閩南語)"

        voice_name, default_filename = VOICES[lang]
        saved_file_path = os.path.abspath(f"server_{default_filename}")

        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(saved_file_path)

        if not os.path.exists(saved_file_path):
            raise HTTPException(status_code=500, detail="語音檔案生成失敗")

        return FileResponse(saved_file_path, media_type="audio/mpeg", filename=default_filename)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"語音合成失敗: {str(e)}")


# ═══════════════════════════════════════════════════════
# API 8: 語音助理控制
# ═══════════════════════════════════════════════════════
@app.get("/api/voice/status")
def voice_status():
    assistant = get_assistant()
    return {
        "running": assistant.running,
        "active": assistant.is_active(),
        "message": "對話中" if assistant.is_active() else (
            "等待喚醒詞「小黃小黃」" if assistant.running else "已停止"
        ),
    }

@app.post("/api/voice/start")
def voice_start():
    assistant = get_assistant()
    if assistant.running:
        return {"success": False, "message": "語音助理已在執行中"}
    threading.Thread(target=assistant.start, daemon=True).start()
    return {"success": True, "message": "語音助理已啟動"}

@app.post("/api/voice/stop")
def voice_stop():
    assistant = get_assistant()
    if not assistant.running:
        return {"success": False, "message": "語音助理未執行"}
    assistant.stop()
    return {"success": True, "message": "語音助理已停止"}


# ═══════════════════════════════════════════════════════
# 靜態檔案與頁面路由
# ═══════════════════════════════════════════════════════

# 串流音訊暫存檔路由（下載後自動刪除）
@app.get("/_stream_audio_{index}.mp3")
async def get_stream_audio(index: int):
    """供前端逐句播放時下載串流音訊暫存檔，下載完成後自動刪除"""
    file_path = os.path.join(config.BASE_DIR, f"_stream_audio_{index}.mp3")
    if os.path.exists(file_path):
        from fastapi.responses import Response
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        # 讀取後立即刪除暫存檔
        try:
            os.remove(file_path)
        except OSError:
            pass
        return Response(content=audio_bytes, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="音訊檔案不存在")

# 圖片資源
app.mount("/images", StaticFiles(directory=config.IMAGES_DIR), name="images")
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="static")
