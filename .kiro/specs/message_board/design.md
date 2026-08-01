# (D) 留言板：雙向互動與 LINE Bot 照護者連結 — 設計文件

## 1. 架構概覽

```
照護者 (LINE)                      EC2 伺服器                         長者 (Web)
─────────────                    ──────────────                    ────────────
                                        
LINE 傳文字/語音 ──► line_bot.py ──► messages.json (unread)
                     (Webhook)                │
                                             ▼
                              長者開始對話 → 前端呼叫 GET /api/messages/unread
                                             │
                                             ▼
                              前端 TTS 播報留言 → 呼叫 POST /mark_read
                                             │
                                             ▼
                              長者口述回覆 → POST /reply → LINE Push 給照護者
```

---

## 2. 檔案變更清單

| 檔案 | 變更類型 | 說明 |
|------|---------|------|
| `core/data_manager.py` | 修改 | 新增留言 CRUD 方法 |
| `services/line_bot.py` | 修改 | Webhook 接收照護者留言，存入 messages.json |
| `app.py` | 修改 | 新增 3 個留言 API 端點 |
| `web/index.html` | 修改 | 前端對話流程整合留言播報 + 回覆 |
| `data/<elder_id>/messages.json` | 新增 | 留言資料檔案 |

---

## 3. 資料層設計

### 3.1 messages.json 結構

```json
{
  "elder_id": "elder_178546685908e66b",
  "messages": [
    {
      "message_id": "msg_1722470400_abc123",
      "sender_type": "caregiver",
      "sender_name": "家人",
      "content_type": "text | audio",
      "content_text": "爸，我今晚會買排骨湯回去看你喔！",
      "content_audio_path": null,
      "status": "unread | read | replied",
      "created_at": "2025-08-01T14:30:00",
      "read_at": null,
      "reply_text": null,
      "replied_at": null
    }
  ]
}
```

### 3.2 DataManager 新增方法

```python
class DataManager:
    # ── 留言相關 ──────────────────────────────────────

    def get_messages(self) -> dict:
        """讀取 messages.json"""

    def get_unread_messages(self) -> list:
        """取得所有 status == 'unread' 的留言"""

    def add_message(self, sender_name: str, content_type: str, 
                    content_text: str, content_audio_path: str = None) -> dict:
        """新增一筆留言（照護者傳送時呼叫）"""

    def mark_message_read(self, message_id: str) -> bool:
        """將留言標記為已讀"""

    def reply_to_message(self, message_id: str, reply_text: str) -> bool:
        """為留言新增長者回覆"""
```

---

## 4. API 設計

### 4.1 GET `/api/messages/{elder_id}/unread`

取得指定長者的未讀留言列表。

**Response:**
```json
{
  "unread_count": 2,
  "messages": [
    {
      "message_id": "msg_1722470400_abc123",
      "sender_name": "家人",
      "content_type": "text",
      "content_text": "爸，我今晚會買排骨湯回去看你喔！",
      "created_at": "2025-08-01T14:30:00"
    }
  ]
}
```

### 4.2 POST `/api/messages/{elder_id}/mark_read`

標記留言為已讀，並推播已讀回報給照護者。

**Request Body:**
```json
{
  "message_id": "msg_1722470400_abc123"
}
```

**Response:**
```json
{ "success": true }
```

**副作用：** 透過 LINE Push API 推播「✅ 長者已收聽您的留言」給照護者。

### 4.3 POST `/api/messages/{elder_id}/reply`

長者回覆留言，並推播回覆內容給照護者。

**Request Body:**
```json
{
  "message_id": "msg_1722470400_abc123",
  "reply_text": "好啊，我等你回來"
}
```

**Response:**
```json
{ "success": true }
```

**副作用：** 透過 LINE Push API 推播長者回覆文字給照護者。

---

## 5. LINE Bot Webhook 擴充設計

### 5.1 接收照護者留言

在現有 `@handler.handle` 的 `MessageEvent` 處理中，新增留言接收邏輯：

```python
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """照護者傳送文字 → 存入留言佇列"""
    user_id = event.source.user_id
    text = event.message.text
    
    # 存入 messages.json
    dm = DataManager(elder_id=TARGET_ELDER_ID)
    dm.add_message(
        sender_name="家人",
        content_type="text",
        content_text=text
    )
    
    # 回覆確認
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="✅ 留言已送出，等長輩上線時會通知他喔！")
    )
```

### 5.2 接收語音留言

