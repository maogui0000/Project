import time
import json
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
    已停用：情緒資料改為從用戶個人數據中讀取（dashboard metrics），
    不再寫入全局的 Environmental_Prompts.txt。
    保留此函數避免其他地方調用時報錯。
    """
    pass

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
    
    prompt_template = f"""# SYSTEM ENVIRONMENT CONTEXT (系統即時環境背景)
# 檔案更新時間: {now.strftime('%Y-%m-%d %H:%M:%S')}
# 這是系統每 6 小時自動更新的全台即時氣象與日落安全數據。請 AI 在回覆時，將這些環境脈絡納入考量：

[目前全台主要縣市環境數據]
{weather_content}

[AI 行為指引]
1. 當使用者聊到出門、散步、回家、天氣、問候時，請務必比對使用者所在縣市的「日落安全」狀態。
2. 如果使用者的縣市狀態顯示為「⚠️ 警告」或「🔴 已日落」，請用極度溫柔、溫暖的語氣，貼心地提醒長輩「天色不早了/外面天黑了，散步要注意安全、早點回家休息、看清步伐」。
3. 同時結合天氣資訊（如降雨機率、保暖穿搭建議）給予最完善的長照關懷。
"""

    # 寫入 (覆寫) Environmental_Prompts.txt
    with open(config.ENVIRONMENTAL_PROMPTS_PATH, "w", encoding="utf-8") as f_out:
        f_out.write(prompt_template)
        
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ 成功將最新【天氣 + 日落】提示詞寫入 Environmental_Prompts.txt")


# ═══════════════════════════════════════════════════════
# LINE Bot 定時推播（每天 19:00 + 5 分鐘緩衝）
# ═══════════════════════════════════════════════════════

def scheduled_line_push(max_wait_seconds: int = 300) -> bool:
    """
    每天 19:00 定時觸發 LINE 推播今日照護摘要。
    
    緩衝機制（demo.md 規格）：
    - 觸發時先檢查背景分析是否仍在執行
    - 若仍在執行，最多等待 5 分鐘（每 30 秒檢查一次）
    - 確保 LINE 通知包含最即時、完整的照護摘要
    
    :return: True 推播成功 / False 推播失敗或已推播過
    """
    from core.data_manager import DataManager
    
    print(f"[LINE 推播] 開始執行每日推播流程...")
    
    # 遍歷 data/ 目錄下的所有長者
    data_dir = os.path.join(config.BASE_DIR, "data")
    if not os.path.exists(data_dir):
        print(f"[LINE 推播] 資料目錄不存在：{data_dir}")
        return False
    
    elder_dirs = [d for d in os.listdir(data_dir) if d.startswith("elder_") and os.path.isdir(os.path.join(data_dir, d))]
    
    if not elder_dirs:
        print("[LINE 推播] 沒有任何長者資料，跳過推播")
        return False
    
    for elder_id in elder_dirs:
        try:
            dm = DataManager(elder_id=elder_id)
            dashboard = dm.get_dashboard_logs()
            
            # 檢查是否已推播過
            if dashboard.get("line_notification_status", {}).get("is_sent", False):
                print(f"[LINE 推播] {elder_id} 今日已推播過，跳過")
                continue
            
            # ── 緩衝機制：檢查背景分析是否仍在執行 ──
            waited = 0
            try:
                # 嘗試 import app 模組的 is_session_analysis_running
                # 注意：weather_cron 作為獨立程序時可能無法 import app
                # 此時改用檔案時間戳判斷
                import importlib
                app_module = importlib.import_module("app")
                is_running_fn = getattr(app_module, "is_session_analysis_running", None)
                
                if is_running_fn and is_running_fn(elder_id):
                    print(f"[LINE 推播] {elder_id} 背景分析仍在執行，啟動緩衝等待（最多 {max_wait_seconds}s）...")
                    while waited < max_wait_seconds:
                        time.sleep(30)
                        waited += 30
                        if not is_running_fn(elder_id):
                            print(f"[LINE 推播] {elder_id} 背景分析已完成（等待了 {waited}s），繼續推播")
                            break
                    else:
                        print(f"[LINE 推播] {elder_id} 等待超時 {max_wait_seconds}s，仍使用目前摘要推播")
            except (ImportError, Exception) as e:
                # 獨立執行時無法 import app，用時間戳判斷
                # 如果最後互動時間在 18:55 之後，等 5 分鐘
                short_term = dm.get_short_term_memory()
                last_time_str = short_term.get("active_context", {}).get("current_time", "")
                if last_time_str:
                    try:
                        last_time = datetime.fromisoformat(last_time_str)
                        now = datetime.now()
                        # 如果最後互動在 5 分鐘內，等待
                        minutes_since_last = (now - last_time).total_seconds() / 60
                        if minutes_since_last < 5:
                            wait_secs = int((5 - minutes_since_last) * 60)
                            print(f"[LINE 推播] {elder_id} 最近 {minutes_since_last:.1f} 分鐘有互動，"
                                  f"延遲 {wait_secs}s 確保摘要完整...")
                            time.sleep(min(wait_secs, max_wait_seconds))
                    except Exception:
                        pass
            
            # ── 重新讀取最新摘要（等待後可能已更新）──
            dashboard = dm.get_dashboard_logs()
            summary = dashboard.get("today_summary", {})
            summary_text = summary.get("text", "")
            metrics = summary.get("metrics", {})
            
            # 如果完全沒有摘要內容，跳過推播
            if not summary_text and not any(v and v != "尚未記錄" for v in metrics.values() if isinstance(v, str)):
                print(f"[LINE 推播] {elder_id} 今日無有效摘要，跳過推播")
                continue
            
            # 讀取長者名稱
            profile = dm.get_profile()
            elder_name = profile.get("personal_info", {}).get("name", elder_id)
            
            # 讀取情緒摘要
            emotion_text = metrics.get("emotion", "")
            emotion_line = f"\n\n🎭 今日情緒：{emotion_text}" if emotion_text and emotion_text != "尚未偵測" else ""
            
            # 組裝 LINE 訊息
            today_str = datetime.now().strftime("%Y-%m-%d")
            diet = metrics.get("diet", "對話中未提及相關資訊")
            sleep = metrics.get("sleep", "對話中未提及相關資訊")
            med_taken = metrics.get("medication_taken", False)
            med_time = metrics.get("medication_time", "")
            med_status = f"已服藥（{med_time}）" if med_taken else "今日尚未記錄服藥"
            
            formatted_text = (
                f"📅 【{elder_name} 今日生活摘要】\n"
                f"日期：{today_str}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📝 綜合摘要：\n{summary_text}\n\n"
                f"🍎 飲食狀況：\n{diet}\n\n"
                f"😴 睡眠品質：\n{sleep}\n\n"
                f"💊 用藥紀錄：\n{med_status}"
                f"{emotion_line}"
            )
            
            # 推播到 LINE
            push_success = _send_line_push(formatted_text)
            
            if push_success:
                dm.mark_line_notification_sent()
                print(f"[LINE 推播] ✅ {elder_name}（{elder_id}）今日摘要已成功推播到 LINE！")
            else:
                print(f"[LINE 推播] ❌ {elder_id} 推播失敗")
                
        except Exception as e:
            print(f"[LINE 推播] {elder_id} 處理失敗: {e}")
    
    return True


def _send_line_push(text: str) -> bool:
    """
    透過 LINE Bot API 推播訊息給目標使用者。
    直接使用 LINE Messaging API HTTP 呼叫，不依賴 Flask 的 line_bot.py。
    """
    # 從 config 或硬編碼取得 LINE 設定
    access_token = config.LINE_CHANNEL_ACCESS_TOKEN
    target_user = config.LINE_TARGET_USER_ID
    
    # 若 config 未設定，嘗試從 line_bot.py 的硬編碼讀取
    if not access_token:
        access_token = "l+QP6SuTqqETfAdeY3bJZSSU1ZmF6eBoxeOnWd/mlQpx7E7ihH7mIMR/hYmdSDimr3OWejX0c8kE0MY5LitY4WAHwIyn8fEtFfCT+57kFUayX6ovFZe34BAeMAN6ZcT+53FyVfF1aeb/GhGqihypoQdB04t89/1O/w1cDnyilFU="
    if not target_user:
        target_user = "U8ea3d1facf0625457e60e3e831b2a13c"
    
    if not access_token or not target_user:
        print("[LINE 推播] ⚠️ LINE 設定不完整（無 access_token 或 target_user）")
        return False
    
    try:
        import json as _json
        from urllib.request import Request, urlopen
        from urllib.error import URLError, HTTPError
        
        url = "https://api.line.me/v2/bot/message/push"
        payload = _json.dumps({
            "to": target_user,
            "messages": [{"type": "text", "text": text}]
        }, ensure_ascii=False).encode('utf-8')
        
        req = Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json; charset=UTF-8')
        req.add_header('Authorization', 'Bearer ' + access_token)
        
        response = urlopen(req, timeout=10)
        
        if response.status == 200:
            return True
        else:
            print(f"[LINE 推播] API 回應異常：{response.status}")
            return False
    except HTTPError as e:
        print(f"[LINE 推播] HTTP 錯誤：{e.code} {e.read().decode('utf-8','ignore')[:200]}")
        return False
    except Exception as e:
        print(f"[LINE 推播] 發送失敗: {e}")
        return False

if __name__ == "__main__":
    print("=== 天氣與日落環境監控服務 + LINE 定時推播已開啟 ===")
    print(f"    天氣更新：每 6 小時")
    print(f"    LINE 推播：每天 19:00（含 5 分鐘緩衝機制）")
    
    _last_line_push_date = None  # 記錄今天是否已推播過
    
    while True:
        fetch_and_generate_prompt()
        
        # ── LINE 定時推播檢查（每分鐘輪詢）──
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 每天 19:00 ~ 19:10 區間內觸發推播（一天只推一次）
        if now.hour == 19 and now.minute <= 10 and _last_line_push_date != today_str:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 📢 LINE 推播觸發時間到！")
            push_success = scheduled_line_push()
            if push_success:
                _last_line_push_date = today_str
        
        print("進入等待狀態，6 小時後將自動重新讀取... (欲關閉請直接關閉視窗，或按 Ctrl+C)")
        
        # 如果在 18:50~19:10 區間，改為每 60 秒檢查一次（確保不會錯過推播時間）
        if now.hour == 18 and now.minute >= 50:
            print("  [即將進入推播時段，60 秒後再檢查]")
            time.sleep(60)
        elif now.hour == 19 and now.minute <= 10:
            print("  [推播時段內，60 秒後再檢查]")
            time.sleep(60)
        else:
            time.sleep(21600)