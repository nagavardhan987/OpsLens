@echo off
echo =====================================================================
echo Enabling Web Browser Feature in EcoStruxure Operator Terminal Expert
echo =====================================================================
powershell -Command "$p='C:\Program Files\Schneider Electric\EcoStruxure Operator Terminal Expert 4.4\Buildtime\EcoStruxure Operator Terminal Expert.exe.config'; (Get-Content $p) -replace 'key=\"IsWebBrowserEnabled\" value=\"false\"', 'key=\"IsWebBrowserEnabled\" value=\"true\"' | Set-Content $p"
echo.
echo [SUCCESS] Web Browser has been enabled!
echo Please restart EcoStruxure Operator Terminal Expert.
pause
