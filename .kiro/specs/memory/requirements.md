# Requirements Document

## Introduction

本模組為「智慧長照陪伴系統」的**數據核心與唯一持久化層**，負責長者所有結構化資料的儲存與管理，包含：長者註冊資料（elder_profile）、長期記憶事件、短期對話上下文、提醒事項（reminders）、留言板（messages）、情緒歷史追蹤、互動統計與每日報告輸出。所有儲存媒介統一採用 JSON 格式。

本模組為系統中**所有長者資料的唯一 Source of Truth**：其他模組（LLM 功能層、語音介面模組、通知與看板模組）須透過本模組提供的 API 進行資料讀寫，不得自行實作持久化邏輯。

**重要區分**：本模組僅負責「資料」的儲存與讀寫。LLM 的對話風格、人設指令、安全限制等屬於「提示詞（Prompt Templates）」層面，由 LLM 功能層自行管理，不存放於本模組。

### 模組間依賴關係

- **上游 — 語音介面模組（Voice_Interface_Module）**：接收對話 session 結束事件與互動計數
- **上游 — LLM 功能層（Dialogue_Engine）**：接收對話文本、情緒分析結果、提醒事項寫入
- **上游 — LLM 功能層（Summary_Generator）**：接收每日結構化摘要 JSON
- **外部 — 中央氣象署 CWA Open Data API**：定時取得天氣資訊寫入 active_context
- **下游 — LLM 功能層（Dialogue_Engine）**：提供短期對話上下文、長者註冊資料、active_context
- **下游 — LLM 功能層（Summary_Generator）**：提供長記憶事件清單、情緒歷史
- **下游 — 通知與看板模組（Dashboard / Notification_Service）**：提供 dashboard_logs.json
- **下游 — 語音介面模組**：提供提醒事項供主動發話觸發

### 不負責的範疇

- AI 對話文本生成與提示詞管理（LLM 功能層的 Prompt Templates）
- 語音辨識 / 合成（語音介面模組）
- 上下文 token 預算管理與壓縮策略（LLM 功能層）
- 情緒分析推論（LLM 功能層透過文字關鍵詞偵測執行）

## Glossary

- **Memory_Manager（記憶管理器）**：本模組的核心服務，負責所有 JSON 資料檔案的結構化讀寫與清理
- **elder_profile（長者註冊資料）**：長者的完整個人資料，包含 personal_info、medical_safety、physical_care、mental_cognitive、localization_settings 等區塊
- **Long-term Memory（長期記憶）**：重要生活事件的儲存，依重要性設定不同 TTL（15天至永久）
- **Short-term Context（短期對話上下文）**：包含 active_context（天氣/時間/話題）與 dialogue_history，每條對話依重要性有不同 TTL
- **Reminders（提醒事項）**：長者透過對話提出的提醒需求（如服藥提醒），由系統到時主動通知
- **Messages（留言板）**：照護者透過 LINE Bot 傳送的留言，待長者上線時播報
- **emotion_history（情緒歷史）**：文字情緒（關鍵詞偵測）的時序記錄
- **dashboard_logs.json**：本模組產出的每日報告結構化檔案，為通知與看板模組的唯一資料來源
- **CWA Open Data API**：中央氣象署開放資料平台，提供天氣預報與即時觀測資料

## Requirements

### 需求 1：長者註冊資料管理（Elder Profile）

**使用者故事：** 身為系統管理員，我希望有統一的長者資料管理 API，以便所有模組都從同一來源取得長者資訊，確保資料一致性。

#### 驗收條件

1. THE Memory_Manager SHALL 提供長者註冊資料（elder_profile）的 CRUD API，支援新增、查詢、更新操作
2. THE Memory_Manager SHALL 確保 elder_profile 包含以下資料區塊：personal_info（姓名、慣稱、性別、年齡、居住地）、emergency_contact（緊急聯絡人）、medical_safety（慢性疾病、用藥、過敏）、physical_care（行動能力、飲食禁忌）、mental_cognitive（失智狀態、認知備註）、localization_settings（語言、TTS 口音偏好、persona_relation）
3. THE Memory_Manager SHALL 支援依 elder_id 查詢完整的長者註冊資料
4. THE Memory_Manager SHALL 為每筆 elder_profile 自動維護 meta 欄位（created_at、last_updated）
5. WHEN LLM 功能層需要長者資料時，THE LLM 功能層 SHALL 透過本 API 取得 elder_profile，再自行結合 Prompt Templates 組裝 system prompt

### 需求 2：長期記憶管理 — 重要性分級 TTL

**使用者故事：** 身為照護者，我希望系統能依據事件重要性自動管理記憶保留期限，讓關鍵醫療資訊永久保存，而一般生活事件在適當時間後自動清理。

#### 驗收條件

1. THE Memory_Manager SHALL 提供長記憶事件的 CRUD 操作：新增、查詢、刪除
2. WHEN 新增長記憶事件時，THE Memory_Manager SHALL 儲存以下欄位：category（事件類別：medication/diet/sleep/activity/emotion/health/other）、content（內容描述）、importance（重要性等級）、recorded_at（記錄時間）、expires_at（過期時間）、ttl_days（保留天數）
3. THE Memory_Manager SHALL 依據 importance 等級自動設定 TTL：permanent（藥物過敏、慢性病等醫療安全資訊）→ ttl_days=99999（永久）；high（跌倒、住院等重要事件）→ ttl_days≥365；medium（情緒波動、特殊飲食等）→ ttl_days=30-90；low（一般飲食、運動等日常事件）→ ttl_days=15-30
4. THE Memory_Manager SHALL 每次操作時自動清除已超過 expires_at 的過期記錄
5. THE Memory_Manager SHALL 確保 importance=permanent 的記錄不會被系統自動清理

