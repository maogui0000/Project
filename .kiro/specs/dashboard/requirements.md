# Requirements Document

## Introduction

本規格書涵蓋智慧長照陪伴系統中的「通知與看板模組」（Notification and Dashboard Module）。此模組負責照護者儀表板視覺化呈現、LINE Bot 定時推播與照護者主動查詢、以及照護者端到端使用者旅程。

系統整體架構中，本模組接收來自 Memory_Manager 產出的結構化日誌資料（dashboard_logs.json），並透過 Dashboard 與 LINE Bot 將長者生活摘要傳遞給照護者。

**語言支援聲明**：本系統目前僅支援繁體中文。

### 模組間依賴關係

- **上游資料來源 — 記憶管理模組（Memory_Manager）**：`dashboard_logs.json`、elder_profile、reminders
- **觸發上游 — LLM 功能層（Summary_Generator）**：排程器觸發每日摘要生成 / 照護者主動查詢時觸發即時摘要
- **共用 — 使用者管理模組（user_management）**：LINE 綁定認證流程由 user_management 統一處理，本模組消費其綁定結果
- **無直接互動 — 語音介面模組**：所有資料透過 Memory_Manager 間接取得

## Glossary

- **Dashboard（儀表板）**: 照護者多頁式資訊介面
- **Notification_Service（推播服務）**: LINE Bot 推播與互動模組
- **Memory_Manager（記憶管理器）**: 產出 dashboard_logs.json、管理 elder_profile 與 reminders
- **Summary_Generator（摘要生成器）**: LLM 功能層子模組
- **dashboard_logs.json**: 每日報告結構化檔案

## Requirements

### 需求 1：照護者儀表板 — 多頁式視覺化

**使用者故事：** 身為照護者，我希望儀表板以分頁方式呈現不同類型的資訊，避免畫面過於擁擠，讓我能有條理地查閱長者狀態。

#### 驗收條件

1. THE Dashboard SHALL 採用多頁式（Multi-page）架構，至少包含以下頁面：首頁總覽、長者資料頁、每日摘要頁、情緒趨勢頁、互動統計頁、事件時間軸頁、提醒事項頁、設定頁
2. THE Dashboard 首頁總覽 SHALL 顯示：今日摘要文字（today_summary.text 節錄）、關鍵指標卡片（用藥狀態、最新情緒、當日互動次數）、異常警示（medication_taken=false 或負面情緒時醒目標示）、LINE 通知狀態
3. THE Dashboard 長者資料頁 SHALL 顯示 elder_profile 中的所有已填寫欄位：personal_info（姓名、慣稱、年齡、居住地）、sensory_preferences（聽力狀況、語言）、interests（話題偏好、興趣、備忘）、medication_schedule（用藥時間表）、caregiver_settings（LINE 綁定狀態）。未填寫的欄位顯示「尚未填寫」並提供編輯入口
4. THE Dashboard 每日摘要頁 SHALL 採用「簡要摘要 + 點擊展開詳情」的分層顯示模式：
   - **預設簡要視圖**：每個類別（飲食、用藥、睡眠、活動、情緒、健康、社交、認知）以條列式呈現結構化摘要，格式如：
     ```
     飲食：
       早上 09:00 — 稀飯半碗
       中午 12:00 — 拉麵一碗
       晚上 — 未提及
     用藥：
       中午 12:30 — 降血壓藥（已服藥）✓
       晚上 — 未提及
     ```
   - **點擊展開詳情**：每個摘要項目下方提供「查看詳細資訊」可展開區塊，展開後顯示：判斷依據原文引用（source_quote）、分類理由（reason）、重要性等級、記錄時間
   - IF 某類別當日無任何相關紀錄，THEN THE Dashboard SHALL 顯示「未提及」而非隱藏該類別
   - THE Dashboard SHALL 支援切換查看歷史日期的摘要
5. THE Dashboard 每日摘要頁的「情緒」類別 SHALL 以長者的**當前/整體情緒狀態**為主體呈現，而非逐時間點列出：
   - 預設顯示：當前情緒標籤 + 情緒圖示 + 一句話 AI 生成的情緒描述（如「今天聊到孫子很開心，整體心情不錯」）
   - 若當日情緒有明顯變化，以簡短文字補充趨勢方向（如「上午偏低落，下午聊天後好轉」）
   - 點擊展開詳情後，方顯示各時間點的情緒記錄明細（時間、情緒標籤、原因、原文引用）
   - 時間軸式的情緒變化細節由「情緒與互動趨勢頁」承接，摘要頁僅呈現結論性描述
