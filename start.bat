@echo off
chcp 65001 > nul
title 🛰 Telegram Tracker PRO

:menu
cls
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo 🟢 Telegram Tracker PRO
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo [1] Первый вход (QR + пароль)
echo [2] Запуск трекера (Авто-обновление)
echo [0] Выход
echo.

set /p choice=Выбери действие: 

if "%choice%"=="1" python login.py
if "%choice%"=="2" (
    echo [!] Режим авто-перезапуска активен.
    watchmedo auto-restart --patterns="*.py" --recursive -- python tracker.py
)
if "%choice%"=="0" exit

echo.
pause
goto menu