import os
import sys

# 確保能 import 根目錄模組
_services_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_services_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, AudioMessage, TextSendMessage
)

app = Flask(__name__)

# LINE Bot 憑證設定
LINE_CHANNEL_SECRET = '31abac3ba0956fe48e14d63bc0077a21'
LINE_CHANNEL_ACCESS_TOKEN = 'l+QP6SuTqqETfAdeY3bJZSSU1ZmF6eBoxeOnWd/mlQpx7E7ihH7mIMR/hYmdSDimr3OWejX0c8kE0MY5LitY4WAHwIyn8fEtFfCT+57kFUayX6ovFZe34BAeMAN6ZcT+53FyVfF1aeb/GhGqihypoQdB04t89/1O/w1cDnyilFU='

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 照護者 LINE User ID + 對應的長者 ID
TARGET_USER_ID = "U8ea3d1facf0625457e60e3e831b2a13c"
TARGET_ELDER_ID = "elder_178546685908e66b"


# ═══════════════════════════════════════════════════════
# Webhook 路由
# ═══════════════════════════════════════════════════════

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# ═══════════════════════════════════════════════════════
# 留言接收：照護者傳文字 → 存入留言佇列
# ═══════════════════════════════════════════════════════

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """照護者傳送文字 → 存入留言佇列"""
    user_id = event.source.user_id
    text = event.message.text.strip()

    if not text:
        return

    # 特殊指令：查看今日動態
    if text in ("今日動態", "查看動態", "動態"):
        _send_today_summary(event.reply_token)
        return

    # 特殊指令：取得自己的 LINE User ID
    if text in ("我的ID", "我的id", "ID", "id", "myid"):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"📋 你的 LINE User ID：\n{user_id}\n\n請將此 ID 填入註冊頁面的 LINE 推播設定欄位。")
        )
        return

    # 一般文字 → 存為留言
    try:
        from core.data_manager import DataManager
        dm = DataManager(elder_id=TARGET_ELDER_ID)

        # 取得照護者名稱（從 profile 讀取）
        profile = dm.get_profile()
        ec = profile.get("emergency_contact", {})
        sender_name = ec.get("name", "家人") or "家人"

        dm.add_message(
            sender_name=sender_name,
            content_type="text",
            content_text=text,
        )

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ 留言已送出！等長輩上線時會通知他喔。\n\n📝 你的留言：「{text[:50]}」")
        )
        print(f"📩 [LINE Bot] 收到照護者留言：「{text[:30]}...」")

    except Exception as e:
        print(f"🚨 [LINE Bot] 留言存入失敗: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ 留言傳送失敗，請稍後再試。")
        )


# ═══════════════════════════════════════════════════════
# 留言接收：照護者傳語音 → 下載音檔 + 存入留言佇列
# ═══════════════════════════════════════════════════════

@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
    """照護者傳送語音 → 下載音檔 + 存入留言佇列"""
    try:
        from core.data_manager import DataManager
        dm = DataManager(elder_id=TARGET_ELDER_ID)

        # 建立音檔存放目錄
        audio_dir = os.path.join(_project_dir, "data", TARGET_ELDER_ID, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        # 下載語音檔
        message_content = line_bot_api.get_message_content(event.message.id)
        audio_filename = f"msg_{event.message.id}.m4a"
        audio_path = os.path.join(audio_dir, audio_filename)

        with open(audio_path, 'wb') as f:
            for chunk in message_content.iter_content():
                f.write(chunk)

        # 取得照護者名稱
        profile = dm.get_profile()
        ec = profile.get("emergency_contact", {})
        sender_name = ec.get("name", "家人") or "家人"

        # 存入留言佇列
        dm.add_message(
            sender_name=sender_name,
            content_type="audio",
            content_text="（語音留言）",
            content_audio_path=audio_path,
        )

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🎙️ 語音留言已送出！等長輩上線時會播放給他聽。")
        )
        print(f"🎙️ [LINE Bot] 收到照護者語音留言，已存入：{audio_path}")

    except Exception as e:
        print(f"🚨 [LINE Bot] 語音留言處理失敗: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ 語音留言傳送失敗，請稍後再試。")
        )


