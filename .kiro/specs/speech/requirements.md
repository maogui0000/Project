# Requirements Document

## Introduction

本模組為長照語音互動專案（小黃語音助理）的核心語音介面模組。系統專為年長使用者設計，提供語音喚醒（或按鈕觸發）、語音辨識、即時串流語音合成、前端同步控制等功能。目標是讓年長使用者能以自然口語方式與 AI 助理互動，並確保回應延遲降至最低。

**語言支援聲明**：本系統目前僅支援繁體中文（國語/普通話）語音互動。

**技術選型**：
- ASR（語音辨識）：前端使用**瀏覽器 Web Speech API**（主要），後端備援使用本地 Taiwan-Tongues-ASR 模型
- TTS（語音合成）：使用 **Edge-TTS**（微軟免費 API，zh-TW 語音）
- 喚醒詞偵測：使用前端 **Web Speech API** 持續監聽偵測「小黃」關鍵詞
- 串流通訊：使用 **SSE（Server-Sent Events）** 逐句串流回覆

### 模組間依賴關係

- **下游 — LLM 功能層（LLM_Service）**：透過 SSE 端點傳送使用者文字並接收 LLM 逐句回覆
- **下游 — 記憶管理模組（Memory_Manager）**：每次互動觸發互動計數 + 對話記錄寫入
- **上游 — 記憶管理模組（Memory_Manager）**：讀取未讀留言（Messages）供對話開始時播報
- **外部 — Edge-TTS**：文字轉語音合成（微軟免費服務）

## Glossary

- **語音介面模組 (Voice_Interface_Module)**：本系統的前端語音互動層，負責喚醒偵測、ASR、TTS、UI 同步
- **喚醒詞偵測 (Wake Word Detection)**：前端 Web Speech API 持續監聽，偵測到「小黃」時啟動對話
- **ASR（瀏覽器 Web Speech API）**：瀏覽器原生語音辨識，即時轉文字
- **TTS（Edge-TTS）**：微軟 Edge 語音合成服務，支援繁體中文多種語音
- **VAD (Voice Activity Detection)**：語音活動偵測，區分使用者說話與環境噪音/靜音
- **SSE (Server-Sent Events)**：伺服器推送事件，用於逐句串流 LLM 回覆 + TTS 音檔
- **TTFB (Time-To-First-Byte)**：收到使用者輸入到播出第一句回覆語音的延遲

## Requirements

### 需求 1：語音喚醒與對話啟動

**使用者故事：** 身為一名年長使用者，我希望只要說出「小黃小黃」或按一下畫面上的按鈕就能開始跟 AI 助理聊天。

#### 驗收條件

1. WHILE 系統處於待機狀態，THE 前端 SHALL 使用 Web Speech API（continuous mode）持續監聽麥克風
2. WHEN 偵測到語音中包含「小黃」關鍵詞，THE 系統 SHALL 啟動對話模式
3. THE 前端 SHALL 在畫面中央顯示一個大圓形按鈕，使用者可點擊按鈕直接啟動對話（效果等同喚醒詞）
4. WHEN 對話啟動時，THE 系統 SHALL 先檢查是否有未讀留言（呼叫 `/api/messages/{elder_id}/unread`），有的話進入留言播報流程
5. IF 瀏覽器不支援 Web Speech API（如非 HTTPS 環境），THEN THE 系統 SHALL 保持按鈕可用，使用者仍可按按鈕啟動對話
6. WHILE 系統處於對話模式中，THE 喚醒詞偵測 SHALL 暫停以避免重複觸發

### 需求 2：語音辨識與傳送

**使用者故事：** 身為一名年長使用者，我希望可以慢慢說話，系統會聽我說完才回覆。

#### 驗收條件

