@echo off
chcp 65001 >nul
setlocal

set VENV_PYTHON=%~dp0.venv\Scripts\python.exe
set MAIN_DIR=%~dp0main

if "%1"=="" goto help
if "%1"=="start" goto start
if "%1"=="stop" goto stop
if "%1"=="restart" goto restart
if "%1"=="status" goto status
if "%1"=="logs" goto logs
if "%1"=="run" goto run
if "%1"=="install" goto install
if "%1"=="help" goto help
goto help

:start
echo 🚀 Запускаем бота...
cd /d "%MAIN_DIR%"
start "" "%VENV_PYTHON%" main.py
timeout /t 2 >nul
echo ✅ Бот запущен
goto end

:stop
echo 🛑 Останавливаем бота...
taskkill /f /im python.exe >nul 2>&1
echo ✅ Бот остановлен
goto end

:restart
call :stop
timeout /t 2 >nul
call :start
goto end

:status
tasklist /fi "imagename eq python.exe" 2>nul | find "python.exe" >nul
if %errorlevel%==0 (
    echo ✅ Бот работает
    tasklist /fi "imagename eq python.exe"
) else (
    echo ❌ Бот не запущен
)
goto end

:logs
if exist "%MAIN_DIR%\bot_log.log" (
    echo 📋 Последние логи:
    powershell -Command "Get-Content '%MAIN_DIR%\bot_log.log' -Tail 30"
) else (
    echo ❌ Логи не найдены
)
goto end

:run
echo 🤖 Запускаем бота в текущем терминале...
cd /d "%MAIN_DIR%"
"%VENV_PYTHON%" main.py
goto end

:install
echo 📦 Установка зависимостей...
if not exist "%~dp0.venv" (
    echo Создаём виртуальное окружение...
    python -m venv "%~dp0.venv"
)
"%VENV_PYTHON%" -m pip install --upgrade pip
"%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt"
"%VENV_PYTHON%" -m pip install tabulate
echo ✅ Готово
goto end

:help
echo.
echo 🤖 Telegram Bot Manager
echo.
echo Использование: bot.bat ^<команда^>
echo.
echo Команды:
echo   start    - Запустить бота в фоне
echo   stop     - Остановить бота  
echo   restart  - Перезапустить бота
echo   status   - Проверить статус
echo   logs     - Показать логи
echo   run      - Запустить в терминале (отладка)
echo   install  - Установить зависимости
echo   help     - Показать справку
echo.
goto end

:end
endlocal

