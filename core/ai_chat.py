import os
import sys
import re

# 確保能 import 根目錄模組
_core_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_core_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import config
from core.bedrock_client import chat as bedrock_chat, chat_stream as bedrock_chat_stream

# 1. 讀取系統提示詞
with open(config.SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
    base_system_prompt = f.read()

system_prompt = base_system_prompt

# ═══════════════════════════════════════════════════════
# 後處理過濾器：移除 LLM 違反能力白名單的表述
# ═══════════════════════════════════════════════════════

# 違規模式：「我幫你/我來/我去/讓我」+ 動作
_VIOLATION_PATTERNS = re.compile(
    r'(?:我(?:來|去|幫你?|替你?|可以幫你?)(?:看|拿|拿|做|煮|泡|調|買|打電話|叫|聯絡|處理|弄|倒|開|關|陪你?去|陪你?走|跑)[\w]*)'
    r'|(?:讓我(?:看看|幫你?|來)[\w]*)'
    r'|(?:我(?:幫|替)[\w]{0,2}(?:打|叫|聯絡|撥)[\w]*)'
    r'|(?:我(?:現在就|馬上)(?:去|來|幫)[\w]*)',
    re.UNICODE
)

# 整句如果主要就是違規內容，替換為安全表述
_FULL_SENTENCE_VIOLATIONS = [
    (re.compile(r'.*我幫你?(?:看看?|檢查).*傷.*'), '您自己先看一下傷口嚴不嚴重喔。'),
    (re.compile(r'.*我幫你?打電話.*'), '您可以請家人幫忙打電話喔。'),
    (re.compile(r'.*我(?:幫你?)?叫救護車.*'), '如果很嚴重，請家人幫忙叫救護車喔。'),
    (re.compile(r'.*我(?:去|來)幫你.*'), '您可以請身邊的人幫忙喔。'),
    (re.compile(r'.*讓我看看.*'), '您自己先看一下狀況喔。'),
    (re.compile(r'.*我幫你?拿.*'), '您慢慢來，小心一點喔。'),
]


def _sanitize_reply(text: str) -> str:
    """
    後處理：過濾 LLM 回覆中違反能力白名單的表述。
    """
    if not text:
        return text
    
    # 逐句檢查是否整句違規，若是則替換
    for pattern, replacement in _FULL_SENTENCE_VIOLATIONS:
        if pattern.match(text):
            return replacement
    
    # 部分違規：移除違規片段
    cleaned = _VIOLATION_PATTERNS.sub('', text)
    
    # 移除 LLM 可能輸出的指令標記（如 /Edit: /Note: 等）
    cleaned = re.sub(r'/?[A-Za-z]+\s*[:：].*', '', cleaned)
    # 移除英文字母和非中文內容（只保留中文、數字、標點）
    cleaned = re.sub(r'[a-zA-Z/]+', '', cleaned)
    
    # 清理可能殘留的多餘標點或空白
    cleaned = re.sub(r'[，、。！？]{2,}', '。', cleaned)
    cleaned = cleaned.strip('，、 /')
    
    # 如果清理後只剩標點或空白，返回空字串（讓上層跳過此句）
    if not cleaned or not re.search(r'[\u4e00-\u9fff]', cleaned):
        return ""
    
    return cleaned

def get_combined_system_prompt(elder_id: str = "elder_001"):
    """
    動態組合完整的 system prompt：
    基礎人設 + 使用者資料（性別、暱稱）+ 當前時間 + 天氣環境 + 情緒狀態
    """
    from datetime import datetime
    from core.data_manager import DataManager
    
    # 讀取使用者 profile（性別、暱稱）
    elder_context = ""
    try:
        elder_dm = DataManager(elder_id=elder_id)
        profile = elder_dm.get_profile()
        personal = profile.get("personal_info", {})
        gender = personal.get("gender", "")
        nickname = personal.get("nickname", "")
        name = personal.get("name", "")
        location = personal.get("location", "")
        
        # 醫療安全資訊
        medical = profile.get("medical_safety", {})
        diseases = medical.get("chronic_diseases", [])
        medications = [m for m in medical.get("current_medications", []) if m and m != "null" and "或" not in m]
        drug_allergies = medical.get("drug_allergies", [])
        food_allergies = medical.get("food_allergies", [])
        
        # 身體照護
        physical = profile.get("physical_care", {})
        mobility = physical.get("mobility", "")
        dietary_restrictions = physical.get("dietary_restrictions", [])
        
        # 認知狀態
        mental = profile.get("mental_cognitive", {})
        has_dementia = mental.get("has_dementia", False)
        cognitive_notes = mental.get("cognitive_notes", "")
        
        # 根據性別設定稱呼方式
        if gender == "male":
            gender_hint = f"這位長輩是男性，請用「阿公」、「爺爺」或暱稱「{nickname}」來稱呼他。"
        elif gender == "female":
            gender_hint = f"這位長輩是女性，請用「阿嬤」、「奶奶」或暱稱「{nickname}」來稱呼她。"
        else:
            gender_hint = f"請用暱稱「{nickname or '長輩'}」來稱呼這位長輩。"
        
        elder_context = f"【當前使用者資料】\n"
        if name:
            elder_context += f"姓名：{name}，暱稱：{nickname}\n"
        elder_context += f"{gender_hint}\n"
        if location:
            elder_context += f"居住地：{location}\n"
        if diseases:
            elder_context += f"慢性疾病：{'、'.join(diseases)}\n"
        if medications:
            elder_context += f"目前用藥：{'、'.join(medications)}\n"
        if drug_allergies:
            elder_context += f"藥物過敏：{'、'.join(drug_allergies)}（絕對不能建議使用這些藥物）\n"
        if food_allergies:
            elder_context += f"食物過敏：{'、'.join(food_allergies)}（絕對不能建議吃這些食物）\n"
        if dietary_restrictions:
            elder_context += f"飲食禁忌：{'、'.join(dietary_restrictions)}\n"
        if mobility:
            elder_context += f"行動能力：{mobility}\n"
        if has_dementia:
            elder_context += f"認知狀態：有失智症，請用更簡單、更有耐心的方式溝通\n"
        if cognitive_notes:
            elder_context += f"照護備註：{cognitive_notes}\n"
    except Exception:
        elder_context = "【當前使用者資料】暫無\n"
    
    # 天氣與情緒環境提示詞
    weather_prompt = ""
    if os.path.exists(config.ENVIRONMENTAL_PROMPTS_PATH):
        with open(config.ENVIRONMENTAL_PROMPTS_PATH, 'r', encoding='utf-8') as f:
            weather_prompt = f.read()
    
    # 當前時間情境（強制使用台灣時區）
    now = config.now_tw()
    hour = now.hour
    if hour < 6:
        time_context = "現在是凌晨，長輩可能睡不著或剛醒來"
    elif hour < 9:
        time_context = "現在是早上，長輩可能剛起床"
    elif hour < 12:
        time_context = "現在是上午"
    elif hour < 14:
        time_context = "現在是中午，可能剛吃完飯或準備吃飯"
    elif hour < 17:
        time_context = "現在是下午"
    elif hour < 19:
        time_context = "現在是傍晚，接近晚餐時間"
    elif hour < 22:
        time_context = "現在是晚上"
    else:
        time_context = "現在是深夜，長輩應該要準備休息了"
    
    # 讀取當前情緒狀態（從 dashboard metrics）
    emotion_context = ""
    try:
        dashboard = elder_dm.get_dashboard_logs()
        current_emotion = dashboard.get("today_summary", {}).get("metrics", {}).get("emotion", "")
        emotion_reason = dashboard.get("today_summary", {}).get("metrics", {}).get("emotion_reason", "")
        if current_emotion and current_emotion != "未檢測":
            if current_emotion in ("難過", "生氣", "恐懼"):
                emotion_context = f"【長者當前情緒】{current_emotion}（原因：{emotion_reason}）\n請用更加溫柔、同理的語氣回覆，主動關心長輩的心情。\n"
            elif current_emotion == "開心":
                emotion_context = f"【長者當前情緒】{current_emotion}\n請順著長輩的好心情互動，讓對話更加愉快自然。\n"
    except Exception:
        pass
    
    combined_prompt = (
        f"{base_system_prompt}\n\n"
        f"=========================================\n"
        f"{elder_context}"
        f"=========================================\n"
        f"【當前時間】{now.strftime('%Y-%m-%d %H:%M')}（{time_context}）\n"
        f"你現在必須根據以上時間來決定問候語和回覆內容。\n"
        f"=========================================\n"
        f"{emotion_context}"
        f"=========================================\n"
        f"【以下為即時環境資訊】\n"
        f"{weather_prompt}\n"
        f"========================================="
    )
    return combined_prompt


# ═══════════════════════════════════════════════════════
# 對外介面：使用 Bedrock 取代 Ollama
# ═══════════════════════════════════════════════════════

# emoji 過濾
_emoji_re = re.compile(
    r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
    r'\U0001F1E0-\U0001F1FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF'
    r'\U00002702-\U000027B0\U00002600-\U000026FF\U0000FE0F\U0000200D\U000020E3]+'
)


def ask_ollama(text, elder_id: str = "elder_001"):
    """非串流對話（保留函式名以維持下游相容性）"""
    current_system_prompt = get_combined_system_prompt(elder_id=elder_id)

    raw_reply = bedrock_chat(
        system=current_system_prompt,
        user_text=text,
        temperature=0.0,
        max_tokens=512,
    )
    raw_reply = _emoji_re.sub('', raw_reply)
    return _sanitize_reply(raw_reply)


def ask_ollama_stream(text):
    """串流對話（印到 stdout，供 CLI 測試用）"""
    current_system_prompt = get_combined_system_prompt()

    for token in bedrock_chat_stream(
        system=current_system_prompt,
        user_text=text,
        temperature=0.0,
        max_tokens=512,
    ):
        print(token, end='', flush=True)


def ask_ollama_stream_sentences(text, model=None, elder_id: str = "elder_001"):
    """
    串流模式逐句生成器：LLM 每產出一個完整句子就 yield 出去。
    
    斷句規則：遇到句號(。)、問號(？)、感嘆號(！)、換行(\n) 視為一句結束。
    每 yield 一次就是一個可以立即送去 TTS 合成的完整句子。
    
    用法：
        for sentence in ask_ollama_stream_sentences("你好"):
            tts_speak(sentence)
    """
    current_system_prompt = get_combined_system_prompt(elder_id=elder_id)
    
    # 句子結束符號
    SENTENCE_ENDINGS = {'。', '！', '？', '!', '?', '\n'}
    # 逗號等也可以作為較長片段的斷點（超過一定長度時）
    SOFT_BREAKS = {'，', '、', '；', ',', ';', '：', ':'}
    MAX_SOFT_BREAK_LEN = 30  # 超過此長度遇到軟斷點也切句
    
    buffer = ""
    
    for token in bedrock_chat_stream(
        system=current_system_prompt,
        user_text=text,
        temperature=0.0,
        max_tokens=1024,
    ):
        token = _emoji_re.sub('', token)  # 過濾 emoji
        buffer += token
        
        # 檢查是否有完整句子可以切出
        while buffer:
            # 找到最早的硬斷點
            hard_pos = -1
            for i, ch in enumerate(buffer):
                if ch in SENTENCE_ENDINGS:
                    hard_pos = i
                    break
            
            if hard_pos >= 0:
                # 有硬斷點：切出這一句（包含斷點符號）
                sentence = buffer[:hard_pos + 1].strip()
                buffer = buffer[hard_pos + 1:]
                if sentence:
                    sanitized = _sanitize_reply(sentence)
                    if sanitized:
                        yield sanitized
                continue
            
            # 沒有硬斷點，但超長了 → 找軟斷點
            if len(buffer) >= MAX_SOFT_BREAK_LEN:
                soft_pos = -1
                for i, ch in enumerate(buffer):
                    if ch in SOFT_BREAKS:
                        soft_pos = i
                # 用最後一個軟斷點切
                if soft_pos > 0:
                    sentence = buffer[:soft_pos + 1].strip()
                    buffer = buffer[soft_pos + 1:]
                    if sentence:
                        sanitized = _sanitize_reply(sentence)
                        if sanitized:
                            yield sanitized
                    continue
            
            # 還沒達到斷句條件，繼續累積
            break
    
    # 串流結束，剩餘的 buffer 全部送出
    if buffer.strip():
        sanitized = _sanitize_reply(buffer.strip())
        if sanitized:
            yield sanitized


if __name__ == "__main__":
    print("【本地對話模式啟動】（已連線 AWS Bedrock）請輸入文字：")
    while 1:
        user_input = input("\n你：")
        print("AI：", end="")
        ask_ollama_stream(user_input)
