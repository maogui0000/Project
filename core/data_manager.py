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

# 短期記憶中每筆對話的存活輪數（新對話初始壽命，每次新互動全部 -1，歸 0 則刪除）
MAX_DIALOGUE_TURNS = 10


def _get_elder_data_dir(elder_id: str = "elder_001") -> str:
    """取得特定長者的資料目錄路徑"""
    return os.path.join(DATA_DIR, elder_id)


def _get_paths(elder_id: str = "elder_001") -> dict:
    """取得特定長者的所有 JSON 檔案路徑"""
    elder_dir = _get_elder_data_dir(elder_id)
    return {
        "profile": os.path.join(elder_dir, "elder_profile.json"),
        "long_term": os.path.join(elder_dir, "long_term_memory.json"),
        "short_term": os.path.join(elder_dir, "short_term_memory.json"),
        "dashboard": os.path.join(elder_dir, "dashboard_logs.json"),
    }


# 預設路徑（向後相容，供其他模組直接 import 用）
PROFILE_PATH = os.path.join(DATA_DIR, "elder_001", "elder_profile.json")
LONG_TERM_PATH = os.path.join(DATA_DIR, "elder_001", "long_term_memory.json")
SHORT_TERM_PATH = os.path.join(DATA_DIR, "elder_001", "short_term_memory.json")
DASHBOARD_PATH = os.path.join(DATA_DIR, "elder_001", "dashboard_logs.json")


