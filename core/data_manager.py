"""
data_manager.py
雲湧智生 — 統一資料存取層

所有模組透過此檔案讀寫 4 個核心 JSON：
  - elder_profile.json     → 長輩基本資料與照護基線
  - long_term_memory.json  → 長期記憶（偏好/習慣/用藥追蹤）
  - short_term_memory.json → 短期記憶（當前對話上下文）
  - dashboard_logs.json    → 每日摘要/統計/時間軸（供看板讀取）

使用方式：
    from data_manager import DataManager
    dm = DataManager()
    profile = dm.get_profile()
    dm.add_dialogue_turn(user_text, ai_reply)
"""

import json
import os
from datetime import datetime, date
from typing import Optional

import config


# ═══════════════════════════════════════════════════════
# 路徑定義
# ═══════════════════════════════════════════════════════
DATA_DIR = os.path.join(config.BASE_DIR, "data")

PROFILE_PATH = os.path.join(DATA_DIR, "elder_profile.json")
LONG_TERM_PATH = os.path.join(DATA_DIR, "long_term_memory.json")
SHORT_TERM_PATH = os.path.join(DATA_DIR, "short_term_memory.json")
DASHBOARD_PATH = os.path.join(DATA_DIR, "dashboard_logs.json")

# 短期記憶最多保留幾輪對話
MAX_DIALOGUE_TURNS = 10


