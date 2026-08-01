# Registration — 實作任務清單

## 任務 1：DataManager 新增感官偏好 / 興趣 / PIN 相關方法
- [ ] 在 elder_profile.json 結構中新增 `sensory_preferences`（hearing_status, primary_language）
- [ ] 在 elder_profile.json 結構中新增 `interests`（topics, other, memo）
- [ ] 新增 `update_sensory_preferences(hearing_status)` 方法
- [ ] 新增 `update_interests(topics, other, memo)` 方法
- [ ] 新增 `set_pin(pin)` 方法（sha256 hash 儲存到 meta.pin_hash）
- [ ] 新增 `verify_pin(pin)` 方法（比對 hash）
- [ ] 備忘事項自動寫入 reminders（如有填寫）

## 任務 2：app.py 擴充註冊 API + 新增 PIN 驗證 API
- [ ] `ElderProfileRequest` 新增欄位：hearing_status, interests, interests_other, memo, pin
- [ ] `/api/elder/profile` 處理新欄位：寫入 sensory_preferences、interests、pin_hash
- [ ] 新增 `POST /api/elder/verify_pin` — 接受 nickname + pin，回傳 elder_id
- [ ] verify_pin 邏輯：遍歷 data/ 目錄找 nickname 匹配 → 比對 pin_hash
- [ ] PIN 錯誤 5 次鎖定 15 分鐘（用 meta.pin_locked_until 記錄）

## 任務 3：前端新增感官偏好 / 興趣話題 UI 區塊
- [ ] 在 `web/index.html` 註冊表單新增「🔊 感官與語言偏好」折疊區塊（聽力狀況 select）
- [ ] 新增「💬 興趣與話題偏好」折疊區塊（多選標籤按鈕 + 自由填寫 + 備忘 textarea）
- [ ] 興趣標籤按鈕點擊切換 active 狀態（toggle class）
- [ ] 註冊送出時收集新欄位並一起 POST

## 任務 4：前端新增 PIN 碼設定 + 驗證畫面
- [ ] 在註冊表單送出按鈕之前新增 PIN 碼設定區塊（兩個 input：設定 + 確認）
- [ ] PIN 碼前端驗證：4~6 位數字、兩次輸入一致
- [ ] 新增 `#pinLoginScreen` 畫面（慣稱 input + PIN input + 驗證按鈕）
- [ ] 新增前端路由邏輯：頁面載入時檢查 localStorage → 有 elder_id 直接進入 / 無則顯示選擇（註冊 or PIN 驗證）
- [ ] PIN 驗證成功後存入 localStorage 並進入主畫面
- [ ] PIN 錯誤顯示錯誤提示，5 次後顯示鎖定訊息

## 任務 5：整合測試
- [ ] 完整註冊流程（含新欄位）→ 確認 elder_profile.json 正確寫入
- [ ] PIN 碼設定 → 確認 hash 儲存正確
- [ ] 清除 localStorage → 確認出現 PIN 驗證畫面
- [ ] PIN 驗證正確 → 進入主畫面
- [ ] PIN 錯誤 5 次 → 確認鎖定機制運作
