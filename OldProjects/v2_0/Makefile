# Makefile для управления Telegram ботом
# Использование: make <команда>

SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

VENV_PYTHON = .venv\Scripts\python.exe
MAIN_DIR = main
LOG_FILE = main\bot_log.log

.PHONY: start stop restart status logs install clean help

## start: Запустить бота в фоновом режиме
start:
	@Write-Host "🚀 Запускаем бота..." -ForegroundColor Cyan
	@cd $(MAIN_DIR); Start-Process -FilePath "..\$(VENV_PYTHON)" -ArgumentList "main.py" -WindowStyle Hidden
	@Start-Sleep -Seconds 2
	@Write-Host "✅ Бот запущен" -ForegroundColor Green

## stop: Остановить бота
stop:
	@Write-Host "🛑 Останавливаем бота..." -ForegroundColor Cyan
	@Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
	@Write-Host "✅ Бот остановлен" -ForegroundColor Green

## restart: Перезапустить бота
restart: stop
	@Start-Sleep -Seconds 2
	@$(MAKE) start

## status: Проверить статус бота
status:
	@$$proc = Get-Process python -ErrorAction SilentlyContinue; if ($$proc) { Write-Host "✅ Бот работает (PID: $$($$proc.Id))" -ForegroundColor Green } else { Write-Host "❌ Бот не запущен" -ForegroundColor Red }

## logs: Показать последние 50 строк логов
logs:
	@if (Test-Path "$(LOG_FILE)") { Get-Content "$(LOG_FILE)" -Tail 50 } else { Write-Host "❌ Логи не найдены" -ForegroundColor Red }

## logs-follow: Следить за логами в реальном времени
logs-follow:
	@Get-Content "$(LOG_FILE)" -Tail 20 -Wait

## install: Установить зависимости
install:
	@Write-Host "📦 Установка зависимостей..." -ForegroundColor Cyan
	@if (-not (Test-Path ".venv")) { python -m venv .venv }
	@$(VENV_PYTHON) -m pip install --upgrade pip
	@$(VENV_PYTHON) -m pip install -r requirements.txt
	@$(VENV_PYTHON) -m pip install tabulate
	@Write-Host "✅ Готово" -ForegroundColor Green

## clean: Очистить кэш и временные файлы
clean:
	@Write-Host "🧹 Очистка..." -ForegroundColor Cyan
	@Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
	@Get-ChildItem -Recurse -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue
	@if (Test-Path "bot.pid") { Remove-Item "bot.pid" -Force }
	@Write-Host "✅ Очищено" -ForegroundColor Green

## run: Запустить бота в текущем терминале (для отладки)
run:
	@cd $(MAIN_DIR); ..\$(VENV_PYTHON) main.py

## help: Показать справку
help:
	@Write-Host ""
	@Write-Host "🤖 Telegram Bot - Доступные команды:" -ForegroundColor Cyan
	@Write-Host ""
	@Write-Host "  make start       - Запустить бота в фоне"
	@Write-Host "  make stop        - Остановить бота"
	@Write-Host "  make restart     - Перезапустить бота"
	@Write-Host "  make status      - Проверить статус"
	@Write-Host "  make logs        - Показать последние логи"
	@Write-Host "  make logs-follow - Следить за логами"
	@Write-Host "  make run         - Запустить в терминале (отладка)"
	@Write-Host "  make install     - Установить зависимости"
	@Write-Host "  make clean       - Очистить кэш"
	@Write-Host ""

# По умолчанию показываем справку
.DEFAULT_GOAL := help

