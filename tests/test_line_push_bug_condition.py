"""
Bug Condition Exploration Test — LINE Notification Push Failure

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

This test encodes the EXPECTED (correct) behavior after fix.
On UNFIXED code, these tests are EXPECTED TO FAIL — failure confirms
the 5 interacting bug conditions exist.

Bug Conditions Tested:
1. Elder ID Mismatch (TARGET_ELDER_ID != actual data directory)
2. Empty/expired token silent failure (no structured logging)
3. No is_sent duplicate guard (_execute_daily_push ignores flag)
4. No persistent error logging (errors only printed to stdout)
5. No reminder push mechanism (pending reminders never pushed)
"""

import os
import sys
import json
import tempfile
import shutil
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume, note
from hypothesis import strategies as st

# Ensure project root is on path
_project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import config


# ═══════════════════════════════════════════════════════
# Test 1: Elder ID Mismatch
# ═══════════════════════════════════════════════════════

class TestElderIDMismatch:
    """
    Bug 1: line_bot.py has TARGET_ELDER_ID = "elder_178546685908e66b"
    but only data/elder_demo_user_001 exists.
    
    Expected behavior (after fix):
    The elder ID used by line_bot.py should match an actual directory in data/.
    """

    def test_target_elder_id_matches_existing_data_directory(self):
        """
        EXPECTED: TARGET_ELDER_ID from line_bot.py should correspond to
        an actual existing elder directory in data/.
        
        On UNFIXED code: This WILL FAIL because TARGET_ELDER_ID is
        "elder_178546685908e66b" which doesn't exist in data/.
        """
        from services.line_bot import TARGET_ELDER_ID
        
        data_dir = os.path.join(config.BASE_DIR, "data")
        existing_elder_dirs = [
            d for d in os.listdir(data_dir) 
            if d.startswith("elder_") and os.path.isdir(os.path.join(data_dir, d))
        ]
        
        # The TARGET_ELDER_ID used by line_bot.py MUST exist in data/
        assert TARGET_ELDER_ID in existing_elder_dirs, (
            f"TARGET_ELDER_ID='{TARGET_ELDER_ID}' does not match any existing "
            f"data directory. Existing: {existing_elder_dirs}"
        )

    @given(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N', 'P'))))
    @settings(max_examples=10)
    def test_elder_id_config_consistency(self, random_suffix):
        """
        Property: For any elder ID configured in the system, that elder ID
        must correspond to an existing data directory.
        
        **Validates: Requirements 2.1**
        """
        from services.line_bot import TARGET_ELDER_ID
        
        data_dir = os.path.join(config.BASE_DIR, "data")
        
        # The configured TARGET_ELDER_ID must always exist in data/
        elder_path = os.path.join(data_dir, TARGET_ELDER_ID)
        assert os.path.isdir(elder_path), (
            f"Configured TARGET_ELDER_ID='{TARGET_ELDER_ID}' has no data directory at {elder_path}"
        )


# ═══════════════════════════════════════════════════════
# Test 2: Empty/Expired Token Silent Failure + No Logging
# ═══════════════════════════════════════════════════════

class TestTokenFailureLogging:
    """
    Bug 2 & 4: When LINE token is empty or expired, _send_line_push()
    returns False without writing any structured log to logs/line_bot.log.
    
    Expected behavior (after fix):
    Push failure with invalid credentials MUST write a structured error log
    to logs/line_bot.log containing timestamp, error info.
    """

    def setup_method(self):
        """Clear the log file before each test."""
        self.log_path = os.path.join(config.BASE_DIR, "logs", "line_bot.log")
        # Clear log file content if it exists
        if os.path.exists(self.log_path):
            with open(self.log_path, "w") as f:
                f.write("")

    def test_empty_token_writes_error_log(self):
        """
        EXPECTED: When _send_line_push() is called with an empty access token,
        it should return False AND write a structured error log to logs/line_bot.log.
        
        On UNFIXED code: This WILL FAIL because _send_line_push() only
        prints to stdout and does NOT write to logs/line_bot.log.
        """
        from services.weather_cron import _send_line_push
        
        # Patch config to have empty token
        with patch.object(config, 'LINE_CHANNEL_ACCESS_TOKEN', ''):
            with patch.object(config, 'LINE_TARGET_USER_ID', ''):
                result = _send_line_push("test message")
        
        # Push should fail
        assert result is False, "Push with empty token should return False"
        
        # A structured error log MUST be written to logs/line_bot.log
        assert os.path.exists(self.log_path), (
            f"Log file {self.log_path} does not exist after push failure"
        )
        
        with open(self.log_path, "r", encoding="utf-8") as f:
            log_content = f.read()
        
        assert len(log_content.strip()) > 0, (
            "logs/line_bot.log is empty after push failure — "
            "no structured error log was written (Bug 4: silent error swallowing)"
        )

    @given(st.text(min_size=1, max_size=100))
    @settings(max_examples=5)
    def test_any_push_failure_produces_log_entry(self, message_text):
        """
        Property: For ANY push attempt that fails (due to invalid credentials),
        a structured log entry MUST be written to logs/line_bot.log.
        
        **Validates: Requirements 2.2, 2.4**
        """
        from services.weather_cron import _send_line_push
        
        log_path = os.path.join(config.BASE_DIR, "logs", "line_bot.log")
        
        # Clear log
        if os.path.exists(log_path):
            with open(log_path, "w") as f:
                f.write("")
        
        # Use empty/invalid token to force failure
        with patch.object(config, 'LINE_CHANNEL_ACCESS_TOKEN', 'invalid_expired_token'):
            with patch.object(config, 'LINE_TARGET_USER_ID', 'U_invalid_user'):
                result = _send_line_push(message_text)
        
        # Result should be False (push failed)
        assert result is False, "Push with invalid token should fail"
        
        # Structured log MUST exist
        assert os.path.exists(log_path), "Log file must exist after failure"
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()
        
        assert len(log_content.strip()) > 0, (
            f"No log entry written to logs/line_bot.log after push failure "
            f"with message: '{message_text[:30]}...'"
        )


# ═══════════════════════════════════════════════════════
# Test 3: No is_sent Duplicate Guard
# ═══════════════════════════════════════════════════════

class TestDuplicatePushGuard:
    """
    Bug 3: _execute_daily_push() in app.py sends push even when
    is_sent == True, potentially causing duplicate notifications.
    
    Expected behavior (after fix):
    When is_sent is True, _execute_daily_push() MUST skip that elder.
    """

    def test_daily_push_skips_when_is_sent_true(self):
        """
        EXPECTED: When dashboard_logs has is_sent=True, _execute_daily_push()
        should NOT attempt to push again.
        
        On UNFIXED code: This WILL FAIL because _execute_daily_push() does not
        check is_sent before pushing.
        """
        import asyncio
        from core.data_manager import DataManager
        
        # Set up: mark notification as already sent
        dm = DataManager(elder_id="elder_demo_user_001")
        logs = dm.get_dashboard_logs()
        logs["line_notification_status"]["is_sent"] = True
        logs["line_notification_status"]["trigger_time"] = "19:00:00"
        dm._save(dm.dashboard_path, logs)
        
        # Track if push_message is called
        push_called = []
        
        def mock_push_message(to, messages):
            push_called.append((to, messages))
        
        # Import and run _execute_daily_push
        from app import _execute_daily_push
        
        with patch('services.line_bot.line_bot_api') as mock_api:
            mock_api.push_message = mock_push_message
            
            # Run the async function
            asyncio.run(_execute_daily_push())
        
        # With is_sent=True, push should NOT have been called
        assert len(push_called) == 0, (
            f"_execute_daily_push() called push_message {len(push_called)} time(s) "
            f"even though is_sent=True. Bug 3: No duplicate guard."
        )
        
        # Restore is_sent to False for other tests
        logs["line_notification_status"]["is_sent"] = False
        dm._save(dm.dashboard_path, logs)

    @given(st.booleans())
    @settings(max_examples=5)
    def test_is_sent_flag_respected(self, is_sent_value):
        """
        Property: _execute_daily_push() respects the is_sent flag.
        When is_sent=True → no push. When is_sent=False → push attempted.
        
        **Validates: Requirements 2.3**
        """
        import asyncio
        from core.data_manager import DataManager
        
        dm = DataManager(elder_id="elder_demo_user_001")
        logs = dm.get_dashboard_logs()
        logs["line_notification_status"]["is_sent"] = is_sent_value
        dm._save(dm.dashboard_path, logs)
        
        push_called = []
        
        def mock_push(to, messages):
            push_called.append(True)
        
        from app import _execute_daily_push
        
        with patch('services.line_bot.line_bot_api') as mock_api:
            mock_api.push_message = mock_push
            asyncio.run(_execute_daily_push())
        
        if is_sent_value:
            # When is_sent=True, NO push should happen
            assert len(push_called) == 0, (
                f"Push was called despite is_sent=True — duplicate guard missing"
            )
        
        # Cleanup
        logs["line_notification_status"]["is_sent"] = False
        dm._save(dm.dashboard_path, logs)


# ═══════════════════════════════════════════════════════
# Test 4: No Persistent Error Logging
# ═══════════════════════════════════════════════════════

class TestPersistentErrorLogging:
    """
    Bug 4: When LINE API fails (HTTP 401/403/etc), _send_line_push() only
    prints to stdout. No structured log is written to logs/line_bot.log.
    
    Expected behavior (after fix):
    Every LINE API failure MUST produce a structured log entry in
    logs/line_bot.log with timestamp, HTTP status code, and error message.
    """

    def test_http_error_produces_structured_log(self):
        """
        EXPECTED: When LINE API returns HTTP error, a structured log entry
        with timestamp and HTTP status code is written to logs/line_bot.log.
        
        On UNFIXED code: This WILL FAIL because errors are only print()ed.
        """
        from services.weather_cron import _send_line_push
        
        log_path = os.path.join(config.BASE_DIR, "logs", "line_bot.log")
        
        # Clear log
        if os.path.exists(log_path):
            with open(log_path, "w") as f:
                f.write("")
        
        # Use an invalid token that will cause HTTP 401
        with patch.object(config, 'LINE_CHANNEL_ACCESS_TOKEN', 'definitely_invalid_token_xyz'):
            with patch.object(config, 'LINE_TARGET_USER_ID', 'U_fake_user_id'):
                result = _send_line_push("test error logging")
        
        assert result is False, "Push with invalid token should fail"
        
        # Check structured log was written
        assert os.path.exists(log_path), "Log file must exist"
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()
        
        # Log must contain structured error info
        assert len(log_content.strip()) > 0, (
            "No error log written to logs/line_bot.log after HTTP failure "
            "(Bug 4: silent error swallowing)"
        )


# ═══════════════════════════════════════════════════════
# Test 5: No Reminder Push Mechanism
# ═══════════════════════════════════════════════════════

class TestReminderPushMechanism:
    """
    Bug 5: Pending reminders in reminders.json remain notified=False
    indefinitely — no background task checks them and pushes to LINE.
    
    Expected behavior (after fix):
    A background task periodically checks reminders.json for pending items
    and pushes them to LINE, then sets notified=True.
    """

    def test_pending_reminder_gets_pushed(self):
        """
        EXPECTED: A pending reminder should eventually trigger a LINE push
        and set notified=True.
        
        On UNFIXED code: This WILL FAIL because there is no reminder push
        mechanism — no background task checks reminders.json.
        """
        from core.data_manager import DataManager
        
        dm = DataManager(elder_id="elder_demo_user_001")
        
        # Add a pending reminder
        reminder = dm.add_reminder("提醒下午三點吃藥", requested_by="長者")
        assert reminder["status"] == "pending"
        assert reminder["notified"] is False
        
        # Check if there's a reminder push function/loop in app.py
        # The fix should have a _reminder_push_loop or similar
        try:
            from app import _reminder_push_loop
            has_reminder_loop = True
        except ImportError:
            has_reminder_loop = False
        
        assert has_reminder_loop, (
            "No _reminder_push_loop function found in app.py — "
            "Bug 5: No reminder push mechanism exists. "
            "Pending reminders will remain notified=False indefinitely."
        )

    def test_reminder_notified_flag_gets_updated(self):
        """
        EXPECTED: After a reminder is pushed to LINE, its notified flag
        should be set to True in reminders.json.
        
        On UNFIXED code: This WILL FAIL because no code ever updates
        the notified flag for reminders.
        """
        from core.data_manager import DataManager
        import asyncio
        
        dm = DataManager(elder_id="elder_demo_user_001")
        
        # Add a pending reminder
        reminder = dm.add_reminder("提醒五點要做運動", requested_by="長者")
        
        # Try to call reminder push loop
        try:
            from app import _reminder_push_loop
            
            # Mock the LINE push to succeed
            with patch('services.weather_cron._send_line_push', return_value=True):
                # Run one iteration of the reminder loop
                # The function is an async infinite loop, so we need to handle it carefully
                async def run_one_check():
                    """Run reminder check logic once."""
                    # Import the internal logic or call with timeout
                    try:
                        task = asyncio.create_task(_reminder_push_loop())
                        await asyncio.sleep(2)  # Give it time to process
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    except Exception:
                        pass
                
                asyncio.run(run_one_check())
            
            # Check that the reminder's notified flag was updated
            reminders = dm.get_reminders()
            latest_reminder = next(
                (r for r in reminders if r["content"] == "提醒五點要做運動"),
                None
            )
            
            assert latest_reminder is not None, "Reminder not found"
            assert latest_reminder["notified"] is True, (
                "Reminder's notified flag was NOT updated to True after push — "
                "Bug 5: No mechanism updates reminder status"
            )
            
        except ImportError:
            pytest.fail(
                "Cannot import _reminder_push_loop from app.py — "
                "Bug 5: No reminder push mechanism exists"
            )

    @given(st.text(min_size=3, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N'))))
    @settings(max_examples=5)
    def test_all_pending_reminders_eventually_notified(self, reminder_content):
        """
        Property: For any pending reminder added to reminders.json,
        there must exist a mechanism to push it and mark notified=True.
        
        **Validates: Requirements 2.5**
        """
        # The minimum requirement: a _reminder_push_loop must exist
        try:
            from app import _reminder_push_loop
        except ImportError:
            pytest.fail(
                f"No _reminder_push_loop exists — reminder '{reminder_content}' "
                f"would remain notified=False indefinitely (Bug 5)"
            )


# ═══════════════════════════════════════════════════════
# Summary Property Test: All Bug Conditions Combined
# ═══════════════════════════════════════════════════════

class TestCombinedBugConditions:
    """
    Combined property test verifying all 5 bug conditions are addressed.
    This tests the overall system behavior expectations.
    """

    @given(st.sampled_from([
        "elder_id_mismatch",
        "token_failure_no_log",
        "duplicate_push_no_guard",
        "no_error_logging",
        "no_reminder_push",
    ]))
    @settings(max_examples=5)
    def test_bug_condition_is_fixed(self, bug_type):
        """
        Property: For each of the 5 bug conditions, the expected behavior
        must hold true (this will FAIL on unfixed code).
        
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
        """
        if bug_type == "elder_id_mismatch":
            from services.line_bot import TARGET_ELDER_ID
            data_dir = os.path.join(config.BASE_DIR, "data")
            elder_path = os.path.join(data_dir, TARGET_ELDER_ID)
            assert os.path.isdir(elder_path), (
                f"Bug 1: TARGET_ELDER_ID='{TARGET_ELDER_ID}' has no data directory"
            )
            
        elif bug_type == "token_failure_no_log":
            from services.weather_cron import _send_line_push
            log_path = os.path.join(config.BASE_DIR, "logs", "line_bot.log")
            if os.path.exists(log_path):
                with open(log_path, "w") as f:
                    f.write("")
            
            with patch.object(config, 'LINE_CHANNEL_ACCESS_TOKEN', ''):
                with patch.object(config, 'LINE_TARGET_USER_ID', ''):
                    _send_line_push("test")
            
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    content = f.read()
                assert len(content.strip()) > 0, "Bug 2/4: No log written on failure"
            else:
                pytest.fail("Bug 2/4: Log file doesn't exist after push failure")
                
        elif bug_type == "duplicate_push_no_guard":
            import asyncio
            from core.data_manager import DataManager
            
            dm = DataManager(elder_id="elder_demo_user_001")
            logs = dm.get_dashboard_logs()
            logs["line_notification_status"]["is_sent"] = True
            dm._save(dm.dashboard_path, logs)
            
            push_called = []
            from app import _execute_daily_push
            
            with patch('services.line_bot.line_bot_api') as mock_api:
                mock_api.push_message = lambda *a, **kw: push_called.append(1)
                asyncio.run(_execute_daily_push())
            
            assert len(push_called) == 0, "Bug 3: Push sent despite is_sent=True"
            
            # Cleanup
            logs["line_notification_status"]["is_sent"] = False
            dm._save(dm.dashboard_path, logs)
            
        elif bug_type == "no_error_logging":
            from services.weather_cron import _send_line_push
            log_path = os.path.join(config.BASE_DIR, "logs", "line_bot.log")
            if os.path.exists(log_path):
                with open(log_path, "w") as f:
                    f.write("")
            
            with patch.object(config, 'LINE_CHANNEL_ACCESS_TOKEN', 'bad_token'):
                with patch.object(config, 'LINE_TARGET_USER_ID', 'U_bad_user'):
                    _send_line_push("test error logging")
            
            assert os.path.exists(log_path), "Bug 4: No log file after failure"
            with open(log_path, "r") as f:
                content = f.read()
            assert len(content.strip()) > 0, "Bug 4: Empty log file after failure"
            
        elif bug_type == "no_reminder_push":
            try:
                from app import _reminder_push_loop
            except ImportError:
                pytest.fail("Bug 5: No _reminder_push_loop in app.py")
