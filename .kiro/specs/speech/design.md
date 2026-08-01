# Speech（語音介面模組）— 設計文件

## 1. 架構概覽

```
瀏覽器 (web/index.html)
  │
  ├── Web Speech API (continuous)  ← 喚醒詞偵測 + ASR
  ├── MediaRecorder / ScriptProcessor ← 錄音 + VAD
  ├── Audio 元素 ← TTS 播放
  └── fetch /api/chat/stream ← SSE 串流
  
後端 (app.py + FastAPI)
  │
  ├── /api/chat/stream ← 接收文字 → Bedrock 串流 → 逐句 TTS → SSE
  ├── /api/asr ← fallback 後端 ASR（需 torch，EC2 輕量部署不啟用）
  └── /api/tts ← 單句 TTS（留言播報用）

語音合成 (Edge-TTS)
  │
  └── edge_tts.Communicate → mp3 bytes → 暫存檔 → 前端下載播放
```

---

## 2. 前端語音流程設計

### 2.1 狀態機

```
waiting_wake ──(喚醒詞/按鈕)──► [checkUnreadMessages]
                                       │
                          有未讀 ──► playMessageFlow ──► listening
                          無未讀 ──► listening
                                       │
listening ──(VAD 偵測到說話)──► recording
recording ──(靜音超過閾值)──► processing (送出文字)
processing ──(SSE 收到第一句)──► speaking
speaking ──(播放完畢)──► listening
speaking ──(收到 end_session)──► waiting_wake
```

### 2.2 喚醒詞偵測

```javascript
function initWakeWordDetection() {
  const recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'zh-TW';

  recognition.onresult = (event) => {
    // 偵測到「小黃」→ 啟動對話
    if (text.includes('小黃')) {
      isSessionActive = true;
      recognition.stop();
      // → checkUnreadMessages()
    }
  };

  recognition.onend = () => {
    // 未啟動對話 → 繼續監聽
    if (!isSessionActive) recognition.start();
    // 已啟動 → 進入留言檢查/對話
    else checkUnreadMessages();
  };
}
```

### 2.3 錄音與 VAD

```javascript
async function startListening() {
  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  // ScriptProcessor 錄音 + 音量偵測
  scriptProcessor.onaudioprocess = (e) => {
    const samples = e.inputBuffer.getChannelData(0);
    // 計算 RMS → 判斷是否有人聲
  };
  // 同時啟動 Web Speech API 即時辨識
  startLiveSpeechRecognition();
}
```

### 2.4 送出文字

```javascript
async function sendAudio() {
  // 取得 Web Speech API 辨識結果
  const text = _liveSpeechResult;
  // POST 到 /api/chat/stream
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    body: JSON.stringify({ text, elder_id: currentUserId })
  });
  // 處理 SSE 串流回覆
  handleSSEStream(response);
}
```

### 2.5 SSE 串流播放

```javascript
function handleSSEStream(response) {
  const reader = response.body.getReader();
  // 逐行讀取 SSE events
  // type: 'sentence' → 加入 audioQueue → 逐句播放
  // type: 'done' → 判斷 end_session
}

function playNextInQueue() {
  const item = audioQueue.shift();
  ttsAudio = new Audio(item.audioUrl);
  ttsAudio.onended = () => playNextInQueue();
  ttsAudio.play();
}
```

---

## 3. 後端 TTS 設計

### 3.1 逐句合成（app.py /api/chat/stream 內）

```python
for sentence in ask_ollama_stream_sentences(full_prompt, elder_id=elder_id):
    # 1. Edge-TTS 合成該句
    audio_data = await synthesize_sentence_to_bytes(sentence)
    # 2. 存暫存檔
    audio_path = f"_stream_audio_{index}.mp3"
    with open(abs_path, "wb") as af:
        af.write(audio_data)
    # 3. SSE 推送
    yield f"data: {json.dumps({'type':'sentence', 'text':sentence, 'audioUrl':f'/{audio_path}'})}\n\n"
```

### 3.2 暫存檔清理

```python
@app.get("/_stream_audio_{index}.mp3")
async def get_stream_audio(index: int):
    # 讀取後立即刪除
    with open(file_path, "rb") as f:
        audio_bytes = f.read()
    os.remove(file_path)
    return Response(content=audio_bytes, media_type="audio/mpeg")
```

### 3.3 獨立 TTS 端點（留言播報用）

```python
@app.get("/api/tts")
async def text_to_speech(text: str, lang: str = "台語 (閩南語)"):
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(saved_file_path)
    return FileResponse(saved_file_path)
```

---

## 4. 留言板播報流程（前端）

```javascript
async function checkUnreadMessages() {
  const resp = await fetch(`/api/messages/${currentUserId}/unread`);
  const data = await resp.json();
  if (data.unread_count > 0) {
    await playMessageFlow(data.messages);  // TTS 唸出 + 問是否回覆
  } else {
    startListening();  // 直接進入正常對話
  }
}
```

---

## 5. 配置參數（config.py）

```python
# TTS 語音
TTS_VOICES = {
    "國語 (華語)": ("zh-TW-HsiaoChenNeural", "mandarin.mp3"),
    "台語 (閩南語)": ("zh-TW-HsiaoYuNeural", "taiwanese.mp3"),
    "客語 (客家語)": ("zh-TW-YunJheNeural", "hakka.mp3"),
}

# VAD 設定
ENERGY_THRESHOLD = 0.008
RECORD_SECONDS = 6
SAMPLE_RATE = 16000

# 喚醒詞
WAKE_WORDS = ["小黃小黃", "小黃", "xiaohuang"]
```

---

## 6. 限制與降級

| 情境 | 降級方式 |
|------|---------|
| 瀏覽器不支援 Web Speech API | 按鈕啟動 + 錄音送後端 /api/asr |
| 非 HTTPS 環境 | Web Speech API 不可用，僅按鈕模式 |
| Edge-TTS 失敗 | 前端 fallback 到 `speechSynthesis` |
| 後端 torch 未安裝 | /api/asr 回傳空字串，前端 ASR 為主 |

---

## 7. 尚待實作

| 功能 | 狀態 | 說明 |
|------|------|------|
| 喚醒詞偵測 | ✅ 已實作 | 前端 Web Speech API |
| 瀏覽器 ASR | ✅ 已實作 | startLiveSpeechRecognition() |
| Edge-TTS 逐句合成 | ✅ 已實作 | synthesize_sentence_to_bytes() |
| SSE 串流播放 | ✅ 已實作 | audioQueue + playNextInQueue |
| 留言播報流程 | ✅ 已實作 | checkUnreadMessages + playMessageFlow |
| 聽力偏好調整 TTS 速度/音量 | 待實作 | 讀取 sensory_preferences 調整 |
| 主動提醒發話 | 待實作 | 前端定時輪詢 reminders |

---

## 8. 實作順序（尚待完成的部分）

| 順序 | 任務 |
|------|------|
| 1 | 聽力偏好 → TTS 語速/音量調整 |
| 2 | 前端主動提醒排程（定時檢查 reminders） |
| 3 | Barge-in 打斷機制完善 |
