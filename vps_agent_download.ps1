$WebClient = New-Object System.Net.WebClient
$content = $WebClient.DownloadString("https://raw.githubusercontent.com/j7282/searchgood/main/vps_agent.py")
Set-Content -Path "vps_agent.py" -Value $content
Write-Host "✅ Archivo actualizado."
