# LLM 功能層 — 實作任務清單

## 任務 1：Bedrock Client 基礎服務 ✅
- [x] 建立 `core/bedrock_client.py` 封裝 Bedrock Converse API
- [x] 實作 `chat()` 同步呼叫
- [x] 實作 `chat_stream()` 串流呼叫（逐 token generator）
- [x] 實作 `chat_json()` JSON 模式呼叫
- [x] 連線失敗重試機制（3 次，adaptive mode）
- [x] 使用 inference profile ID（`us.anthropic.claude-sonnet-4-20250514-v1:0`）

## 任務 2：對話生成引擎 ✅
- [x] `ai_chat.py` 改用 bedrock_client（取代 Ollama）
- [x] `get_combined_system_prompt()` 動態組合 system prompt（profile + 天氣 + 時間 + 情緒）
- [x] `ask_ollama_stream_sentences()` 串流逐句生成器（斷句 + emoji 過濾）
- [x] `_sanitize_reply()` 後處理：移除違反能力白名單的表述
- [x] 保留原函式名以維持下游相容性

## 任務 3：健康分析萃取 ✅
- [x] `memory_controller._analyze_health_info()` 呼叫 Bedrock 分析用藥/飲食/症狀
- [x] 分析結果自動寫入長期記憶 + dashboard metrics
- [x] 用藥名稱自動寫入 elder_profile.medical_safety.current_medications
- [x] 用藥按時段記錄（medication_by_period）

## 任務 4：每日摘要生成 ✅
- [x] `ai_summary.py` 改用 bedrock_client.chat_json
- [x] 輸出結構化 JSON（overallSummary + structuredData）
- [x] Session 閒置 2 分鐘自動觸發摘要生成
- [x] 摘要完成後觸發 LINE 推播

## 任務 5：情緒偵測（文字關鍵詞）✅
- [x] `app.py _detect_chat_emotion()` 兩層偵測：關鍵詞精確匹配 + 正則模糊匹配
- [x] 情緒結果寫入 emotion_history（source=text）
- [x] 情緒結果更新 dashboard metrics

## 任務 6：告別偵測 ✅
- [x] `app.py _detect_farewell()` 呼叫 Bedrock + farewell_detection_prompt.txt
- [x] SSE done 事件中回傳 end_session 布林值
- [x] end_session=true 時觸發 Session 結束分析

## 任務 7：記憶重要性判斷 ✅
- [x] `data_manager._evaluate_importance()` 呼叫 Bedrock 評分（1~10）
- [x] 依評分決定 ttl_minutes（30/60/240）

## 任務 8：SSE 串流對話端點 ✅
- [x] `POST /api/chat/stream` 接收文字 → 串流逐句回覆
- [x] 每句同時 TTS 合成 → 回傳 audioUrl
- [x] 背景任務：記憶分析 + 情緒偵測 + dashboard 更新

## 任務 9：求助意圖偵測（待實作）
- [ ] 在對話分析中偵測求助意圖（如「我跌倒了」「好痛」「不舒服」）
- [ ] 觸發 LINE 推播緊急通知給照護者
- [ ] 在 dashboard timeline_events 中記錄為 health 類型事件

## 任務 10：記憶安全規則完善（待實作）
- [ ] 將關鍵詞安全規則抽出為可配置 JSON 檔案
- [ ] 新增更多規則：跌倒/住院 → 強制 permanent；服藥 → 最低 medium
- [ ] 規則覆蓋 LLM 判斷（取高者）
