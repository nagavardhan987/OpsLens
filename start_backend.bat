@echo off
setlocal EnableExtensions
title OpsLens Backend (FastAPI :8001)
cd /d "%~dp0edge_intelligence"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Backend environment not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  echo [INFO] No .env found - copying .env.example. Edit edge_intelligence\.env to change settings.
  copy /y ".env.example" ".env" >nul
)

rem Optional services: report, never block startup.
powershell -NoProfile -Command "try { Invoke-RestMethod -TimeoutSec 2 http://localhost:11434/api/tags | Out-Null; Write-Host '[OK] Ollama reachable - Ask OpsLens can use the local model.' } catch { Write-Host '[INFO] Ollama not running - OpsLens will use deterministic answers. (Optional: ollama serve)' }"
powershell -NoProfile -Command "try { Invoke-RestMethod -TimeoutSec 2 http://localhost:6333/collections | Out-Null; Write-Host '[OK] Qdrant reachable - vector SOP search enabled.' } catch { Write-Host '[INFO] Qdrant not running - BM25 keyword SOP retrieval will be used.' }"

echo.
echo Starting OpsLens backend on http://127.0.0.1:8001  (Ctrl+C to stop)
echo Health:      http://127.0.0.1:8001/api/health
echo Diagnostics: http://127.0.0.1:8001/api/diagnostics
echo.
".venv\Scripts\python.exe" server.py
echo.
echo [INFO] Backend stopped. If it closed immediately, read the error above
echo        (common cause: port 8001 already in use - see TROUBLESHOOTING.md).
pause