# ═══════════════════════════════════════════════════════
# 推播回報函數（供 app.py 呼叫）
# ═══════════════════════════════════════════════════════

def notify_caregiver_read():
    """留言已讀時通知照護者"""
    try:
        line_bot_api.push_message(
            TARGET_USER_ID,
            TextSendMessage(text="✅ 長輩已收聽您的留言")
        )
        print("📤 [LINE Bot] 已推播已讀回報")
    except Exception as e:
        print(f"⚠️ [LINE Bot] 已讀推播失敗: {e}")


def notify_caregiver_reply(reply_text: str):
    """長者回覆時通知照護者"""
    try:
        line_bot_api.push_message(
            TARGET_USER_ID,
            TextSendMessage(text=f"💬 長輩回覆您：「{reply_text}」")
        )
        print(f"📤 [LINE Bot] 已推播長者回覆：「{reply_text[:30]}」")
    except Exception as e:
        print(f"⚠️ [LINE Bot] 回覆推播失敗: {e}")


# ═══════════════════════════════════════════════════════
# 輔助：查看今日動態
# ═══════════════════════════════════════════════════════

def _send_today_summary(reply_token):
    """回覆照護者今日動態摘要"""
    try:
        from core.data_manager import DataManager
        dm = DataManager(elder_id=TARGET_ELDER_ID)
        dashboard = dm.get_dashboard_logs()
        summary = dashboard.get("today_summary", {})
        summary_text = summary.get("text", "今天還沒有互動紀錄")
        metrics = summary.get("metrics", {})

        msg = f"📊 【今日動態】\n━━━━━━━━━━━\n"
        msg += f"📝 {summary_text}\n\n"
        msg += f"🍚 飲食：{metrics.get('diet', '未提及')}\n"
        msg += f"🏃 活動：{metrics.get('activity', '未提及')}\n"
        msg += f"😴 睡眠：{metrics.get('sleep', '未提及')}\n"
        msg += f"💊 用藥：{metrics.get('medication', '未提及')}\n"
        msg += f"🎭 情緒：{metrics.get('emotion', '未檢測')}"

        line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
    except Exception as e:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=f"⚠️ 無法取得今日動態：{e}")
        )


# ═══════════════════════════════════════════════════════
# 報告推播路由（保留原有功能）
# ═══════════════════════════════════════════════════════

@app.route("/report", methods=['POST'])
def receive_report():
    try:
        if request.data:
            try:
                import json
                raw_data = request.data.decode('utf-8')
                data = json.loads(raw_data)
            except Exception:
                data = request.get_json(force=True, silent=True)
        else:
            data = request.json

        if not data:
            return "No JSON data received", 400

        date = data.get("date", "")
        summary = data.get("overallSummary", "")
        struct = data.get("structuredData", {})

        diet = struct.get("diet", "對話中未提及相關資訊")
        activity = struct.get("activity", "對話中未提及相關資訊")
        sleep = struct.get("sleep", "對話中未提及相關資訊")
        medication = struct.get("medication", "對話中未提及相關資訊")

        formatted_text = (
            f"📅 【生活摘要】 日期：{date}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📝 綜合摘要：\n{summary}\n\n"
            f"🍎 飲食狀況：\n{diet}\n\n"
            f"🏃 Daily活動：\n{activity}\n\n"
            f"😴 睡眠品質：\n{sleep}\n\n"
            f"💊 用藥紀錄：\n{medication}"
        )

        line_bot_api.push_message(TARGET_USER_ID, TextSendMessage(text=formatted_text))
        return "JSON report sent to LINE successfully!", 200

    except Exception as e:
        print(f"處理摘要發生錯誤: {str(e)}")
        return "Internal Server Error", 500


if __name__ == "__main__":
    from waitress import serve
    print("LINE Bot 伺服器已啟動... 目前正在監聽 Port 5000")
    serve(app, host='0.0.0.0', port=5000)
