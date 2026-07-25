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

# 匯入 AI 對話函數
try:
    from core.ai_chat import ask_ollama
    print("✅ [記憶控制] 成功對接 Ollama AI 模型接口！")
except ImportError as e:
    print(f"⚠️ [記憶控制] 無法匯入 AI_Chat ({e})")
    ask_ollama = None


class MemoryController:
    """
    記憶控制器：管理長短期記憶，與 AI 分析用藥/飲食/症狀。
    
    底層使用 DataManager 讀寫 data/ 目錄下的 JSON 檔案。
    保留舊有介面方法，確保 voice_assistant.py、app.py 等不需大改。
    """

    def __init__(self):
        self.dm = DataManager()

    def get_history_summary_text(self) -> str:
        """
        將短期對話歷史轉成文字 prompt，塞進 AI 的對話脈絡
        """
        return self.dm.get_history_summary_text()

    def update_memories(self, user_text: str, ai_text: str):
        """
        情境判斷與記憶更新：
        1. 加入短期對話記憶
        2. 用 AI 分析是否有用藥/飲食/症狀資訊
        3. 如有，更新長期記憶與看板日誌
        """
        now = datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 寫入短期記憶
        self.dm.add_dialogue_turn(user_text, ai_text)

        # 2. 用 AI 分析健康資訊
        analysis = self._analyze_health_info(user_text, current_time_str)

        has_medication = analysis.get("medication", {}).get("status") != "未提及"
        has_diet = analysis.get("diet") is not None
        has_symptom = analysis.get("symptom") is not None

        is_long_term_updated = False

        # 3. 根據分析結果更新長期記憶與看板
        if has_medication:
            med_info = analysis["medication"]
            taken = med_info.get("status") == "已吃"
            med_time = med_info.get("time") or current_time_str

            # 更新長期記憶的用藥追蹤
            self.dm.update_medication_compliance(taken=taken, time_str=med_time)

            # 更新看板的用藥 metrics
            self.dm.update_today_summary(
                text="",  # 不覆蓋摘要文字
                metrics={"medication_taken": taken, "medication_time": med_time}
            )

            # 加入時間軸事件
            status_text = "已服藥" if taken else "未服藥"
            med_name = med_info.get("name") or "藥物"
            self.dm.add_timeline_event(
                event_type="health",
                title=f"用藥紀錄：{med_name}（{status_text}）",
                description=f"長者提及 {med_name}，狀態：{status_text}，時間：{med_time}"
            )
            is_long_term_updated = True

        if has_diet:
            diet_text = analysis["diet"]
            self.dm.update_today_summary(text="", metrics={"diet": diet_text})
            self.dm.add_preference("likes", diet_text)
            is_long_term_updated = True

        if has_symptom:
            symptom_text = analysis["symptom"]
            self.dm.add_timeline_event(
                event_type="health",
                title=f"健康紀錄：{symptom_text}",
                description=f"長者提及身體狀況：{symptom_text}"
            )
            is_long_term_updated = True

        # 疾病偵測 → 自動加入 care_baseline.diseases
        has_chronic = analysis.get("chronic_disease") is not None
        if has_chronic:
            disease_name = analysis["chronic_disease"]
            # 讀取現有的疾病列表，避免重複加入
            profile = self.dm.get_profile()
            existing = profile.get("care_baseline", {}).get("diseases", [])
            if disease_name not in existing:
                existing.append(disease_name)
                self.dm.update_care_baseline(diseases=existing)
                self.dm.add_timeline_event(
                    event_type="health",
                    title=f"新增病史：{disease_name}",
                    description=f"長者對話中提及患有{disease_name}，已自動記錄至病史"
                )
                print(f"⚙️ [記憶控制] 偵測到疾病「{disease_name}」，已加入病史。")
            is_long_term_updated = True

        if is_long_term_updated:
            print("⚙️ [記憶控制] 偵測到重要健康資訊，長期記憶與看板已自動更新。")

        return is_long_term_updated

    def _analyze_health_info(self, user_text: str, current_time_str: str) -> dict:
        """用 AI 分析長者的話中是否包含健康資訊"""
        if ask_ollama is None:
            return {"medication": {"status": "未提及", "name": None, "time": None}, "diet": None, "symptom": None, "chronic_disease": None}

        analysis_prompt = f"""
        你是一位高齡照護分析師。
        當前系統精準時間（基準點）：{current_time_str}
        
        請分析長者說的話，並精準提取出以下資訊。
        長者說的話："{user_text}"
        
        請嚴格只依照以下 JSON 格式回傳，不要回答任何說明的廢話、Markdown 標籤：
        {{
            "medication": {{
                "status": "已吃" 或 "未吃" 或 "未提及",
                "name": "藥物名稱或種類，若無則填 null",
                "time": "精準的吃藥時間（格式：2026-07-20 22:15:00），若無法推算或未提及則填 null"
            }},
            "diet": "提及的食物，若無則填 null",
            "symptom": "身體不適症狀，若無則填 null",
            "chronic_disease": "提及的慢性疾病名稱（如高血壓、糖尿病、關節炎等），若無則填 null"
        }}
        """

        try:
            raw_response = ask_ollama(analysis_prompt)
            clean_response = raw_response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_response)
        except Exception:
            return {"medication": {"status": "未提及", "name": None, "time": None}, "diet": None, "symptom": None, "chronic_disease": None}

    # ─── 相容性方法（供舊程式碼不報錯）──────────────────

    def _load_json(self, path):
        """相容舊呼叫：讀取任意 JSON"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @property
    def lt_path(self):
        """相容舊呼叫：長期記憶路徑"""
        from core.data_manager import LONG_TERM_PATH
        return LONG_TERM_PATH

    @property
    def st_path(self):
        """相容舊呼叫：短期記憶路徑"""
        from core.data_manager import SHORT_TERM_PATH
        return SHORT_TERM_PATH


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
