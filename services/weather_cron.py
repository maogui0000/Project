import time
from datetime import datetime
import requests
import urllib3
import os
import sys

# 確保能 import 根目錄模組
_service_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_service_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import config

# 隱藏跳過憑證的紅色警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ═══════════════════════════════════════════════════════
# 情緒上下文區塊（動態注入 Environmental_Prompts.txt）
# ═══════════════════════════════════════════════════════

# 情緒段落的開始/結束標記（用於定位替換）
_EMOTION_SECTION_START = "[長者今日語音情緒狀態]"
_EMOTION_SECTION_END = "[/長者今日語音情緒狀態]"


def _get_emotion_prompt_section() -> str:
    """
    讀取當前情緒摘要，生成環境提示詞中的情緒區塊。
    如果尚無情緒資料，回傳空的佔位區塊。
    """
    try:
        from speech.emotion_recognition import get_emotion_summary
        summary = get_emotion_summary()
    except Exception:
        summary = None

    if not summary or summary.get("total_detections", 0) == 0:
        return (
            f"{_EMOTION_SECTION_START}\n"
            f"- 今日尚未偵測到長者語音情緒資料。\n"
            f"{_EMOTION_SECTION_END}\n\n"
            f"[情緒感知 AI 行為指引]\n"
            f"4. 當語音情緒偵測到長者情緒為「難過」或「生氣」時，請用更加溫柔、同理的語氣回覆，主動關心長輩的心情。\n"
            f"5. 當偵測到「開心」時，可以順著長輩的好心情互動，讓對話更加愉快自然。\n"
            f"6. 當偵測到「恐懼」或「吃驚」時，請先安撫長輩情緒，詢問是否有需要幫忙的地方。\n"
            f"7. 情緒辨識僅作為輔助參考，回覆時不要直接說「我偵測到您的情緒是...」，而是自然地調整語氣和關懷程度。"
        )

    dominant = summary.get("dominant_emotion_zh", "中立")
    latest = summary.get("latest_emotion_zh", "中立")
    total = summary.get("total_detections", 0)
    timeline = summary.get("emotion_timeline", "")
    distribution = summary.get("emotion_distribution", {})

    # 格式化情緒分布
    dist_parts = []
    for emo_en, count in sorted(distribution.items(), key=lambda x: -x[1]):
        from speech.emotion_recognition import EMOTION_LABELS
        emo_zh = emo_en
        for info in EMOTION_LABELS.values():
            if info["en"] == emo_en:
                emo_zh = info["zh"]
                break
        dist_parts.append(f"{emo_zh}({count}次)")
    dist_str = "、".join(dist_parts)

    return (
        f"{_EMOTION_SECTION_START}\n"
        f"- 今日情緒偵測次數：{total} 次\n"
        f"- 主導情緒：{dominant}\n"
        f"- 最近一次情緒：{latest}\n"
        f"- 情緒分布：{dist_str}\n"
        f"- 情緒時間軸：{timeline}\n"
        f"{_EMOTION_SECTION_END}\n\n"
        f"[情緒感知 AI 行為指引]\n"
        f"4. 當語音情緒偵測到長者情緒為「難過」或「生氣」時，請用更加溫柔、同理的語氣回覆，主動關心長輩的心情。\n"
        f"5. 當偵測到「開心」時，可以順著長輩的好心情互動，讓對話更加愉快自然。\n"
        f"6. 當偵測到「恐懼」或「吃驚」時，請先安撫長輩情緒，詢問是否有需要幫忙的地方。\n"
        f"7. 情緒辨識僅作為輔助參考，回覆時不要直接說「我偵測到您的情緒是...」，而是自然地調整語氣和關懷程度。\n"
        f"8. 目前長者主導情緒為「{dominant}」，最新情緒為「{latest}」，請據此微調回覆風格。"
    )


