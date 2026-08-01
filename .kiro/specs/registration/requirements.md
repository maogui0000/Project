# Requirements Document

## Introduction

本模組為「智慧長照陪伴系統」的**使用者管理模組**，負責長者註冊流程與 PIN 碼設定。

註冊完成後帳號資料綁定在該裝置的瀏覽器（localStorage），換裝置需重新輸入 PIN 碼登入。

### 模組間依賴關係

- **下游 — 記憶管理模組（Memory_Manager）**：註冊完成後將 elder_profile 寫入 Memory_Manager
- **下游 — 通知與看板模組（Notification_Service）**：照護者 LINE User ID 供推播使用
- **消費端 — 語音介面模組**：透過 Memory_Manager 讀取 elder_profile 進行個人化互動

### 設計原則

- 註冊流程必須簡潔，適合年長使用者或其照護者操作
- 註冊完直接綁定，不需要額外的登入流程
- PIN 碼自行設定，用於換裝置時驗證身分
- 本系統目前僅支援繁體中文

## Requirements

### 需求 1：長者註冊流程 — 基本身分與居住地

**使用者故事：** 身為照護者或長者本人，我希望透過簡單的表單完成長者的基本資料註冊，以便系統能提供個人化的陪伴服務。

#### 驗收條件

1. THE Registration_Service SHALL 提供註冊表單區塊一「基本身分與居住地」，包含以下欄位：真實姓名（文字輸入框）、慣稱/稱呼（文字輸入框，如「王爺爺」「陳媽媽」）、年齡或出生年月日（數字輸入框）、居住地（文字輸入框）
2. THE Registration_Service SHALL 將居住地資訊用於天氣查詢的地區定位
3. THE Registration_Service SHALL 僅將「真實姓名」與「慣稱」設為必填欄位，其餘欄位皆為選填
4. THE Registration_Service SHALL 支援從前端 Web 頁面進入註冊流程

### 需求 2：長者註冊流程 — 感官與語言偏好

**使用者故事：** 身為照護者，我希望能設定長者的聽力狀況與語言偏好，以便系統調整語音播放方式。

#### 驗收條件

1. THE Registration_Service SHALL 提供註冊表單區塊二「感官與語言偏好」，包含：慣用語言（目前僅支援中文，顯示為固定值）、聽力狀況（單選：聽力良好 / 聽力稍弱需較大音量或放慢速度）
2. WHEN 聽力狀況設定為「聽力稍弱」時，THE Registration_Service SHALL 在 elder_profile 中記錄此偏好，供語音介面模組調整 TTS 音量與播放速度
3. THE Registration_Service SHALL 將語言偏好寫入 elder_profile.localization_settings.primary_language

### 需求 3：長者註冊流程 — 興趣與話題偏好

**使用者故事：** 身為照護者，我希望能設定長者喜愛的聊天話題和興趣，以便 AI 助理能主動聊長者感興趣的內容。

#### 驗收條件

1. THE Registration_Service SHALL 提供註冊表單區塊三「興趣與話題偏好」，包含：喜愛聊天的話題/興趣（多選標籤 + 自由填寫，預設標籤如：過往回憶、戲曲、烹飪、寵物、日常閒聊、運動健康、家人）、長者最近心裡在惦記的事/想記著的備忘（文字輸入框）
2. THE Registration_Service SHALL 將話題偏好寫入 elder_profile，供 LLM 在對話中參考
3. WHEN 長者填寫了備忘事項，THE Registration_Service SHALL 將其作為初始 reminder 寫入 reminders 資料中

### 需求 4：PIN 碼設定

**使用者故事：** 身為照護者，我希望設定一組 PIN 碼，在換裝置或重新開啟時能快速驗證身分。

#### 驗收條件

1. THE Registration_Service SHALL 在註冊最後步驟提供 PIN 碼設定欄位（4~6 位數字）
2. THE Registration_Service SHALL 將 PIN 碼以雜湊（hash）方式儲存於 elder_profile.meta.pin_hash 中，不得明文保存
3. WHEN 使用者在新裝置開啟系統時，THE System SHALL 要求輸入「慣稱 + PIN 碼」進行驗證
4. IF PIN 碼連續輸入錯誤 5 次，THEN THE System SHALL 鎖定 15 分鐘
5. THE Registration_Service SHALL 支援照護者在 Dashboard 設定頁重設 PIN 碼

### 需求 5：帳號綁定與裝置管理

**使用者故事：** 身為長者，我希望在同一台裝置上不用每次都輸入密碼。

#### 驗收條件

1. WHEN 註冊完成或 PIN 碼驗證成功後，THE System SHALL 將 elder_id 存入瀏覽器 localStorage，此後開啟系統自動載入帳號
2. IF localStorage 中沒有 elder_id（新裝置或清除資料後），THEN THE System SHALL 顯示「慣稱 + PIN 碼」驗證畫面
3. THE System SHALL 不使用 session token 或 cookie 認證，完全依賴 localStorage 進行裝置綁定

### 需求 6：帳號管理與資料修改

**使用者故事：** 身為照護者，我希望能修改長者的資料。

#### 驗收條件

1. THE Registration_Service SHALL 提供帳號資料修改功能，允許照護者在 Dashboard 更新 elder_profile 中的所有欄位
2. WHEN 帳號資料修改後，THE Registration_Service SHALL 同步更新 elder_profile 並更新 meta.last_updated 時間戳
