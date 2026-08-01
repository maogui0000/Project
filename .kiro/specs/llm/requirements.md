# Requirements Document

## Introduction

本文件定義智慧長照陪伴系統中 LLM 功能層的需求規格。此系統為「2026 雲湧智生：臺灣生成式 AI 應用黑客松」參賽作品，主題為運用生成式 AI 彌補長照資源缺口。

LLM 功能層負責三大核心能力：
1. **語音互動陪伴對話生成** — 與長者進行自然、動態、有溫度的中文對話
2. **生活記錄與智慧摘要生成** — 從對話中萃取結構化生活資訊並產生每日摘要
3. **情緒分析與意圖辨識** — 透過文字關鍵詞偵測分析情緒，並辨識提醒等特殊意圖

系統部署於 AWS，使用 Amazon Bedrock (Claude Sonnet 4) 作為 LLM 推論引擎。情緒分析使用文字關鍵詞比對（不依賴外部 AWS 服務）。所有對話資料皆為模擬資料（無真實個資）。

### 提示詞管理（Prompt Templates）

本模組自行管理所有 LLM 提示詞模板，存放於 `prompts/` 資料夾中，與 Memory 模組的資料層分離。提示詞模板包含：
- **System Prompt 模板**（chat_prompt.txt）：定義 AI 助理的對話風格與人設
- **健康分析指令**（health_analysis_prompt.txt）：結構化萃取用藥、飲食、症狀等資訊
- **記憶重要性判斷**（memory_importance_prompt.txt）：評估對話重要性等級
- **告別偵測指令**（farewell_detection_prompt.txt）：辨識對話結束意圖
- **生活紀錄指令**（life_records_prompt.txt）：萃取結構化生活資訊

### 模組間依賴關係

- **上游 — 語音介面模組（Voice_Interface_Module）**：接收 ASR 轉譯文字
- **上游 — 記憶管理模組（Memory_Manager）**：讀取 elder_profile、short_term_memory、long_term_memory、reminders
- **下游 — 記憶管理模組（Memory_Manager）**：寫入對話記錄、長記憶事件、emotion_history、reminders、每日摘要
- **下游 — 語音介面模組（Voice_Interface_Module）**：以 SSE 串流回傳 LLM 生成的文字供 TTS 合成
- **外部 — Amazon Bedrock (Claude Sonnet 4)**：LLM 推論

## Glossary

- **LLM_Service**: 基於 Amazon Bedrock Claude 模型的推論服務（core/bedrock_client.py）
- **Dialogue_Engine**: 對話生成引擎（core/ai_chat.py），結合 elder_profile + active_context + prompt templates 產生回覆
- **Summary_Generator**: 從對話中萃取結構化資訊並產生每日摘要（services/ai_summary.py）
- **Intent_Detector**: 意圖辨識，負責辨識提醒設定、告別等特殊意圖
- **Emotion_Detector**: 透過文字關鍵詞比對進行情緒偵測（app.py 中的 _detect_chat_emotion）
- **Prompt_Templates**: 存放於 `prompts/` 資料夾的 LLM 提示詞模板

## Requirements

### Requirement 1: LLM 推論服務（Amazon Bedrock）

**User Story:** 身為系統操作者，我希望 LLM 服務能連接到 Amazon Bedrock Claude，以便系統執行文字生成任務。

#### Acceptance Criteria

1. WHEN the LLM_Service is initialized, THE LLM_Service SHALL establish a connection to Amazon Bedrock using configured AWS credentials and region settings
2. WHEN the LLM_Service receives a text generation request, THE LLM_Service SHALL forward the request to the Claude model on Amazon Bedrock and return the generated response
3. THE LLM_Service SHALL support both synchronous (chat) and streaming (chat_stream) response modes
4. IF the Amazon Bedrock connection fails, THEN THE LLM_Service SHALL retry with exponential backoff (max 3 retries), and if all retries fail, return a predefined friendly error message
5. THE LLM_Service SHALL use the Bedrock Converse API for all model invocations

### Requirement 2: 情境感知對話生成

**User Story:** 身為年長使用者，我希望系統能根據當下情境自然地跟我聊天，讓我感覺像在跟一位貼心的晚輩聊天。

#### Acceptance Criteria

1. WHEN a user message is received, THE Dialogue_Engine SHALL generate a contextual response in Traditional Chinese that addresses the user's input
2. WHEN generating a response, THE Dialogue_Engine SHALL retrieve the elder_profile from Memory_Manager and incorporate relevant personal context（健康狀況、用藥、過敏）into the prompt
3. WHEN generating a response, THE Dialogue_Engine SHALL incorporate current weather and time of day from the environmental prompt (Environmental_Prompts.txt)
4. WHEN generating a response, THE Dialogue_Engine SHALL retrieve recent conversation history from short_term_memory to maintain dialogue coherence
5. THE Dialogue_Engine SHALL generate dynamic responses using LLM for each interaction rather than selecting from pre-defined scripted responses
6. WHEN initiating a new conversation session (first turn after wake word), THE Dialogue_Engine SHALL generate a personalized greeting incorporating contextual elements (weather, time, elder nickname)
7. WHEN the user seems disengaged, THE Dialogue_Engine SHALL proactively introduce topics to maintain engaging conversation

### Requirement 3: 提示詞管理與對話風格

**User Story:** 身為年長使用者，我希望系統用溫暖、耐心、關懷的語氣跟我說話。

#### Acceptance Criteria

