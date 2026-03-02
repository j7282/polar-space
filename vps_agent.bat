@echo off
title DLP Auditor - Agente VPS Independiente (Windows)
color 0a

echo ==========================================================
echo        SISTEMA DE AUDITORIA DLP (VPS AGENT)
echo ==========================================================
echo.
echo Presiona CTRL+C en cualquier momento para detener el Agente.
echo.

REM Variables esenciales que el script de Python necesita en Windows:
set DATABASE_URL=postgresql://searchgood_db_il0e_user:j0J25UROGJReJIwaijSeGgTtkKGpCphG@dpg-d6hiadsr85hc739g4l7g-a.oregon-postgres.render.com/searchgood_db_il0e
set TARGET_GROUP=HOTMAIL HQ
set FILTER_KEYWORD=HOTMAIL HQ

REM Si tienes llaves de Gemini o Groq, ponlas aqui:
REM set GEMINI_API_KEY=tu_llave_aqui
REM set GROQ_API_KEY=tu_llave_aqui

python vps_agent.py
pause
