# Memory（記憶管理模組）— 設計文件

## 1. 架構概覽

```
core/data_manager.py (DataManager)
  │
  ├── data/<elder_id>/elder_profile.json      ← 長者基本資料
  ├── data/<elder_id>/long_term_memory.json   ← 長期記憶 + 情緒歷史
  ├── data/<elder_id>/short_term_memory.json  ← 短期對話上下文
  ├── data/<elder_id>/dashboard_logs.json     ← 每日報告
  ├── data/<elder_id>/reminders.json          ← 提醒事項
  └── data/<elder_id>/messages.json           ← 留言板

core/memory_controller.py (MemoryController)
  │
  ├── 呼叫 Bedrock LLM 分析健康資訊（用藥/飲食/症狀）
  ├── 自動分類並寫入長期記憶
  └── 更新 dashboard_logs metrics

services/weather_cron.py
  │
  └── 定時取得 CWA 天氣 → 寫入 Environmental_Prompts.txt
```

---

## 2. 核心類別設計

### 2.1 DataManager（core/data_manager.py）

已實作的統一資料存取層，所有 JSON 讀寫透過此類別。

```python
class DataManager:
    def __init__(self, elder_id: str):
        # 初始化路徑，確保所有 JSON 存在
    
    # ── Profile ──
    def get_profile() -> dict
    def update_profile(name, nickname, age, location, gender)
    def update_emergency_contact(name, relationship, phone)
    def update_medical_safety(chronic_diseases, current_medications, drug_allergies, food_allergies)
    def update_physical_care(mobility, dietary_restrictions)
    def update_mental_cognitive(has_dementia, has_wandering_history, cognitive_notes)
    def update_sensory_preferences(hearing_status)          # 新增
    def update_interests(topics, other, memo)               # 新增
    def set_pin(pin) / verify_pin(pin)                      # 新增
    
    # ── Long-term Memory ──
    def get_long_term_memory() -> dict
    def add_long_term_record(category, content, importance)
    def get_long_term_summary_text() -> str
    
    # ── Short-term Memory ──
    def get_short_term_memory() -> dict
    def add_dialogue_turn(user_text, ai_text)
    def get_history_summary_text() -> str
    
    # ── Dashboard Logs ──
    def get_dashboard_logs() -> dict
    def update_today_summary(text, metrics)
    def add_timeline_event(event_type, title, description)
    def add_emotion_record(emotion, reason, confidence, source)
    
    # ── Reminders ──
    def get_reminders() -> dict
    def add_reminder(content, requested_by)
    
    # ── Messages ──
    def get_messages() -> dict
    def get_unread_messages() -> list
    def add_message(sender_name, content_type, content_text, content_audio_path)
    def mark_message_read(message_id) -> bool
    def reply_to_message(message_id, reply_text) -> bool
    
    # ── Dashboard 整合 ──
    def get_full_dashboard_data() -> dict
    def record_full_interaction(user_text, ai_text)
```

### 2.2 MemoryController（core/memory_controller.py）

負責智慧記憶分析（呼叫 LLM 判斷健康資訊）：

```python
class MemoryController:
    def __init__(self, elder_id: str):
        self.dm = DataManager(elder_id)
    
    def update_memories(self, user_text: str, ai_text: str):
        """
        1. 寫入短期對話記憶
        2. 呼叫 LLM 分析健康資訊（_analyze_health_info）
        3. 根據分析結果更新長期記憶 + dashboard metrics
        """
    
    def _analyze_health_info(self, user_text, current_time) -> dict:
        """呼叫 Bedrock 一次性分析：用藥/飲食/症狀/活動/睡眠/提醒"""
```

---

## 3. JSON 檔案結構

### 3.1 elder_profile.json

```json
{
  "elder_id": "elder_xxx",
  "meta": {
    "created_at": "ISO8601",
    "last_updated": "ISO8601",
    "pin_hash": "sha256_hash"
  },
  "personal_info": { "name", "nickname", "gender", "age", "location" },
  "emergency_contact": { "name", "relationship", "phone" },
  "medical_safety": { "chronic_diseases[]", "current_medications[]", "drug_allergies[]", "food_allergies[]" },
  "physical_care": { "mobility", "dietary_restrictions[]" },
  "mental_cognitive": { "has_dementia", "cognitive_notes" },
  "sensory_preferences": { "hearing_status", "primary_language" },
  "interests": { "topics[]", "other", "memo" },
  "localization_settings": { "primary_language", "tts_accent", "persona_relation" }
}
```

### 3.2 long_term_memory.json

```json
{
  "elder_id": "elder_xxx",
  "meta": { "last_analyzed_at": "ISO8601" },
  "records": [
    { "category", "content", "importance", "recorded_at", "expires_at", "ttl_days" }
  ],
  "emotion_history": [
    { "time", "emotion", "reason", "confidence", "source" }
  ]
}
```

### 3.3 short_term_memory.json

```json
{
  "elder_id": "elder_xxx",
  "current_session_id": "sess_xxx",
  "active_context": { "weather", "current_time", "topic_focus" },
  "dialogue_history": [
    { "turn", "timestamp", "expires_at", "ttl_minutes", "user", "ai", "is_flagged_for_long_term" }
  ]
}
```

### 3.4 dashboard_logs.json / reminders.json / messages.json

結構同需求文件定義。

---

## 4. 天氣整合（services/weather_cron.py）

- 每 6 小時呼叫 CWA Open Data API
- 寫入 `prompts/Environmental_Prompts.txt`
- LLM 組裝 prompt 時讀取此檔案

---

## 5. 尚待實作

| 功能 | 狀態 | 說明 |
|------|------|------|
| sensory_preferences 讀寫 | 待實作 | Registration 任務 1 |
| interests 讀寫 | 待實作 | Registration 任務 1 |
| PIN 碼 set/verify | 待實作 | Registration 任務 1 |
| TTL 自動清理過期記錄 | 待實作 | 每次讀取時檢查 expires_at |
| dialogue_history TTL 清理 | 待實作 | 每次讀取時清理超過 ttl_minutes 的記錄 |

---

## 6. 實作順序

| 順序 | 任務 |
|------|------|
| 1 | 新增 sensory_preferences / interests / PIN 方法（跟 Registration 一起做） |
| 2 | 長期記憶 TTL 自動清理 |
| 3 | 短期對話 TTL 自動清理 |
| 4 | 記憶重要性 → TTL 自動設定完善化 |