1. THE Dialogue_Engine SHALL maintain all prompt templates in the `prompts/` folder
2. THE Dialogue_Engine SHALL dynamically compose the system prompt from: base persona prompt + elder_profile data + environmental context + emotion state
3. THE Dialogue_Engine SHALL use simple and clear language, avoiding technical jargon
4. THE Dialogue_Engine SHALL include safety constraints: health information is for reference only, no medical diagnoses, encourage consulting professionals
5. IF the user expresses distress or negative emotions, THEN THE Dialogue_Engine SHALL generate an empathetic response
6. IF the user describes symptoms suggesting a medical emergency, THEN THE Dialogue_Engine SHALL advise contacting medical services or caregiver

### Requirement 4: 情緒偵測（文字關鍵詞比對）

**User Story:** 身為照護者，我希望系統能自動偵測長者的情緒狀態，以便我監控他們的心理狀況。

#### Acceptance Criteria

1. WHEN a user message is received, THE Emotion_Detector SHALL analyze the text using keyword matching and regex patterns to identify emotional state
2. THE Emotion_Detector SHALL map detected patterns to system emotion labels（開心/難過/生氣/恐懼/吃驚/中立/未檢測）
3. THE Emotion_Detector SHALL support two-layer detection: (a) exact keyword matching (b) regex fuzzy pattern matching for variants
4. THE Emotion_Detector SHALL write emotion_history records to Memory_Manager (source=text)
5. THE Emotion_Detector SHALL process emotion detection without blocking the dialogue response generation

### Requirement 5: 意圖辨識與提醒建立

**User Story:** 身為年長使用者，我希望能口頭告訴 AI 助理需要提醒的事情，它會自動幫我設定提醒。

#### Acceptance Criteria

1. WHEN a user message is received, THE Intent_Detector SHALL analyze the message for reminder-setting intent（如「下午一點要吃藥」「等一下提醒我...」）
2. WHEN a reminder intent is detected, THE Intent_Detector SHALL extract the reminder content and call Memory_Manager to create a new reminder
3. WHEN a reminder is successfully created, THE Dialogue_Engine SHALL confirm the reminder in the response（如「好的，我下午一點會提醒你吃藥喔」）
4. THE Intent_Detector SHALL detect farewell intent（告別偵測）using LLM to determine if the user wants to end the conversation
5. THE Intent_Detector SHALL detect help-seeking intent (求助) and flag the event for caregiver notification

### Requirement 6: 對話內容結構化萃取（健康分析）

**User Story:** 身為照護者，我希望系統能自動從對話中萃取用藥、飲食等結構化資訊。

#### Acceptance Criteria

1. WHEN a conversation turn is processed, THE Summary_Generator SHALL use LLM to extract structured health information, categorizing into: medication（用藥）、diet（飲食）、symptom（症狀）、chronic_disease（慢性疾病）、activity（活動）、sleep（睡眠）、reminder（提醒）
2. FOR medication extraction, THE Summary_Generator SHALL distinguish: status（已吃/沒吃/未提及）、name（藥物名稱）、time（服藥時間）
3. THE Summary_Generator SHALL output results as structured JSON for downstream storage
4. IF no relevant health information is detected, THE Summary_Generator SHALL return default "未提及" values
5. THE Summary_Generator SHALL use the health_analysis_prompt.txt template for extraction

### Requirement 7: 每日生活摘要生成

**User Story:** 身為照護者，我希望系統能自動生成每日結構化摘要，讓我在 Dashboard 快速查看長者狀況。

#### Acceptance Criteria

1. WHEN a daily summary is requested (Session idle timeout or manual trigger), THE Summary_Generator SHALL aggregate conversation records and produce a structured JSON summary
2. THE Summary_Generator SHALL output: overallSummary（AI 生成的敘事摘要）+ structuredData containing: diet、medication、sleep、activity
3. THE Summary_Generator SHALL generate the summary content using the LLM_Service
4. THE Summary_Generator SHALL produce the summary in Traditional Chinese
5. WHEN the summary is generated, THE Summary_Generator SHALL write it to dashboard_logs via Memory_Manager

### Requirement 8: 串流對話（SSE）

**User Story:** 身為前端開發者，我希望 LLM 回覆能以串流方式逐句傳回，讓 TTS 可以邊生成邊播放。

#### Acceptance Criteria

1. THE LLM_Service SHALL expose an SSE endpoint (/api/chat/stream) for streaming dialogue responses
2. THE LLM_Service SHALL stream responses sentence-by-sentence (以句號、問號、感嘆號為斷點)
3. FOR each streamed sentence, THE System SHALL simultaneously synthesize TTS audio and return both text + audio URL
4. THE LLM_Service SHALL include a final "done" event with the full reply and farewell detection result
5. THE LLM_Service SHALL implement the API using Python with FastAPI framework

### Requirement 9: 記憶重要性判斷機制

**User Story:** 身為系統設計者，我希望系統能可靠地評估對話內容的重要性，確保關鍵健康資訊不會遺失。

#### Acceptance Criteria

1. THE Dialogue_Engine SHALL use LLM to assess importance of each conversation turn (1~10 scale)
2. THE Dialogue_Engine SHALL apply safety rule overrides: medication keywords → minimum importance high, health emergency keywords → importance permanent
3. THE Dialogue_Engine SHALL assign ttl_minutes based on importance: high/permanent → 240 min, medium → 60 min, low → 30 min
4. THE Dialogue_Engine SHALL maintain a keyword dictionary for the safety rule layer
5. WHEN importance is assessed as high or permanent, THE Dialogue_Engine SHALL flag the turn for long-term memory storage
