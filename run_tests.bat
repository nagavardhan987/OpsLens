@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo === Backend tests (edge_intelligence\tests) ===
pushd edge_intelligence
".venv\Scripts\python.exe" -m pytest tests -q
set BACKEND=%errorlevel%
popd
echo.
echo === Frontend unit tests and production build (hmi_ui) ===
pushd hmi_ui
call npm test
set FRONTEND=%errorlevel%
call npm run build
set BUILD=%errorlevel%
popd
echo.
echo Backend exit=%BACKEND%  Frontend tests exit=%FRONTEND%  Build exit=%BUILD%
pause