class DataManager:
    """統一資料存取層，封裝所有 JSON 讀寫操作"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._ensure_files_exist()

    # ─── 內部工具 ─────────────────────────────────────

    def _load(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, path: str, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_files_exist(self):
        """確保所有 JSON 檔案存在，不存在則建立預設結構"""
        defaults = {
            PROFILE_PATH: {
                "elder_id": "elder_001",
                "meta": {"created_at": datetime.now().isoformat(), "last_updated": datetime.now().isoformat()},
                "personal_info": {"name": "長輩", "nickname": "", "gender": "", "age": None, "birth_year": None, "location": ""},
                "localization_settings": {"primary_language": "中文", "secondary_language": "", "tts_accent": "台灣國語腔調", "persona_relation": "貼心孝順的晚輩"},
                "care_baseline": {"chronic_diseases": [], "emergency_contact": "", "core_emotional_need": ""}
            },
            LONG_TERM_PATH: {
                "elder_id": "elder_001",
                "meta": {"last_analyzed_at": None},
                "extracted_preferences": {"likes": [], "dislikes": []},
                "historical_habits": {"morning_routine": "", "afternoon_routine": ""},
                "medication_tracker": {"prescription_name": "", "requirement": "", "compliance_rate_this_week": 0.0}
            },
            SHORT_TERM_PATH: {
                "elder_id": "elder_001",
                "current_session_id": f"sess_{datetime.now().strftime('%Y%m%d')}_001",
                "active_context": {"weather": "", "current_time": datetime.now().isoformat(), "topic_focus": ""},
                "dialogue_history": []
            },
            DASHBOARD_PATH: {
                "elder_id": "elder_001",
                "report_date": date.today().isoformat(),
                "line_notification_status": {"trigger_time": "19:00:00", "is_sent": False},
                "today_summary": {"text": "", "metrics": {"diet": "尚未記錄", "sleep": "尚未記錄", "medication_taken": False, "medication_time": None}},
                "interaction_stats": {"total_turns": 0, "weekly_trend": [{"day": d, "count": 0} for d in ["週一","週二","週三","週四","週五","週六","週日"]]},
                "timeline_events": []
            }
        }
        for path, default_data in defaults.items():
            if not os.path.exists(path) or os.stat(path).st_size == 0:
                self._save(path, default_data)

    # ═══════════════════════════════════════════════════
    # 1. Elder Profile（長輩基本資料）
    # ═══════════════════════════════════════════════════

    def get_profile(self) -> dict:
        return self._load(PROFILE_PATH)

    def update_profile(self, **kwargs):
        """更新 personal_info 中的欄位"""
        data = self._load(PROFILE_PATH)
        for key, val in kwargs.items():
            if key in data["personal_info"]:
                data["personal_info"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(PROFILE_PATH, data)

    def update_care_baseline(self, **kwargs):
        """更新 care_baseline 中的欄位"""
        data = self._load(PROFILE_PATH)
        for key, val in kwargs.items():
            if key in data["care_baseline"]:
                data["care_baseline"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(PROFILE_PATH, data)

    # ═══════════════════════════════════════════════════
    # 2. Long-Term Memory（長期記憶）
    # ═══════════════════════════════════════════════════

    def get_long_term_memory(self) -> dict:
        return self._load(LONG_TERM_PATH)

    def update_medication_compliance(self, taken: bool, time_str: str = None):
        """記錄用藥狀態"""
        data = self._load(LONG_TERM_PATH)
        data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
        # 簡易計算：如果有吃就微調 compliance_rate
        current_rate = data["medication_tracker"].get("compliance_rate_this_week", 0.0)
        if taken:
            data["medication_tracker"]["compliance_rate_this_week"] = min(1.0, current_rate + 0.05)
        else:
            data["medication_tracker"]["compliance_rate_this_week"] = max(0.0, current_rate - 0.1)
        self._save(LONG_TERM_PATH, data)

    def add_preference(self, category: str, item: str):
        """新增偏好（likes 或 dislikes）"""
        data = self._load(LONG_TERM_PATH)
        if category in data["extracted_preferences"]:
            if item not in data["extracted_preferences"][category]:
                data["extracted_preferences"][category].append(item)
                data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
                self._save(LONG_TERM_PATH, data)

    def update_long_term_field(self, section: str, key: str, value):
        """通用更新長期記憶欄位"""
        data = self._load(LONG_TERM_PATH)
        if section in data and key in data[section]:
            data[section][key] = value
            data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
            self._save(LONG_TERM_PATH, data)

    # ═══════════════════════════════════════════════════
    # 3. Short-Term Memory（短期記憶 / 對話歷史）
    # ═══════════════════════════════════════════════════

    def get_short_term_memory(self) -> dict:
        return self._load(SHORT_TERM_PATH)

    def get_dialogue_history(self) -> list:
        data = self._load(SHORT_TERM_PATH)
        return data.get("dialogue_history", [])

    def get_history_summary_text(self) -> str:
        """將短期對話歷史轉為文字 prompt（供 AI 對話使用）"""
        history = self.get_dialogue_history()
        if not history:
            return ""
        summary = "\n[前幾次對話歷史紀錄]\n"
        for turn in history:
            summary += f"長者：{turn['user']}\n"
            summary += f"助理：{turn['ai']}\n"
        summary += "[歷史紀錄結束，請根據以上脈絡回應以下最新對話]\n"
        return summary

    def add_dialogue_turn(self, user_text: str, ai_reply: str, flagged: bool = False):
        """新增一輪對話到短期記憶"""
        data = self._load(SHORT_TERM_PATH)
        turn_number = len(data["dialogue_history"]) + 1
        data["dialogue_history"].append({
            "turn": turn_number,
            "timestamp": datetime.now().isoformat(),
            "user": user_text,
            "ai": ai_reply,
            "is_flagged_for_long_term": flagged
        })
        # 保持最多 MAX_DIALOGUE_TURNS 輪
        if len(data["dialogue_history"]) > MAX_DIALOGUE_TURNS:
            data["dialogue_history"] = data["dialogue_history"][-MAX_DIALOGUE_TURNS:]
        # 更新時間
        data["active_context"]["current_time"] = datetime.now().isoformat()
        self._save(SHORT_TERM_PATH, data)

    def update_active_context(self, weather: str = None, topic_focus: str = None):
        """更新當前對話的環境上下文"""
        data = self._load(SHORT_TERM_PATH)
        if weather is not None:
            data["active_context"]["weather"] = weather
        if topic_focus is not None:
            data["active_context"]["topic_focus"] = topic_focus
        data["active_context"]["current_time"] = datetime.now().isoformat()
        self._save(SHORT_TERM_PATH, data)

    def reset_session(self):
        """開始新的對話 session（喚醒詞觸發時）"""
        data = self._load(SHORT_TERM_PATH)
        data["current_session_id"] = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        data["dialogue_history"] = []
        data["active_context"]["current_time"] = datetime.now().isoformat()
        data["active_context"]["topic_focus"] = ""
        self._save(SHORT_TERM_PATH, data)

    # ═══════════════════════════════════════════════════
    # 4. Dashboard Logs（看板日誌）
    # ═══════════════════════════════════════════════════

    def get_dashboard_logs(self) -> dict:
        data = self._load(DASHBOARD_PATH)
        # 如果日期不是今天，自動重置為今日
        today = date.today().isoformat()
        if data.get("report_date") != today:
            data["report_date"] = today
            data["today_summary"] = {"text": "", "metrics": {"diet": "尚未記錄", "sleep": "尚未記錄", "medication_taken": False, "medication_time": None}}
            data["timeline_events"] = []
            data["interaction_stats"]["total_turns"] = 0
            data["line_notification_status"]["is_sent"] = False
            self._save(DASHBOARD_PATH, data)
        return data

    def update_today_summary(self, text: str, metrics: dict = None):
        """更新今日摘要"""
        data = self.get_dashboard_logs()
        data["today_summary"]["text"] = text
        if metrics:
            data["today_summary"]["metrics"].update(metrics)
        self._save(DASHBOARD_PATH, data)

    def add_timeline_event(self, event_type: str, title: str, description: str, time_str: str = None):
        """新增時間軸事件"""
        data = self.get_dashboard_logs()
        event = {
            "time": time_str or datetime.now().isoformat(),
            "type": event_type,
            "title": title,
            "description": description
        }
        data["timeline_events"].insert(0, event)
        # 最多保留 50 筆
        if len(data["timeline_events"]) > 50:
            data["timeline_events"] = data["timeline_events"][:50]
        self._save(DASHBOARD_PATH, data)

    def increment_interaction_count(self):
        """增加今日互動次數"""
        data = self.get_dashboard_logs()
        data["interaction_stats"]["total_turns"] += 1
        # 更新本週趨勢（根據今天星期幾）
        weekday_index = datetime.now().weekday()  # 0=週一
        if 0 <= weekday_index < len(data["interaction_stats"]["weekly_trend"]):
            data["interaction_stats"]["weekly_trend"][weekday_index]["count"] += 1
        self._save(DASHBOARD_PATH, data)

    def mark_line_notification_sent(self):
        """標記 LINE 通知已發送"""
        data = self.get_dashboard_logs()
        data["line_notification_status"]["is_sent"] = True
        self._save(DASHBOARD_PATH, data)

    # ═══════════════════════════════════════════════════
    # 綜合操作（跨多個 JSON 的寫入）
    # ═══════════════════════════════════════════════════

    def record_full_interaction(self, user_text: str, ai_reply: str, summary_text: str = None, metrics: dict = None):
        """
        一次完整互動後的統一寫入：
        1. 短期記憶加入對話
        2. Dashboard 加入時間軸事件
        3. Dashboard 互動次數 +1
        4. 如果有摘要，更新 today_summary
        """
        # 1. 短期記憶
        self.add_dialogue_turn(user_text, ai_reply)

        # 2. 時間軸事件
        self.add_timeline_event(
            event_type="interaction",
            title="智慧語音關懷",
            description=f"長者說：{user_text}\nAI回覆：{ai_reply}"
        )

        # 3. 互動計數
        self.increment_interaction_count()

        # 4. 摘要
        if summary_text:
            self.update_today_summary(summary_text, metrics)

    def get_full_dashboard_data(self) -> dict:
        """
        供 Dashboard API 一次回傳的完整資料包
        整合 profile + dashboard_logs
        """
        profile = self.get_profile()
        logs = self.get_dashboard_logs()
        long_term = self.get_long_term_memory()

        return {
            "elder_id": profile.get("elder_id", "elder_001"),
            "personal_info": profile.get("personal_info", {}),
            "localization_settings": profile.get("localization_settings", {}),
            "care_baseline": profile.get("care_baseline", {}),
            "medication_tracker": long_term.get("medication_tracker", {}),
            "report_date": logs.get("report_date", ""),
            "today_summary": logs.get("today_summary", {}),
            "interaction_stats": logs.get("interaction_stats", {}),
            "timeline_events": logs.get("timeline_events", []),
            "line_notification_status": logs.get("line_notification_status", {}),
        }
