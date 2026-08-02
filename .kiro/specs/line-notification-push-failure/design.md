# LINE Notification Push Failure Bugfix Design

## Overview

LINE 推播通知全面失敗，照護者完全收不到系統推播（每日摘要、即時互動通知、提醒推播、緊急推播）。根本原因是五個交互作用的缺陷：Elder ID 不一致、LINE 憑證來源混亂、雙重排程衝突、錯誤處理靜默吞掉、以及缺少提醒推播機制。修復策略為：統一資料來源、收斂憑證到 `config.py`、移除重複排程、加入結構化日誌、新增提醒推播迴圈。

## Glossary

- **Bug_Condition (C)**: 任何觸發 LINE 推播的情境（每日 19:00 摘要、Session 結束即時推播、關鍵詞提醒、緊急求助），在當前程式碼下全部靜默失敗
- **Property (P)**: 觸發推播時，訊息正確送達照護者 LINE，且失敗時有結構化日誌可追溯
- **Preservation**: 照護者 LINE → 系統的 webhook 接收（留言、語音留言、指令回覆）、對話系統（ASR/LLM/TTS）、天氣環境更新、Dashboard API 皆不受影響
- **`_send_line_push()`**: `services/weather_cron.py` 中的 LINE 推播函數，使用 urllib 直接呼叫 LINE Messaging API
- **`_daily_line_push_scheduler()`**: `app.py` 中基於 asyncio 的每日 19:00 排程任務
- **`scheduled_line_push()`**: `weather_cron.py` 中的推播邏輯（含緩衝等待機制）
- **`TARGET_ELDER_ID`**: `line_bot.py` 中硬編碼的長者 ID，用於 webhook 收到訊息後存入對應長者資料
- **`config.py`**: 統一配置中心，從 `.env` 讀取 LINE 憑證

## Bug Details

### Bug Condition

推播失敗在以下五個獨立但交互的條件下發生。任一條件成立即可導致推播靜默失敗：

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type LinePushAttempt { elder_id, access_token, target_user_id, scheduler_source, reminder_pending }
  OUTPUT: boolean

  // Bug 1: Elder ID mismatch
  condition_1 := (input.elder_id == "elder_178546685908e66b") 
                 AND NOT exists(data_dir / "elder_178546685908e66b")

  // Bug 2: Credential inconsistency
  condition_2 := (config.LINE_CHANNEL_ACCESS_TOKEN == "") 
                 AND (hardcoded_token_expired_or_revoked)

  // Bug 3: Dual scheduler conflict
  condition_3 := (input.scheduler_source == "weather_cron_while_loop") 
                 AND (app_asyncio_scheduler_also_running)

  // Bug 4: Silent error swallowing
  condition_4 := (LINE_API_returns_error) 
                 AND (no_persistent_log_written)

  // Bug 5: No reminder push mechanism
  condition_5 := (input.reminder_pending == True) 
                 AND (no_scheduler_checks_reminders)

  RETURN condition_1 OR condition_2 OR condition_3 OR condition_4 OR condition_5