def update_emotion_in_prompt():
    """
    即時更新 Environmental_Prompts.txt 中的情緒區塊。
    此函數在每次情緒辨識完成後呼叫，不需等待 6 小時天氣更新。
    
    策略：讀取現有檔案 → 定位情緒區塊 → 替換為最新情緒資料 → 寫回。
    若檔案中尚無情緒區塊，則附加在末尾。
    """
    prompt_path = config.ENVIRONMENTAL_PROMPTS_PATH
    
    if not os.path.exists(prompt_path):
        print("⚠️ [情緒更新] Environmental_Prompts.txt 不存在，跳過情緒注入")
        return
    
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 生成最新的情緒區塊
        new_emotion_section = _get_emotion_prompt_section()
        
        # 檢查是否已有情緒區塊
        if _EMOTION_SECTION_START in content:
            # 找到舊區塊的範圍並替換
            start_idx = content.index(_EMOTION_SECTION_START)
            
            # 找到情緒行為指引的結尾（第 8 條或區塊結束標記之後的內容）
            # 我們替換從 _EMOTION_SECTION_START 到文件末尾（因為情緒區塊在最後面）
            content = content[:start_idx].rstrip() + "\n\n" + new_emotion_section + "\n"
        else:
            # 尚無情緒區塊，附加在末尾
            content = content.rstrip() + "\n\n" + new_emotion_section + "\n"
        
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✅ [情緒更新] Environmental_Prompts.txt 情緒區塊已更新")
    
    except Exception as e:
        print(f"⚠️ [情緒更新] 寫入失敗: {e}")

