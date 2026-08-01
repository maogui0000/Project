# Speech（語音介面模組）— 實作任務清單

## 任務 1：喚醒詞偵測 ✅
- [x] 前端 Web Speech API continuous 模式持續監聽
- [x] 偵測到「小黃」關鍵詞 → 啟動對話
- [x] 按鈕點擊直接啟動（效果等同喚醒詞）
- [x] 對話模式中暫停喚醒偵測

## 任務 2：瀏覽器 ASR 語音辨識 ✅
- [x] startLiveSpeechRecognition() 即時語音辨識
- [x] VAD 音量偵測（ScriptProcessor + RMS 計算）
- [x] 靜音超過閾值 → 自動送出辨識文字
- [x] fallback：錄音送後端 /api/asr（torch 可用時）

## 任務 3：Edge-TTS 逐句合成 ✅
- [x] synthesize_sentence_to_bytes() 合成單句 mp3
- [x] SSE 串流每句附帶 audioUrl
- [x] 暫存檔下載後自動刪除
- [x] fallback：前端 speechSynthesis

## 任務 4：SSE 串流播放 ✅
- [x] audioQueue 佇列 + playNextInQueue() 逐句播放
- [x] 播放完畢 → 重新進入 listening 狀態
- [x] end_session → 回到待機

## 任務 5：留言播報流程 ✅
- [x] checkUnreadMessages() 喚醒後檢查未讀
- [x] playMessageFlow() 留言播報主流程
- [x] ttsPrompt() TTS 唸出留言
- [x] listenForShortResponse() 等待長者回應
- [x] submitReply() 送出回覆

## 任務 6：前端 UI 狀態機 ✅
- [x] 4 種狀態：waiting_wake / listening / recording / speaking
- [x] 按鈕顏色 + 圖示 + 脈衝動畫對應狀態
- [x] 回覆文字即時顯示（replyBox）

## 任務 7：聽力偏好調整 TTS（待實作）
- [ ] 對話開始時讀取 elder_profile.sensory_preferences.hearing_status
- [ ] hearing_status="weak" → TTS 音量提升 30% + 語速降低
- [ ] 透過 Edge-TTS 的 rate/volume SSML 參數調整
- [ ] 前端 Audio 元素 volume 屬性調整

## 任務 8：主動提醒排程（待實作）
- [ ] 前端 setInterval 每 30 秒輪詢 `/api/reminders/{elder_id}/pending`
- [ ] 若有到期提醒 → 中斷待機 → TTS 播報提醒內容
- [ ] 播報後等待 10 秒 → 有回應進入對話 / 無回應恢復待機
- [ ] 後端標記提醒為 notified

## 任務 9：Barge-in 打斷機制（待實作）
- [ ] TTS 播放中偵測到使用者說話（VAD）
- [ ] 200ms 內停止播放
- [ ] 切換回 listening 狀態接收使用者語音
