#!/bin/bash
# ═══════════════════════════════════════════════════════
# 雲湧智生 — EC2 一鍵部署腳本
# 
# 使用方式：
#   1. 啟動一台 EC2（建議 Ubuntu 22.04, t3.medium 以上）
#   2. 將專案上傳到 EC2（git clone 或 scp）
#   3. 執行：chmod +x deploy_ec2.sh && ./deploy_ec2.sh
#
# 前提條件：
#   - EC2 的 IAM Role 需有 bedrock:InvokeModel 和 bedrock:InvokeModelWithResponseStream 權限
#   - Security Group 開放 port 8001（API）和 5000（LINE Bot）
# ═══════════════════════════════════════════════════════

set -e

echo "═══════════════════════════════════════════════"
echo "  雲湧智生 — EC2 部署開始"
echo "═══════════════════════════════════════════════"

# ── 1. 系統更新與基本工具 ─────────────────────────────
echo "[1/6] 更新系統套件..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git ffmpeg portaudio19-dev

# ── 2. 建立虛擬環境 ──────────────────────────────────
echo "[2/6] 建立 Python 虛擬環境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# ── 3. 安裝 Python 依賴 ──────────────────────────────
echo "[3/6] 安裝 Python 依賴..."
pip install --upgrade pip
pip install -r requirements.txt

# ── 4. 建立 .env（如果不存在）─────────────────────────
echo "[4/6] 檢查環境設定..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  已建立 .env 檔案，請編輯填入必要設定："
    echo "    - AWS_REGION（預設 us-east-1）"
    echo "    - BEDROCK_MODEL_ID（預設 Claude 3.5 Sonnet）"
    echo "    - LINE_CHANNEL_SECRET"
    echo "    - LINE_CHANNEL_ACCESS_TOKEN"
    echo "    - LINE_TARGET_USER_ID"
fi

# ── 5. 建立必要目錄 ──────────────────────────────────
echo "[5/6] 確認資料目錄..."
mkdir -p data logs

# ── 6. 啟動服務 ──────────────────────────────────────
echo "[6/6] 啟動 API 伺服器..."
echo ""
echo "═══════════════════════════════════════════════"
echo "  部署完成！"
echo ""
echo "  啟動指令："
echo "    source venv/bin/activate"
echo "    python -m uvicorn app:app --host 0.0.0.0 --port 8001"
echo ""
echo "  或用 nohup 背景執行："
echo "    nohup python -m uvicorn app:app --host 0.0.0.0 --port 8001 > logs/api_server.log 2>&1 &"
echo ""
echo "  用 systemd 設為系統服務（建議正式環境使用）："
echo "    sudo cp elder-care.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable elder-care"
echo "    sudo systemctl start elder-care"
echo "═══════════════════════════════════════════════"
