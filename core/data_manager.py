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
from datetime import datetime, date, timedelta
from typing import Optional

import config


# ═══════════════════════════════════════════════════════
# 路徑定義
# ═══════════════════════════════════════════════════════
DATA_DIR = os.path.join(config.BASE_DIR, "data")

# 短期記憶 TTL 設定（時間制）
# 一般對話：30 分鐘後過期
# 重要對話（用藥、健康等）：120 分鐘後過期
# 極重要對話（跌倒、求救）：240 分鐘後過期
SHORT_TERM_TTL_MINUTES = {
    "low": 30,       # 不重要對話 TTL：30 分鐘
    "normal": 60,    # 一般對話 TTL：60 分鐘
    "high": 120,     # 重要對話 TTL：120 分鐘（2 小時）
    "critical": 240, # 極重要對話 TTL：240 分鐘（4 小時）
}

# Session 閒置超時（秒）：超過此時間視為 Session 結束，觸發背景記憶分析
SESSION_IDLE_TIMEOUT_SECONDS = 120  # 2 分鐘


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


# 預設路徑（已棄用，保留僅為避免舊模組 import 報錯）
PROFILE_PATH = None
LONG_TERM_PATH = None
SHORT_TERM_PATH = None
DASHBOARD_PATH = None


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
        self.reminders_path = os.path.join(self.elder_dir, "reminders.json")
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
                "personal_info": {
                    "name": "",
                    "nickname": "",
                    "gender": "",
                    "age": None,
                    "birth_year": None,
                    "location": "",
                    "health_insurance_id": ""
                },
                "emergency_contact": {
                    "name": "",
                    "relationship": "",
                    "phone": "",
                    "phone_2": ""
                },
                "medical_safety": {
                    "drug_allergies": [],
                    "food_allergies": [],
                    "chronic_diseases": [],
                    "current_medications": [],
                    "medication_schedule": {}
                },
                "physical_care": {
                    "mobility": "",
                    "swallowing_ability": "",
                    "dietary_restrictions": [],
                    "toileting_status": ""
                },
                "mental_cognitive": {
                    "has_dementia": False,
                    "dementia_level": "",
                    "has_wandering_history": False,
                    "emotional_traits": "",
                    "cognitive_notes": ""
                },
                "localization_settings": {
                    "primary_language": "中文",
                    "secondary_language": "",
                    "tts_accent": "台灣國語腔調",
                    "persona_relation": "貼心孝順的晚輩"
                }
            },
            self.long_term_path: {
                "elder_id": self.elder_id,
                "meta": {"last_analyzed_at": None},
                "records": [],
                "emotion_history": []
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
        # reminders.json 單獨處理
        if not os.path.exists(self.reminders_path) or os.stat(self.reminders_path).st_size == 0:
            self._save(self.reminders_path, {"elder_id": self.elder_id, "reminders": []})

    # ═══════════════════════════════════════════════════
    # 1. Elder Profile（長輩基本資料）
    # ═══════════════════════════════════════════════════

    def get_profile(self) -> dict:
        data = self._load(self.profile_path)
        # 相容遷移：若舊資料有 care_baseline，自動遷移到新結構
        if "care_baseline" in data:
            old = data.pop("care_baseline")
            # 遷移慢性病到 medical_safety
            if "medical_safety" not in data:
                data["medical_safety"] = {"drug_allergies": [], "food_allergies": [], "chronic_diseases": [], "current_medications": [], "medication_schedule": {}}
            diseases = old.get("chronic_diseases", old.get("diseases", []))
            if diseases:
                data["medical_safety"]["chronic_diseases"] = diseases
            # 遷移緊急聯絡人
            if "emergency_contact" not in data:
                data["emergency_contact"] = {"name": "", "relationship": "", "phone": "", "phone_2": ""}
            if old.get("emergency_contact"):
                data["emergency_contact"]["phone"] = old["emergency_contact"]
            data["meta"]["last_updated"] = datetime.now().isoformat()
            self._save(self.profile_path, data)
        return data

    def update_profile(self, **kwargs):
        """更新 personal_info 中的欄位"""
        data = self._load(self.profile_path)
        if "personal_info" not in data:
            data["personal_info"] = {}
        for key, val in kwargs.items():
            if key in data.get("personal_info", {}):
                data["personal_info"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    def update_care_baseline(self, **kwargs):
        """更新醫療安全資訊（相容舊介面，實際寫入 medical_safety）"""
        data = self._load(self.profile_path)
        # 相容處理：若傳入 diseases，對應到 chronic_diseases
        if "diseases" in kwargs:
            kwargs["chronic_diseases"] = kwargs.pop("diseases")
        # 相容處理：core_emotional_need 對應到 mental_cognitive.emotional_traits
        if "core_emotional_need" in kwargs:
            emotional_note = kwargs.pop("core_emotional_need")
            if emotional_note:
                if "mental_cognitive" not in data:
                    data["mental_cognitive"] = {"has_dementia": False, "dementia_level": "", "has_wandering_history": False, "emotional_traits": "", "cognitive_notes": ""}
                data["mental_cognitive"]["cognitive_notes"] = emotional_note
        # 確保 medical_safety 區塊存在
        if "medical_safety" not in data:
            data["medical_safety"] = {"drug_allergies": [], "food_allergies": [], "chronic_diseases": [], "current_medications": [], "medication_schedule": {}}
        for key, val in kwargs.items():
            if key in data["medical_safety"]:
                data["medical_safety"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    def update_medical_safety(self, **kwargs):
        """更新醫療與用藥安全資訊"""
        data = self._load(self.profile_path)
        if "medical_safety" not in data:
            data["medical_safety"] = {"drug_allergies": [], "food_allergies": [], "chronic_diseases": [], "current_medications": [], "medication_schedule": {}}
        for key, val in kwargs.items():
            data["medical_safety"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    def update_physical_care(self, **kwargs):
        """更新生理與日常照護資訊"""
        data = self._load(self.profile_path)
        if "physical_care" not in data:
            data["physical_care"] = {"mobility": "", "swallowing_ability": "", "dietary_restrictions": [], "toileting_status": ""}
        for key, val in kwargs.items():
            data["physical_care"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    def update_mental_cognitive(self, **kwargs):
        """更新精神與認知狀態資訊"""
        data = self._load(self.profile_path)
        if "mental_cognitive" not in data:
            data["mental_cognitive"] = {"has_dementia": False, "dementia_level": "", "has_wandering_history": False, "emotional_traits": "", "cognitive_notes": ""}
        for key, val in kwargs.items():
            data["mental_cognitive"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    def update_emergency_contact(self, **kwargs):
        """更新緊急聯絡人資訊"""
        data = self._load(self.profile_path)
        if "emergency_contact" not in data:
            data["emergency_contact"] = {"name": "", "relationship": "", "phone": "", "phone_2": ""}
        for key, val in kwargs.items():
            data["emergency_contact"][key] = val
        data["meta"]["last_updated"] = datetime.now().isoformat()
        self._save(self.profile_path, data)

    # ═══════════════════════════════════════════════════
    # 2. Long-Term Memory（長期記憶 — 帶 TTL）
    # ═══════════════════════════════════════════════════

    # TTL 對照表（天數）：根據重要程度決定保存多久
    _LONG_TERM_TTL_DAYS = {
        "permanent": 99999,  # 永久保存（用藥、疾病等長期資料）
        "critical": 365,     # 極重要（受傷）：保留 1 年
        "high": 90,          # 重要（健康症狀、睡眠異常）：保留 3 個月
        "normal": 30,        # 一般（飲食、活動）：保留 30 天
        "low": 15,           # 不重要（一般閒聊提取的偏好）：保留 15 天
    }

    def get_long_term_memory(self) -> dict:
        data = self._load(self.long_term_path)
        # 自動清理過期記錄
        self._cleanup_expired_long_term_records(data)
        return data

    def _cleanup_expired_long_term_records(self, data: dict):
        """清理已超過 TTL 的長期記憶記錄"""
        now = datetime.now()
        records = data.get("records", [])
        original_count = len(records)
        
        data["records"] = [
            r for r in records
            if datetime.fromisoformat(r.get("expires_at", now.isoformat())) > now
        ]
        
        removed = original_count - len(data["records"])
        if removed > 0:
            print(f"🗑️ [長期記憶] 清理 {removed} 筆過期記錄")
            self._save(self.long_term_path, data)

    def add_long_term_record(self, category: str, content: str, importance: str = "normal"):
        """
        新增一筆長期記憶記錄（帶 TTL）。
        
        category: medication / diet / activity / sleep / symptom / preference / social
        importance: critical（1年）/ high（3月）/ normal（30天）/ low（15天）
        """
        data = self._load(self.long_term_path)
        if "records" not in data:
            data["records"] = []
        
        ttl_days = self._LONG_TERM_TTL_DAYS.get(importance, 30)
        expires_at = datetime.now() + timedelta(days=ttl_days)
        
        record = {
            "category": category,
            "content": content,
            "importance": importance,
            "recorded_at": datetime.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_days": ttl_days,
        }
        
        data["records"].insert(0, record)
        data["meta"]["last_analyzed_at"] = datetime.now().isoformat()
        
        # 限制最大記錄數（防止無限增長）
        if len(data["records"]) > 200:
            data["records"] = data["records"][:200]
        
        self._save(self.long_term_path, data)
        print(f"📝 [長期記憶] 新增 [{category}] {content[:30]}（保留 {ttl_days} 天）")

    def get_long_term_summary_text(self) -> str:
        """將長期記憶轉為文字 prompt，供 LLM 參考"""
        data = self.get_long_term_memory()
        records = data.get("records", [])
        if not records:
            return ""
        
        summary = "\n[長期記憶紀錄（以下為過去的重要資訊）]\n"
        # 按類別分組顯示，最多顯示最近 20 筆
        for record in records[:20]:
            cat = record.get("category", "")
            content = record.get("content", "")
            summary += f"- [{cat}] {content}\n"
        summary += "[長期記憶結束]\n"
        return summary

    def update_medication_compliance(self, taken: bool, time_str: str = None):
        """記錄用藥狀態（相容舊介面）"""
        pass  # 用藥記錄改由 add_long_term_record 處理

    def add_emotion_record(self, emotion: str, reason: str = "", confidence: float = 0.0, source: str = "text"):
        """
        新增情緒歷史紀錄（用於心情趨勢圖）。
        
        source: 'text'（文字判斷）或 'voice'（語音辨識）
        """
        data = self._load(self.long_term_path)
        if "emotion_history" not in data:
            data["emotion_history"] = []
        
        record = {
            "time": datetime.now().isoformat(),
            "emotion": emotion,
            "reason": reason[:50] if reason else "",
            "confidence": round(confidence, 2),
            "source": source,
        }
        data["emotion_history"].insert(0, record)
        
        # 最多保留 100 筆（約 1~2 週的資料）
        if len(data["emotion_history"]) > 100:
            data["emotion_history"] = data["emotion_history"][:100]
        
        self._save(self.long_term_path, data)

    def get_emotion_history(self) -> list:
        """取得情緒歷史紀錄（供趨勢圖使用）"""
        data = self._load(self.long_term_path)
        return data.get("emotion_history", [])

    def add_health_record(self, record_type: str, description: str):
        """新增健康紀錄（相容舊介面，委派給 add_long_term_record）"""
        importance = "critical" if record_type == "injury" else "high"
        self.add_long_term_record("symptom", description, importance)

    # ═══════════════════════════════════════════════════
    # 提醒事項（reminders.json）
    # ═══════════════════════════════════════════════════

    def add_reminder(self, content: str, requested_by: str = "長者") -> dict:
        """
        新增提醒事項。
        回傳新增的 reminder 物件。
        """
        data = self._load(self.reminders_path)
        if "reminders" not in data:
            data["reminders"] = []
        
        reminder = {
            "content": content,
            "requested_by": requested_by,
            "created_at": datetime.now().isoformat(),
            "status": "pending",
            "notified": False,
        }
        data["reminders"].insert(0, reminder)
        
        # 最多保留 50 筆
        if len(data["reminders"]) > 50:
            data["reminders"] = data["reminders"][:50]
        
        self._save(self.reminders_path, data)
        return reminder

    def get_reminders(self) -> list:
        """取得所有提醒事項"""
        data = self._load(self.reminders_path)
        return data.get("reminders", [])

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
        """將短期對話歷史轉為文字 prompt（供 AI 對話使用），自動過濾已過期對話"""
        self._cleanup_expired_dialogues()
        history = self.get_dialogue_history()
        if not history:
            return ""
        summary = "\n[前幾次對話歷史紀錄]\n"
        for turn in history:
            summary += f"長者：{turn['user']}\n"
            summary += f"助理：{turn['ai']}\n"
        summary += "[歷史紀錄結束，請根據以上脈絡回應以下最新對話]\n"
        return summary

    def _cleanup_expired_dialogues(self):
        """清理已超過 TTL 過期時間的短期對話"""
        data = self._load(self.short_term_path)
        now = datetime.now()
        original_count = len(data["dialogue_history"])
        
        data["dialogue_history"] = [
            entry for entry in data["dialogue_history"]
            if datetime.fromisoformat(entry.get("expires_at", now.isoformat())) > now
        ]
        
        removed = original_count - len(data["dialogue_history"])
        if removed > 0:
            print(f"🗑️ [TTL] 清理 {removed} 筆過期短期記憶")
            self._save(self.short_term_path, data)

    def add_dialogue_turn(self, user_text: str, ai_reply: str, flagged: bool = False):
        """
        新增一輪對話到短期記憶（時間制 TTL）。
        
        TTL 策略：
        - 由 LLM 判斷重要程度（1~10 分），依分數對應不同過期時間
        - 1~3 分（不重要）→ 30 分鐘後過期
        - 4~6 分（一般）  → 60 分鐘後過期
        - 7~8 分（重要）  → 120 分鐘後過期（2 小時）
        - 9~10 分（極重要）→ 240 分鐘後過期（4 小時）
        """
        data = self._load(self.short_term_path)
        now = datetime.now()
        
        # 1. 清理已過期的對話
        data["dialogue_history"] = [
            entry for entry in data["dialogue_history"]
            if datetime.fromisoformat(entry.get("expires_at", now.isoformat())) > now
        ]
        
        # 2. 用 LLM 判斷本次對話的重要程度（決定 TTL）
        importance = self._evaluate_importance(user_text, ai_reply)
        
        # 3. 根據重要度決定 TTL 分鐘數
        if importance >= 9:
            ttl_minutes = SHORT_TERM_TTL_MINUTES["critical"]
        elif importance >= 7:
            ttl_minutes = SHORT_TERM_TTL_MINUTES["high"]
        elif importance >= 4:
            ttl_minutes = SHORT_TERM_TTL_MINUTES["normal"]
        else:
            ttl_minutes = SHORT_TERM_TTL_MINUTES["low"]
        
        expires_at = now + timedelta(minutes=ttl_minutes)
        
        # 4. 新增本次對話（含明確的過期時間戳）
        data["dialogue_history"].append({
            "turn": importance,
            "timestamp": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_minutes": ttl_minutes,
            "user": user_text,
            "ai": ai_reply,
            "is_flagged_for_long_term": flagged or (importance >= 8)
        })
        
        print(f"⏳ [TTL] 新對話存活 {ttl_minutes} 分鐘（重要度 {importance}/10），"
              f"過期時間：{expires_at.strftime('%H:%M:%S')}")
        
        # 更新時間
        data["active_context"]["current_time"] = now.isoformat()
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
            
            # 從檔案讀取提示詞
            try:
                with open(config.MEMORY_IMPORTANCE_PROMPT_PATH, 'r', encoding='utf-8') as f:
                    base_prompt = f.read()
            except Exception:
                base_prompt = "你是記憶重要度評分系統。只回傳一個 1~10 的數字。"
            
            prompt = f"{base_prompt}\n\n長者說：「{user_text}」"

            response = chat(
                model=config.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={'temperature': 0.0},
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
        """
        更新今日摘要（合併模式，不覆蓋已有內容）。
        - text: 新增摘要文字，會與舊摘要合併（不覆蓋）
        - metrics: 只更新有值的欄位，空值不覆蓋
        """
        data = self.get_dashboard_logs()
        
        # 摘要文字：合併而非覆蓋
        if text and text.strip():
            existing_text = data["today_summary"].get("text", "")
            if existing_text and text.strip() != existing_text.strip():
                # 合併，用換行分隔，保留最新的在前面
                data["today_summary"]["text"] = text.strip() + "\n" + existing_text.strip()
                # 限制最大長度（保留最新的 500 字）
                if len(data["today_summary"]["text"]) > 500:
                    data["today_summary"]["text"] = data["today_summary"]["text"][:500]
            elif not existing_text:
                data["today_summary"]["text"] = text.strip()
        
        # metrics：只更新有值的欄位，None/空字串不覆蓋現有值
        if metrics:
            existing_metrics = data["today_summary"].get("metrics", {})
            for key, val in metrics.items():
                if val is not None and val != "":
                    existing_metrics[key] = val
            data["today_summary"]["metrics"] = existing_metrics
        
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

        # 2. 時間軸事件（記錄長者說的話和小黃的回覆）
        self.add_timeline_event(
            event_type="interaction",
            title="智慧語音關懷",
            description=f"長者說：{user_text}\n小黃：{ai_reply}"
        )

        # 3. 互動計數
        self.increment_interaction_count()

        # 4. 摘要
        if summary_text:
            self.update_today_summary(summary_text, metrics)

    def get_full_dashboard_data(self) -> dict:
        """
        供 Dashboard API 一次回傳的完整資料包
        整合 profile + dashboard_logs + 情緒摘要
        """
        profile = self.get_profile()
        logs = self.get_dashboard_logs()
        long_term = self.get_long_term_memory()

        # 取得情緒摘要（若可用）
        emotion_summary = {}
        try:
            from speech.emotion_recognition import get_emotion_summary
            emotion_summary = get_emotion_summary()
        except Exception:
            pass

        return {
            "elder_id": profile.get("elder_id", ""),
            "personal_info": profile.get("personal_info", {}),
            "emergency_contact": profile.get("emergency_contact", {}),
            "medical_safety": profile.get("medical_safety", {}),
            "physical_care": profile.get("physical_care", {}),
            "mental_cognitive": profile.get("mental_cognitive", {}),
            "localization_settings": profile.get("localization_settings", {}),
            "medication_tracker": long_term.get("medication_tracker", {}),
            "health_records": long_term.get("health_records", {}),
            "report_date": logs.get("report_date", ""),
            "today_summary": logs.get("today_summary", {}),
            "interaction_stats": logs.get("interaction_stats", {}),
            "timeline_events": logs.get("timeline_events", []),
            "line_notification_status": logs.get("line_notification_status", {}),
            "emotion_summary": emotion_summary,
            "emotion_history": self.get_emotion_history(),
        }
