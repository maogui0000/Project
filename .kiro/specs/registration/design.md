# Registration 設計文件

## 1. 架構概覽

```
前端 (web/index.html)                    後端 (app.py)
─────────────────────                    ──────────────
                                        
註冊表單（loginScreen）                    
  ├─ 區塊 1：基本身分        ──POST──►  /api/elder/profile
  ├─ 區塊 2：感官偏好                      │
  ├─ 區塊 3：興趣話題                      ▼
  └─ 區塊 4：PIN 碼設定              DataManager.update_profile()
                                    DataManager._save(pin_hash)
         │                                 │
         ▼                                 ▼
  localStorage 存入 elder_id         data/<elder_id>/elder_profile.json
  → 進入語音互動主畫面
```

---

## 2. 前端 UI 設計

### 2.1 註冊表單佈局（web/index.html `#loginScreen`）

現有結構已有「基本身分」和「可折疊更多資訊」。需新增以下區塊：

#### 區塊 2：感官與語言偏好（新增）

位置：在「緊急聯絡人」折疊區塊之後

```html
<details class="group rounded-lg border border-slate-200 overflow-hidden">
  <summary>🔊 感官與語言偏好</summary>
  <div class="p-4 space-y-3">
    <!-- 聽力狀況 -->
    <div>
      <label>聽力狀況</label>
      <select id="reg_hearing">
        <option value="normal">聽力良好</option>
        <option value="weak">聽力稍弱（需較大音量/較慢語速）</option>
      </select>
    </div>
    <!-- 慣用語言（固定） -->
    <div>
      <label>慣用語言</label>
      <input disabled value="中文（繁體）">
    </div>
  </div>
</details>
```

#### 區塊 3：興趣與話題偏好（新增）

```html
<details class="group rounded-lg border border-slate-200 overflow-hidden">
  <summary>💬 興趣與話題偏好</summary>
  <div class="p-4 space-y-3">
    <!-- 多選標籤 -->
    <div>
      <label>喜愛聊的話題（可多選）</label>
      <div class="flex flex-wrap gap-2" id="interest_tags">
        <!-- 預設標籤按鈕：點擊切換 active 狀態 -->
        <button data-tag="過往回憶">過往回憶</button>
        <button data-tag="戲曲">戲曲</button>
        <button data-tag="烹飪">烹飪</button>
        <button data-tag="寵物">寵物</button>
        <button data-tag="日常閒聊">日常閒聊</button>
        <button data-tag="運動健康">運動健康</button>
        <button data-tag="家人">家人</button>
      </div>
    </div>
    <!-- 自由填寫 -->
    <div>
      <label>其他興趣（自由填寫）</label>
      <input id="reg_interests_other" placeholder="例：種花、下棋">
    </div>
    <!-- 備忘 -->
    <div>
      <label>想記住的事情 / 備忘</label>
      <textarea id="reg_memo" rows="2" placeholder="例：孫子下禮拜要來看我"></textarea>
    </div>
  </div>
</details>
```

#### 區塊 4：PIN 碼設定（新增）

位置：在送出按鈕之前

```html
<div class="border-t border-slate-100 pt-4">
  <label class="block text-xs font-bold text-slate-600 mb-2">🔒 設定 PIN 碼（4~6 位數字）</label>
  <p class="text-xs text-slate-400 mb-2">換裝置時需要輸入此 PIN 碼驗證身分</p>
  <div class="grid grid-cols-2 gap-3">
    <input id="reg_pin" type="password" inputmode="numeric" maxlength="6" 
           placeholder="設定 PIN 碼">
    <input id="reg_pin_confirm" type="password" inputmode="numeric" maxlength="6" 
           placeholder="確認 PIN 碼">
  </div>
</div>
```

### 2.2 PIN 碼驗證畫面（新增）

當 localStorage 中沒有 `active_elder_id` 時顯示：

