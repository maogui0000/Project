# 雲湧智生 — 智慧長照關懷系統

> 2026 AWS Hackathon 參賽作品

一套以 AI 語音互動為核心的智慧長照陪伴系統，透過 Amazon Bedrock（Claude Sonnet 4）提供長者日常陪伴、健康追蹤、情緒關懷與照護者即時通知。

---

## 系統特色

- **AI 語音對話** — 支援國語/台語/客語語音辨識（Taiwan-Tongues-ASR），搭配 Edge TTS 自然語音合成
- **喚醒詞偵測** — 說「小黃小黃」即可喚醒語音助理，無需手動操作
- **記憶系統** — 短期記憶（對話上下文，TTL 自動過期）+ 長期記憶（偏好/用藥/習慣永久保存）
- **健康追蹤** — AI 自動從對話中擷取用藥、飲食、睡眠、活動資訊，生成每日結構化摘要
- **語音情緒辨識** — 使用 emotion2vec+ 偵測長者語音情緒，AI 回覆自動調整語氣
- **環境感知** — 即時天氣 + 日落資料整合，主動提醒外出安全
- **LINE Bot 推播** — 每日 19:00 自動推送照護摘要、緊急通知即時推播、照護者語音留言
- **照護者後台** — Web Dashboard 提供每日摘要、情緒趨勢、互動統計、事件時間軸
- **安全防護** — 輸入驗證防注入、PIN 碼登入鎖定機制、身分證格式驗證、對話內容後處理過濾

---

## 技術架構

| 層次 | 技術 |
|------|------|
| 前端 | HTML + Tailwind CSS + Web Speech API |
| 後端 | FastAPI + Uvicorn |
| AI 模型 | Amazon Bedrock（Claude Sonnet 4） |
| 語音辨識 | Taiwan-Tongues-ASR（faster-whisper / CTranslate2 int8） |
| 語音合成 | Edge TTS（微軟 Neural 語音） |
| 情緒辨識 | emotion2vec+（FunASR / ModelScope） |
| 通知推播 | LINE Messaging API |
| 天氣資料 | 中央氣象署開放資料 API |
| 部署 | AWS EC2 + Let's Encrypt SSL + systemd |

---

## 專案結構

```
Project/
├── app.py                  # FastAPI 主應用程式（所有 API 端點）
├── config.py               # 統一配置中心
├── requirements.txt        # Python 依賴清單
├── start.sh                # Linux 一鍵啟動腳本
├── start.bat               # Windows 啟動腳本
├── deploy_ec2.sh           # EC2 一鍵部署腳本
├── elder-care.service      # systemd 服務設定檔
├── iam-bedrock-policy.json # AWS IAM 權限範本
│
├── core/                   # 核心模組
│   ├── ai_chat.py          # AI 對話引擎（串流逐句生成）
│   ├── bedrock_client.py   # Amazon Bedrock LLM 統一呼叫
│   ├── data_manager.py     # 統一資料存取層（4 個 JSON）
│   ├── memory_controller.py# 長短期記憶控制器
│   └── voice_assistant.py  # 語音助理主控制器
│
├── speech/                 # 語音處理模組
│   ├── asr_tts.py          # 語音辨識 + 語音合成
│   ├── emotion_recognition.py # 語音情緒辨識
│   └── wake_word.py        # 喚醒詞偵測
│
├── services/               # 背景服務
│   ├── ai_summary.py       # AI 每日摘要生成
│   ├── line_bot.py         # LINE Bot 留言 + 推播
│   └── weather_cron.py     # 天氣/日落環境提示詞更新
│
├── prompts/                # AI 提示詞
│   ├── chat_prompt.txt     # 主對話人設提示詞
│   ├── Environmental_Prompts.txt # 即時環境提示詞（自動更新）
│   ├── life_records_prompt.txt   # 每日摘要分析提示詞
│   ├── health_analysis_prompt.txt# 健康資訊分析提示詞
│   ├── farewell_detection_prompt.txt # 告別偵測提示詞
│   ├── memory_importance_prompt.txt  # 記憶重要性判斷提示詞
│   └── safety_rules.json   # 安全規則（關鍵詞觸發）
│
├── web/                    # 前端頁面
│   ├── index.html          # 長者語音互動頁面
│   ├── dashboard.html      # 照護者資訊後台
│   └── admin.html          # 管理員設定頁面
│
├── data/                   # 長者資料（JSON）
│   └── elder_xxx/
│       ├── elder_profile.json     # 長者基本資料
│       ├── long_term_memory.json  # 長期記憶
│       ├── short_term_memory.json # 短期記憶
│       ├── dashboard_logs.json    # 每日摘要/統計
│       ├── reminders.json         # 提醒事項
│       └── messages.json          # 照護者留言
│
├── models/                 # ASR 模型檔案
│   └── taiwan-tongues-asr/ # Taiwan-Tongues-ASR 本地模型
│
├── images/                 # 靜態圖片資源
└── logs/                   # 執行日誌
```