1. WHEN 系統進入對話模式，THE 前端 SHALL 開啟麥克風錄音，同時啟動瀏覽器 Web Speech API 做即時語音辨識
2. THE 前端 SHALL 使用 VAD（音量閾值偵測）判斷使用者是否在說話
3. WHEN VAD 偵測到使用者停止說話（靜音超過設定閾值），THE 系統 SHALL 將辨識完成的文字送出至後端 `/api/chat/stream` API
4. THE 前端 SHALL 同時將原始錄音資料保存，作為後端 ASR 的 fallback（`/api/asr` 端點）
5. IF 瀏覽器 Web Speech API 辨識失敗或不可用，THEN THE 系統 SHALL 將錄音送至後端 `/api/asr` 做伺服器端辨識
6. THE 前端 SHALL 支援繁體中文語音辨識（`lang = 'zh-TW'`）
7. WHEN 對話超過最大閒置時間（無人說話），THE 系統 SHALL 自動結束對話並回到待機

### 需求 3：即時 TTS 串流語音合成（Edge-TTS）

**使用者故事：** 身為一名年長使用者，我希望 AI 的回覆能被快速唸出來，不需要閱讀螢幕文字。

#### 驗收條件

1. WHEN 後端 LLM 產出一個完整句子，THE 後端 SHALL 即時呼叫 Edge-TTS 合成該句語音（mp3）
2. THE 後端 SHALL 透過 SSE 將每句的文字 + 音檔 URL 推送給前端
3. THE 前端 SHALL 收到一句就立即播放一句，實現逐句串流播放
4. THE TTS 語音 SHALL 使用台灣繁體中文女聲（`zh-TW-HsiaoChenNeural`）
5. WHILE 播放當前句子時，THE 後端 SHALL 同時合成下一句，減少句間等待
6. IF Edge-TTS 合成失敗，THEN THE 前端 SHALL 使用瀏覽器內建 `speechSynthesis` 作為 fallback
7. WHEN 所有句子播放完畢，THE 系統 SHALL 重新開始監聽使用者語音（繼續對話）

### 需求 4：前端 UI 與同步控制

**使用者故事：** 身為一名年長使用者，我希望螢幕上的顯示能讓我清楚知道系統在做什麼。

#### 驗收條件

1. THE 前端 SHALL 使用狀態機管理 UI：waiting_wake（待機）→ listening（錄音中）→ recording（處理中）→ speaking（回覆中）
2. THE 前端按鈕 SHALL 根據狀態顯示不同顏色與圖示：
   - 待機：綠色脈衝動畫 + 🎙️
   - 錄音中：紅色脈衝動畫 + ⏺️
   - 處理中：旋轉動畫 + ⏳
   - 回覆中：藍色脈衝動畫 + 🔊
3. WHEN AI 正在回覆時，THE 前端 SHALL 在畫面上顯示回覆文字（逐句更新）
4. THE 前端 SHALL 確保字體大小適合年長使用者閱讀（不小於 18px）
5. WHEN 使用者在 AI 說話時按下按鈕，THE 系統 SHALL 停止當前播放（打斷機制）

### 需求 5：告別偵測與對話結束

**使用者故事：** 身為一名年長使用者，我希望說「掰掰」或表示想結束時，系統會好好道別然後回到待機。

#### 驗收條件

1. WHEN 使用者的文字送至後端，THE 後端 SHALL 使用 LLM 判斷是否有告別意圖（farewell_detection_prompt.txt）
2. IF 判定為告別，THEN THE 後端 SHALL 在 SSE 的 done 事件中回傳 `end_session: true`
3. WHEN 前端收到 `end_session: true`，THE 前端 SHALL 播放完最後回覆後回到待機狀態
4. THE 後端 SHALL 在 Session 結束時觸發背景記憶分析（摘要生成、情緒更新、LINE 推播）
5. WHEN 閒置超過 2 分鐘無互動，THE 後端 SHALL 自動觸發 Session 結束分析

### 需求 6：語音資料處理

**使用者故事：** 身為系統管理員，我希望語音處理不會佔用過多伺服器空間。

#### 驗收條件

1. THE 後端 SHALL NOT 永久儲存使用者的原始語音檔案；TTS 產出的暫存 mp3 於前端下載後立即刪除
2. THE 後端 SHALL 僅保留 ASR 轉譯的文字結果（透過 Memory_Manager 存入對話記錄）
3. THE 系統 SHALL 支援繁體中文（國語）語音互動
