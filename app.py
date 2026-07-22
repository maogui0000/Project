# app.py
"""
雲湧智生 — 智慧長照關懷系統 後端 API 伺服器
整合語音辨識 (ASR)、語音合成 (TTS)、AI 對話、生活摘要、LINE Bot 推播

資料層：使用 data_manager.DataManager 統一存取 4 個 JSON 檔案
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
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
    print(f"  AI 模型：{config.OLLAMA_MODEL}")
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

# ── 全域 DataManager 實例 ────────────────────────────
dm = DataManager()


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
def get_elder_dashboard_data(elder_id: str):
    """回傳整合後的完整看板資料"""
    try:
        elder_dm = DataManager(elder_id=elder_id)
        data = elder_dm.get_full_dashboard_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料讀取失敗: {str(e)}")


# ═══════════════════════════════════════════════════════
# API 2b: 純文字串流對話（前端已用瀏覽器 ASR 辨識完，只送文字）
# ═══════════════════════════════════════════════════════
@app.post("/api/chat/stream")
async def handle_chat_stream(
    text: str = Query(..., description="使用者說的文字"),
    elder_id: str = Query(default="elder_001", description="長者 ID")
):
    """
    前端已用瀏覽器 Web Speech API 做完 ASR，直接送文字過來。
    後端只做 LLM 串流 + TTS 合成，大幅縮短延遲。
    """
    import time as _t
    _total_start = _t.time()
    
    user_text = text.strip()
    if not user_text:
        user_text = "（空白輸入）"
    
    print(f"🔥 [Chat] 收到文字：{user_text}")
    
    # 為該長者建立 DataManager
    elder_dm = DataManager(elder_id=elder_id)
    
    # 組合 prompt
    history_ctx = elder_dm.get_history_summary_text()
    full_prompt = f"{history_ctx}長者最新說的話：{user_text}"

    async def _post_chat_tasks_text(u_text: str, ai_text: str, eid: str):
        """背景後處理"""
        import time as _bt
        _bg_start = _bt.time()
        try:
            elder_dm.record_full_interaction(u_text, ai_text)
        except Exception as e:
            print(f"⚠️ [背景] record_full_interaction: {e}")
        try:
            assistant = get_assistant()
            assistant.memory.update_memories(u_text, ai_text)
        except Exception as e:
            print(f"⚠️ [背景] update_memories: {e}")
        try:
            ai_result = services.ai_summary.get_elder_daily_summary(
                current_chat=f"長者說：{u_text}\nAI回覆：{ai_text}"
            )
            summary_text = ai_result.get("overallSummary", "")
            structured = ai_result.get("structuredData", {})
            metrics = {}
            if structured.get("diet"): metrics["diet"] = structured["diet"]
            if structured.get("sleep"): metrics["sleep"] = structured["sleep"]
            if summary_text: elder_dm.update_today_summary(summary_text, metrics)
        except Exception:
            pass
        broadcast_event({"type": "speech_interaction", "elder_id": eid, "user_text": u_text, "ai_reply": ai_text, "summary_updated": True})
        print(f"⏱️ [背景] 後處理完成：{_bt.time() - _bg_start:.2f}s")

    async def generate():
        full_reply = ""
        sentence_index = 0

        yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        try:
            _stream_start = _t.time()
            _first = True

            for sentence in ask_ollama_stream_sentences(full_prompt):
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
        yield f"data: {json.dumps({'type': 'done', 'full_reply': full_reply}, ensure_ascii=False)}\n\n"

        asyncio.ensure_future(_post_chat_tasks_text(user_text, full_reply, elder_id))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })


# ═══════════════════════════════════════════════════════
# API 2c: 獨立 ASR 端點（fallback，僅在瀏覽器 ASR 失敗時使用）
# ═══════════════════════════════════════════════════════
@app.post("/api/asr")
async def standalone_asr(
    file: UploadFile = File(...),
    elder_id: str = Query(default="elder_001")
):
    """獨立 ASR 端點：收音檔回傳文字。僅作為 fallback。"""
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
    elder_id: str = Query(default="elder_001", description="長者 ID")
):
    """
    前端 POST 音檔 → 後端 ASR 辨識 → LLM 串流逐句生成 → 每句即時 TTS 合成
    → SSE 逐句推送 {sentence, audioUrl} 給前端 → 前端收到一句播一句
    
    SSE 事件格式：
      data: {"type":"asr", "text":"長輩說的話"}
      data: {"type":"sentence", "index":0, "text":"第一句", "audioUrl":"/api/tts/stream/0.mp3"}
      data: {"type":"sentence", "index":1, "text":"第二句", "audioUrl":"/api/tts/stream/1.mp3"}
      data: {"type":"done", "full_reply":"完整回覆"}
    """
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
        """
        與聊天無關的後處理任務，在獨立背景 task 中執行。
        """
        import time as _bt
        _bg_start = _bt.time()
        
        # 1. 寫入短期記憶 + 看板時間軸 + 互動計數
        _s = _bt.time()
        try:
            elder_dm.record_full_interaction(u_text, ai_text)
        except Exception as e:
            print(f"⚠️ [背景] record_full_interaction 失敗: {e}")
        print(f"⏱️ [背景1] 記憶寫入：{_bt.time() - _s:.2f}s")

        # 2. AI 分析健康資訊 → 更新長期記憶
        _s = _bt.time()
        try:
            assistant = get_assistant()
            assistant.memory.update_memories(u_text, ai_text)
        except Exception as e:
            print(f"⚠️ [背景] memory.update_memories 失敗: {e}")
        print(f"⏱️ [背景2] 健康分析：{_bt.time() - _s:.2f}s")

        # 3. AI 摘要分析 → 更新看板今日摘要（含情緒資訊）
        _s = _bt.time()
        try:
            ai_result = services.ai_summary.get_elder_daily_summary(
                current_chat=f"長者說：{u_text}\nAI回覆：{ai_text}"
            )
            summary_text = ai_result.get("overallSummary", "")
            structured = ai_result.get("structuredData", {})
            metrics = {}
            if structured.get("diet"):
                metrics["diet"] = structured["diet"]
            if structured.get("sleep"):
                metrics["sleep"] = structured["sleep"]
            
            # 寫入情緒資訊到 metrics
            if emotion and emotion.get("confidence", 0) > 0:
                emotion_summary = get_emotion_summary()
                metrics["emotion"] = emotion_summary.get("dominant_emotion_zh", "中立")
                metrics["latest_emotion"] = emotion.get("emotion_zh", "中立")
                metrics["emotion_confidence"] = emotion.get("confidence", 0.0)
                metrics["emotion_timeline"] = emotion_summary.get("emotion_timeline", "")
            
            if summary_text:
                elder_dm.update_today_summary(summary_text, metrics)
        except Exception as e:
            print(f"⚠️ [背景] AI 摘要失敗: {e}")
        print(f"⏱️ [背景3] AI 摘要：{_bt.time() - _s:.2f}s")

        # 3.5 更新環境提示詞中的情緒區塊
        if emotion and emotion.get("confidence", 0) > 0:
            try:
                update_emotion_in_prompt()
            except Exception as e:
                print(f"⚠️ [背景] 情緒提示詞更新失敗: {e}")

        # 4. 廣播給 Dashboard（SSE push）
        try:
            broadcast_event({
                "type": "speech_interaction",
                "elder_id": eid,
                "user_text": u_text,
                "ai_reply": ai_text,
                "emotion": emotion.get("emotion_zh", "中立") if emotion else "中立",
                "summary_updated": True,
            })
        except Exception as e:
            print(f"⚠️ [背景] broadcast_event 失敗: {e}")

        print(f"⏱️ [背景] 全部後處理完成：{_bt.time() - _bg_start:.2f}s")

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

            for sentence in ask_ollama_stream_sentences(full_prompt):
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
        yield f"data: {json.dumps({'type': 'done', 'full_reply': full_reply}, ensure_ascii=False)}\n\n"

        # 5. 交由獨立背景 task 處理（記憶寫入、AI摘要、Dashboard廣播）
        #    完全不阻塞串流，聊天對話已結束，後台慢慢跑
        asyncio.ensure_future(_post_chat_tasks(user_text, full_reply, elder_id, emotion_result))

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
    elder_id: str
    name: str
    nickname: str
    age: Optional[int] = None
    location: str
    primary_language: str = "中文"
    gender: str = ""
    health_status: List[str] = []
    care_notes: str = ""

@app.post("/api/elder/profile")
def save_elder_profile(req: ElderProfileRequest):
    try:
        # 為該長者建立專屬 DataManager（會自動建立資料目錄）
        elder_dm = DataManager(elder_id=req.elder_id)
        elder_dm.update_profile(
            name=req.name,
            nickname=req.nickname,
            age=req.age,
            location=req.location,
            gender=req.gender,
        )
        elder_dm.update_care_baseline(
            chronic_diseases=req.health_status,
            core_emotional_need=req.care_notes,
        )
        # 更新語言設定
        profile = elder_dm.get_profile()
        profile["localization_settings"]["primary_language"] = req.primary_language
        profile["meta"]["last_updated"] = datetime.now().isoformat()
        elder_dm._save(elder_dm.profile_path, profile)

        return {"success": True, "message": f"✅ 長者 {req.name} 基本資料已儲存！"}
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
            metrics["diet"] = structured["diet"]
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
