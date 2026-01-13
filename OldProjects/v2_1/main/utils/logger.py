"""
Улучшенная система логирования с ротацией и структурированным контекстом.
"""

import logging
import sys
import io
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from functools import wraps

# Часовой пояс UTC+3 (Москва)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# Список чувствительных ключей для маскирования в логах
SENSITIVE_KEYS = {
    'password', 'token', 'secret', 'api_key', 'apikey', 'access_token',
    'refresh_token', 'authorization', 'auth', 'credential', 'private_key',
    'otrs_password', 'db_password'
}


class MSKFormatter(logging.Formatter):
    """Форматтер с временем по MSK (UTC+3) и улучшенным форматированием."""
    
    def formatTime(self, record, datefmt=None):
        # Конвертируем время записи в MSK
        ct = datetime.fromtimestamp(record.created, tz=MSK_TIMEZONE)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")
    
    def format(self, record):
        # Добавляем контекст к сообщению, если он есть
        if hasattr(record, 'context') and record.context:
            context_str = self._format_context(record.context)
            record.msg = f"{record.msg} | {context_str}" if record.msg else context_str
        
        return super().format(record)
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """Форматирует контекст для логирования."""
        parts = []
        for key, value in context.items():
            # Маскируем чувствительные данные
            if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
                value = self._mask_sensitive(value)
            parts.append(f"{key}={value}")
        return ", ".join(parts)
    
    def _mask_sensitive(self, value: Any) -> str:
        """Маскирует чувствительные данные."""
        if value is None:
            return "None"
        value_str = str(value)
        if len(value_str) <= 8:
            return "***"
        return f"{value_str[:3]}***{value_str[-2:]}" if len(value_str) > 5 else "***"