END FUNCTION
```

### Examples

- **Bug 1**: 照護者透過 LINE 傳「吃飯了嗎」→ `line_bot.py` 用 `TARGET_ELDER_ID = "elder_178546685908e66b"` 建立 `DataManager` → 資料目錄 `data/elder_178546685908e66b/` 不存在 → `_ensure_files_exist()` 建立空白 JSON → 留言存入錯誤目錄，前端看不到
- **Bug 2**: `_send_line_push("每日摘要...")` → 使用硬編碼的過期 token → LINE API 回 HTTP 401 → `except` 吞掉錯誤印到 stdout → 回傳 `False` → 呼叫端不知原因
- **Bug 3**: 19:00 到達 → `app.py` 的 asyncio task 先觸發 `_execute_daily_push()` → 數秒後 `weather_cron.py` 的 while loop 也觸發 `scheduled_line_push()` → 可能重複推播或 race condition
- **Bug 4**: LINE token 權限不足 → HTTP 403 → `_send_line_push()` 印出 `"[LINE 推播] HTTP 錯誤：403 ..."` 到 stdout → 無日誌檔紀錄 → 重啟後完全不可追溯
- **Bug 5**: 長者說「提醒我三點要吃藥」→ `add_reminder()` 寫入 `reminders.json` 為 `pending` → 無任何排程任務檢查該檔案 → 提醒永遠不會被推播

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- 照護者透過 LINE 傳文字/語音留言到系統（webhook 接收流程）不受影響
- 照護者輸入「今日動態」等指令，系統正確回覆（reply 功能不變）
- `weather_cron.py` 的天氣/日落資料抓取與 `Environmental_Prompts.txt` 更新不受影響
- 長者對話流程（ASR → LLM → TTS）完全不受影響
- Dashboard API (`/api/elder/{elder_id}`) 正常回傳
- `data_manager.py` 的資料讀寫邏輯不變
- 前端提醒 API (`/api/reminders/{elder_id}/pending`) 行為不變

**Scope:**
所有不涉及 LINE 推播「發送」端的操作應完全不受此修復影響。包括：
- LINE webhook 接收（`line_bot.py` 的 `/callback` 路由）
- 對話系統的所有 API 端點
- 天氣資料更新（`fetch_and_generate_prompt()`）
- Dashboard 資料讀取
- 長者註冊/登入流程

## Hypothesized Root Cause

Based on the bug analysis, the 5 root causes are:

1. **Elder ID Hardcoding Mismatch**: `line_bot.py` 中 `TARGET_ELDER_ID = "elder_178546685908e66b"` 是開發時的測試 ID，而實際資料目錄是 `data/elder_demo_user_001`。所有透過 webhook 存入的留言都進入了一個不存在或空白的目錄。
   - 受影響：`handle_text_message()`、`handle_audio_message()`、`_send_today_summary()`

2. **LINE Credential Chaos**: 三個來源的 token 互相衝突：
   - `config.py` 從 `.env` 讀取 `LINE_CHANNEL_ACCESS_TOKEN`（可能為空）
   - `line_bot.py` 直接硬編碼 token
   - `weather_cron.py` 的 `_send_line_push()` 有 fallback 硬編碼
   - 若 `.env` 未設定，`config.py` 回傳空字串 → `_send_line_push()` 使用可能已過期的硬編碼 token

3. **Dual Scheduler Conflict**: 兩個獨立的排程器同時運作：
   - `app.py` 的 `_daily_line_push_scheduler()` — asyncio task，在 FastAPI lifespan 中啟動
   - `weather_cron.py` 的 `if __name__ == "__main__"` while loop — 獨立 process
   - `_execute_daily_push()` 不檢查 `is_sent` 旗標就直接推播

4. **Silent Error Swallowing**: `_send_line_push()` 的 except 只 `print()` 到 stdout，沒有：
   - 寫入持久化日誌（`logs/line_bot.log`）
   - 回傳具體錯誤資訊給呼叫端
   - 紀錄時間戳和 HTTP 狀態碼

5. **Missing Reminder Push Loop**: `add_reminder()` 可以新增提醒，但沒有任何背景任務會：
   - 定期檢查 `reminders.json` 中的 pending 項目
   - 在提醒時間到達時推播到 LINE
   - 標記已推播的提醒

## Correctness Properties

Property 1: Bug Condition - LINE Push Delivers Successfully

_For any_ LINE push attempt where the system has valid credentials (non-empty `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_TARGET_USER_ID` in config), a correct elder ID mapping (matching actual `data/` directory entries), and the LINE API is reachable, the fixed `_send_line_push()` SHALL successfully deliver the message to the target user AND return `True`.

**Validates: Requirements 2.1, 2.2, 2.4**

Property 2: Preservation - Non-Push Operations Unchanged

_For any_ operation that does NOT involve LINE push message sending (webhook receiving, chat processing, weather updates, dashboard reads, reminder creation), the fixed code SHALL produce exactly the same behavior as the original code, preserving all existing functionality for non-push operations.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

Property 3: Bug Condition - Single Scheduler No Duplicates

_For any_ daily 19:00 trigger event, exactly ONE scheduler (app.py asyncio) SHALL execute the push, and the push SHALL check `is_sent` flag before sending, preventing duplicate notifications.

**Validates: Requirements 2.3**

Property 4: Bug Condition - Error Logging on Failure

_For any_ LINE API call that returns an error (HTTP 4xx/5xx or network error), the fixed code SHALL write a structured log entry to `logs/line_bot.log` containing timestamp, error code, and error message.

**Validates: Requirements 2.2, 2.4**

Property 5: Bug Condition - Pending Reminders Get Pushed

_For any_ reminder in `reminders.json` with `status: "pending"` and `notified: False`, the fixed code SHALL periodically check and push the reminder content to LINE, then set `notified: True`.

**Validates: Requirements 2.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `services/line_bot.py`

**Changes**:
1. **Remove hardcoded credentials**: Delete `LINE_CHANNEL_SECRET` and `LINE_CHANNEL_ACCESS_TOKEN` hardcoded strings, replace with `config.LINE_CHANNEL_SECRET` and `config.LINE_CHANNEL_ACCESS_TOKEN`
2. **Fix TARGET_ELDER_ID**: Replace `"elder_178546685908e66b"` with dynamic lookup — scan `data/` directory for existing elder directories, or use `"elder_demo_user_001"` as configurable default via `config.py`
3. **Use config-based LineBotApi**: Initialize `LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)` and `WebhookHandler(config.LINE_CHANNEL_SECRET)`

---

**File**: `config.py`

**Changes**:
4. **Add `LINE_TARGET_ELDER_ID`**: New config variable `LINE_TARGET_ELDER_ID = os.getenv("LINE_TARGET_ELDER_ID", "elder_demo_user_001")` for the webhook-associated elder ID
5. **Ensure `.env` has valid LINE tokens**: Document required env vars (no code change, just validation at startup)

---

**File**: `services/weather_cron.py`

**Changes**:
6. **Fix `_send_line_push()`**: Remove hardcoded fallback token. Use only `config.LINE_CHANNEL_ACCESS_TOKEN` and `config.LINE_TARGET_USER_ID`. If either is empty, log error and return `False`
7. **Add structured logging**: Write errors to `logs/line_bot.log` with timestamp, HTTP status, error detail
8. **Remove `if __name__ == "__main__"` scheduler loop**: Keep only `fetch_and_generate_prompt()` and weather functions. Remove the while-loop that triggers `scheduled_line_push()` at 19:00 — let `app.py` be the sole scheduler
9. **Keep `scheduled_line_push()` function**: It's still called by `app.py`'s `_execute_daily_push()` indirectly; refactor it to be callable without its own scheduling

---

**File**: `app.py`

**Changes**:
10. **Fix `_execute_daily_push()`**: Add `is_sent` check before pushing (currently missing — it pushes without checking)
11. **Use unified `_send_line_push()`**: Replace direct `line_bot_api.push_message()` calls with `_send_line_push()` from weather_cron (or a new shared utility) for consistent error handling
12. **Add reminder push loop**: New asyncio task `_reminder_push_loop()` that runs every 60 seconds, checks all elders' `reminders.json` for pending+unnotified items, and pushes them via LINE
13. **Register reminder loop in lifespan**: Start `_reminder_push_loop` alongside `_daily_line_push_scheduler`

---

**File**: `core/data_manager.py`

**Changes**:
14. **No changes needed**: `mark_line_notification_sent()` and `add_reminder()` work correctly — the bugs are in the callers, not in the data layer

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate LINE push attempts under the 5 bug conditions and assert failure behavior. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **Elder ID Mismatch Test**: Create a `DataManager("elder_178546685908e66b")` and verify it creates an empty directory separate from actual data (will demonstrate data isolation bug)
2. **Empty Token Test**: Set `config.LINE_CHANNEL_ACCESS_TOKEN = ""` and call `_send_line_push("test")` — verify it fails silently with no log file written (will fail on unfixed code)
3. **Dual Scheduler Race Test**: Simulate both schedulers triggering — verify no `is_sent` check in `_execute_daily_push()` allows duplicate sends (will demonstrate on unfixed code)
4. **Error Logging Test**: Mock LINE API to return 401 — call `_send_line_push()` — verify `logs/line_bot.log` does NOT exist or doesn't contain the error (will fail on unfixed code)
5. **Reminder Not Pushed Test**: Add a pending reminder via `DataManager.add_reminder()` — wait — verify no LINE push occurs (will demonstrate bug on unfixed code)

**Expected Counterexamples**:
- `_send_line_push()` returns `False` without any persistent logging
- `_execute_daily_push()` sends even when `is_sent == True`
- `DataManager("elder_178546685908e66b")` creates an orphan directory
- Pending reminders remain `notified: False` indefinitely

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixed_send_line_push(input)
  ASSERT (result.success == True AND message_delivered)
         OR (result.success == False AND log_file_contains_error(input))
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT original_webhook_handler(input) == fixed_webhook_handler(input)
  ASSERT original_chat_api(input) == fixed_chat_api(input)
  ASSERT original_weather_update(input) == fixed_weather_update(input)
  ASSERT original_dashboard_api(input) == fixed_dashboard_api(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (various elder IDs, message types, API calls)
- It catches edge cases that manual unit tests might miss (boundary elder IDs, special characters in messages)
- It provides strong guarantees that behavior is unchanged for all non-push operations

**Test Plan**: Observe behavior on UNFIXED code first for webhook receives, chat API calls, and dashboard reads, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Webhook Preservation**: Verify that LINE webhook text/audio message handling continues to work correctly after fix (message stored, reply sent)
2. **Chat Flow Preservation**: Verify `/api/chat/stream` produces same LLM + TTS output for same input text
3. **Weather Update Preservation**: Verify `fetch_and_generate_prompt()` still generates correct `Environmental_Prompts.txt`
4. **Dashboard API Preservation**: Verify `/api/elder/{elder_id}` returns same data structure

### Unit Tests

- Test `_send_line_push()` with valid token → assert HTTP 200 and return True
- Test `_send_line_push()` with empty token → assert return False and log written
- Test `_send_line_push()` with invalid token → assert return False and log contains HTTP 401
- Test `_execute_daily_push()` skips when `is_sent == True`
- Test `_execute_daily_push()` pushes when `is_sent == False`
- Test elder ID resolution from `config.LINE_TARGET_ELDER_ID`
- Test reminder push loop detects pending reminders and pushes

### Property-Based Tests

- Generate random elder IDs → verify `DataManager` always maps to existing directory or raises clear error
- Generate random LINE API error codes → verify every failure produces a log entry
- Generate random push trigger times → verify exactly one scheduler fires (no duplicates)
- Generate random reminder creation/check cycles → verify all pending reminders eventually get pushed

### Integration Tests

- Full flow: create reminder → wait for push loop → verify LINE API called with correct message → verify `notified: True`
- Full flow: 19:00 trigger → `_execute_daily_push()` → verify single push per elder → verify `is_sent` flag set
- Full flow:照護者 LINE 傳留言 → webhook → verify stored in correct elder directory (`elder_demo_user_001`)
- Full flow: `_send_line_push()` failure → verify `logs/line_bot.log` has structured error entry
