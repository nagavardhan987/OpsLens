$configPath = "C:\Program Files\Schneider Electric\EcoStruxure Operator Terminal Expert 4.4\Buildtime\EcoStruxure Operator Terminal Expert.exe.config"
$content = Get-Content $configPath -Raw
$newContent = $content -replace 'key="IsWebBrowserEnabled"\s+value="false"', 'key="IsWebBrowserEnabled" value="true"'
Set-Content -Path $configPath -Value $newContent -Force
Write-Host "EcoStruxure OTE Web Browser enabled successfully!"
Start-Sleep -Seconds 2
