from ollama import chat
import os
import sys

# 確保能 import 根目錄模組
_core_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_core_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import config

# 1. 讀取系統提示詞
with open(config.SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
    base_system_prompt = f.read()

system_prompt = base_system_prompt

def get_combined_system_prompt():
    """
    動態組合完整的 system prompt：
    基礎人設 + 當前時間 + 天氣環境 + 情緒狀態
    """
    from datetime import datetime
    
    # 天氣與情緒環境提示詞
    weather_prompt = ""
    if os.path.exists(config.ENVIRONMENTAL_PROMPTS_PATH):
        with open(config.ENVIRONMENTAL_PROMPTS_PATH, 'r', encoding='utf-8') as f:
            weather_prompt = f.read()
    
    # 當前時間情境
    now = datetime.now()
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
    
    combined_prompt = (
        f"{base_system_prompt}\n\n"
        f"=========================================\n"
        f"【當前時間】{now.strftime('%Y-%m-%d %H:%M')}（{time_context}）\n"
        f"=========================================\n"
        f"【以下為即時環境資訊】\n"
        f"{weather_prompt}\n"
        f"========================================="
    )
    return combined_prompt

def ask_ollama(text):
    # 每次對話時都重新抓取最新的組合提示詞
    current_system_prompt = get_combined_system_prompt()
    
    import re
    _emoji_re = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF'
        r'\U00002702-\U000027B0\U00002600-\U000026FF\U0000FE0F\U0000200D\U000020E3]+'
    )
    
    response = chat(
        model=config.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": current_system_prompt},
            {'role': 'user', 'content': text}
        ],
        stream=False,
    )
    return _emoji_re.sub('', response['message']['content'])

def ask_ollama_stream(text):
    # 串流模式也同步動態更新
    current_system_prompt = get_combined_system_prompt()
    
    stream = chat(
        model=config.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": current_system_prompt},
            {'role': 'user', 'content': text}
        ],
        stream=True,
    )
    for chunk in stream:
        print(chunk['message']['content'], end='', flush=True)


def ask_ollama_stream_sentences(text, model=None):
    """
    串流模式逐句生成器：LLM 每產出一個完整句子就 yield 出去。
    
    斷句規則：遇到句號(。)、問號(？)、感嘆號(！)、換行(\n) 視為一句結束。
    每 yield 一次就是一個可以立即送去 TTS 合成的完整句子。
    
    用法：
        for sentence in ask_ollama_stream_sentences("你好"):
            tts_speak(sentence)
    """
    if model is None:
        model = config.OLLAMA_MODEL
    current_system_prompt = get_combined_system_prompt()
    
    # 句子結束符號
    SENTENCE_ENDINGS = {'。', '！', '？', '!', '?', '\n'}
    # 逗號等也可以作為較長片段的斷點（超過一定長度時）
    SOFT_BREAKS = {'，', '、', '；', ',', ';', '：', ':'}
    MAX_SOFT_BREAK_LEN = 30  # 超過此長度遇到軟斷點也切句
    
    # emoji 過濾
    import re
    _emoji_re = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF'
        r'\U00002702-\U000027B0\U00002600-\U000026FF\U0000FE0F\U0000200D\U000020E3]+'
    )
    
    stream = chat(
        model=model,
        messages=[
            {"role": "system", "content": current_system_prompt},
            {'role': 'user', 'content': text}
        ],
        stream=True,
    )
    
    buffer = ""
    
    for chunk in stream:
        token = chunk['message']['content']
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
                    yield sentence
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
                        yield sentence
                    continue
            
            # 還沒達到斷句條件，繼續累積
            break
    
    # 串流結束，剩餘的 buffer 全部送出
    if buffer.strip():
        yield buffer.strip()

if __name__ == "__main__":
    print("【本地對話模式啟動】（已成功載入動態天氣環境系統）請輸入文字：")
    while 1:
        user_input = input("\n你：")
        print("AI：", end="")
        ask_ollama_stream(user_input)