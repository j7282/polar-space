$TargetUrl = "https://searchgood123.onrender.com/api/cron-wakeup"
$Interval = 30

Write-Host "🚀 Iniciando Keep-Alive Monitor para Render Server..." -ForegroundColor Cyan
Write-Host "🔗 Objetivo: $TargetUrl"
Write-Host "⏱️ Intervalo: $Interval segundos"
Write-Host "Presiona [CTRL+C] para detener." -ForegroundColor Red
Write-Host "---------------------------------------------------"

while ($true) {
    try {
        $response = Invoke-WebRequest -Uri $TargetUrl -Method Get -UseBasicParsing -ErrorAction Stop
        $StatusCode = $response.StatusCode
        $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$Timestamp] ✅ Ping Exitoso ($StatusCode OK) - Servidor Despierto" -ForegroundColor Green
    } catch {
        $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$Timestamp] ⚠️ Advertencia: El servidor no respondió correctamente -> $_" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds $Interval
}
