#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#   雲湧智生 — 智慧長照關懷系統 Linux 啟動腳本
#   2026 AWS Hackathon Demo
#   整合模組：語音 AI + LINE Bot + 天氣監控
# ═══════════════════════════════════════════════════════

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 切換到腳本所在目錄
cd "$(dirname "$0")"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  雲湧智生 — 智慧長照關懷系統${NC}"
echo -e "${CYAN}  2026 AWS Hackathon Demo${NC}"
echo -e "${CYAN}  整合模組：語音 AI + LINE Bot + 天氣監控${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ─── 環境檢查 ───────────────────────────────────────
echo -e "${YELLOW}[環境檢查]${NC} 確認 Python 環境..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 找不到 Python3！請先安裝 Python 3.10+${NC}"
    exit 1
fi
python3 --version

echo -e "${YELLOW}[環境檢查]${NC} 確認 Ollama 服務..."
if ! curl -s http://localhost:11434/api/version &> /dev/null; then
    echo -e "${YELLOW}⚠️  Ollama 服務未啟動！正在嘗試啟動...${NC}"
    nohup ollama serve > /dev/null 2>&1 &
    sleep 3
    if curl -s http://localhost:11434/api/version &> /dev/null; then
        echo -e "${GREEN}✅ Ollama 已成功啟動${NC}"
    else
        echo -e "${RED}❌ Ollama 啟動失敗，請手動執行: ollama serve${NC}"
    fi
else
    echo -e "${GREEN}✅ Ollama 服務已在運行${NC}"
fi

echo ""
echo -e "${CYAN}─── 開始啟動各服務模組 ────────────────────────────${NC}"
echo ""

# 清理可能被佔用的 port（在啟動服務前先確保 port 空出來）
echo -e "${YELLOW}[清理]${NC} 確保 port 8001/5000 未被佔用..."
fuser -k 8001/tcp 2>/dev/null
fuser -k 5000/tcp 2>/dev/null
pkill -f ngrok 2>/dev/null
sleep 2

# 建立 logs 目錄
mkdir -p logs

# 記錄所有背景程序的 PID
PIDS=()

# ─── 1. 天氣環境提示詞自動更新 ─────────────────────
echo -e "${YELLOW}[1/5]${NC} 啟動天氣環境提示詞自動更新器 (每 6 小時背景輪詢)..."
python3 -m services.weather_cron > logs/weather_cron.log 2>&1 &
PIDS+=($!)
echo -e "      PID: $! → logs/weather_cron.log"

# ─── 2. FastAPI 後端 API 伺服器 ─────────────────────
echo -e "${YELLOW}[2/5]${NC} 啟動後端 API 伺服器 (port 8001)..."
python3 -m uvicorn app:app --host 0.0.0.0 --port 8001 > logs/api_server.log 2>&1 &
PIDS+=($!)
echo -e "      PID: $! → logs/api_server.log"

# ─── 3. LINE Bot 模組 ───────────────────────────────
echo -e "${YELLOW}[3/5]${NC} 啟動 LINE Bot 模組 (port 5000)..."
python3 -m services.line_bot > logs/line_bot.log 2>&1 &
PIDS+=($!)
echo -e "      PID: $! → logs/line_bot.log"

# ─── 4. 語音助理（小黃小黃喚醒詞偵測）───────────────
echo -e "${YELLOW}[4/5]${NC} 啟動語音助理（喚醒詞「小黃小黃」）..."
python3 -c "from core.voice_assistant import get_assistant; a = get_assistant(); a.start(); import time; [time.sleep(1) for _ in iter(int, 1)]" > logs/voice_assistant.log 2>&1 &
PIDS+=($!)
echo -e "      PID: $! → logs/voice_assistant.log"

# ─── 5. ngrok HTTPS 穿透（遠端麥克風需要 HTTPS）────
echo -e "${YELLOW}[5/5]${NC} 啟動 ngrok HTTPS 穿透..."
if command -v ngrok &> /dev/null; then
    ngrok http 8001 --log=stdout > logs/ngrok.log 2>&1 &
    PIDS+=($!)
    echo -e "      PID: $! → logs/ngrok.log"
    sleep 3
    # 自動抓取 ngrok 公開 URL
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; data=json.load(sys.stdin); print(data['tunnels'][0]['public_url'])" 2>/dev/null)
    if [ -n "$NGROK_URL" ]; then
        echo -e "      ${GREEN}✅ ngrok 穿透成功！${NC}"
        echo -e "      ${CYAN}🌐 外網網址：${NGROK_URL}${NC}"
    else
        echo -e "      ${YELLOW}⚠️  ngrok 啟動中，請稍後查看 logs/ngrok.log 或 http://localhost:4040${NC}"
    fi
else
    echo -e "      ${YELLOW}⚠️  ngrok 未安裝，跳過。遠端使用需手動執行：ngrok http 8001${NC}"
fi

echo ""
echo -e "${YELLOW}等待各項後端服務啟動中...${NC}"
sleep 4

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ 所有服務全數啟動完成！${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
if [ -n "$NGROK_URL" ]; then
    echo -e "  📌 外網服務網址："
    echo -e "  ─────────────────────────────────────────────"
    echo -e "  🌐 長輩語音互動頁面：  ${CYAN}${NGROK_URL}/index.html${NC}"
    echo -e "  📊 照護者資訊後台：    ${CYAN}${NGROK_URL}/dashboard.html${NC}"
    echo -e "  ⚙️  管理員設定頁面：    ${CYAN}${NGROK_URL}/admin.html${NC}"
    echo -e "  ─────────────────────────────────────────────"
else
    echo -e "  ${YELLOW}⚠️  ngrok 未取得外網網址，請查看 logs/ngrok.log${NC}"
fi
echo ""
echo -e "  📝 日誌檔案位於 logs/ 目錄"
echo -e "  💡 按 Ctrl+C 停止所有服務"
echo ""

# ─── 優雅關閉 ───────────────────────────────────────
cleanup() {
    echo ""
    echo -e "${YELLOW}正在關閉所有服務...${NC}"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo -e "  停止 PID $pid"
        fi
    done
    echo -e "${GREEN}✅ 所有服務已關閉${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# 保持腳本存活，等待 Ctrl+C
wait
