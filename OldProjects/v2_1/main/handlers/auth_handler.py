"""
Обработчик авторизации пользователей через email.
Использует FSM для управления состоянием авторизации.
"""

import asyncio
import logging
import random
import string
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database.connection import get_db_pool
from config.settings import get_settings
from config.security import get_security_manager

logger = logging.getLogger(__name__)

# Часовой пояс MSK (UTC+3)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# Разрешённые домены для авторизации
ALLOWED_EMAIL_DOMAINS = ['meb52.com', 'tdegregor.ru', 'test.com']


class AuthStates(StatesGroup):
    """Состояния FSM для авторизации."""
    waiting_email = State()
    waiting_code = State()


def generate_code(length: int = 6) -> str:
    """Генерирует случайный код подтверждения."""
    return ''.join(random.choices(string.digits, k=length))


def is_valid_email(email: str) -> bool:
    """Проверяет формат email."""
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
    import os
    security = get_security_manager()
    settings = get_settings()
    
    # Читаем все настройки SMTP из БД
    smtp_host = await settings.get("SMTP_HOST", "")
    smtp_port_str = await settings.get("SMTP_PORT", "587")
    smtp_port = int(smtp_port_str) if smtp_port_str else 587
    smtp_user = await settings.get("SMTP_USER", "")
    smtp_from_name = await settings.get("SMTP_FROM_NAME", "TBot")
    smtp_use_tls_str = await settings.get("SMTP_USE_TLS", "true")
    # Для порта 465 используется SSL (не TLS), для 587 - STARTTLS (TLS)
    # Если порт 465, то автоматически используем SSL (smtp_use_tls = false)
    if smtp_port == 465:
        smtp_use_tls = False
    else:
        smtp_use_tls = smtp_use_tls_str.lower() == "true" if isinstance(smtp_use_tls_str, str) else bool(smtp_use_tls_str)
    
    # Только пароль читаем из Windows Credential Manager или .env (секрет)
    smtp_password = security.get_secret("SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")
    
    if not smtp_host or not smtp_user:
        logger.warning("SMTP not configured, cannot send verification email")
        return False
    
    try:
        # Создаём сообщение
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Код подтверждения: {code}'
        msg['From'] = f'{smtp_from_name} <{smtp_user}>'
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
        await loop.run_in_executor(None, _send_email_sync, msg, email, smtp_host, smtp_port, smtp_user, smtp_password, smtp_use_tls)
        
        logger.info(f"Verification email sent to {email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {email}: {e}")
        return False


def _send_email_sync(msg: MIMEMultipart, to_email: str, smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str, smtp_use_tls: bool):
    """Синхронная отправка email (запускается в executor)."""
    import ssl
    
    # Порт 465 = SSL, порт 587 = STARTTLS
    if smtp_port == 465:
        # SSL
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context)
    elif smtp_use_tls:
        # STARTTLS
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        server.starttls()
    else:
        # Plain
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
    
    if smtp_password:
        server.login(smtp_user, smtp_password)
    
    server.send_message(msg)
    server.quit()


