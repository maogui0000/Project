import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage 

app = Flask(__name__)

# LINE Bot 憑證設定
LINE_CHANNEL_SECRET = '31abac3ba0956fe48e14d63bc0077a21'
LINE_CHANNEL_ACCESS_TOKEN = 'l+QP6SuTqqETfAdeY3bJZSSU1ZmF6eBoxeOnWd/mlQpx7E7ihH7mIMR/hYmdSDimr3OWejX0c8kE0MY5LitY4WAHwIyn8fEtFfCT+57kFUayX6ovFZe34BAeMAN6ZcT+53FyVfF1aeb/GhGqihypoQdB04t89/1O/w1cDnyilFU='

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 你的 LINE User ID
TARGET_USER_ID = "U8ea3d1facf0625457e60e3e831b2a13c"


# 🚪 路由一：維持原樣，專門給 LINE 官方用的 Webhook 通道
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# 門 路由二：新增這個！專門給你晚上 7 點接收外部系統 JSON 的通道
@app.route("/report", methods=['POST'])
def receive_report():
    try:
        # 💡 關鍵改動：如果發現收到的資料不是用 utf-8 解碼，強制幫它轉回 utf-8
        if request.data:
            try:
                # 嘗試用 utf-8 解析原始字節資料
                import json
                raw_data = request.data.decode('utf-8')
                data = json.loads(raw_data)
            except Exception:
                # 如果解碼失敗，就使用 Flask 預設的 get_json
                data = request.get_json(force=True, silent=True)
        else:
            data = request.json

        if not data:
            return "No JSON data received", 400
        
        # 解析 JSON 欄位
        date = data.get("date", "")
        summary = data.get("overallSummary", "")
        struct = data.get("structuredData", {})
        
        diet = struct.get("diet", "對話中未提及相關資訊")
        activity = struct.get("activity", "對話中未提及相關資訊")
        sleep = struct.get("sleep", "對話中未提及相關資訊")
        medication = struct.get("medication", "對話中未提及相關資訊")
        
        # 排版 LINE 訊息文字
        formatted_text = (
            f"📅 【生活摘要】 日期：{date}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📝 綜合摘要：\n{summary}\n\n"
            f"🍎 飲食狀況：\n{diet}\n\n"
            f"🏃 Daily活動：\n{activity}\n\n"
            f"😴 睡眠品質：\n{sleep}\n\n"
            f"💊 用藥紀錄：\n{medication}"
        )
        
        # 使用 push_message 主動推播給使用者
        line_bot_api.push_message(TARGET_USER_ID, TextSendMessage(text=formatted_text))
        return "JSON report sent to LINE successfully!", 200
        
    except Exception as e:
        print(f"處理摘要發生錯誤: {str(e)}")
        return "Internal Server Error", 500

if __name__ == "__main__":
    from waitress import serve
    print("LINE Bot 伺服器已啟動... 目前正在監聽 Port 5000")
    serve(app, host='0.0.0.0', port=5000)