6. THE Dashboard 每日摘要頁的「用藥」類別 SHALL 以下列格式清楚區分各時段的服藥狀態：
   - 使用明確圖示區分四種狀態：✓ 已服藥（綠色）、⏳ 待確認/需服藥（黃色）、✗ 未服藥/漏服（紅色）、— 不適用（灰色）
   - 依時段（早上/中午/下午/晚上）逐一列出每種藥物的狀態
   - IF elder_profile 中有設定 medication_schedule，THEN THE Dashboard SHALL 自動比對排程與實際紀錄，標示可能的漏服時段
   - 範例格式：
     ```
     用藥：
       早上 08:00 — 降血壓藥 ✓ 已服藥
       中午 12:30 — 降血糖藥 ⏳ 待確認（排程時間已到，尚未提及）
       晚上       — 降血壓藥 ✗ 未服藥（長者表示忘記吃）
     ```
7. THE Dashboard 情緒趨勢頁 SHALL 以大型折線圖（佔頁面主要區域）呈現長者**最近 20 筆情緒記錄**的變化趨勢（時間跨度不固定，可能涵蓋數小時至數天，取決於互動頻率），圖表下方顯示：
   - 當前情緒狀態區塊：大字顯示最新情緒標籤 + 圖示 + AI 生成的一句話情緒描述
   - 圖表 X 軸為各筆記錄的實際時間戳，Y 軸為情緒等級（從負面到正面），每個數據點標示情緒標籤
   - 可點擊圖表上的任一數據點或下方「查看詳細記錄」展開該筆情緒的明細（時間、情緒標籤、原因、source_quote 原文引用）
   - 圖表中若出現明顯情緒低谷或連續負面趨勢，SHALL 以紅色標記提醒照護者注意
8. THE Dashboard 互動統計頁 SHALL 以長條圖呈現最近 7 天的每日互動次數（interaction_stats.weekly_trend 中的 day 與 count），並在圖表下方顯示當日累計互動次數（total_turns）
9. THE Dashboard 事件時間軸頁 SHALL 將 timeline_events 依時間由早到晚排序，以時間軸形式呈現各事件的 time、type、title、description。事件的 type 統一使用系統分類：diet（🍚飲食）、medication（💊用藥）、sleep（😴睡眠）、activity（🏃活動）、emotion（😊情緒）、health（🏥健康）、social（👥社交）、cognitive（🧠認知）、system（⚙️系統事件，如對話開始/結束、提醒觸發）、other（📌其他）。每個事件以對應類別的圖示標示。頁面頂部 SHALL 提供類別篩選列，照護者可勾選/取消勾選特定類別以過濾顯示的事件（預設為全選顯示所有類別）
10. THE Dashboard 提醒事項頁 SHALL 顯示長者目前所有 reminders（含 pending 與歷史 notified 狀態），並標示各提醒的 content、remind_at 時間、狀態
11. THE Dashboard 設定頁 SHALL 包含以下功能區塊：
    - **帳號資訊**：顯示當前登入方式（LINE 帳號名稱）、PIN 碼狀態（已設定/未設定）、提供重設 PIN 碼功能、顯示上次登入時間
    - **裝置管理**：顯示已綁定的語音裝置名稱與綁定時間、提供解除綁定功能（需二次確認）
    - **通知偏好**：LINE 推播開關、每日推播時間調整、長者傳話即時通知開關
    - **隱私與資料**：查看完整隱私權政策說明、顯示同意狀態與同意時間、提供「匯出我的資料」功能（下載 JSON 格式）、提供「刪除帳號」功能（需二次確認，提示 30 天內永久清除）
    - **系統資訊**：系統版本號、語言支援說明（僅繁體中文）、聯繫方式

### 需求 2：LINE Bot 定時推播

**使用者故事：** 身為照護者，我希望每天收到長者的生活摘要推播。

#### 驗收條件

1. THE Notification_Service SHALL 於每日 18:50（UTC+8）觸發 Summary_Generator 每日摘要生成 API
2. THE Notification_Service SHALL 於每日 19:00（UTC+8）透過 LINE Bot 推送當日摘要，30 秒內送達
3. WHEN 19:00 時 dashboard_logs.json 尚未更新，THE Notification_Service SHALL 每 30 秒檢查，最多等 5 分鐘
4. IF 超過 5 分鐘仍未更新，THEN THE Notification_Service SHALL 以現有資料推送並標示可能不完整
5. THE Notification_Service SHALL 推播內容包含：飲食摘要、互動次數、整體狀態節錄、最新情緒、用藥狀態
6. IF 當日互動次數=0，THEN THE Notification_Service SHALL 推送提醒照護者關注長者
7. IF 推播失敗，THEN THE Notification_Service SHALL 1 分鐘後重試，最多 3 次

