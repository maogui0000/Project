"""
Long_Short_Term_Memory_Control/Control.py
記憶控制器 — 適配新版 4 檔 JSON 資料格式

此模組作為相容層，保留原有的 MemoryController 介面，
底層委派給統一資料存取層 DataManager 執行實際讀寫。
"""

import os
import sys
import json
from datetime import datetime

# 確保能 import 上層模組
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.data_manager import DataManager

# 匯入配置
import config

# 匯入 AI 對話函數
try:
    from core.ai_chat import ask_ollama
    print("✅ [記憶控制] 成功對接 Bedrock AI 模型接口！")
except ImportError as e:
    print(f"⚠️ [記憶控制] 無法匯入 AI_Chat ({e})")
    ask_ollama = None


class MemoryController:
    """
    記憶控制器：管理長短期記憶，與 AI 分析用藥/飲食/症狀。
    
    底層使用 DataManager 讀寫 data/ 目錄下的 JSON 檔案。
    保留舊有介面方法，確保 voice_assistant.py、app.py 等不需大改。
    """

    def __init__(self, elder_id: str = None):
        # 如果沒有指定 elder_id，延遲初始化（不立即建立 DataManager）
        self._elder_id = elder_id
        if elder_id:
            self.dm = DataManager(elder_id=elder_id)
        else:
            self.dm = None

    def set_elder_id(self, elder_id: str):
        """動態設定長者 ID 並初始化 DataManager"""
        self._elder_id = elder_id
        self.dm = DataManager(elder_id=elder_id)

    def _ensure_dm(self):
        """確保 DataManager 已初始化"""
        if self.dm is None:
            raise RuntimeError("MemoryController 尚未設定 elder_id，請先呼叫 set_elder_id()")

    def get_history_summary_text(self) -> str:
        """
        將短期對話歷史轉成文字 prompt，塞進 AI 的對話脈絡
        """
        if self.dm is None:
            return ""
        return self.dm.get_history_summary_text()

    def update_memories(self, user_text: str, ai_text: str):
        """
        情境判斷與記憶更新：
        1. 加入短期對話記憶
        2. 用 AI 分析是否有用藥/飲食/症狀資訊
        3. 如有，更新長期記憶與看板日誌
        """
        if self.dm is None:
            print("⚠️ [記憶控制] 尚未設定 elder_id，跳過記憶更新")
            return False
        
        now = config.now_tw()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 寫入短期記憶
        self.dm.add_dialogue_turn(user_text, ai_text)

        # 2. 用 AI 分析健康資訊
        analysis = self._analyze_health_info(user_text, current_time_str)

        has_medication = analysis.get("medication", {}).get("status") != "未提及"
        has_diet = analysis.get("diet") is not None
        has_symptom = analysis.get("symptom") is not None
        
        print(f"⚙️ [統整分析結果] med={has_medication}({analysis.get('medication',{}).get('status')}), diet={has_diet}({analysis.get('diet')}), symptom={has_symptom}, activity={analysis.get('activity')}, sleep={analysis.get('sleep')}")

        is_long_term_updated = False
        
        # 通用時段判斷
        hour = now.hour
        if 5 <= hour < 11:
            current_period = "早上"
        elif 11 <= hour < 14:
            current_period = "中午"
        elif 17 <= hour < 21:
            current_period = "晚上"
        else:
            current_period = "其他"

        # 3. 根據分析結果更新長期記憶與看板
        if has_medication:
            med_info = analysis["medication"]
            taken = med_info.get("status") == "已吃"
            med_time = med_info.get("time") or current_time_str
            status_text = "已服藥" if taken else "未服藥"
            med_name = med_info.get("name") or "藥物"

            # 寫入長期記憶（用藥：永久保存，除非使用者說要改藥）
            self.dm.add_long_term_record(
                category="medication",
                content=f"{current_period} 服用{med_name}（{status_text}）",
                importance="permanent"
            )
            
            # 將藥物名稱寫入 profile
            if med_name and med_name != "藥物" and med_name != "null" and "或" not in med_name:
                profile = self.dm.get_profile()
                current_meds = profile.get("medical_safety", {}).get("current_medications", [])
                if med_name not in current_meds:
                    current_meds.append(med_name)
                    self.dm.update_medical_safety(current_medications=current_meds)

            # 按時段累加用藥記錄
            dashboard = self.dm.get_dashboard_logs()
            existing_med = dashboard.get("today_summary", {}).get("metrics", {}).get("medication_by_period", {})
            existing_med[current_period] = f"{med_name}（{status_text}）"
            
            med_display_parts = []
            for p in ["早上", "中午", "晚上"]:
                if p in existing_med:
                    med_display_parts.append(f"{p}：{existing_med[p]}")
            if "其他" in existing_med:
                med_display_parts.append(f"其他：{existing_med['其他']}")
            med_display = "\n".join(med_display_parts) if med_display_parts else f"{current_period}：{med_name}（{status_text}）"

            self.dm.update_today_summary(text="", metrics={
                "medication_taken": taken,
                "medication_name": med_name,
                "medication": med_display,
                "medication_by_period": existing_med,
            })

            # 時間軸事件
            event_desc = f"長者表示已服用{med_name}" if taken else f"長者表示尚未服用{med_name}"
            self.dm.add_timeline_event(
                event_type="health",
                title=f"用藥紀錄：{med_name}（{status_text}）",
                description=event_desc
            )
            is_long_term_updated = True

        if has_diet:
            diet_text = analysis["diet"]
            
            # 按時段累加飲食記錄
            dashboard = self.dm.get_dashboard_logs()
            existing_diet = dashboard.get("today_summary", {}).get("metrics", {}).get("diet_by_period", {})
            existing_diet[current_period] = diet_text
            
            diet_display_parts = []
            for p in ["早上", "中午", "晚上"]:
                if p in existing_diet:
                    diet_display_parts.append(f"{p}：{existing_diet[p]}")
            if "其他" in existing_diet:
                diet_display_parts.append(f"其他：{existing_diet['其他']}")
            diet_display = "\n".join(diet_display_parts)
            
            self.dm.update_today_summary(text="", metrics={
                "diet": diet_display,
                "diet_by_period": existing_diet,
            })
            # 寫入長期記憶（飲食：一般，保留 30 天）
            self.dm.add_long_term_record(
                category="diet",
                content=f"{current_period} 吃了{diet_text}",
                importance="normal"
            )
            is_long_term_updated = True

        if has_symptom:
            symptom_text = analysis["symptom"]
            self.dm.add_timeline_event(
                event_type="health",
                title=f"健康紀錄：{symptom_text}",
                description=f"長者提及身體狀況：{symptom_text}"
            )
            injury_keywords = ["跌倒", "撞", "扭", "割", "燙", "骨折", "瘀青", "流血", "摔"]
            is_injury = any(kw in symptom_text for kw in injury_keywords)
            self.dm.add_health_record("injury" if is_injury else "symptom", symptom_text)
            is_long_term_updated = True

        # 疾病偵測
        has_chronic = analysis.get("chronic_disease") is not None
        if has_chronic:
            disease_name = analysis["chronic_disease"]
            profile = self.dm.get_profile()
            existing = profile.get("medical_safety", {}).get("chronic_diseases", [])
            if disease_name not in existing:
                existing.append(disease_name)
                self.dm.update_care_baseline(chronic_diseases=existing)
                self.dm.add_timeline_event(
                    event_type="health",
                    title=f"新增病史：{disease_name}",
                    description=f"長者對話中提及患有{disease_name}"
                )
            is_long_term_updated = True

        # 活動（按時段累加）
        has_activity = analysis.get("activity") is not None
        if has_activity:
            activity_text = analysis["activity"]
            
            dashboard = self.dm.get_dashboard_logs()
            existing_act = dashboard.get("today_summary", {}).get("metrics", {}).get("activity_by_period", {})
            existing_act[current_period] = activity_text
            
            act_display_parts = []
            for p in ["早上", "中午", "晚上"]:
                if p in existing_act:
                    act_display_parts.append(f"{p}：{existing_act[p]}")
            if "其他" in existing_act:
                act_display_parts.append(f"其他：{existing_act['其他']}")
            act_display = "\n".join(act_display_parts)
            
            self.dm.update_today_summary(text="", metrics={
                "activity": act_display,
                "activity_by_period": existing_act,
            })
            self.dm.add_timeline_event(event_type="activity", title="日常活動", description=f"{current_period}：{activity_text}")
            # 寫入長期記憶（活動：一般，保留 30 天）
            self.dm.add_long_term_record(
                category="activity",
                content=f"{current_period} {activity_text}",
                importance="normal"
            )

        # 睡眠（按時段累加）
        has_sleep = analysis.get("sleep") is not None
        if has_sleep:
            sleep_text = analysis["sleep"]
            
            dashboard = self.dm.get_dashboard_logs()
            existing_sleep = dashboard.get("today_summary", {}).get("metrics", {}).get("sleep_by_period", {})
            existing_sleep[current_period] = sleep_text
            
            sleep_display_parts = []
            for p in ["早上", "中午", "晚上"]:
                if p in existing_sleep:
                    sleep_display_parts.append(f"{p}：{existing_sleep[p]}")
            if "其他" in existing_sleep:
                sleep_display_parts.append(f"其他：{existing_sleep['其他']}")
            sleep_display = "\n".join(sleep_display_parts)
            
            self.dm.update_today_summary(text="", metrics={
                "sleep": sleep_display,
                "sleep_by_period": existing_sleep,
            })
            self.dm.add_timeline_event(event_type="health", title="睡眠紀錄", description=f"{current_period}：{sleep_text}")
            # 寫入長期記憶（睡眠：重要，保留 3 個月）
            self.dm.add_long_term_record(
                category="sleep",
                content=f"{current_period} {sleep_text}",
                importance="high"
            )

        # 提醒事項（偵測到時寫入 reminders.json 並通知家人）
        has_reminder = analysis.get("reminder") is not None
        if has_reminder:
            reminder_text = analysis["reminder"]
            self.dm.add_reminder(reminder_text, "長者")
            # 透過 LINE Bot 即時通知家人
            try:
                from services.weather_cron import _send_line_push
                profile = self.dm.get_profile()
                elder_name = profile.get("personal_info", {}).get("nickname") or profile.get("personal_info", {}).get("name") or self.dm.elder_id
                line_msg = f"⏰ 【{elder_name} 提醒轉達】\n{reminder_text}"
                _send_line_push(line_msg)
                print(f"📢 [提醒] 已透過 LINE 通知家人：{reminder_text}")
            except Exception as e:
                print(f"⚠️ [提醒] LINE 通知失敗: {e}")

        if is_long_term_updated:
            print("⚙️ [記憶控制] 偵測到重要健康資訊，長期記憶與看板已自動更新。")

        return is_long_term_updated

    def _analyze_health_info(self, user_text: str, current_time_str: str) -> dict:
        """
        一次 LLM 調用統整判斷 6 個類別：
        用藥、飲食、症狀、慢性疾病、活動、睡眠
        """
        default = {"medication": {"status": "未提及", "name": None, "time": None}, "diet": None, "symptom": None, "chronic_disease": None, "activity": None, "sleep": None, "reminder": None}
        
        if ask_ollama is None:
            return default

        try:
            with open(config.HEALTH_ANALYSIS_PROMPT_PATH, 'r', encoding='utf-8') as f:
                prompt = f.read()
        except Exception as _e:
            print(f"⚠️ [統整分析] 讀取 prompt 失敗: {_e}")
            return default

        user_input = f"{prompt}\n\n當前系統時間：{current_time_str}\n長者說的話：「{user_text}」"

        try:
            from core.bedrock_client import chat as bedrock_chat
            raw = bedrock_chat(
                user_text=user_input,
                temperature=0.0,
                max_tokens=512,
            )
            # 強力 JSON 提取：移除各種可能的包裝
            clean = raw.strip()
            if '```' in clean:
                # 提取 ``` 之間的內容
                parts = clean.split('```')
                for part in parts:
                    part = part.strip()
                    if part.startswith('json'):
                        part = part[4:].strip()
                    if part.startswith('{'):
                        clean = part
                        break
            # 確保只取第一個 JSON 對象
            if '{' in clean:
                start = clean.index('{')
                end = clean.rindex('}') + 1
                clean = clean[start:end]
            
            print(f"⚙️ [統整分析] LLM 原始輸出：{raw[:100]}")
            parsed = json.loads(clean)
            
            # 確保結構完整
            result = default.copy()
            
            # 用藥
            med = parsed.get("medication", {})
            if isinstance(med, dict) and med.get("status") and med["status"] != "未提及":
                result["medication"] = med
            
            # 飲食
            diet = parsed.get("diet")
            if diet and diet != "null" and str(diet).strip():
                result["diet"] = str(diet)
            
            # 症狀
            symptom = parsed.get("symptom")
            if symptom and symptom != "null" and str(symptom).strip():
                result["symptom"] = str(symptom)
            
            # 慢性疾病
            disease = parsed.get("chronic_disease")
            if disease and disease != "null" and str(disease).strip():
                result["chronic_disease"] = str(disease)
            
            # 活動
            activity = parsed.get("activity")
            if activity and activity != "null" and str(activity).strip():
                result["activity"] = str(activity)
            
            # 睡眠
            sleep = parsed.get("sleep")
            if sleep and sleep != "null" and str(sleep).strip():
                result["sleep"] = str(sleep)
            
            # 提醒
            reminder = parsed.get("reminder")
            if reminder and reminder != "null" and str(reminder).strip():
                result["reminder"] = str(reminder)
            
            print(f"⚙️ [統整分析] 結果：用藥={result['medication']['status']}，飲食={result['diet']}，症狀={result['symptom']}，活動={result['activity']}，睡眠={result['sleep']}，提醒={result.get('reminder')}")
            return result
            
        except Exception as e:
            import traceback
            print(f"⚠️ [統整分析] 失敗: {e}")
            traceback.print_exc()
            return default

    # ─── 藥物分類強制修正（代碼層硬邏輯）──────────────────

    @staticmethod
    def _is_period_passed(period: str, current_hour: int) -> bool:
        """判斷某個時段是否已經過了"""
        period_end_hours = {
            "早上": 11,
            "中午": 14,
            "下午": 18,
            "晚上": 22,
            "宵夜": 5,  # 隔天凌晨5點前都算宵夜時段
        }
        end_hour = period_end_hours.get(period, 24)
        if period == "宵夜":
            # 宵夜特殊：22:00~05:00，只有在 05:00~22:00 之間才算「已過」
            return 5 <= current_hour < 22
        return current_hour >= end_hour

    # 藥物關鍵詞白名單
    _MEDICATION_KEYWORDS = [
        "藥", "吃藥", "服藥", "用藥", "高血壓藥", "降血壓藥", "血壓藥",
        "降血糖藥", "血糖藥", "糖尿病藥", "胰島素",
        "心臟病藥", "心臟藥", "安眠藥", "止痛藥", "消炎藥", "抗生素",
        "感冒藥", "咳嗽藥", "過敏藥", "胃藥", "腸胃藥",
        "維他命", "維生素", "保健食品", "鈣片", "魚油",
        "眼藥水", "藥膏", "藥水", "藥丸", "藥片", "膠囊",
    ]

    def _force_medication_classification(self, user_text: str, analysis: dict, current_time_str: str) -> dict:
        """
        代碼層硬邏輯：如果使用者的話中包含藥物關鍵詞，
        但 LLM 沒有正確歸類到 medication，則強制修正。
        只清除 diet 中「含有藥物關鍵詞」的內容（表示 LLM 把藥物錯放到飲食），
        保留真正的食物資訊。
        """
        text = user_text.strip()
        
        # 偵測文字中是否包含藥物關鍵詞
        found_med_keyword = None
        for kw in self._MEDICATION_KEYWORDS:
            if kw in text:
                found_med_keyword = kw
                break
        
        if not found_med_keyword:
            return analysis
        
        # 檢查 diet 欄位是否包含藥物關鍵詞（表示 LLM 把藥物錯放到飲食）
        diet_value = analysis.get("diet")
        if diet_value:
            diet_contains_med = False
            for kw in self._MEDICATION_KEYWORDS:
                if kw in diet_value:
                    diet_contains_med = True
                    break
            if diet_contains_med:
                # diet 裡有藥物關鍵詞 → 這是 LLM 分類錯誤，清掉
                print(f"⚙️ [強制修正] diet 中包含藥物「{diet_value}」，已清除")
                analysis["diet"] = None
        
        # 有藥物關鍵詞但 LLM 把 medication 標為「未提及」→ 強制修正
        med_status = analysis.get("medication", {}).get("status", "未提及")
        if med_status == "未提及":
            # 判斷是「已吃」還是「未吃」
            not_eaten_indicators = ["沒吃", "忘了吃", "還沒吃", "沒有吃", "忘記吃", "不想吃藥", "沒有服"]
            
            status = "已吃"  # 預設：提到藥就當作已吃（通常長輩是在報告吃藥）
            for indicator in not_eaten_indicators:
                if indicator in text:
                    status = "未吃"
                    break
            
            # 找到具體藥名（比通用關鍵詞更精確的）
            # 支援「高血壓的藥」「血壓的藥」等有「的」字的變體
            import re as _med_re
            _med_patterns = [
                ("高血壓藥", _med_re.compile(r'高血壓.{0,1}藥')),
                ("降血壓藥", _med_re.compile(r'降血壓.{0,1}藥')),
                ("血壓藥", _med_re.compile(r'血壓.{0,1}藥')),
                ("降血糖藥", _med_re.compile(r'降血糖.{0,1}藥')),
                ("血糖藥", _med_re.compile(r'血糖.{0,1}藥')),
                ("糖尿病藥", _med_re.compile(r'糖尿病.{0,1}藥')),
                ("心臟藥", _med_re.compile(r'心臟.{0,1}藥')),
                ("安眠藥", _med_re.compile(r'安眠.{0,1}藥')),
                ("止痛藥", _med_re.compile(r'止痛.{0,1}藥')),
                ("消炎藥", _med_re.compile(r'消炎.{0,1}藥')),
                ("感冒藥", _med_re.compile(r'感冒.{0,1}藥')),
                ("咳嗽藥", _med_re.compile(r'咳嗽.{0,1}藥')),
                ("過敏藥", _med_re.compile(r'過敏.{0,1}藥')),
                ("胃藥", _med_re.compile(r'胃.{0,1}藥')),
            ]
            med_name = "藥物"
            for name, pattern in _med_patterns:
                if pattern.search(text):
                    med_name = name
                    break
            
            analysis["medication"] = {
                "status": status,
                "name": med_name,
                "time": current_time_str
            }
            print(f"⚙️ [強制修正] 偵測到藥物關鍵詞「{found_med_keyword}」，強制歸類為 medication（{status}，{med_name}）")
        
        return analysis

    # ─── 相容性方法（供舊程式碼不報錯）──────────────────

    def _load_json(self, path):
        """相容舊呼叫：讀取任意 JSON"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @property
    def lt_path(self):
        """相容舊呼叫：長期記憶路徑"""
        return self.dm.long_term_path if self.dm else None

    @property
    def st_path(self):
        """相容舊呼叫：短期記憶路徑"""
        return self.dm.short_term_path if self.dm else None


# ==================== 互動對話控制台（單獨測試用）====================
if __name__ == "__main__":
    controller = MemoryController()

    print("\n【長短期記憶監控 - AI 陪伴系統啟動】")
    print("提示：輸入 'exit' 或 'quit' 可結束對話\n")

    while True:
        try:
            user_input = input("\n👴 長輩：").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("系統關閉，祝您身體健康！")
                break

            # 組合歷史脈絡
            history_context = controller.get_history_summary_text()
            full_prompt = f"{history_context}長者最新說的話：{user_input}"

            # 呼叫 AI
            print("🤖 AI 陪伴：", end="", flush=True)
            ai_reply = ask_ollama(full_prompt) if ask_ollama else "（AI 未連線）"
            print(ai_reply)

            # 儲存記憶
            is_updated = controller.update_memories(user_input, ai_reply)
            if is_updated:
                print("⚙️ [系統] 偵測到重要健康資訊，長期記憶已自動更新。")

        except KeyboardInterrupt:
            print("\n程式被強制中止。")
            break
