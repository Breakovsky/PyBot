# main/utils/logger.py

import logging
import sys
import io
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Часовой пояс UTC+3 (Москва)
MSK_TIMEZONE = timezone(timedelta(hours=3))


class MSKFormatter(logging.Formatter):
    """Форматтер с временем по MSK (UTC+3)."""
    
    def formatTime(self, record, datefmt=None):
        # Конвертируем время записи в MSK
        ct = datetime.fromtimestamp(record.created, tz=MSK_TIMEZONE)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")


def setup_logger(log_file: str = "bot_log.log", level=logging.DEBUG):
    """
    Sets up the logger to output logs to both a file and the console.
    Compatible with both Windows and Docker/Linux environments.
    """
    # Определяем путь для логов
    log_dir = Path(log_file).parent
    if log_dir != Path("."):
        log_dir.mkdir(parents=True, exist_ok=True)
    
    # Настройка кодировки для stdout/stderr (только для Windows, если нужно)
    try:
        if sys.platform == "win32" and hasattr(sys.stdout, 'detach'):
            try:
                sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")
                sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding="utf-8")
            except (AttributeError, ValueError):
                # Если уже TextIOWrapper или другой тип, пропускаем
                pass
    except Exception:
        # В Docker/Linux может не работать detach, это нормально
        pass
    
    # Создаем handlers
    handlers = []
    
    # File handler
    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        handlers.append(file_handler)
    except Exception as e:
        # Если не удалось создать файловый handler, логируем только в консоль
        print(f"Warning: Could not create file handler: {e}")
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    handlers.append(console_handler)
    
    # Настройка форматирования с временем по MSK
    formatter = MSKFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    for handler in handlers:
        handler.setFormatter(formatter)
    
    # Настройка root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Удаляем существующие handlers чтобы избежать дублирования
    root_logger.handlers.clear()
    
    # Добавляем новые handlers
    for handler in handlers:
        root_logger.addHandler(handler)
    
    logger = logging.getLogger(__name__)
    logger.info("Logger initialized.")
    return logger