### 需求 3：短期對話上下文管理

**使用者故事：** 身為年長使用者，我希望系統記得我們正在聊的話題和之前說過的事，並且能根據天氣和時間自然地調整對話。

#### 驗收條件

1. THE Memory_Manager SHALL 為每位長者維護一份短期對話上下文（short_term_memory），包含 current_session_id、active_context 與 dialogue_history
2. THE Memory_Manager SHALL 在 active_context 中儲存以下即時情境資訊：weather（天氣狀態）、current_time（當前時間）、topic_focus（當前話題焦點）
3. THE Memory_Manager SHALL 提供 dialogue_history 的新增與查詢 API，每筆對話紀錄包含：turn（輪次）、timestamp、expires_at、ttl_minutes（依重要性分級：30/60/240 分鐘）、user（長者發言）、ai（AI 回覆）、is_flagged_for_long_term（是否標記轉存長期記憶）
4. THE Memory_Manager SHALL 依據每筆對話的 ttl_minutes 進行個別過期清除
5. WHEN 對話被標記 is_flagged_for_long_term=true 時，THE Memory_Manager SHALL 將該對話內容轉存至長期記憶

### 需求 4：天氣資訊整合（CWA Open Data API）

**使用者故事：** 身為年長使用者，我希望 AI 助理能根據今天的天氣狀況提醒我注意事項，讓對話更自然貼心。

#### 驗收條件

1. THE Memory_Manager SHALL 透過中央氣象署 CWA Open Data API 定時取得長者所在地的天氣預報資訊（溫度、天氣描述、降雨機率）
2. THE Memory_Manager SHALL 定期更新天氣資訊，並寫入環境提示詞檔案
3. THE Memory_Manager SHALL 使用已配置的 CWA API 授權碼進行 API 呼叫，授權碼儲存於環境變數中
4. IF CWA API 呼叫失敗，THEN THE Memory_Manager SHALL 保留上次成功取得的天氣資料
5. THE Memory_Manager SHALL 依據 elder_profile.personal_info.location 決定查詢哪個地區的天氣預報

### 需求 5：提醒事項管理（Reminders）

**使用者故事：** 身為年長使用者，我希望能口頭告訴 AI 助理我需要提醒的事情（如吃藥時間），到時間時助理會主動提醒我。

#### 驗收條件

1. THE Memory_Manager SHALL 提供提醒事項的 CRUD API，每筆提醒包含：content（提醒內容）、requested_by（請求來源）、created_at（建立時間）、status（pending / notified）、notified（是否已通知）
2. WHEN LLM 功能層從對話中辨識出提醒意圖（如「下午一點要吃藥」），THE LLM 功能層 SHALL 透過本 API 新增一筆提醒事項
3. WHEN 提醒被成功通知後，THE Memory_Manager SHALL 將該筆提醒的 status 更新為 notified
4. THE Memory_Manager SHALL 支援依 elder_id 查詢所有提醒，供 Dashboard 顯示

### 需求 6：留言板管理（Messages）

**使用者故事：** 身為照護者，我希望能透過 LINE Bot 傳留言給長者，長者上線時會收到通知。

#### 驗收條件

1. THE Memory_Manager SHALL 提供留言的 CRUD API，每筆留言包含：message_id、sender_name、content_type（text/audio）、content_text、content_audio_path、status（unread/read/replied）、created_at、read_at、reply_text、replied_at
2. THE Memory_Manager SHALL 提供取得未讀留言（status=unread）的查詢 API
3. THE Memory_Manager SHALL 支援標記留言為已讀（更新 status 和 read_at）
4. THE Memory_Manager SHALL 支援為留言新增回覆（更新 status、reply_text、replied_at）

### 需求 7：情緒歷史追蹤（Emotion History）

**使用者故事：** 身為照護者，我希望能在儀表板上看到長者的情緒趨勢變化，以便及早發現異常情緒狀態並給予關懷。

#### 驗收條件

1. THE Memory_Manager SHALL 為每位長者維護 emotion_history 時序陣列，每筆記錄包含：time（時間戳）、emotion（情緒標籤，如「開心」「難過」「生氣」「中立」「未檢測」）、reason（情緒原因描述）、confidence（信心分數 0.0~1.0）、source（來源：「text」表示文字關鍵詞偵測）
2. WHEN 對話中偵測到情緒變化（文字關鍵詞比對），THE System SHALL 寫入一筆 emotion_history 記錄（source=text）
3. THE Memory_Manager SHALL 保留 emotion_history 記錄供 Dashboard 情緒趨勢圖表使用
4. THE Memory_Manager SHALL 提供依 elder_id + 時間範圍查詢 emotion_history 的 API

### 需求 8：互動統計與每日報告輸出（Dashboard Logs）

**使用者故事：** 身為照護者，我希望儀表板能直接讀取結構化的每日報告，包含互動統計、情緒趨勢、生活摘要與時間軸事件。

#### 驗收條件

1. THE Memory_Manager SHALL 記錄長者每日互動次數（total_turns）
2. THE Memory_Manager SHALL 負責產出並維護 dashboard_logs.json，此檔案為通知與看板模組的唯一資料來源
3. THE Memory_Manager SHALL 確保 dashboard_logs.json 包含以下結構：elder_id、report_date、line_notification_status、today_summary（text + metrics）、interaction_stats（total_turns / weekly_trend）、timeline_events 陣列
4. THE Memory_Manager SHALL 確保 today_summary.metrics 包含：diet、sleep、medication_taken、medication_time、latest_emotion、emotion、medication_name、medication_by_period、emotion_reason、activity
5. WHEN LLM 功能層完成每日摘要生成後，THE Memory_Manager SHALL 將摘要結果寫入 dashboard_logs.json