```html
<div id="pinLoginScreen" class="fixed inset-0 bg-white z-50 flex flex-col items-center justify-center">
  <h2 class="text-xl font-bold mb-6">歡迎回來</h2>
  <p class="text-sm text-slate-500 mb-4">請輸入您的慣稱和 PIN 碼</p>
  <input id="pin_nickname" placeholder="慣稱（如：阿香婆婆）" class="...">
  <input id="pin_code" type="password" inputmode="numeric" placeholder="PIN 碼" class="...">
  <button onclick="verifyPin()">驗證</button>
  <p id="pin_error" class="text-red-500 text-xs hidden">慣稱或 PIN 碼錯誤</p>
  <p class="text-xs text-slate-400 mt-4">還沒註冊？<a href="#" onclick="showRegister()">點此註冊</a></p>
</div>
```

---

## 3. 後端 API 設計

### 3.1 現有 API 擴充（`/api/elder/profile`）

在 `ElderProfileRequest` model 中新增欄位：

```python
class ElderProfileRequest(BaseModel):
    # 現有欄位...
    name: str
    nickname: str
    gender: str
    age: Optional[int] = None
    location: Optional[str] = ""
    id_number: Optional[str] = ""
    # ...緊急聯絡人、醫療資訊...
    
    # 新增欄位
    hearing_status: Optional[str] = "normal"     # "normal" | "weak"
    interests: Optional[List[str]] = []          # 話題偏好標籤
    interests_other: Optional[str] = ""          # 其他興趣
    memo: Optional[str] = ""                     # 備忘事項
    pin: Optional[str] = ""                      # PIN 碼（明文傳入，後端 hash）
```

### 3.2 新增 API：PIN 碼驗證

```
POST /api/elder/verify_pin
Body: { "nickname": "阿香婆婆", "pin": "1234" }
Response: { "success": true, "elder_id": "elder_xxx" }
```

驗證邏輯：
1. 遍歷 `data/` 目錄所有 elder_profile.json
2. 找到 `nickname` 匹配的帳號
3. 比對 PIN hash
4. 成功回傳 elder_id，失敗回傳 401

---

## 4. 資料層設計

### 4.1 elder_profile.json 新增欄位

```json
{
  "meta": {
    "created_at": "...",
    "last_updated": "...",
    "pin_hash": "sha256_hash_of_pin"
  },
  "personal_info": { ... },
  "sensory_preferences": {
    "hearing_status": "normal",
    "primary_language": "中文"
  },
  "interests": {
    "topics": ["過往回憶", "烹飪", "家人"],
    "other": "種花、下棋",
    "memo": "孫子下禮拜要來看我"
  },
  ...
}
```

### 4.2 DataManager 新增方法

```python
def update_sensory_preferences(self, hearing_status: str):
    """更新感官偏好"""

def update_interests(self, topics: list, other: str, memo: str):
    """更新興趣與話題偏好"""

def set_pin(self, pin: str):
    """設定 PIN（hash 儲存）"""

def verify_pin(self, pin: str) -> bool:
    """驗證 PIN 碼"""
```

---

## 5. 前端邏輯流程

```
頁面載入
  │
  ├── localStorage 有 active_elder_id？
  │     ├── 是 → 直接進入語音互動主畫面
  │     └── 否 → 顯示選擇畫面
  │              ├── 「我要註冊」→ 顯示註冊表單（loginScreen）
  │              └── 「已有帳號」→ 顯示 PIN 驗證畫面（pinLoginScreen）
  │
  └── 註冊送出
        ├── 呼叫 POST /api/elder/profile
        ├── localStorage 存入 elder_id
        ├── 如有備忘 → 呼叫寫入 reminders
        └── 進入語音互動主畫面
```

---

## 6. 實作順序

| 順序 | 任務 |
|------|------|
| 1 | DataManager 新增 sensory_preferences / interests / pin 相關方法 |
| 2 | app.py 擴充 /api/elder/profile 接受新欄位 + 新增 /api/elder/verify_pin |
| 3 | web/index.html 新增感官偏好 / 興趣話題 / PIN 碼 UI 區塊 |
| 4 | web/index.html 新增 PIN 驗證畫面 + 前端路由邏輯 |
| 5 | 整合測試 |
