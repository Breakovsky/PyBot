# main/modules/handlers/otrs_auth.py

"""
Модуль авторизации пользователей OTRS через email.
- Отправка кодов подтверждения на email
- Верификация кодов
- Хранение авторизованных пользователей
"""

import asyncio
import logging
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Tuple

from assets.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM_NAME, SMTP_USE_TLS, now_msk
)
from modules.handlers.monitor_db import get_db

logger = logging.getLogger(__name__)


def generate_code(length: int = 6) -> str:
    """Генерирует случайный код подтверждения."""
    return ''.join(random.choices(string.digits, k=length))


# Разрешённые домены для авторизации
ALLOWED_EMAIL_DOMAINS = ['meb52.com', 'tdegregor.ru', 'test.com']


def is_valid_email(email: str) -> bool:
    """Проверяет формат email."""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def is_allowed_domain(email: str) -> bool:
    """Проверяет, что домен email разрешён."""
    if not email or '@' not in email:
        return False
    domain = email.lower().split('@')[1]
    return domain in ALLOWED_EMAIL_DOMAINS


def get_allowed_domains_text() -> str:
    """Возвращает текст с разрешёнными доменами."""
    return ", ".join([f"@{d}" for d in ALLOWED_EMAIL_DOMAINS])


async def send_verification_email(email: str, code: str) -> bool:
    """
    Отправляет email с кодом верификации.
    Возвращает True при успехе, False при ошибке.
    """
    if not SMTP_HOST or not SMTP_USER:
        logger.warning("SMTP not configured, cannot send verification email")
        return False
    
    try:
        # Создаём сообщение
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Код подтверждения: {code}'
        msg['From'] = f'{SMTP_FROM_NAME} <{SMTP_USER}>'
        msg['To'] = email
        
        # Текстовая версия
        text_content = f"""
Ваш код подтверждения для авторизации в Telegram-боте OTRS:

{code}

Код действителен 10 минут.

Если вы не запрашивали этот код, проигнорируйте это письмо.
        """
        
        # HTML версия
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .code {{ font-size: 36px; font-weight: bold; color: #2196F3; text-align: center; letter-spacing: 8px; margin: 30px 0; padding: 20px; background: #f0f8ff; border-radius: 8px; }}
        .footer {{ color: #888; font-size: 12px; text-align: center; margin-top: 30px; }}
        h2 {{ color: #333; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>🔐 Код подтверждения</h2>
        <p>Вы запросили авторизацию в Telegram-боте OTRS.</p>
        <p>Ваш код подтверждения:</p>
        <div class="code">{code}</div>
        <p style="text-align:center; color:#666;">Код действителен <b>10 минут</b></p>
        <div class="footer">
            Если вы не запрашивали этот код, проигнорируйте это письмо.
        </div>
    </div>
</body>
</html>
        """
        
        msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # Отправляем в отдельном потоке, чтобы не блокировать asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_email_sync, msg, email)
        
        logger.info(f"Verification email sent to {email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {email}: {e}")
        return False


def _send_email_sync(msg: MIMEMultipart, to_email: str):
    """Синхронная отправка email (запускается в executor)."""
    import ssl
    
    # Порт 465 = SSL, порт 587 = STARTTLS
    if SMTP_PORT == 465:
        # SSL
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30, context=context)
    elif SMTP_USE_TLS:
        # STARTTLS
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.starttls()
    else:
        # Plain
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    
    if SMTP_PASSWORD:
        server.login(SMTP_USER, SMTP_PASSWORD)
    
    server.send_message(msg)
    server.quit()


class OTRSAuthManager:
    """Менеджер авторизации пользователей OTRS."""
    
    def __init__(self):
        self.db = get_db()
    
    def is_authenticated(self, telegram_id: int) -> bool:
        """Проверяет, авторизован ли пользователь."""
        user = self.db.get_otrs_user(telegram_id)
        return user is not None
    
    def get_user_email(self, telegram_id: int) -> Optional[str]:
        """Получает email авторизованного пользователя."""
        user = self.db.get_otrs_user(telegram_id)
        if user:
            return user.get('otrs_email')
        return None
    
    def get_user_info(self, telegram_id: int) -> Optional[dict]:
        """Получает полную информацию о пользователе."""
        return self.db.get_otrs_user(telegram_id)
    
    async def start_verification(self, telegram_id: int, email: str) -> Tuple[bool, str]:
        """
        Начинает процесс верификации email.
        Возвращает (success, message).
        """
        # Проверяем формат email
        if not is_valid_email(email):
            return False, "❌ Неверный формат email"
        
        # Генерируем код
        code = generate_code()
        
        # Сохраняем в БД
        self.db.save_verification_code(telegram_id, email, code, expires_minutes=10)
        
        # Отправляем email
        if await send_verification_email(email, code):
            return True, f"📧 Код отправлен на {email}\n\nВведите полученный код:"
        else:
            # Удаляем неиспользованную верификацию
            self.db.delete_verification(telegram_id)
            return False, "❌ Не удалось отправить email. Проверьте адрес и попробуйте снова."
    
    async def verify_code(self, telegram_id: int, code: str, telegram_username: str = None, 
                    telegram_full_name: str = None) -> Tuple[bool, str]:
        """
        Проверяет код верификации.
        Возвращает (success, message).
        """
        # Очищаем код от пробелов
        code = code.strip()
        
        # Проверяем код
        email = self.db.verify_code(telegram_id, code)
        
        if email:
            # Код верный! Пытаемся получить ФИО из MDaemon
            full_name = telegram_full_name  # По умолчанию используем из Telegram
            
            try:
                from modules.handlers.mdaemon_handler import get_mdaemon_client
                mdaemon_client = get_mdaemon_client()
                if mdaemon_client:
                    # Пробуем получить ФИО из MDaemon, но не критично если не получится
                    try:
                        mdaemon_user = await mdaemon_client.get_user_by_email(email)
                        if mdaemon_user and mdaemon_user.full_name:
                            full_name = mdaemon_user.full_name
                            logger.info(f"Retrieved full name from MDaemon for {email}: {full_name}")
                    except Exception as mdaemon_error:
                        # MDaemon недоступен или ошибка - не критично, используем Telegram имя
                        logger.debug(f"MDaemon unavailable for {email}: {mdaemon_error}")
            except ImportError:
                # Модуль MDaemon не настроен - это нормально
                logger.debug(f"MDaemon module not available")
            except Exception as e:
                logger.debug(f"Failed to get full name from MDaemon for {email}: {e}")
            
            # Сохраняем пользователя
            self.db.save_otrs_user(
                telegram_id=telegram_id,
                telegram_username=telegram_username or "",
                otrs_email=email,
                otrs_username=email.split('@')[0],  # Используем часть до @ как username
                full_name=full_name
            )
            return True, f"✅ Авторизация успешна!\n\nВаш email: {email}\n\nТеперь вы можете работать с заявками OTRS."
        else:
            # Проверяем, есть ли ожидающая верификация
            pending = self.db.get_verification(telegram_id)
            if pending:
                return False, "❌ Неверный код. Попробуйте ещё раз или запросите новый."
            else:
                return False, "❌ Код истёк. Пожалуйста, запросите новый код."
    
    def logout(self, telegram_id: int) -> str:
        """Выполняет выход из аккаунта OTRS."""
        if self.is_authenticated(telegram_id):
            self.db.delete_otrs_user(telegram_id)
            return "✅ Вы успешно вышли из аккаунта OTRS"
        else:
            return "ℹ️ Вы не были авторизованы"
    
    def has_pending_verification(self, telegram_id: int) -> bool:
        """Проверяет, есть ли ожидающая верификация."""
        return self.db.get_verification(telegram_id) is not None
    
    def cancel_verification(self, telegram_id: int):
        """Отменяет ожидающую верификацию."""
        self.db.delete_verification(telegram_id)


# Глобальный экземпляр
_auth_manager: Optional[OTRSAuthManager] = None


def get_auth_manager() -> OTRSAuthManager:
    """Возвращает менеджер авторизации."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = OTRSAuthManager()
    return _auth_manager

