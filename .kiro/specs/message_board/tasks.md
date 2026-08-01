# (D) 留言板功能 — 實作任務清單

## 任務 1：DataManager 新增留言 CRUD 方法
- [ ] 在 `core/data_manager.py` 的 `_ensure_files_exist()` 中加入 `messages.json` 初始化
- [ ] 新增 `get_messages()` 方法：讀取 messages.json
- [ ] 新增 `get_unread_messages()` 方法：篩選 status == "unread" 的留言
- [ ] 新增 `add_message()` 方法：新增一筆留言（含自動產生 message_id）
- [ ] 新增 `mark_message_read()` 方法：更新狀態為 "read" + 寫入 read_at
- [ ] 新增 `reply_to_message()` 方法：更新狀態為 "replied" + 寫入 reply_text/replied_at

## 任務 2：app.py 新增留言 API 端點
- [ ] GET `/api/messages/{elder_id}/unread` — 回傳未讀留言列表
- [ ] POST `/api/messages/{elder_id}/mark_read` — 標記留言為已讀
- [ ] POST `/api/messages/{elder_id}/reply` — 長者回覆留言，並觸發 LINE 推播

## 任務 3：LINE Bot Webhook 擴充接收留言
- [ ] 在 `services/line_bot.py` 新增 `@handler.add(MessageEvent, message=TextMessage)` 處理照護者文字留言
- [ ] 新增 `@handler.add(MessageEvent, message=AudioMessage)` 處理照護者語音留言
- [ ] 語音留言下載音檔存入 `data/<elder_id>/audio/` 目錄
- [ ] 接收留言後回覆照護者確認訊息（「✅ 留言已送出」）

## 任務 4：LINE Bot 推播回報函數
- [ ] 新增 `notify_caregiver_read()` — 留言已讀時推播「✅ 長輩已收聽您的留言」
- [ ] 新增 `notify_caregiver_reply(reply_text)` — 長者回覆時推播回覆內容

## 任務 5：前端留言播報流程整合
- [ ] 在 `web/index.html` 新增 `checkUnreadMessages()` — 喚醒詞觸發後檢查未讀留言
- [ ] 新增 `playMessageFlow(messages)` — 留言播報主流程（TTS 唸出 + 問是否回覆）
- [ ] 新增 `listenForResponse()` — 等待長者語音回應（同意/拒絕）
- [ ] 新增 `submitReply(messageId, replyText)` — 送出長者回覆
- [ ] 整合進喚醒詞觸發流程：偵測到「小黃」後先 checkUnreadMessages，再進正常對話

## 任務 6：整合測試
- [ ] 從 LINE 傳文字留言 → 確認存入 messages.json（status=unread）
- [ ] 前端觸發對話 → 確認系統 TTS 播報未讀留言
- [ ] 長者口述回覆 → 確認照護者 LINE 收到回覆文字
- [ ] 確認留言狀態流轉正確（unread → read → replied）
- [ ] 確認系統重啟後未讀留言仍可播報