### 需求 3：LINE Bot 照護者主動查詢

**使用者故事：** 身為照護者，我希望能隨時透過 LINE 主動詢問長者目前的狀況，而不是只能等每日推播或登入 Dashboard。

#### 驗收條件

1. WHEN 照護者透過 LINE Bot 發送查詢訊息（如「今天狀況如何？」「現在好嗎？」），THE Notification_Service SHALL 觸發 LLM 功能層的 Summary_Generator 進行即時摘要生成（基於當日已有的對話紀錄）
2. THE Notification_Service SHALL 在收到照護者查詢後 30 秒內回覆一份當前時點的長者狀態摘要
3. THE Notification_Service SHALL 在即時摘要中包含：最近一次對話的時間、當日已進行的互動次數、最新情緒狀態、是否已服藥、簡短的 AI 生成狀態描述
4. IF 當日尚無任何對話紀錄，THEN THE Notification_Service SHALL 回覆告知照護者長者今日尚未與系統互動
5. WHEN 長者透過對話表達想傳話給照護者（如「幫我跟女兒說我很好」），THE Notification_Service SHALL 透過 LINE Bot 將長者的訊息即時轉達給照護者
6. WHEN 照護者透過 LINE Bot 發送非查詢類的一般對話訊息，THE Notification_Service SHALL 將該訊息存為留言（存入 messages.json），等待長者上線時播報。同時回覆照護者「✅ 留言已送出」確認

### 需求 4：LINE 平台認證（共用 user_management）

**使用者故事：** 身為照護者，我希望 LINE 綁定流程安全且只需進行一次。

#### 驗收條件

1. THE Notification_Service SHALL 消費 user_management 模組提供的 LINE 綁定關係資料（照護者 LINE User ID ↔ 長者 elder_id）
2. THE Notification_Service SHALL 在每次推播或回覆前驗證綁定狀態有效
3. WHEN 照護者要求解除綁定（透過 LINE Bot 或 Dashboard），THE Notification_Service SHALL 於 5 秒內停止推播服務
4. THE Notification_Service SHALL NOT 自行實作 LINE OAuth 流程，而是依賴 user_management 的 Registration_Service 或 Dashboard 設定頁面完成綁定

### 需求 5：端到端使用者旅程

**使用者故事：** 身為照護者，我希望從註冊到日常使用的流程簡單直覺。

#### 驗收條件

1. THE System SHALL 支援完整照護者旅程：註冊（user_management）→ LINE 綁定（選填）→ 每日推播 / 主動查詢 → Dashboard 多頁查閱 → 趨勢追蹤
2. WHEN 照護者收到 LINE 推播，THE Notification_Service SHALL 提供可直接開啟 Dashboard 對應日期摘要頁的連結
3. THE Dashboard SHALL 採用以下整體佈局結構：
   - **頂部列（Top Bar）**：左側顯示系統名稱與 Logo（小黃陪伴系統）、中間顯示當前長者慣稱（如「王爺爺」）、右側顯示設定圖示與登出按鈕
   - **側邊導航列（Side Navigation）**：垂直排列所有頁面入口（🏠 首頁、👤 長者資料、📋 每日摘要、😊 情緒趨勢、📊 互動統計、⏱️ 事件時間軸、🔔 提醒事項），底部放置 ⚙️ 設定入口。當前所在頁面以高亮標示
   - **主要內容區（Main Content）**：佔據側邊導航右側的全部剩餘空間，顯示當前頁面內容
   - 在手機/平板等小螢幕裝置上，側邊導航 SHALL 收合為漢堡選單（hamburger menu），點擊後展開
4. IF 推播連結存取時 token 過期，THEN THE Dashboard SHALL 引導重新認證

### 需求 6：個資保護與資安規範

**使用者故事：** 身為照護者，我希望個人資料受到妥善保護。

#### 驗收條件

1. THE Notification_Service SHALL 以加密方式儲存 LINE User ID 與綁定關係
2. THE Dashboard SHALL 所有通訊透過 HTTPS
3. THE Notification_Service SHALL 為 Dashboard token 設定有效期限（不超過 24 小時）
4. THE System SHALL 確保照護者僅能存取綁定的長者資料
5. THE System SHALL 在測試環境使用去識別化模擬資料
