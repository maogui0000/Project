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
    動態讀取最新 6 小時更新的天氣提示詞，並與原本的 system_prompt 結合
    """
    weather_prompt = ""
    if os.path.exists(config.ENVIRONMENTAL_PROMPTS_PATH):
        with open(config.ENVIRONMENTAL_PROMPTS_PATH, 'r', encoding='utf-8') as f:
            weather_prompt = f.read()
    else:
        print("\n[警告] 找不到 Environmental_Prompts.txt，請確認 weather_cron.py 是否正在運行。")
    
    # 將原本的 system_prompt 與天氣提示詞組裝在一起
    combined_prompt = f"{base_system_prompt}\n\n" \
                      f"=========================================\n" \
                      f"【以下為即時串接的外部環境資訊（每6小時自動更新）】\n" \
                      f"{weather_prompt}\n" \
                      f"========================================="
    return combined_prompt

def ask_ollama(text):
    # 每次對話時都重新抓取最新的組合提示詞
    current_system_prompt = get_combined_system_prompt()
    
    response = chat(
        model='gemma2',
        messages=[
            {"role": "system", "content": current_system_prompt},
            {'role': 'user', 'content': text}
        ],
        stream=False,
    )
    return response['message']['content']

def ask_ollama_stream(text):
    # 串流模式也同步動態更新
    current_system_prompt = get_combined_system_prompt()
    
    stream = chat(
        model='gemma2',
        messages=[
            {"role": "system", "content": current_system_prompt},
            {'role': 'user', 'content': text}
        ],
        stream=True,
    )
    for chunk in stream:
        print(chunk['message']['content'], end='', flush=True)


def ask_ollama_stream_sentences(text, model='gemma2'):
    """
    串流模式逐句生成器：LLM 每產出一個完整句子就 yield 出去。
    
    斷句規則：遇到句號(。)、問號(？)、感嘆號(！)、換行(\n) 視為一句結束。
    每 yield 一次就是一個可以立即送去 TTS 合成的完整句子。
    
    用法：
        for sentence in ask_ollama_stream_sentences("你好"):
            tts_speak(sentence)
    """
    current_system_prompt = get_combined_system_prompt()
    
    # 句子結束符號
    SENTENCE_ENDINGS = {'。', '！', '？', '!', '?', '\n'}
    # 逗號等也可以作為較長片段的斷點（超過一定長度時）
    SOFT_BREAKS = {'，', '、', '；', ',', ';', '：', ':'}
    MAX_SOFT_BREAK_LEN = 30  # 超過此長度遇到軟斷點也切句
    
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