class AuthHandler:
    """Обработчик авторизации пользователей."""
    
    def __init__(self, db_pool, bot: Bot, otrs_handler=None):
        """
        Инициализирует обработчик авторизации.
        
        Args:
            db_pool: Пул соединений с БД
            bot: Экземпляр бота
            otrs_handler: Обработчик OTRS (опционально)
        """
        self.db_pool = db_pool
        self.bot = bot
        self.otrs_handler = otrs_handler
        self.storage = MemoryStorage()  # FSM storage
        self.auth_states = {}  # Временное хранилище состояний: user_id -> state
    
    async def is_authenticated(self, telegram_id: int) -> bool:
        """Проверяет, авторизован ли пользователь."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT otrs.otrs_users.id 
                FROM otrs.otrs_users
                JOIN telegram.telegram_users ON otrs.otrs_users.telegram_user_id = telegram.telegram_users.id
                WHERE telegram.telegram_users.telegram_id = $1
                """,
                telegram_id
            )
            return row is not None
    
    async def get_user_info(self, telegram_id: int) -> Optional[dict]:
        """Получает полную информацию о пользователе."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 
                    tu.telegram_id,
                    tu.telegram_username,
                    ou.otrs_email,
                    ou.otrs_username,
                    tu.full_name,
                    ou.verified_at
                FROM telegram.telegram_users tu
                JOIN otrs.otrs_users ou ON ou.telegram_user_id = tu.id
                WHERE tu.telegram_id = $1
                """,
                telegram_id
            )
            if row:
                return dict(row)
            return None
    
    async def start_verification(self, telegram_id: int, email: str) -> Tuple[bool, str]:
        """
        Начинает процесс верификации email.
        Возвращает (success, message).
        """
        # Проверяем формат email
        if not is_valid_email(email):
            return False, "❌ Неверный формат email"
        
        # Проверяем домен
        if not is_allowed_domain(email):
            allowed = get_allowed_domains_text()
            return False, f"❌ Домен email не разрешён. Используйте корпоративную почту ({allowed})"
        
        # Генерируем код
        code = generate_code()
        
        # Сохраняем в БД
        expires_at = datetime.now(MSK_TIMEZONE) + timedelta(minutes=10)
        async with self.db_pool.acquire() as conn:
            # Удаляем старую верификацию
            await conn.execute(
                """
                DELETE FROM telegram.verification_codes
                WHERE telegram_id = $1
                """,
                telegram_id
            )
            
            # Сохраняем новую
            await conn.execute(
                """
                INSERT INTO telegram.verification_codes (telegram_id, email, code, expires_at)
                VALUES ($1, $2, $3, $4)
                """,
                telegram_id, email, code, expires_at
            )
        
        # Отправляем email
        if await send_verification_email(email, code):
            return True, f"📧 Код отправлен на {email}\n\nВведите полученный код:"
        else:
            # Удаляем неиспользованную верификацию
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    DELETE FROM telegram.verification_codes
                    WHERE telegram_id = $1
                    """,
                    telegram_id
                )
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
        now = datetime.now(MSK_TIMEZONE)
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT email FROM telegram.verification_codes
                WHERE telegram_id = $1 AND code = $2 AND expires_at > $3
                """,
                telegram_id, code, now
            )
            
            if not row:
                # Проверяем, есть ли ожидающая верификация
                pending = await conn.fetchrow(
                    """
                    SELECT email FROM telegram.verification_codes
                    WHERE telegram_id = $1
                    """,
                    telegram_id
                )
                if pending:
                    return False, "❌ Неверный код. Попробуйте ещё раз или запросите новый."
                else:
                    return False, "❌ Код истёк. Пожалуйста, запросите новый код."
            
            email = row['email']
            
            # Удаляем использованный код
            await conn.execute(
                """
                DELETE FROM telegram.verification_codes
                WHERE telegram_id = $1
                """,
                telegram_id
            )
            
            # Сохраняем пользователя
            otrs_username = email.split('@')[0]  # Используем часть до @ как username
            verified_at = now
            
            # Сначала создаем или получаем запись в telegram_users
            telegram_user_row = await conn.fetchrow(
                """
                INSERT INTO telegram.telegram_users (telegram_id, telegram_username, full_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    telegram_username = EXCLUDED.telegram_username,
                    full_name = EXCLUDED.full_name
                RETURNING id
                """,
                telegram_id, telegram_username or "", telegram_full_name or ""
            )
            
            if not telegram_user_row:
                # Если не получили ID, пытаемся получить существующую запись
                telegram_user_row = await conn.fetchrow(
                    "SELECT id FROM telegram.telegram_users WHERE telegram_id = $1",
                    telegram_id
                )
            
            if telegram_user_row:
                telegram_user_id = telegram_user_row['id']
                
                # Теперь создаем или обновляем запись в otrs_users
                await conn.execute(
                    """
                    INSERT INTO otrs.otrs_users (
                        telegram_user_id, otrs_email, otrs_username, verified_at
                    ) VALUES ($1, $2, $3, $4)
                    ON CONFLICT (telegram_user_id) DO UPDATE SET
                        otrs_email = EXCLUDED.otrs_email,
                        otrs_username = EXCLUDED.otrs_username,
                        verified_at = EXCLUDED.verified_at
                    """,
                    telegram_user_id, email, otrs_username, verified_at
                )
        
        return True, f"✅ Авторизация успешна!\n\nВаш email: {email}\n\nТеперь вы можете работать с заявками OTRS."
    
    async def logout(self, telegram_id: int) -> str:
        """Выполняет выход из аккаунта OTRS."""
        if await self.is_authenticated(telegram_id):
            async with self.db_pool.acquire() as conn:
                # Получаем telegram_user_id
                telegram_user_row = await conn.fetchrow(
                    "SELECT id FROM telegram.telegram_users WHERE telegram_id = $1",
                    telegram_id
                )
                if telegram_user_row:
                    telegram_user_id = telegram_user_row['id']
                    await conn.execute(
                        """
                        DELETE FROM otrs.otrs_users
                        WHERE telegram_user_id = $1
                        """,
                        telegram_user_id
                    )
            return "✅ Вы успешно вышли из аккаунта OTRS"
        else:
            return "ℹ️ Вы не были авторизованы"
    
    async def has_pending_verification(self, telegram_id: int) -> bool:
        """Проверяет, есть ли ожидающая верификация."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT telegram_id FROM telegram.verification_codes
                WHERE telegram_id = $1
                """,
                telegram_id
            )
            return row is not None
    
    async def cancel_verification(self, telegram_id: int):
        """Отменяет ожидающую верификацию."""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM telegram.verification_codes
                WHERE telegram_id = $1
                """,
                telegram_id
            )
    
    async def handle_start(self, message: Message):
        """Обработчик команды /start в личных сообщениях."""
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.storage.memory import MemoryStorage
        
        user_id = message.from_user.id
        user_name = message.from_user.full_name or message.from_user.first_name
        
        # Проверяем, авторизован ли пользователь
        if await self.is_authenticated(user_id):
            # Показываем лобби
            await self.show_lobby(message, user_id)
        else:
            # Показываем форму авторизации
            text = (
                f"<b>Здравствуйте, {user_name}!</b>👋\n"
                f"\n"
                f"Я бот технической поддержки ГК \"МОБИ\".\n"
                f"\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"🔐 <b>Пожалуйста, авторизуйтесь в системе заявок!</b>"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Авторизоваться", callback_data="auth_start")]
            ])
            
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    
    async def show_lobby(self, message: Message, user_id: int):
        """Показывает главное меню (лобби) для авторизованного пользователя."""
        user_info = await self.get_user_info(user_id)
        if not user_info:
            return
        
        user_name = message.from_user.full_name or message.from_user.first_name
        email = user_info.get('otrs_email', 'Unknown')
        
        text = (
            f"👋 <b>Здравствуйте, {user_name}!</b>\n\n"
            f"✅ Вы авторизованы в системе заявок\n"
            f"📧 Email: <code>{email}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 <b>Выберите действие:</b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Моя статистика", callback_data="lobby_mystats")],
            [InlineKeyboardButton(text="📈 Еженедельный отчёт", callback_data="lobby_report")],
            [InlineKeyboardButton(text="✅ Статус авторизации", callback_data="lobby_status")]
        ])
        
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    
    async def handle_callback(self, callback: CallbackQuery):
        """Обработчик callback queries для авторизации."""
        from aiogram.fsm.context import FSMContext
        
        data = callback.data
        user_id = callback.from_user.id
        
        if data == "auth_start":
            await callback.answer()
            user_name = callback.from_user.full_name or callback.from_user.first_name
            await callback.message.edit_text(
                f"<b>Здравствуйте, {user_name}!</b>👋\n"
                f"\n"
                f"Я бот технической поддержки ГК \"МОБИ\".\n"
                f"\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"🔐 <b>Авторизация в системе заявок</b>\n"
                f"\n"
                f"<i>Отправьте ваш корпоративный email адрес:</i>",
                parse_mode="HTML",
                reply_markup=None
            )
            # Устанавливаем состояние ожидания email
            self.auth_states[user_id] = "waiting_email"
        
        elif data == "auth_change_email":
            await callback.answer()
            user_name = callback.from_user.full_name or callback.from_user.first_name
            # Отменяем текущую верификацию
            if await self.has_pending_verification(user_id):
                await self.cancel_verification(user_id)
            # Возвращаем к вводу email
            self.auth_states[user_id] = "waiting_email"
            await callback.message.edit_text(
                f"<b>Здравствуйте, {user_name}!</b>👋\n"
                f"\n"
                f"Я бот технической поддержки ГК \"МОБИ\".\n"
                f"\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"🔐 <b>Авторизация в системе заявок</b>\n"
                f"\n"
                f"<i>Отправьте ваш корпоративный email адрес:</i>",
                parse_mode="HTML",
                reply_markup=None
            )
        
        elif data == "lobby_back":
            await callback.answer()
            await self.show_lobby(callback.message, user_id)
        
        elif data == "lobby_status":
            await callback.answer()
            user_info = await self.get_user_info(user_id)
            if user_info:
                email = user_info.get('otrs_email', 'Unknown')
                verified_at = user_info.get('verified_at', 'Unknown')
                user_name = callback.from_user.full_name or callback.from_user.first_name
                
                text = (
                    f"✅ <b>Статус авторизации</b>\n\n"
                    f"👤 {user_name}\n"
                    f"📧 <code>{email}</code>\n"
                    f"🕐 Авторизован: {verified_at}"
                )
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
                ])
                
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        
        elif data == "lobby_mystats":
            await callback.answer("📊 Загружаю статистику...")
            
            # Получаем статистику из OTRSHandler
            if not self.otrs_handler:
                from handlers.otrs_handler import OTRSHandler
                self.otrs_handler = OTRSHandler(self.db_pool, self.bot)
            
            stats = await self.otrs_handler.get_user_stats(user_id)
            
            if stats:
                user_name = callback.from_user.full_name or callback.from_user.first_name
                user_info = await self.get_user_info(user_id)
                email = user_info.get('otrs_email', 'Unknown') if user_info else 'Unknown'
                
                text = (
                    f"📊 <b>Ваша статистика OTRS</b>\n\n"
                    f"👤 {user_name}\n"
                    f"📧 {email}\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ Закрыто заявок: <b>{stats.get('closed', 0)}</b>\n"
                    f"❌ Отклонено: <b>{stats.get('rejected', 0)}</b>\n"
                    f"👤 Взято в работу: <b>{stats.get('assigned', 0)}</b>\n"
                    f"💬 Комментариев: <b>{stats.get('commented', 0)}</b>\n\n"
                    f"📈 <b>Всего действий: {stats.get('total', 0)}</b>"
                )
            else:
                text = "📊 <b>Ваша статистика OTRS</b>\n\n❌ Статистика недоступна."
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
            ])
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        
        elif data == "lobby_report":
            await callback.answer("📈 Загружаю отчёт...")
            
            # Получаем еженедельный отчёт (используем логику из cmd_report)
            from datetime import timedelta
            today = datetime.now(MSK_TIMEZONE).date()
            days_since_monday = today.weekday()  # 0 = понедельник
            last_monday = today - timedelta(days=days_since_monday + 7)
            last_sunday = last_monday + timedelta(days=6)
            
            start_date = datetime.combine(last_monday, datetime.min.time())
            end_date = datetime.combine(last_sunday, datetime.max.time())
            start_date = start_date.replace(tzinfo=MSK_TIMEZONE)
            end_date = end_date.replace(tzinfo=MSK_TIMEZONE)
            
            async with self.db_pool.acquire() as conn:
                # Статистика по пользователям
                user_stats_rows = await conn.fetch("""
                    SELECT 
                        tu.telegram_id,
                        tu.telegram_username,
                        ou.otrs_email,
                        om.action_type,
                        COUNT(*) as count
                    FROM otrs.otrs_metrics om
                    JOIN telegram.telegram_users tu ON om.telegram_user_id = tu.id
                    LEFT JOIN otrs.otrs_users ou ON ou.telegram_user_id = tu.id
                    WHERE om.action_time >= $1 AND om.action_time <= $2
                    GROUP BY tu.telegram_id, tu.telegram_username, ou.otrs_email, om.action_type
                    ORDER BY count DESC
                """, start_date, end_date)
                
                # Общая статистика
                totals_row = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) FILTER (WHERE action_type = 'closed') as closed,
                        COUNT(*) FILTER (WHERE action_type = 'rejected') as rejected,
                        COUNT(*) FILTER (WHERE action_type = 'assigned') as assigned,
                        COUNT(*) FILTER (WHERE action_type = 'commented') as commented,
                        COUNT(*) as total
                    FROM otrs.otrs_metrics
                    WHERE action_time >= $1 AND action_time <= $2
                """, start_date, end_date)
            
            # Формируем отчёт
            start_str = start_date.strftime('%d.%m.%Y')
            end_str = end_date.strftime('%d.%m.%Y')
            
            text_parts = [
                "📊 <b>ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ OTRS</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━",
                "",
                f"📅 Период: <b>{start_str} — {end_str}</b>",
                ""
            ]
            
            # Общая статистика
            totals = {
                'closed': totals_row['closed'] if totals_row else 0,
                'rejected': totals_row['rejected'] if totals_row else 0,
                'assigned': totals_row['assigned'] if totals_row else 0,
                'commented': totals_row['commented'] if totals_row else 0,
                'total': totals_row['total'] if totals_row else 0,
            }
            
            text_parts.extend([
                "📈 <b>Общая статистика:</b>",
                "┌─────────────────────",
                f"│ ✅ Закрыто:     <b>{totals['closed']}</b>",
                f"│ ❌ Отклонено:   <b>{totals['rejected']}</b>",
                f"│ 👤 Назначено:   <b>{totals['assigned']}</b>",
                f"│ 💬 Комментариев: <b>{totals['commented']}</b>",
                "└─────────────────────",
                f"📊 Всего действий: <b>{totals['total']}</b>",
                ""
            ])
            
            # Собираем статистику по пользователям
            user_stats = {}
            for row in user_stats_rows:
                uid = row['telegram_id']
                if uid not in user_stats:
                    user_stats[uid] = {
                        'username': row['telegram_username'] or 'Unknown',
                        'closed': 0,
                        'rejected': 0,
                        'commented': 0,
                    }
                action_type = row['action_type']
                count = row['count']
                if action_type in user_stats[uid]:
                    user_stats[uid][action_type] = count
            
            # Сортируем по закрытым заявкам
            sorted_users = sorted(
                user_stats.values(),
                key=lambda x: (x['closed'], x.get('total', 0)),
                reverse=True
            )
            
            # Топ по закрытым заявкам
            if sorted_users:
                text_parts.append("🏆 <b>Рейтинг по закрытым заявкам:</b>")
                text_parts.append("")
                medals = ['🥇', '🥈', '🥉']
                
                for i, user in enumerate(sorted_users[:10]):
                    if user['closed'] == 0:
                        continue
                    
                    if i < 3:
                        medal = medals[i]
                    else:
                        medal = f"  {i+1}."
                    
                    name = user['username']
                    if len(name) > 15:
                        name = name[:12] + "..."
                    
                    details = []
                    if user['closed'] > 0:
                        details.append(f"✅{user['closed']}")
                    if user['rejected'] > 0:
                        details.append(f"❌{user['rejected']}")
                    if user['commented'] > 0:
                        details.append(f"💬{user['commented']}")
                    
                    details_str = " ".join(details)
                    text_parts.append(f"{medal} <b>{name}</b>: {details_str}")
                
                if not any(u['closed'] > 0 for u in sorted_users):
                    text_parts.append("   <i>Нет закрытых заявок за период</i>")
            else:
                text_parts.append("📭 <i>Нет данных за указанный период</i>")
            
            text_parts.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━",
                "🤖 <i>Автоматический отчёт Telegram Bot</i>"
            ])
            
            text = "\n".join(text_parts)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
            ])
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    
    async def handle_text_message(self, message: Message):
        """Обработчик текстовых сообщений для авторизации."""
        if message.chat.type != "private":
            return
        
        user_id = message.from_user.id
        text = message.text.strip()
        
        # Проверяем состояние авторизации
        state = self.auth_states.get(user_id)
        
        if state:
            
            if state == "waiting_email":
                # Ожидаем email
                if is_valid_email(text) and is_allowed_domain(text):
                    # Удаляем сообщение пользователя
                    try:
                        await self.bot.delete_message(message.chat.id, message.message_id)
                    except:
                        pass
                    
                    # Начинаем верификацию
                    success, result_msg = await self.start_verification(user_id, text)
                    
                    if success:
                        # Обновляем состояние на ожидание кода
                        self.auth_states[user_id] = "waiting_code"
                        
                        # Редактируем сообщение
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📧 Изменить email", callback_data="auth_change_email")]
                        ])
                        
                        await message.answer(
                            f"📧 {message.from_user.first_name}, ваш код был отправлен на:\n"
                            f"<code>{text}</code>\n\n"
                            f"<i>Введите полученный код:</i>",
                            parse_mode="HTML",
                            reply_markup=keyboard
                        )
                    else:
                        await message.answer(result_msg, parse_mode="HTML")
                else:
                    # Неверный email - удаляем сообщение
                    try:
                        await self.bot.delete_message(message.chat.id, message.message_id)
                    except:
                        pass
            
            elif state == "waiting_code":
                # Ожидаем код
                if text.isdigit() and len(text) == 6:
                    # Удаляем сообщение пользователя
                    try:
                        await self.bot.delete_message(message.chat.id, message.message_id)
                    except:
                        pass
                    
                    # Проверяем код
                    success, result_msg = await self.verify_code(
                        user_id, text,
                        message.from_user.username,
                        message.from_user.full_name
                    )
                    
                    if success:
                        # Удаляем состояние
                        self.auth_states.pop(user_id, None)
                        
                        # Показываем лобби
                        await self.show_lobby(message, user_id)
                    else:
                        await message.answer(result_msg, parse_mode="HTML")
                else:
                    # Неверный формат кода
                    try:
                        await self.bot.delete_message(message.chat.id, message.message_id)
                    except:
                        pass
                    
                    await message.answer(
                        "❌ <b>Неверный формат кода</b>\n\n"
                        "Код должен состоять из 6 цифр.\n"
                        "Проверьте письмо на вашей почте.\n\n"
                        "<i>Введите полученный код:</i>",
                        parse_mode="HTML"
                    )
        else:
            # Пользователь не в процессе авторизации - удаляем сообщение
            if not await self.is_authenticated(user_id):
                try:
                    await self.bot.delete_message(message.chat.id, message.message_id)
                except:
                    pass
