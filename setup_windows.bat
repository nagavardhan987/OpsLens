@echo off
setlocal EnableExtensions
title OpsLens - first-time setup
cd /d "%~dp0"
echo ============================================================
echo   OpsLens first-time setup (Windows)
echo   Creates edge_intelligence\.venv and installs hmi_ui packages.
echo   Safe to run again; it only adds what is missing.
echo ============================================================
echo.

rem ---- 1. Python ------------------------------------------------------------
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo [ERROR] Python 3.10+ was not found.
  echo         Install it from https://www.python.org/downloads/ and tick
  echo         "Add python.exe to PATH", then run this script again.
  goto :fail
)
%PYEXE% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.10 or newer is required.
  %PYEXE% --version
  goto :fail
)
echo [OK] Python found:
%PYEXE% --version

rem ---- 2. Backend virtual environment --------------------------------------
if not exist "edge_intelligence\.venv\Scripts\python.exe" (
  echo Creating virtual environment edge_intelligence\.venv ...
  %PYEXE% -m venv "edge_intelligence\.venv" || goto :fail
)
set "VPY=%~dp0edge_intelligence\.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip >nul

echo Installing backend packages (full: includes sentence-transformers for Qdrant search)...
"%VPY%" -m pip install -r "edge_intelligence\requirements.txt"
if errorlevel 1 (
  echo.
  echo [WARN] Full install failed (usually PyTorch / sentence-transformers).
  echo        Installing the core set instead. OpsLens will use BM25 SOP retrieval.
  "%VPY%" -m pip install -r "edge_intelligence\requirements-core.txt" || goto :fail
)
"%VPY%" -m pip install "pytest>=8" >nul

rem ---- 3. Backend configuration --------------------------------------------
if not exist "edge_intelligence\.env" (
  copy /y "edge_intelligence\.env.example" "edge_intelligence\.env" >nul
  echo [OK] Created edge_intelligence\.env from .env.example - review it before going live.
) else (
  echo [OK] edge_intelligence\.env already exists - not changed.
)

rem ---- 4. Frontend ---------------------------------------------------------
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js / npm not found. Install Node.js 18 LTS or newer from https://nodejs.org/
  goto :fail
)
echo Installing frontend packages (hmi_ui)...
pushd hmi_ui
if exist package-lock.json (call npm ci) else (call npm install)
if errorlevel 1 ( popd & goto :fail )
popd

rem ---- 5. Optional services (information only) -----------------------------
echo.
echo Checking optional services (OpsLens runs without them):
powershell -NoProfile -Command "try { Invoke-RestMethod -TimeoutSec 2 http://localhost:11434/api/tags | Out-Null; Write-Host '[OK] Ollama is running on port 11434' } catch { Write-Host '[INFO] Ollama is not running. Optional. Start it with: ollama serve  then: ollama pull qwen2.5:3b' }"
powershell -NoProfile -Command "try { Invoke-RestMethod -TimeoutSec 2 http://localhost:6333/collections | Out-Null; Write-Host '[OK] Qdrant is running on port 6333' } catch { Write-Host '[INFO] Qdrant is not running. Optional - BM25 keyword retrieval will be used. To start: docker compose up -d qdrant' }"

echo.
echo ============================================================
echo  Setup complete. Next: double-click start_all.bat
echo ============================================================
pause
exit /b 0

:fail
echo.
echo Setup did not finish. Fix the message above and run setup_windows.bat again.
pause
exit /b 1