class DataManager:
    """統一資料存取層，封裝所有 JSON 讀寫操作"""

    def __init__(self, elder_id: str = "elder_001"):
        self.elder_id = elder_id
        self.elder_dir = _get_elder_data_dir(elder_id)
        paths = _get_paths(elder_id)
        self.profile_path = paths["profile"]
        self.long_term_path = paths["long_term"]
        self.short_term_path = paths["short_term"]
        self.dashboard_path = paths["dashboard"]
        os.makedirs(self.elder_dir, exist_ok=True)
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
            self.profile_path: {
                "elder_id": self.elder_id,
                "meta": {"created_at": datetime.now().isoformat(), "last_updated": datetime.now().isoformat()},
                "personal_info": {"name": "長輩", "nickname": "", "gender": "", "age": None, "birth_year": None, "location": ""},
                "localization_settings": {"primary_language": "中文", "secondary_language": "", "tts_accent": "台灣國語腔調", "persona_relation": "貼心孝順的晚輩"},
                "care_baseline": {"diseases": [], "emergency_contact": "", "core_emotional_need": ""}
            },
            self.long_term_path: {
                "elder_id": self.elder_id,
                "meta": {"last_analyzed_at": None},
                "extracted_preferences": {"likes": [], "dislikes": []},
                "historical_habits": {"morning_routine": "", "afternoon_routine": ""},
                "medication_tracker": {"prescription_name": "", "requirement": "", "compliance_rate_this_week": 0.0}
            },
            self.short_term_path: {
                "elder_id": self.elder_id,
                "current_session_id": f"sess_{datetime.now().strftime('%Y%m%d')}_001",
                "active_context": {"weather": "", "current_time": datetime.now().isoformat(), "topic_focus": ""},
                "dialogue_history": []
            },
            self.dashboard_path: {
                "elder_id": self.elder_id,
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
        return self._load(self.profile_path)

    def update_profile(self, **kwargs):
        """更新 personal_info 中的欄位"""
        data = self._load(self.profile_path)
        for key, val in kwargs.items():
            if key in data["personal_info"]:
                data["personal_info"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    def update_care_baseline(self, **kwargs):
        """更新 care_baseline 中的欄位"""
        data = self._load(self.profile_path)
        for key, val in kwargs.items():
            if key in data["care_baseline"]:
                data["care_baseline"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    # ═══════════════════════════════════════════════════
    # 2. Long-Term Memory（長期記憶）
    # ═══════════════════════════════════════════════════

    def get_long_term_memory(self) -> dict:
        return self._load(self.long_term_path)

    def update_medication_compliance(self, taken: bool, time_str: str = None):
        """記錄用藥狀態"""
        data = self._load(self.long_term_path)
        data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
        # 簡易計算：如果有吃就微調 compliance_rate
        current_rate = data["medication_tracker"].get("compliance_rate_this_week", 0.0)
        if taken:
            data["medication_tracker"]["compliance_rate_this_week"] = min(1.0, current_rate + 0.05)
        else:
            data["medication_tracker"]["compliance_rate_this_week"] = max(0.0, current_rate - 0.1)
        self._save(self.long_term_path, data)

    def add_preference(self, category: str, item: str):
        """新增偏好（likes 或 dislikes）"""
        data = self._load(self.long_term_path)
        if category in data["extracted_preferences"]:
            if item not in data["extracted_preferences"][category]:
                data["extracted_preferences"][category].append(item)
                data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
                self._save(self.long_term_path, data)

    def update_long_term_field(self, section: str, key: str, value):
        """通用更新長期記憶欄位"""
        data = self._load(self.long_term_path)
        if section in data and key in data[section]:
            data[section][key] = value
            data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
            self._save(self.long_term_path, data)

    # ═══════════════════════════════════════════════════
    # 3. Short-Term Memory（短期記憶 / 對話歷史）
    # ═══════════════════════════════════════════════════

    def get_short_term_memory(self) -> dict:
        return self._load(self.short_term_path)

    def get_dialogue_history(self) -> list:
        data = self._load(self.short_term_path)
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
        """
        新增一輪對話到短期記憶。
        turn 代表存活剩餘輪數：由 LLM 判斷重要程度決定（1~10）。
        每次新增時所有舊對話 turn -1，turn <= 0 的刪除。
        """
        data = self._load(self.short_term_path)
        
        # 1. 所有既有對話的存活輪數 -1
        for entry in data["dialogue_history"]:
            entry["turn"] = entry.get("turn", 1) - 1
        
        # 2. 移除存活輪數 <= 0 的過期對話
        data["dialogue_history"] = [
            entry for entry in data["dialogue_history"] if entry.get("turn", 0) > 0
        ]
        
        # 3. 用 LLM 判斷本次對話的重要程度（決定存活輪數）
        importance = self._evaluate_importance(user_text, ai_reply)
        
        # 4. 新增本次對話
        data["dialogue_history"].append({
            "turn": importance,
            "timestamp": datetime.now().isoformat(),
            "user": user_text,
            "ai": ai_reply,
            "is_flagged_for_long_term": flagged or (importance >= 8)
        })
        
        # 更新時間
        data["active_context"]["current_time"] = datetime.now().isoformat()
        self._save(self.short_term_path, data)

    def _evaluate_importance(self, user_text: str, ai_reply: str) -> int:
        """
        用 LLM 評估一段對話的重要程度，回傳 1~10 的存活輪數。
        
        判斷標準：
        - 10: 極重要（用藥、身體不適、跌倒、求救）
        - 7~9: 重要（飲食、睡眠、情緒低落、重要生活事件）
        - 4~6: 一般（日常閒聊、問候、天氣話題）
        - 1~3: 不重要（無意義語音、辨識錯誤、重複問候）
        """
        try:
            from ollama import chat
            import config
            
            prompt = f"""你是記憶重要度評分系統。請評估以下長者對話的重要程度，只回傳一個 1~10 的數字。

評分標準：
- 9~10: 極重要（提到用藥、身體不適、疼痛、跌倒、求救、緊急狀況）
- 7~8: 重要（飲食內容、睡眠狀況、情緒低落、重要生活事件、家人相關）
- 4~6: 一般（日常閒聊、分享心情、問候、天氣、一般活動）
- 1~3: 不重要（無意義的語音、語音辨識錯誤、單字回應、重複問候）

長者說：「{user_text}」

只回傳數字，不要任何解釋："""

            response = chat(
                model=config.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            
            result = response["message"]["content"].strip()
            # 提取數字
            import re
            numbers = re.findall(r'\d+', result)
            if numbers:
                score = int(numbers[0])
                score = max(1, min(10, score))  # 限制在 1~10
                print(f"⚙️ [記憶評分] 「{user_text[:20]}...」→ 存活 {score} 輪")
                return score
        except Exception as e:
            print(f"⚠️ [記憶評分] LLM 評分失敗: {e}")
        
        # 預設存活 5 輪（一般重要度）
        return 5

    def update_active_context(self, weather: str = None, topic_focus: str = None):
        """更新當前對話的環境上下文"""
        data = self._load(self.short_term_path)
        if weather is not None:
            data["active_context"]["weather"] = weather
        if topic_focus is not None:
            data["active_context"]["topic_focus"] = topic_focus
        data["active_context"]["current_time"] = datetime.now().isoformat()
        self._save(self.short_term_path, data)

    def reset_session(self):
        """開始新的對話 session（喚醒詞觸發時）"""
        data = self._load(self.short_term_path)
        data["current_session_id"] = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        data["dialogue_history"] = []
        data["active_context"]["current_time"] = datetime.now().isoformat()
        data["active_context"]["topic_focus"] = ""
        self._save(self.short_term_path, data)

    # ═══════════════════════════════════════════════════
    # 4. Dashboard Logs（看板日誌）
    # ═══════════════════════════════════════════════════

    def get_dashboard_logs(self) -> dict:
        data = self._load(self.dashboard_path)
        # 如果日期不是今天，自動重置為今日
        today = date.today().isoformat()
        if data.get("report_date") != today:
            data["report_date"] = today
            data["today_summary"] = {"text": "", "metrics": {"diet": "尚未記錄", "sleep": "尚未記錄", "medication_taken": False, "medication_time": None}}
            data["timeline_events"] = []
            data["interaction_stats"]["total_turns"] = 0
            data["line_notification_status"]["is_sent"] = False
            self._save(self.dashboard_path, data)
        return data

    def update_today_summary(self, text: str, metrics: dict = None):
        """更新今日摘要"""
        data = self.get_dashboard_logs()
        data["today_summary"]["text"] = text
        if metrics:
            data["today_summary"]["metrics"].update(metrics)
        self._save(self.dashboard_path, data)

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
        self._save(self.dashboard_path, data)

    def increment_interaction_count(self):
        """更新今日互動統計：total_turns 反映短期記憶中存活的對話輪數"""
        data = self.get_dashboard_logs()
        # total_turns = 當前短期記憶中保留的對話輪數
        short_term = self._load(self.short_term_path)
        data["interaction_stats"]["total_turns"] = len(short_term.get("dialogue_history", []))
        # 更新本週趨勢（根據今天星期幾）
        weekday_index = datetime.now().weekday()  # 0=週一
        if 0 <= weekday_index < len(data["interaction_stats"]["weekly_trend"]):
            data["interaction_stats"]["weekly_trend"][weekday_index]["count"] = data["interaction_stats"]["total_turns"]
        self._save(self.dashboard_path, data)

    def mark_line_notification_sent(self):
        """標記 LINE 通知已發送"""
        data = self.get_dashboard_logs()
        data["line_notification_status"]["is_sent"] = True
        self._save(self.dashboard_path, data)

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
