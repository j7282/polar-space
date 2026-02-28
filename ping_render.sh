#!/bin/bash
# ═══════════════════════════════════════════════════════
#  DLP AUDIT - SERVER KEEP-ALIVE SCRIPT
#  Ejecutar en un VPS Linux (Ubuntu/Debian/CentOS)
# ═══════════════════════════════════════════════════════

TARGET_URL="https://searchgood123.onrender.com/api/cron-wakeup"
INTERVAL=30 # Segundos entre cada ping

echo "🚀 Iniciando Keep-Alive Monitor para Render Server..."
echo "🔗 Objetivo: $TARGET_URL"
echo "⏱️  Intervalo: $INTERVAL segundos"
echo "Presiona [CTRL+C] para detener."
echo "---------------------------------------------------"

while true; do
    # Usamos curl para hacer un GET rápido y silencioso
    HTTP_STATUS=$(curl -o /dev/null -s -w "%{http_code}\n" "$TARGET_URL")
    
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
    
    if [ "$HTTP_STATUS" -eq 200 ]; then
        echo "[$TIMESTAMP] ✅ Ping Exitoso (200 OK) - Servidor Despierto"
    else
        echo "[$TIMESTAMP] ⚠️ Advertencia: Código HTTP $HTTP_STATUS recibido."
    fi
    
    sleep $INTERVAL
done
