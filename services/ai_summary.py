"""
Life_Records/ai_service.py
AI 摘要服務 — 適配新版 4 檔 JSON 資料格式

從 DataManager 讀取短期對話歷史與長期記憶，
呼叫 Amazon Bedrock 生成結構化 JSON 每日摘要。
"""

import json
import os
import sys
from datetime import datetime

# 確保能 import 上層模組
_base_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.abspath(os.path.join(_base_dir, ".."))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

import config
from core.data_manager import DataManager
from core.bedrock_client import chat_json as bedrock_chat_json

# ── 載入 System Prompt ────────────────────────────────
_prompt_path = config.LIFE_RECORDS_PROMPT_PATH

try:
    with open(_prompt_path, 'r', encoding='utf-8') as f:
        system_prompt = f.read()
except Exception as e:
    print(f"⚠️ 讀取 life_records_prompt.txt 失敗: {e}")
    system_prompt = (
        "你是一個專門將長者對話轉換為結構化 JSON 數據的後端自動化 API。"
        "嚴格從對話紀錄中擷取飲食、活動、睡眠、用藥四個維度的資訊。"
        "必須只輸出一個合法的 JSON 字串。"
    )


def load_context_for_summary(elder_id: str = None) -> str:
    """
    從 DataManager 撈取今日對話歷史與健康記憶，組成給 AI 分析的素材
    """
    if not elder_id:
        return ""
    dm = DataManager(elder_id=elder_id)

    pieces = []

    # 1. 短期對話歷史
    short_term = dm.get_short_term_memory()
    dialogue = short_term.get("dialogue_history", [])
    if dialogue:
        pieces.append("[今日對話紀錄]")
        for turn in dialogue:
            pieces.append(f"長者：{turn['user']}")
            pieces.append(f"助理：{turn['ai']}")

    # 2. 長期記憶中的用藥與習慣
    long_term = dm.get_long_term_memory()
    med = long_term.get("medication_tracker", {})
    if med.get("prescription_name"):
        pieces.append(f"\n[用藥資訊] {med['prescription_name']}，{med.get('requirement', '')}")

    habits = long_term.get("historical_habits", {})
    if habits.get("morning_routine"):
        pieces.append(f"[日常習慣] 早晨：{habits['morning_routine']}")
    if habits.get("afternoon_routine"):
        pieces.append(f"[日常習慣] 下午：{habits['afternoon_routine']}")

    # 3. 環境上下文
    context = short_term.get("active_context", {})
    if context.get("weather"):
        pieces.append(f"[環境] 天氣：{context['weather']}")

    return "\n".join(pieces)


def get_elder_daily_summary(current_chat: str = None) -> dict:
    """
    結合記憶資料與當前最新對話，呼叫 Ollama 生成結構化摘要。

    回傳格式：
    {
        "date": "2026-07-20",
        "overallSummary": "...",
        "structuredData": {"diet": "...", "activity": "...", "sleep": "...", "medication": "..."},
        "timeline": [{"time": "...", "type": "...", "title": "...", "content": "..."}]
    }
    """
    # 組合分析素材
    memory_context = load_context_for_summary()

    combined_pieces = []
    if memory_context:
        combined_pieces.append(memory_context)
    if current_chat:
        combined_pieces.append(f"\n[{datetime.now().strftime('%H:%M')}] 最新互動：\n{current_chat}")

    user_input = "\n".join(combined_pieces).strip()

    # 防禦：如果完全沒有資料
    fallback = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "overallSummary": "目前對話紀錄較少，已為您同步最新的語音互動。",
        "structuredData": {
            "diet": "對話中未提及相關資訊",
            "activity": "對話中未提及相關資訊",
            "sleep": "對話中未提及相關資訊",
            "medication": "對話中未提及相關資訊",
        },
        "timeline": []
    }

    if not user_input:
        return fallback

    print("=== 📥 AI 摘要分析素材 ===")
    print(user_input[:500])
    print("===========================")

    try:
        result = bedrock_chat_json(
            system=system_prompt,
            user_text=user_input,
            temperature=0.0,
            max_tokens=1024,
        )

        # 確保必要欄位存在
        if not result:
            return fallback
        if "overallSummary" not in result:
            result["overallSummary"] = fallback["overallSummary"]
        if "structuredData" not in result:
            result["structuredData"] = fallback["structuredData"]
        if "date" not in result:
            result["date"] = fallback["date"]

        return result

    except Exception as model_err:
        print(f"❌ Bedrock 摘要生成失敗: {model_err}")
        return fallback


if __name__ == "__main__":
    try:
        result = get_elder_daily_summary(current_chat="手動測試：長輩今天說頭有點暈")
        print("\n🎉 AI 摘要結果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"測試失敗: {e}")
