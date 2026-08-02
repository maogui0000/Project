# Bugfix Requirements Document

## Introduction

LINE 推播通知（push messages）無法送達照護者。系統中有多條推播路徑（每日定時摘要、Session 結束即時推播、提醒關鍵詞推播、緊急求助推播）全部靜默失敗，照護者完全收不到任何通知。根本原因包含：Elder ID 不一致導致資料讀取失敗、LINE 憑證設定不一致與錯誤處理不足、雙重排程器衝突、`_send_line_push()` 吞掉所有錯誤、以及缺少提醒推播的排程機制。

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `line_bot.py` 中的 `TARGET_ELDER_ID` 被硬編碼為 `"elder_178546685908e66b"` 但實際資料目錄為 `elder_demo_user_001` THEN the system 在收到照護者留言或語音時存入不存在的長者目錄，導致資料遺失或例外

1.2 WHEN `.env` 中 `LINE_CHANNEL_ACCESS_TOKEN` 為空字串且硬編碼的 token 已過期或被撤銷 THEN the system 的所有 LINE 推播呼叫靜默失敗（HTTP 401），無任何可持久化的錯誤日誌

1.3 WHEN 每天 19:00 到達時，`weather_cron.py` 的 `while True` 迴圈和 `app.py` 的 `_daily_line_push_scheduler()` asyncio 任務同時觸發 THEN the system 可能產生重複推播或互相干擾（`_execute_daily_push()` 不檢查 `is_sent` 旗標）

1.4 WHEN `_send_line_push()` 呼叫 LINE API 失敗（如 401、400 回應）THEN the system 僅 `print()` 錯誤訊息到 stdout 並回傳 `False`，呼叫端無法得知失敗原因，也無持久化日誌可追溯

1.5 WHEN 長者透過對話建立提醒（`reminders.json` 中 `status: "pending"`、`notified: False`）THEN the system 沒有任何排程任務會在提醒時間到達時主動推播 LINE 通知給照護者

### Expected Behavior (Correct)

2.1 WHEN 系統需要讀取長者資料時 THEN the system SHALL 使用統一的、可配置的 elder ID 來源（例如從 `data/` 目錄動態掃描或從設定檔讀取），確保 `line_bot.py`、`weather_cron.py`、`app.py` 三者使用一致的 elder ID

2.2 WHEN LINE 推播被觸發時 THEN the system SHALL 使用單一、統一的 LINE 憑證來源（優先從 `config.py` / `.env` 讀取），並在 token 無效時記錄結構化錯誤日誌（寫入 `logs/` 目錄），不再靜默失敗

2.3 WHEN 每日 19:00 定時推播觸發時 THEN the system SHALL 由唯一的一個排程機制負責（移除重複排程），並在推播前檢查 `is_sent` 旗標以防止重複推播

2.4 WHEN `_send_line_push()` 或任何 LINE API 呼叫失敗時 THEN the system SHALL 記錄包含 HTTP 狀態碼、錯誤訊息、時間戳的結構化日誌到 `logs/line_bot.log`，並向呼叫端回傳具體錯誤資訊

2.5 WHEN `reminders.json` 中存在 `status: "pending"` 且 `notified: False` 的提醒項目，且提醒時間已到達 THEN the system SHALL 自動推播格式化的提醒通知給照護者的 LINE，並將 `notified` 標記為 `True`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 照護者透過 LINE 傳送文字或語音留言給長者 THEN the system SHALL CONTINUE TO 正確接收並存入留言佇列（webhook 功能不受影響）

3.2 WHEN 長者與 AI 進行正常對話（不觸發提醒或緊急關鍵詞）THEN the system SHALL CONTINUE TO 正常執行 ASR、LLM 串流、TTS 合成等對話流程

3.3 WHEN `weather_cron.py` 定期更新天氣與日落資料 THEN the system SHALL CONTINUE TO 正確生成 `Environmental_Prompts.txt` 環境提示詞

3.4 WHEN 照護者在 LINE 中輸入「今日動態」指令 THEN the system SHALL CONTINUE TO 回覆今日動態摘要（reply 功能不受影響）

3.5 WHEN Dashboard 前端請求長者資料（`/api/elder/{elder_id}`）THEN the system SHALL CONTINUE TO 正確回傳完整看板資料