def fetch_and_generate_prompt():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在更新氣象與日落資料並重新生成 Prompt...")
    
    if not os.path.exists(config.WEATHER_API_KEY_PATH):
        print("錯誤：找不到 api_key.txt 檔案，請確認路徑。")
        return
        
    with open(config.WEATHER_API_KEY_PATH, "r", encoding="utf-8") as f:
        api_key = f.read().strip()

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    today_md = now.strftime("%m-%d")

    # ==========================================
    # 1. 抓取日落天文資料 (A-B0062-001)
    # ==========================================
    sun_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/A-B0062-001"
    sun_data = {}
    try:
        sun_response = requests.get(sun_url, params={"Authorization": api_key, "format": "JSON", "limit": "12000"}, verify=False)
        sun_raw = sun_response.json()
        
        # 建立一個方便查詢的字典: {"臺北市": "18:45", "宜蘭縣": "18:41"}
        for loc in sun_raw["records"]["locations"]["location"]:
            county_name = loc.get("locationName") or loc.get("CountyName") or ""
            # 正規化名稱，例如「臺北」或「台北」都轉成一致
            county_key = county_name.replace("台", "臺")
            
            for entry in loc["time"]:
                if entry.get("Date") == today_str or entry.get("Date", "").endswith(today_md):
                    sunset_time_str = entry.get("SunSetTime")
                    if sunset_time_str:
                        sun_data[county_key] = sunset_time_str
                    break
    except Exception as e:
        print(f"日落 API 連線或解析失敗: {e}")

    # ==========================================
    # 2. 抓取天氣資料 (F-C0032-001)
    # ==========================================
    weather_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
    weather_reports = []
    
    try:
        weather_response = requests.get(weather_url, params={"Authorization": api_key, "format": "JSON"}, verify=False)
        weather_raw = weather_response.json()
        
        def get_clothing_advice(avg_temp):
            advices = [
                (26, ["短袖、短褲（天氣炎熱，注意防曬）"]),
                (23, ["薄長袖/長褲/長裙", "襯衫/薄外套"]),
                (20, ["針織衫/薄毛衣/薄帽踢", "西裝外套"]),
                (15, ["風衣/厚帽踢", "發熱衣/輕羽絨/鋪棉外套"]),
                (0,  ["發熱衣", "毛呢大衣/厚毛衣", "羽絨外套/羔毛外套"])
            ]
            for limit, clothes in advices:
                if avg_temp >= limit:
                    return clothes
            return ["保暖衣物、厚外套"]

        for loc in weather_raw["records"]["location"]:
            city = loc["locationName"]
            city_key = city.replace("台", "臺")
            
            # 天氣解析
            elem = {e["elementName"]: e["time"][0]["parameter"]["parameterName"] for e in loc["weatherElement"]}
            wx = elem["Wx"]
            pop = elem["PoP"]
            min_t = int(elem["MinT"])
            max_t = int(elem["MaxT"])
            avg_temp = (min_t + max_t) / 2
            advice = " + ".join(get_clothing_advice(avg_temp))
            
            # 日落與安全狀態計算
            sunset_str = sun_data.get(city_key) or sun_data.get(city_key + "縣") or sun_data.get(city_key + "市")
            safety_status = "未知"
            
            if sunset_str:
                try:
                    sunset_dt = datetime.strptime(f"{today_str} {sunset_str}", "%Y-%m-%d %H:%M")
                    minutes_left = (sunset_dt - now).total_seconds() / 60
                    
                    if minutes_left > 30:
                        safety_status = f"🟢 時間充足（距離日落還有 {int(minutes_left)} 分鐘）"
                    elif 0 <= minutes_left <= 30:
                        safety_status = f"⚠️ ⚠️ 警告：快天黑了！僅剩 {int(minutes_left)} 分鐘日落，提醒長輩若在外面請準備回家！"
                    else:
                        safety_status = f"🔴 已日落（天黑了 {int(abs(minutes_left))} 分鐘），若長輩還在外請特別注意視線與安全"
                except:
                    safety_status = f"時間數據解析錯誤 ({sunset_str})"
            else:
                sunset_str = "暫無資料"
                safety_status = "無法計算安全狀態"

            # 整合該縣市的綜合環境報表
            report = (
                f"- 【{city}】\n"
                f"  * 天氣氣溫：{wx}，降雨機率 {pop}%，溫度 {min_t}°C ~ {max_t}°C ({advice})\n"
                f"  * 日落安全：今日日落 {sunset_str} | 目前狀態：{safety_status}"
            )
            weather_reports.append(report)

    except Exception as e:
        print(f"天氣 API 連線或解析失敗: {e}")
        return

    weather_content = "\n".join(weather_reports)

    # ==========================================
    # 3. 封裝生成最終的 System Prompt
    # ==========================================
    
    # 讀取當前情緒摘要（如有）
    emotion_section = _get_emotion_prompt_section()
    
    prompt_template = f"""# SYSTEM ENVIRONMENT CONTEXT (系統即時環境背景)
# 檔案更新時間: {now.strftime('%Y-%m-%d %H:%M:%S')}
# 這是系統每 6 小時自動更新的全台即時氣象與日落安全數據。請 AI 在回覆時，將這些環境脈絡納入考量：

[目前全台主要縣市環境數據]
{weather_content}

[AI 行為指引]
1. 當使用者聊到出門、散步、回家、天氣、問候時，請務必比對使用者所在縣市的「日落安全」狀態。
2. 如果使用者的縣市狀態顯示為「⚠️ 警告」或「🔴 已日落」，請用極度溫柔、溫暖的語氣，貼心地提醒長輩「天色不早了/外面天黑了，散步要注意安全、早點回家休息、看清步伐」。
3. 同時結合天氣資訊（如降雨機率、保暖穿搭建議）給予最完善的長照關懷。

{emotion_section}
"""

    # 寫入 (覆寫) Environmental_Prompts.txt
    with open(config.ENVIRONMENTAL_PROMPTS_PATH, "w", encoding="utf-8") as f_out:
        f_out.write(prompt_template)
        
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ 成功將最新【天氣 + 日落】提示詞寫入 Environmental_Prompts.txt")

if __name__ == "__main__":
    print("=== 天氣與日落環境監控服務已開啟 ===")
    while True:
        fetch_and_generate_prompt()
        print("進入等待狀態，6 小時後將自動重新讀取... (欲關閉請直接關閉視窗，或按 Ctrl+C)")
        time.sleep(21600)