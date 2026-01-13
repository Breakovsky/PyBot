@echo off
REM Скрипт для запуска бота TBot v2.1

echo ========================================
echo Запуск TBot v2.1
echo ========================================
echo.

REM Активируем виртуальное окружение если оно существует
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo Виртуальное окружение активировано
) else (
    echo Предупреждение: Виртуальное окружение не найдено
    echo Убедитесь, что зависимости установлены
)

echo.
echo Запуск бота...
echo.

python main\main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================
    echo Бот завершился с ошибкой
    echo Проверьте логи в logs\tbot.log
    echo ========================================
    pause
)

