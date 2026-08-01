# LLM 功能層 — 設計文件

## 1. 架構概覽

```
前端 (web/index.html)
  │  POST /api/chat/stream { text, elder_id }
  ▼
app.py (FastAPI)
  │  組合 prompt → 呼叫 Bedrock → SSE 逐句回傳
  │  每句 TTS 合成 → 附帶 audioUrl
  ▼
core/ai_chat.py                    core/bedrock_client.py
  ├── get_combined_system_prompt()     ├── chat()          (同步)
  ├── ask_ollama()                     ├── chat_stream()   (串流 generator)
  ├── ask_ollama_stream_sentences()    └── chat_json()     (JSON 模式)
  └── _sanitize_reply()
                │
                ▼
core/memory_controller.py          services/ai_summary.py
  ├── _analyze_health_info()         └── get_elder_daily_summary()
  └── update_memories()
```

---

## 2. 核心模組設計

### 2.1 bedrock_client.py（LLM 推論服務）

統一封裝 Amazon Bedrock Converse API：

```python
# 同步呼叫
def chat(system, messages, user_text, temperature, max_tokens, model_id) -> str

# 串流呼叫（逐 token yield）
def chat_stream(system, messages, user_text, temperature, max_tokens, model_id) -> Generator[str]

# JSON 模式（強制回傳 JSON）
def chat_json(system, messages, user_text, temperature, max_tokens, model_id) -> dict
```

- 模型：`us.anthropic.claude-sonnet-4-20250514-v1:0`
- 區域：`us-west-2`
- 重試：3 次，adaptive mode

### 2.2 ai_chat.py（對話生成引擎）

```python
def get_combined_system_prompt(elder_id) -> str:
    """
    動態組合 system prompt：
    base_prompt + elder_profile + 時間情境 + 天氣環境 + 情緒狀態
    """

def ask_ollama(text, elder_id) -> str:
    """非串流對話（供內部使用）"""

def ask_ollama_stream_sentences(text, elder_id) -> Generator[str]:
    """
    串流逐句生成器：
    1. 呼叫 bedrock_client.chat_stream
    2. 累積 token 直到遇到句號/問號/嘆號
    3. 每完整句子 yield 一次
    4. 過濾 emoji + sanitize（移除違規表述）
    """

def _sanitize_reply(text) -> str:
    """後處理：移除 LLM 超出能力範圍的表述（如「我幫你打電話」）"""
```

### 2.3 memory_controller.py（健康分析萃取）

```python
class MemoryController:
    def update_memories(self, user_text, ai_text):
        """每輪對話後執行：
        1. 寫入短期記憶
        2. LLM 分析健康資訊
        3. 更新長期記憶 + dashboard metrics
        """

    def _analyze_health_info(self, user_text, current_time) -> dict:
        """
        呼叫 Bedrock（使用 health_analysis_prompt.txt）
        回傳：{medication, diet, symptom, chronic_disease, activity, sleep, reminder}
        """
```

### 2.4 ai_summary.py（每日摘要生成）

```python
def get_elder_daily_summary(current_chat) -> dict:
    """
    呼叫 Bedrock（chat_json 模式）
    輸入：當日對話文字
    輸出：{overallSummary, structuredData: {diet, medication, sleep, activity}, date}
    """
```

---

## 3. Prompt Templates（prompts/ 目錄）

| 檔案 | 用途 | 呼叫者 |
|------|------|--------|
| `chat_prompt.txt` | AI 人設 + 對話風格 + 安全限制 | ai_chat.py |
| `health_analysis_prompt.txt` | 一次性萃取用藥/飲食/症狀 JSON | memory_controller.py |
| `memory_importance_prompt.txt` | 評估對話重要性（1~10 分） | data_manager.py |
| `farewell_detection_prompt.txt` | 判斷使用者是否想結束對話 | app.py |
| `life_records_prompt.txt` | 結構化生活紀錄萃取 | ai_summary.py |
| `Environmental_Prompts.txt` | 天氣 + 情緒環境資訊（動態更新） | ai_chat.py |

---

## 4. 情緒偵測（文字關鍵詞）

位於 `app.py` 的 `_detect_chat_emotion()`：

```python
# 第一層：關鍵詞精確匹配
_EMOTION_KEYWORDS = {
    "開心": ["開心", "高興", "快樂", ...],
    "難過": ["難過", "傷心", "哭", ...],
    "生氣": ["生氣", "氣死", ...],
    "恐懼": ["害怕", "可怕", ...],
    "吃驚": ["天啊", "真的假的", ...],
}

# 第二層：正則模糊匹配
_negative_mood_patterns = [
    re.compile(r'心情.{0,3}(?:不好|差|糟)'),
    re.compile(r'(?:很|好|超).{0,2}(?:難過|傷心|低落)'),
    ...
]
```

不依賴外部 AWS 服務，純 Python 正則比對。

---

## 5. SSE 串流對話流程

```
前端 POST /api/chat/stream { text, elder_id }
  │
  ▼
app.py handle_chat_stream():
  1. 組合 prompt（short_term_memory + long_term_memory + user_text）
  2. SSE event: { type: 'thinking' }
  3. for sentence in ask_ollama_stream_sentences(prompt):
       a. TTS 合成該句 → 存暫存 mp3
       b. SSE event: { type: 'sentence', text, audioUrl }
  4. LLM 告別偵測
  5. SSE event: { type: 'done', full_reply, end_session }
  6. 背景任務：記憶分析 + 情緒偵測 + dashboard 更新
```

---

## 6. 告別偵測

```python
def _detect_farewell(user_text) -> bool:
    """
    呼叫 Bedrock（farewell_detection_prompt.txt）
    LLM 只回答 yes/no
    """
```

---

## 7. 尚待實作 / 可改善

| 功能 | 狀態 | 說明 |
|------|------|------|
| 記憶重要性 LLM 判斷 | 已實作 | data_manager._evaluate_importance() |
| 安全規則兜底（關鍵詞強制升級） | 已部分實作 | memory_controller._MEDICATION_KEYWORDS |
| 意圖辨識（提醒） | 已實作 | memory_controller 在分析中偵測 reminder |
| 求助意圖偵測 → 通知照護者 | 待實作 | 可透過 LLM 分析加入 |
| Session 閒置 2 分鐘 → 自動摘要 | 已實作 | app.py _session_idle_countdown |

---

## 8. 實作順序（尚待完成的部分）

| 順序 | 任務 |
|------|------|
| 1 | 求助意圖偵測 → 觸發 LINE 推播照護者 |
| 2 | 記憶重要性安全規則完善（可配置 JSON） |
| 3 | 對話壓縮摘要（超長對話歷史壓縮） |
