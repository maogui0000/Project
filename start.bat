@echo off
chcp 65001 >nul

title 雲湧智生 — 智慧長照關懷系統 啟動中...
color 0A

echo ============================================
echo   雲湧智生 — 智慧長照關懷系統
echo   2026 AWS Hackathon Demo
echo   整合模組：語音 AI + LINE Bot + 天氣監控
echo ============================================
echo.

:: ─── 環境檢查 ───────────────────────────────────────
echo [環境檢查] 確認 Python 環境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 找不到 Python！請先安裝 Python 3.10+
    pause
    exit /b 1
)

echo [環境檢查] 確認 Ollama 服務...
curl -s http://localhost:11434/api/version >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Ollama 服務未啟動！正在嘗試啟動...
    start "Ollama" cmd /k "ollama serve"
    timeout /t 5 /nobreak >nul
)

echo.
echo ─── 開始啟動各服務模組 ────────────────────────────
echo.

:: ─── 1. 天氣環境提示詞自動更新 ─────────────────────
echo [1/4] 啟動天氣環境提示詞自動更新器 (每 6 小時背景輪詢)...
start "天氣提示詞定時更新" /min cmd /k "python -m services.weather_cron"

:: ─── 2. FastAPI 後端 API 伺服器 ─────────────────────
echo [2/4] 啟動後端 API 伺服器 (port 8001)...
start "後端 API (FastAPI)" cmd /k "python -m uvicorn app:app --host 0.0.0.0 --port 8001 --reload"

:: ─── 3. LINE Bot 模組 ───────────────────────────────
echo [3/4] 啟動 LINE Bot 模組 (port 5000)...
start "LINE Bot" cmd /k "python -m services.line_bot"

echo.
echo 等待各項後端服務啟動中...
timeout /t 4 /nobreak >nul

:: ─── 自動開啟瀏覽器看板頁面 ─────────────────────────
echo [自動開啟] 正在用瀏覽器開啟看板與長輩互動頁面...
start "" "http://localhost:8001/index.html"
start "" "http://localhost:8001/dashboard.html"

:: ─── 4. ngrok 穿透（可選） ───────────────────────────
echo [4/4] 啟動 ngrok 網路穿透 (選用)...
echo.

:: 嘗試多通道穿透
ngrok http 8001 2>nul
if errorlevel 1 (
    echo.
    echo   💡 提示：ngrok 未安裝或啟動失敗。
    echo   如果您在本機測試，可忽略此步驟。
    echo   如需外網存取，請手動執行：ngrok http 8001
    echo.
)

echo.
echo ═══════════════════════════════════════════════════
echo   ✅ 所有服務全數啟動完成！
echo ═══════════════════════════════════════════════════
echo.
echo   📌 服務網址一覽：
echo   ─────────────────────────────────────────────
echo   🌐 長輩語音互動頁面：  http://localhost:8001/index.html
echo   📊 照護者資訊後台：    http://localhost:8001/dashboard.html
echo   ⚙️  管理員設定頁面：    http://localhost:8001/admin.html
echo   🤖 LINE Bot Webhook：  http://localhost:5000/callback
echo   ─────────────────────────────────────────────
echo.
echo   💡 如需外網存取，請查看 ngrok 視窗中的 Forwarding URL
echo   💡 按任意鍵關閉此視窗（各服務將繼續在背景執行）
echo.
pause
