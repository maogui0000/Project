# Requirements Document

## Introduction

本模組為長照語音互動專案（小黃語音助理）的安全防護模組（Security Protection Module）。針對系統面臨的常見 Web 安全威脅，提供目錄遍歷與資訊洩露防護、API 參數與路徑加密傳輸、以及使用者註冊防注入等機制，確保系統在對外服務時具備基本的安全防線。

### 模組間依賴關係

- **上游 — 使用者管理模組（User_Management）**：註冊流程的輸入驗證與防注入機制需與使用者管理模組協同
- **橫切 — 所有對外 API 模組**：參數加密與路徑保護機制適用於所有暴露的 RESTful / WebSocket 端點
- **外部 — API Gateway / Reverse Proxy**：部分安全策略（如路徑白名單、速率限制）可於 API Gateway 層實施

## Glossary

- **目錄遍歷攻擊 (Directory Traversal / Path Traversal)**：攻擊者透過構造含 `../` 等特殊字元的路徑，試圖存取伺服器上未授權的檔案或目錄
- **資訊洩露 (Information Disclosure)**：系統無意間暴露敏感資訊，如伺服器版本、目錄結構、堆疊追蹤、設定檔路徑等
- **參數加密 (Parameter Encryption)**：對 API 請求中的敏感參數（如使用者 ID、檔案路徑）進行加密或簽章，防止竄改與窺探
- **路徑混淆 (Path Obfuscation)**：將內部系統路徑映射為不可預測的外部 URL，避免暴露系統結構
- **SQL Injection（SQL 注入）**：攻擊者透過惡意 SQL 片段注入輸入欄位，試圖操作或竊取資料庫資料
- **NoSQL Injection（NoSQL 注入）**：針對 NoSQL 資料庫（如 DynamoDB、MongoDB）的注入攻擊，利用查詢運算子或結構化物件繞過驗證
- **XSS (Cross-Site Scripting)**：攻擊者透過注入惡意腳本至輸入欄位，於其他使用者瀏覽器上執行
- **HMAC (Hash-based Message Authentication Code)**：基於雜湊的訊息認證碼，用於驗證資料完整性與來源
- **Rate Limiting（速率限制）**：限制單一來源在時間窗口內的請求次數，防止暴力破解與濫用

## Requirements

### 需求 1：目錄遍歷與資訊洩露防護

**使用者故事：** 身為系統管理員，我希望系統能防止攻擊者透過 URL 或 API 參數存取到未授權的檔案與目錄，且不會洩露內部系統結構。

#### 驗收條件

1. WHEN 系統收到包含路徑參數的 API 請求，THE Security_Module SHALL 對路徑進行正規化（canonicalization）處理，移除所有 `../`、`..\\`、`%2e%2e%2f`、`%2e%2e/`、`..%2f` 等變體，並驗證正規化後的路徑仍位於允許的根目錄範圍內
2. IF 路徑正規化後超出允許範圍，THEN THE Security_Module SHALL 拒絕請求並回傳 HTTP 400 Bad Request（不透露具體原因），同時記錄為安全事件（含來源 IP、請求路徑、時間戳）
3. THE Security_Module SHALL 實作路徑白名單機制，僅允許存取預先定義的目錄與檔案類型，所有未列入白名單的路徑一律拒絕
4. THE Security_Module SHALL 確保所有錯誤回應（4xx、5xx）不包含伺服器版本、堆疊追蹤、內部檔案路徑、資料庫連線字串等敏感資訊
5. THE Security_Module SHALL 於所有 HTTP 回應中設定以下安全標頭：
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
   - `Content-Security-Policy: default-src 'self'`
   - `Server:` 標頭移除或設為通用值（不暴露伺服器軟體與版本）
6. THE Security_Module SHALL 停用目錄索引功能（directory listing），任何對目錄路徑的請求均回傳 HTTP 404 Not Found
7. IF 系統偵測到同一來源 IP 在 1 分鐘內發起超過 10 次包含路徑遍歷特徵的請求，THEN THE Security_Module SHALL 暫時封鎖該 IP 30 分鐘，並發送安全告警至系統管理員

### 需求 2：API 參數與路徑加密

**使用者故事：** 身為系統管理員，我希望對外暴露的 API 路徑與敏感參數經過加密或混淆處理，使攻擊者無法透過觀察 URL 推測系統結構或竄改參數。

#### 驗收條件

1. THE Security_Module SHALL 對所有對外 API 端點中的敏感路徑片段（如 elder_id、session_id、file_path）進行加密編碼，使用 AES-256-GCM 對稱加密演算法，加密金鑰由 AWS KMS 管理
2. WHEN 前端或外部系統發起 API 請求，THE Security_Module SHALL 驗證加密參數的完整性（透過 GCM 認證標籤），若驗證失敗則拒絕請求並回傳 HTTP 403 Forbidden
3. THE Security_Module SHALL 為每組加密參數附加時間戳（timestamp），WHEN 參數時間戳與伺服器時間差異超過 5 分鐘，THE Security_Module SHALL 視為過期並拒絕請求（防止重放攻擊）
4. THE Security_Module SHALL 將內部 API 路徑結構映射為不可預測的外部路徑（路徑混淆），外部路徑使用 UUID v4 或 Base62 編碼，不暴露資源類型或層級結構
5. THE Security_Module SHALL 對所有 API 請求實施 HMAC 簽章驗證：請求端須以共享密鑰對請求方法、路徑、時間戳、請求體進行 HMAC-SHA256 簽章，伺服器端驗證後才處理請求
6. IF HMAC 簽章驗證失敗，THEN THE Security_Module SHALL 拒絕請求並回傳 HTTP 401 Unauthorized，同時記錄為安全事件
7. THE Security_Module SHALL 確保加密金鑰每 90 天自動輪換，舊金鑰保留 7 天以支援過渡期間的請求解密，過期後永久刪除
8. WHILE 參數加解密處理中，THE Security_Module SHALL 將單次加解密延遲控制在 5 毫秒以內，不影響 API 整體回應時間

