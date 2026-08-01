# Memory（記憶管理模組）— 實作任務清單

## 任務 1：DataManager 基礎 CRUD ✅
- [x] elder_profile.json 讀寫（get_profile / update_profile / update_medical_safety 等）
- [x] long_term_memory.json 讀寫（add_long_term_record / get_long_term_memory）
- [x] short_term_memory.json 讀寫（add_dialogue_turn / get_history_summary_text）
- [x] dashboard_logs.json 讀寫（update_today_summary / add_timeline_event）
- [x] reminders.json 讀寫（add_reminder / get_reminders）
- [x] messages.json 讀寫（add_message / get_unread_messages / mark_read / reply）
- [x] emotion_history 讀寫（add_emotion_record）
- [x] _ensure_files_exist() 初始化所有 JSON

## 任務 2：MemoryController 健康分析 ✅
- [x] update_memories() 整合流程（短期記憶 + LLM 分析 + 長期記憶更新）
- [x] _analyze_health_info() 呼叫 Bedrock 萃取用藥/飲食/症狀
- [x] 用藥按時段分類記錄
- [x] 藥物名稱自動寫入 profile

## 任務 3：天氣整合 ✅
- [x] weather_cron.py 定時取得 CWA API 天氣資訊
- [x] 寫入 Environmental_Prompts.txt
- [x] 情緒狀態同步更新到環境提示詞

## 任務 4：新增 sensory_preferences / interests / PIN 方法（待實作）
- [ ] `update_sensory_preferences(hearing_status)` — 寫入 elder_profile
- [ ] `update_interests(topics, other, memo)` — 寫入 elder_profile
- [ ] `set_pin(pin)` — sha256 hash 存入 meta.pin_hash
- [ ] `verify_pin(pin)` — 比對 hash，回傳 bool
- [ ] 備忘自動寫入 reminders

## 任務 5：TTL 自動清理機制（待實作）
- [ ] 長期記憶：每次讀取時檢查 expires_at，移除過期記錄
- [ ] 短期對話：每次讀取時檢查 ttl_minutes，移除超時記錄
- [ ] permanent 等級永不清理

## 任務 6：互動統計完善（待實作）
- [ ] weekly_trend 自動更新（每次互動 increment 當天的 count）
- [ ] 隔天自動 reset total_turns
- [ ] report_date 自動更新
