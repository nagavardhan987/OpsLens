@echo off
echo ============================================================
echo   OpsLens AI Copilot - Schneider Electric Hackathon Demo
echo ============================================================
echo.
echo [1/3] Starting OpsLens backend (edge_intelligence) on port 8001...
cd /d "%~dp0edge_intelligence"
start "OpsLens Backend (Port 8001)" cmd /k ".venv\Scripts\python.exe server.py"

echo.
echo Waiting 4 seconds for backend to initialize...
timeout /t 4 /nobreak >nul

echo.
echo [2/3] Starting Operator HMI Dashboard on port 5173...
cd /d "%~dp0hmi_ui"
start "OpsLens Operator HMI (Port 5173)" cmd /k "npm run dev"

echo.
echo [3/3] Starting Engineering Console ^& Scenario Lab on port 5174...
cd /d "%~dp0hmi_ui"
start "OpsLens Engineering Console (Port 5174)" cmd /k "npm run dev:console"

echo.
echo ============================================================
echo  ALL SERVICES STARTED:
echo    1. Backend API:            http://localhost:8001
echo    2. Operator HMI Dashboard: http://localhost:5173
echo    3. Scenario Lab Console:   http://localhost:5174
echo ============================================================
echo.
echo  QUICK DEMO FLOW:
echo   1. Open Engineering Console at http://localhost:5174
echo   2. Select any scenario (e.g. Pump-02 Valve Restriction, Tank-01 High Level)
echo   3. Click "START SCENARIO"
echo   4. Switch to Operator HMI at http://localhost:5173:
echo      - Watch the real-time BLUF Alarm Popup slide in!
echo      - Click "Ask OpsLens Copilot"
echo      - Observe live LLM token streaming (powered by Groq)
echo      - View the retrieved SOP procedure and operational impact metrics!
echo.
echo Press any key to open both dashboards in your browser...
pause
start http://localhost:5173
start http://localhost:5174