```python
@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
    """照護者傳送語音 → 下載音檔 + 存入留言佇列"""
    message_content = line_bot_api.get_message_content(event.message.id)
    
    # 儲存音檔
    audio_path = f"data/{TARGET_ELDER_ID}/audio/msg_{event.message.id}.m4a"
    with open(audio_path, 'wb') as f:
        for chunk in message_content.iter_content():
            f.write(chunk)
    
    # 存入 messages.json
    dm = DataManager(elder_id=TARGET_ELDER_ID)
    dm.add_message(
        sender_name="家人",
        content_type="audio",
        content_text="（語音留言）",
        content_audio_path=audio_path
    )
    
    # 回覆確認
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="🎙️ 語音留言已送出！")
    )
```

### 5.3 推播回報

```python
def notify_caregiver_read(message_id: str):
    """留言已讀時通知照護者"""
    line_bot_api.push_message(
        TARGET_USER_ID,
        TextSendMessage(text="✅ 長輩已收聽您的留言")
    )

def notify_caregiver_reply(reply_text: str):
    """長者回覆時通知照護者"""
    line_bot_api.push_message(
        TARGET_USER_ID,
        TextSendMessage(text=f"💬 長輩回覆：「{reply_text}」")
    )
```

---

## 6. 前端整合設計

### 6.1 對話啟動時檢查未讀留言

在 `initWakeWordDetection()` 的 `recognition.onresult` 中，偵測到「小黃」並啟動對話後，先呼叫 API 檢查未讀留言：

```javascript
async function checkUnreadMessages() {
  const resp = await fetch(`/api/messages/${elderId}/unread`);
  const data = await resp.json();
  if (data.unread_count > 0) {
    // 進入留言播報流程
    await playMessageFlow(data.messages);
  } else {
    // 正常對話流程
    startListening();
  }
}
```

### 6.2 留言播報流程

```javascript
async function playMessageFlow(messages) {
  // 1. TTS 提醒：「家人留了訊息給你，要聽嗎？」
  await ttsSpeak("家人剛才在LINE上留了訊息給你喔，要聽聽看嗎？");
  
  // 2. 等待長者回應（Web Speech API 辨識）
  const response = await listenForResponse();
  
  if (isAffirmative(response)) {
    // 3. 逐筆播報留言
    for (const msg of messages) {
      await ttsSpeak(`家人說：${msg.content_text}`);
      await markRead(msg.message_id);
    }
    
    // 4. 問是否回覆
    await ttsSpeak("聽完了，要不要回覆家人呢？");
    const replyResponse = await listenForResponse();
    
    if (isAffirmative(replyResponse)) {
      // 5. 錄製回覆
      await ttsSpeak("好的，請說你想回覆的內容");
      const replyText = await listenForReply();
      await submitReply(messages[messages.length - 1].message_id, replyText);
      await ttsSpeak("好的，我幫你傳給家人囉！");
    }
  }
  
  // 6. 回到正常對話
  startListening();
}
```

### 6.3 輔助函數

```javascript
function isAffirmative(text) {
  const yes_words = ['好', '聽', '可以', '要', '說什麼', '聽聽'];
  return yes_words.some(w => text.includes(w));
}

function isNegative(text) {
  const no_words = ['不', '等', '晚點', '不用', '沒'];
  return no_words.some(w => text.includes(w));
}
```

---

## 7. 錯誤處理

| 情境 | 處理方式 |
|------|---------|
| LINE Webhook 接收失敗 | 回傳 500，LINE 會自動重試 |
| messages.json 不存在 | DataManager 初始化時自動建立空結構 |
| 留言播報時 TTS 失敗 | 跳過該筆，標記為 read，log 錯誤 |
| 長者回覆推播失敗 | 回覆已存入 JSON（不丟失），log 錯誤，下次重試 |
| 語音檔下載失敗 | 存文字替代「（語音留言下載失敗）」，通知照護者重傳 |

---

## 8. 實作順序

| 順序 | 任務 | 預估複雜度 |
|------|------|-----------|
| 1 | DataManager 新增留言 CRUD 方法 | 低 |
| 2 | app.py 新增 3 個 API 端點 | 低 |
| 3 | line_bot.py 擴充 Webhook 接收留言 | 中 |
| 4 | line_bot.py 新增推播回報函數 | 低 |
| 5 | web/index.html 前端留言播報流程 | 中 |
| 6 | 整合測試 | 中 |