---

## 快速開始

### 前置需求

- Python 3.10+
- AWS 帳號（已啟用 Amazon Bedrock，具有 Claude 模型存取權限）
- EC2 IAM Role 需有 `bedrock:InvokeModel` 和 `bedrock:InvokeModelWithResponseStream` 權限
- LINE Developers 帳號（選配，用於 LINE 推播功能）
- 中央氣象署 API Key（選配，用於天氣功能）

### 安裝步驟

```bash
# 1. Clone 專案
git clone https://github.com/maogui0000/Project.git
cd Project

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 設定環境變數
cp .env.example .env
# 編輯 .env 填入：
#   AWS_REGION=us-east-1
#   BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-20250514-v1:0
#   LINE_CHANNEL_SECRET=xxx
#   LINE_CHANNEL_ACCESS_TOKEN=xxx
```

### 本地開發

```bash
# 啟動 API 伺服器
python -m uvicorn app:app --host 0.0.0.0 --port 8001

# 或使用一鍵啟動（含天氣/LINE Bot/語音助理）
chmod +x start.sh
./start.sh
```

啟動後存取：
- 語音互動頁面：http://localhost:8001/index.html
- 照護者後台：http://localhost:8001/dashboard.html
- 管理員設定：http://localhost:8001/admin.html

---

## EC2 部署

```bash
# 一鍵部署
chmod +x deploy_ec2.sh
./deploy_ec2.sh

# 設為系統服務
sudo cp elder-care.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable elder-care
sudo systemctl start elder-care
```

### HTTPS 設定（Let's Encrypt）

```bash
# 安裝 certbot
sudo apt install certbot python3-certbot-nginx

# 取得憑證（用 nip.io 免費域名）
sudo certbot --nginx -d <你的IP>.nip.io

# 或直接用 uvicorn 帶 SSL
sudo python -m uvicorn app:app --host 0.0.0.0 --port 443 \
  --ssl-keyfile /etc/letsencrypt/live/<域名>/privkey.pem \
  --ssl-certfile /etc/letsencrypt/live/<域名>/fullchain.pem
```

---

## API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/chat` | AI 對話（非串流） |
| POST | `/api/chat/stream` | AI 對話（SSE 串流逐句） |
| POST | `/api/speech` | 語音辨識 + AI 回覆 + TTS 合成 |
| POST | `/api/elder/profile` | 長者註冊/建立 Profile |
| POST | `/api/elder/verify_pin` | PIN 碼驗證登入 |
| GET  | `/api/elder/{id}/profile` | 取得長者資料 |
| GET  | `/api/dashboard/{id}` | 取得看板資料（摘要/統計） |
| GET  | `/api/dashboard/{id}/events` | SSE 即時事件推送 |
| POST | `/api/reminders/{id}/add` | 新增提醒事項 |
| GET  | `/api/reminders/{id}/pending` | 取得待處理提醒 |

---

## 環境變數

| 變數名 | 預設值 | 說明 |
|--------|--------|------|
| `AWS_REGION` | `us-east-1` | AWS 區域 |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock 模型 ID |
| `API_PORT` | `8001` | API 伺服器 port |
| `LINE_CHANNEL_SECRET` | — | LINE Bot Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | — | LINE Bot Access Token |
| `LINE_TARGET_USER_ID` | — | 照護者 LINE User ID |
| `ASR_MODEL_PATH` | `models/taiwan-tongues-asr` | ASR 模型路徑 |
| `WEATHER_UPDATE_INTERVAL` | `21600` | 天氣更新間隔（秒） |

---

## 授權

本專案為 2026 AWS Hackathon 參賽作品。