class ContextLogger:
    """Обертка для logger с поддержкой контекста."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def _with_context(self, level: int, msg: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Логирует сообщение с контекстом."""
        if context:
            # Создаем новую запись с контекстом
            extra = kwargs.get('extra', {})
            extra['context'] = context
            kwargs['extra'] = extra
        self.logger.log(level, msg, **kwargs)
    
    def info(self, msg: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Логирует информационное сообщение с контекстом."""
        self._with_context(logging.INFO, msg, context, **kwargs)
    
    def debug(self, msg: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Логирует отладочное сообщение с контекстом."""
        self._with_context(logging.DEBUG, msg, context, **kwargs)
    
    def warning(self, msg: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Логирует предупреждение с контекстом."""
        self._with_context(logging.WARNING, msg, context, **kwargs)
    
    def error(self, msg: str, context: Optional[Dict[str, Any]] = None, exc_info=None, **kwargs):
        """Логирует ошибку с контекстом."""
        if exc_info is not None:
            kwargs['exc_info'] = exc_info
        self._with_context(logging.ERROR, msg, context, **kwargs)
    
    def critical(self, msg: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Логирует критическую ошибку с контекстом."""
        self._with_context(logging.CRITICAL, msg, context, **kwargs)
    
    def operation(self, operation: str, status: str = "started", 
                  context: Optional[Dict[str, Any]] = None, **kwargs):
        """Логирует операцию (started, completed, failed)."""
        status_emoji = {
            'started': '▶️',
            'completed': '✅',
            'failed': '❌',
            'in_progress': '⏳'
        }
        emoji = status_emoji.get(status, '📝')
        msg = f"{emoji} {operation} [{status.upper()}]"
        level = logging.INFO if status != 'failed' else logging.ERROR
        self._with_context(level, msg, context, **kwargs)
    
    def user_action(self, action: str, user_id: Optional[int] = None,
                   username: Optional[str] = None, chat_id: Optional[int] = None,
                   **extra_context):
        """Логирует действие пользователя."""
        context = {
            'action': action,
            **(extra_context or {})
        }
        if user_id:
            context['user_id'] = user_id
        if username:
            context['username'] = username
        if chat_id:
            context['chat_id'] = chat_id
        
        self.info(f"👤 User action: {action}", context=context)
    
    def db_operation(self, operation: str, table: str, record_id: Optional[int] = None,
                    **extra_context):
        """Логирует операцию с БД."""
        context = {
            'db_operation': operation,
            'table': table,
            **(extra_context or {})
        }
        if record_id:
            context['record_id'] = record_id
        
        self.info(f"💾 DB {operation}: {table}", context=context)
    
    def api_request(self, method: str, path: str, status_code: Optional[int] = None,
                   user_id: Optional[int] = None, **extra_context):
        """Логирует API запрос."""
        context = {
            'method': method,
            'path': path,
            **extra_context
        }
        if status_code:
            context['status_code'] = status_code
        if user_id:
            context['user_id'] = user_id
        
        # Определяем эмодзи по статусу, если он есть
        if status_code:
            status_emoji = '✅' if status_code < 400 else '⚠️' if status_code < 500 else '❌'
        else:
            status_emoji = '📡'  # Для запросов без статуса (входящие запросы)
        self.info(f"{status_emoji} API {method} {path}", context=context)


def get_logger(name: str) -> ContextLogger:
    """
    Получает logger с поддержкой контекста.
    
    Args:
        name: Имя логгера (обычно __name__)
        
    Returns:
        ContextLogger с поддержкой структурированного логирования
    """
    return ContextLogger(logging.getLogger(name))


def setup_logger(
    log_file: str = "logs/tbot.log",
    level=logging.INFO,
    rotation_size_mb: int = 10,
    rotation_backup_count: int = 10,
    json_format: bool = False
):
    """
    Настраивает логирование с ротацией файлов.
    
    Args:
        log_file: Путь к файлу логов
        level: Уровень логирования
        rotation_size_mb: Максимальный размер файла в MB перед ротацией
        rotation_backup_count: Количество файлов для хранения
        json_format: Использовать JSON формат (для структурированного логирования)
    """
    # Создаем директорию для логов
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Настройка кодировки для stdout/stderr (Windows)
    try:
        if sys.platform == "win32" and hasattr(sys.stdout, 'detach'):
            try:
                sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")
                sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding="utf-8")
            except (AttributeError, ValueError):
                pass
    except Exception:
        pass
    
    # Создаем handlers
    handlers = []
    
    # File handler с ротацией по размеру
    try:
        max_bytes = rotation_size_mb * 1024 * 1024
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=rotation_backup_count,
            encoding='utf-8'
        )
        handlers.append(file_handler)
    except Exception as e:
        print(f"Warning: Could not create file handler: {e}")
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    handlers.append(console_handler)
    
    # Настройка форматирования
    if json_format:
        # JSON формат для структурированного логирования
        try:
            from pythonjsonlogger import jsonlogger
            formatter = jsonlogger.JsonFormatter(
                '%(asctime)s %(name)s %(levelname)s %(message)s',
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        except ImportError:
            # Fallback на обычный формат, если библиотека не установлена
            formatter = MSKFormatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
    else:
        formatter = MSKFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    for handler in handlers:
        handler.setFormatter(formatter)
    
    # Настройка root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Удаляем существующие handlers
    root_logger.handlers.clear()
    
    # Добавляем новые handlers
    for handler in handlers:
        root_logger.addHandler(handler)
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logger initialized. File: {log_file}, Level: {logging.getLevelName(level)}")
    return logger


def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Маскирует чувствительные данные в словаре для безопасного логирования.
    
    Args:
        data: Словарь с данными
        
    Returns:
        Словарь с замаскированными чувствительными данными
    """
    masked = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(sensitive in key_lower for sensitive in SENSITIVE_KEYS):
            if isinstance(value, str):
                if len(value) <= 8:
                    masked[key] = "***"
                else:
                    masked[key] = f"{value[:3]}***{value[-2:]}"
            else:
                masked[key] = "***"
        elif isinstance(value, dict):
            masked[key] = mask_sensitive_data(value)
        else:
            masked[key] = value
    return masked


def log_operation(logger: ContextLogger, operation_name: str):
    """
    Декоратор для логирования операций (старт, завершение, ошибки).
    
    Args:
        logger: ContextLogger
        operation_name: Название операции
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Получаем контекст из аргументов
            context = {}
            if args:
                # Пытаемся извлечь user_id, chat_id и т.д. из первого аргумента
                first_arg = args[0]
                if hasattr(first_arg, 'from_user') and hasattr(first_arg.from_user, 'id'):
                    context['user_id'] = first_arg.from_user.id
                    context['username'] = getattr(first_arg.from_user, 'username', None)
                if hasattr(first_arg, 'chat') and hasattr(first_arg.chat, 'id'):
                    context['chat_id'] = first_arg.chat.id
            
            logger.operation(f"{operation_name}", "started", context=context)
            try:
                result = await func(*args, **kwargs)
                logger.operation(f"{operation_name}", "completed", context=context)
                return result
            except Exception as e:
                logger.operation(f"{operation_name}", "failed", context=context, exc_info=True)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            context = {}
            if args:
                first_arg = args[0]
                if hasattr(first_arg, 'from_user') and hasattr(first_arg.from_user, 'id'):
                    context['user_id'] = first_arg.from_user.id
                    context['username'] = getattr(first_arg.from_user, 'username', None)
                if hasattr(first_arg, 'chat') and hasattr(first_arg.chat, 'id'):
                    context['chat_id'] = first_arg.chat.id
            
            logger.operation(f"{operation_name}", "started", context=context)
            try:
                result = func(*args, **kwargs)
                logger.operation(f"{operation_name}", "completed", context=context)
                return result
            except Exception as e:
                logger.operation(f"{operation_name}", "failed", context=context, exc_info=True)
                raise
        
        # Определяем, асинхронная ли функция
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