### 需求 3：註冊防注入機制

**使用者故事：** 身為系統管理員，我希望使用者（長者或家屬）在註冊帳號時，系統能有效防止各類注入攻擊，確保註冊資料安全寫入且不影響系統穩定。

#### 驗收條件

1. WHEN 使用者提交註冊表單，THE Security_Module SHALL 對所有輸入欄位（姓名、電話、Email、密碼、地址等）執行輸入驗證，包含：
   - 長度限制：各欄位設定最大長度（姓名 50 字元、Email 254 字元、電話 20 字元、地址 200 字元）
   - 字元白名單：姓名僅允許中文字、英文字母、空格與常見符號（·．-）；電話僅允許數字、+、-；Email 依 RFC 5322 格式驗證
   - 禁止特殊字元：所有欄位禁止包含 SQL 關鍵字模式（如 `' OR 1=1`、`; DROP TABLE`、`UNION SELECT`）及 NoSQL 運算子（如 `$gt`、`$ne`、`$where`）
2. THE Security_Module SHALL 對所有註冊輸入執行 HTML 實體編碼（HTML Entity Encoding），將 `<`、`>`、`&`、`"`、`'` 等字元轉換為對應的 HTML 實體，防止儲存型 XSS 攻擊
3. THE Security_Module SHALL 使用參數化查詢（Parameterized Query / Prepared Statement）執行所有資料庫寫入操作，絕不以字串拼接方式組合 SQL 或 NoSQL 查詢語句
4. WHEN 註冊請求中偵測到注入特徵（如 SQL 關鍵字、Script 標籤、NoSQL 運算子），THE Security_Module SHALL 拒絕該次註冊並回傳通用錯誤訊息「註冊資料格式不正確，請檢查後重試」，不揭露具體偵測原因
5. THE Security_Module SHALL 對註冊端點實施速率限制：同一 IP 每分鐘最多 5 次註冊請求，同一手機號碼每小時最多 3 次註冊請求；超過限制回傳 HTTP 429 Too Many Requests
6. THE Security_Module SHALL 對註冊密碼欄位執行以下處理：
   - 密碼最小長度 8 字元，須包含大寫、小寫、數字至少各一
   - 使用 bcrypt（cost factor ≥ 12）或 Argon2id 進行雜湊後儲存，永不儲存明文密碼
   - 密碼欄位不出現在任何 API 回應或日誌中
7. THE Security_Module SHALL 於註冊流程中加入 CAPTCHA 驗證（如 reCAPTCHA v3 或 hCaptcha），score 低於 0.5 時要求使用者完成圖形驗證，防止自動化批量註冊
8. IF 同一 IP 在 10 分鐘內觸發超過 3 次注入偵測告警，THEN THE Security_Module SHALL 暫時封鎖該 IP 1 小時，並記錄為高風險安全事件通知系統管理員
9. THE Security_Module SHALL 對所有註冊相關的安全事件（注入嘗試、速率超限、CAPTCHA 失敗）保留審計日誌，日誌包含時間戳、來源 IP、User-Agent、輸入摘要（脫敏後），保留期限 90 天
10. WHEN 註冊成功，THE Security_Module SHALL 以 HTTP-only、Secure、SameSite=Strict 屬性設定 Session Cookie，防止 CSRF 與 Cookie 竊取攻擊

### 需求 4：安全監控與告警

**使用者故事：** 身為系統管理員，我希望所有安全事件都有集中監控與即時告警，讓我能快速回應潛在威脅。

#### 驗收條件

1. THE Security_Module SHALL 將所有安全事件（路徑遍歷嘗試、參數竄改、注入攻擊、速率超限、IP 封鎖）統一寫入安全事件日誌（Security Event Log），格式包含：事件類型、嚴重等級（LOW/MEDIUM/HIGH/CRITICAL）、時間戳、來源 IP、請求詳情（脫敏）、處置結果
2. WHEN 發生 HIGH 或 CRITICAL 等級的安全事件，THE Security_Module SHALL 在 30 秒內透過設定的告警管道（Email / LINE Notify / SNS）通知系統管理員
3. THE Security_Module SHALL 提供安全儀表板 API 端點，回傳過去 24 小時內的安全事件統計（依類型與嚴重等級分類）
4. THE Security_Module SHALL 每 24 小時自動產出安全摘要報告，包含事件總數、Top 10 攻擊來源 IP、攻擊類型分佈、已封鎖 IP 清單
5. WHILE 運行中，THE Security_Module SHALL 將安全事件處理延遲控制在 50 毫秒以內，不影響正常請求的回應時間
