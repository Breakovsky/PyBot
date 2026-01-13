import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

from utils.logger import setup_logger
from assets.config import (
    TOKEN,
    SUPERCHAT_TOKEN,
    BOT_TOPIC_ID,
    PING_TOPIC_ID,
    EXCEL_TOPIC_ID,
    EXCEL_PASSWORD,
    EXCEL_FILE_PATH,
    IP_ADDRESSES_PATH,
    BOT_STARTUP_MESSAGE,
    ALLOWED_THREADS,
    METRICS_TOPIC_ID,
    TASKS_TOPIC_ID,
    OTRS_URL,
    now_msk
)

from utils.formatters import escape_markdown_v2, escape_markdown_v2_advanced
from modules.handlers.monitor_handler import start_monitoring, stop_monitoring, get_monitor
from modules.handlers.monitor_db import get_db
from modules.handlers.otrs_handler import (
    start_otrs_integration, stop_otrs_integration, 
    get_otrs_manager, get_otrs_client
)
from modules.handlers.otrs_auth import (
    get_auth_manager, is_valid_email, is_allowed_domain, get_allowed_domains_text
)

USER_MESSAGE_DELETE_DELAY = 30
MONITOR_CHECK_INTERVAL = 30  # Интервал проверки серверов (секунды)
BOT_MESSAGE_DELETE_DELAY = 600
BUTTON_MESSAGE_DELETE_DELAY = 0
UPTIME_NEW_MESSAGE_DELETE_DELAY = 10
EXCEL_MESSAGE_DELETE_DELAY = 300  # 5 минут для сообщений в Excel топике

logger = logging.getLogger(__name__)

BOT_START_TIME: datetime | None = None

# Используем DefaultBotProperties для установки parse_mode по умолчанию
default_bot_properties = DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
bot = Bot(token=TOKEN, default=default_bot_properties)
dp = Dispatcher(bot=bot)

# Глобальная переменная для отслеживания доступности чата
_chat_availability_cache: Dict[int, Tuple[bool, datetime]] = {}  # chat_id -> (is_available, last_check)


async def check_chat_availability(chat_id: int) -> bool:
    """
    Проверяет доступность чата для бота.
    Возвращает True если чат доступен, False если нет.
    Использует кэш на 5 минут.
    """
    from datetime import timedelta
    
    # Проверяем кэш
    if chat_id in _chat_availability_cache:
        is_available, last_check = _chat_availability_cache[chat_id]
        if now_msk() - last_check < timedelta(minutes=5):
            return is_available
    
    # Проверяем доступность чата
    try:
        chat = await bot.get_chat(chat_id)
        is_available = True
        logger.debug(f"Chat {chat_id} is available: {chat.title if hasattr(chat, 'title') else 'N/A'}")
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower() or "chat_id is empty" in str(e).lower():
            is_available = False
            logger.warning(f"Chat {chat_id} is not available: {e}")
        else:
            # Другие ошибки - считаем чат доступным (может быть временная проблема)
            is_available = True
            logger.warning(f"Error checking chat {chat_id}: {e}")
    except Exception as e:
        # Неизвестная ошибка - считаем чат доступным
        is_available = True
        logger.warning(f"Unexpected error checking chat {chat_id}: {e}")
    
    # Обновляем кэш
    _chat_availability_cache[chat_id] = (is_available, now_msk())
    return is_available


def is_chat_not_found_error(error: Exception) -> bool:
    """Проверяет, является ли ошибка ошибкой 'chat not found'."""
    error_str = str(error).lower()
    return (
        "chat not found" in error_str or
        "chat_id is empty" in error_str or
        "bad request: chat not found" in error_str
    )

# Хранилище ID главных сообщений для каждого пользователя (для динамического редактирования)
user_main_messages: Dict[int, int] = {}  # user_id -> message_id

# Флаги для защиты от гонок при создании сообщений
message_creation_in_progress: Dict[int, bool] = {}  # user_id -> bool

# Флаги, что пользователь нажал кнопку "Авторизоваться"
user_auth_button_pressed: Dict[int, bool] = {}  # user_id -> bool (True если кнопка нажата)

async def delete_message_later(chat_id: int, message_id: int, delay: int, topic_id: int | None = None):
    """
    Удаляет сообщение через `delay` секунд, если тема разрешена.
    """
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        if topic_id is None:
            logger.debug(f"Skipping deletion of message ID={message_id}, topic_id=None.")
            return
        if topic_id not in ALLOWED_THREADS:
            logger.debug(f"Topic {topic_id} not in ALLOWED_THREADS, skipping deletion of message ID={message_id}.")
            return
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted message ID={message_id} in chat ID={chat_id}, topic {topic_id}.")
        
        # Удаляем из БД если было в очереди
        try:
            db = get_db()
            db.remove_pending_deletion(chat_id, message_id)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error deleting message ID={message_id} in chat ID={chat_id}, topic {topic_id}: {e}")

async def delete_private_message_later(chat_id: int, message_id: int, delay: int):
    """
    Удаляет сообщение в личном чате через `delay` секунд.
    """
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.debug(f"Deleted private message ID={message_id} in chat ID={chat_id}")
    except Exception as e:
        logger.debug(f"Error deleting private message ID={message_id} in chat ID={chat_id}: {e}")

async def send_message_with_deletion(chat_id: int, text: str, delay: int = BOT_MESSAGE_DELETE_DELAY, topic_id: int | None = None):
    """
    Отправляет сообщение и планирует его удаление через `delay` секунд.
    """
    # Проверяем доступность чата перед отправкой
    if not await check_chat_availability(chat_id):
        logger.error(f"Cannot send message: chat {chat_id} is not available. Bot may not be in the chat or chat was deleted.")
        return None
    
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            message_thread_id=topic_id,
            parse_mode='MarkdownV2'
        )
        logger.info(f"Sent message ID={msg.message_id} in chat ID={chat_id}, topic ID={topic_id}.")
        asyncio.create_task(delete_message_later(chat_id, msg.message_id, delay, topic_id=topic_id))
        return msg
    except TelegramBadRequest as e:
        if is_chat_not_found_error(e):
            logger.error(f"Cannot send message: chat {chat_id} not found. Bot may not be in the chat or chat was deleted.")
            # Обновляем кэш
            _chat_availability_cache[chat_id] = (False, now_msk())
        else:
            logger.error(f"Bad request sending message to chat ID={chat_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error sending message to chat ID={chat_id}: {e}")
        return None

@dp.message(Command(commands=['start']))
async def cmd_start(message: Message):
    """
    Обработчик команды /start.
    В личных сообщениях - показывает меню авторизации или главное меню.
    В группах - стандартное приветствие.
    """
    # Проверяем, это личное сообщение или группа
    if message.chat.type == "private":
        auth_manager = get_auth_manager()
        user_name = message.from_user.full_name or message.from_user.first_name
        
        if auth_manager.is_authenticated(message.from_user.id):
            # Пользователь авторизован - показываем соответствующее меню
            user_info = auth_manager.get_user_info(message.from_user.id)
            email = user_info.get('otrs_email', 'Unknown')
            
            # Проверяем, является ли пользователь агентом OTRS
            client = get_otrs_client()
            is_agent = False
            if client:
                try:
                    otrs_login = await client.get_agent_login_by_email(email)
                    is_agent = otrs_login is not None
                except Exception as e:
                    logger.warning(f"Failed to check if user is agent: {e}")
            
            if is_agent:
                # Агент OTRS - показываем лобби с кнопками
                await show_lobby(message.from_user.id, message.chat.id, user_name, email)
            else:
                # Обычный пользователь - показываем меню для создания заявок
                # TODO: Получить ФИО из MDaemon
                full_name = user_info.get('full_name') or user_name
                
                from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
                
                keyboard = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="📝 Написать заявку")],
                        [KeyboardButton(text="📋 Посмотреть мои заявки")]
                    ],
                    resize_keyboard=True
                )
                
                text = (
                    f"Здравствуйте, {full_name}!👋\n"
                    f"Я бот технической поддержки ГК 'Компания'.\n"
                    f"\n"
                    f"Выберите действие:"
                )
                await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            # Не авторизован - показываем приветствие с кнопкой авторизации
            user_id = message.from_user.id
            
            # Очищаем старую верификацию и сбрасываем флаги при /start
            auth_manager = get_auth_manager()
            if auth_manager.has_pending_verification(user_id):
                auth_manager.cancel_verification(user_id)
                logger.debug(f"Cancelled pending verification for user {user_id} on /start")
            user_auth_button_pressed.pop(user_id, None)
            
            # Проверяем, не создаётся ли уже сообщение для этого пользователя (защита от гонок)
            if message_creation_in_progress.get(user_id):
                logger.debug(f"Message creation already in progress for user {user_id}, ignoring duplicate /start")
                return
            
            # Проверяем, есть ли уже главное сообщение у пользователя
            existing_msg_id = user_main_messages.get(user_id)
            if existing_msg_id:
                # Устанавливаем флаг перед редактированием (защита от гонок)
                message_creation_in_progress[user_id] = True
                try:
                    # Пытаемся проверить, существует ли сообщение и отредактировать его
                    text = (
                        f"<b>Здравствуйте, {user_name}!</b>👋\n"
                        f"\n"
                        f"Я бот технической поддержки ГК \"МОБИ\".\n"
                        f"\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"\n"
                        f"🔐 <b>Пожалуйста, авторизуйтесь в системе заявок!</b>"
                    )
                    
                    # Создаём кнопку "Авторизоваться"
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔐 Авторизоваться", callback_data="start_auth")]
                    ])
                    
                    # Пытаемся отредактировать существующее сообщение
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=existing_msg_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                    # Сообщение успешно отредактировано - выходим, не создаём новое
                    logger.debug(f"Edited existing start message (ID={existing_msg_id}) for user {user_id}")
                    logger.info(f"/start command in private chat from user ID={user_id} (edited existing message)")
                    return
                except Exception as e:
                    # Сообщение не существует или не может быть отредактировано - удаляем из кеша
                    logger.debug(f"Could not edit existing message (ID={existing_msg_id}): {e}, will create new one")
                    del user_main_messages[user_id]
                finally:
                    # Снимаем флаг создания сообщения
                    message_creation_in_progress.pop(user_id, None)
            
            # Устанавливаем флаг, что создание сообщения началось
            message_creation_in_progress[user_id] = True
            
            try:
                # Создаём новое сообщение
                text = (
                    f"<b>Здравствуйте, {user_name}!</b>👋\n"
                    f"\n"
                    f"Я бот технической поддержки ГК \"МОБИ\".\n"
                    f"\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"\n"
                    f"🔐 <b>Пожалуйста, авторизуйтесь в системе заявок!</b>"
                )
                
                # Создаём кнопку "Авторизоваться"
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔐 Авторизоваться", callback_data="start_auth")]
                ])
                
                sent_msg = await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
                # Сохраняем ID сообщения для дальнейшего редактирования
                user_main_messages[user_id] = sent_msg.message_id
                logger.debug(f"Created new start message (ID={sent_msg.message_id}) for user {user_id}")
                logger.info(f"/start command in private chat from user ID={user_id}")
            finally:
                # Снимаем флаг создания сообщения
                message_creation_in_progress.pop(user_id, None)
        
        return
    
    # Группа - стандартное поведение
    greeting = "Привет! Я бот, готовый к работе."
    escaped_greeting = escape_markdown_v2_advanced(greeting)
    sent = await message.answer(escaped_greeting, parse_mode='MarkdownV2')
    logger.info(f"/start command from user ID={message.from_user.id}.")

    # Планируем удаление сообщений
    tasks = [
        (message.chat.id, message.message_id, USER_MESSAGE_DELETE_DELAY, message.message_thread_id),
        (sent.chat.id, sent.message_id, BOT_MESSAGE_DELETE_DELAY, sent.message_thread_id)
    ]
    for chat_id, msg_id, delay, topic_id in tasks:
        asyncio.create_task(delete_message_later(chat_id, msg_id, delay, topic_id=topic_id))


@dp.message(Command(commands=['logout']))
async def cmd_logout(message: Message):
    """Выход из аккаунта OTRS (только в личных сообщениях)."""
    if message.chat.type != "private":
        return
    
    auth_manager = get_auth_manager()
    user_name = message.from_user.full_name or message.from_user.first_name
    
    if auth_manager.is_authenticated(message.from_user.id):
        auth_manager.logout(message.from_user.id)
        await message.answer(
            f"👋 <b>До свидания, {user_name}!</b>\n\n"
            f"Вы вышли из системы заявок.\n\n"
            f"Для повторной авторизации отправьте корпоративный email.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "ℹ️ Вы не авторизованы.",
            parse_mode="HTML"
        )


async def show_lobby(user_id: int, chat_id: int = None, user_name: str = None, email: str = None):
    """Показывает главное сообщение лобби с кнопками для агента."""
    auth_manager = get_auth_manager()
    
    if not user_name or not email:
        user_info = auth_manager.get_user_info(user_id)
        if not user_info:
            return None
        
        user_name = user_info.get('telegram_full_name') or f"User {user_id}"
        email = user_info.get('otrs_email', 'Unknown')
    
    if chat_id is None:
        chat_id = user_id  # По умолчанию личный чат
    
    text = (
        f"👋 <b>Здравствуйте, {user_name}!</b>\n\n"
        f"✅ Вы авторизованы в системе заявок\n"
        f"📧 Email: <code>{email}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 <b>Выберите действие:</b>"
    )
    
    # Создаём кнопки
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="lobby_mystats")],
        [InlineKeyboardButton(text="📈 Еженедельный отчёт", callback_data="lobby_report")],
        [InlineKeyboardButton(text="✅ Статус авторизации", callback_data="lobby_status")]
    ])
    
    main_msg_id = user_main_messages.get(user_id)
    
    if main_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=main_msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return main_msg_id
        except Exception as e:
            logger.debug(f"Could not edit lobby message: {e}")
            # Если не удалось отредактировать - создаём новое
            del user_main_messages[user_id]
    
    # Создаём новое сообщение
    sent_msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    user_main_messages[user_id] = sent_msg.message_id
    return sent_msg.message_id


@dp.message(Command(commands=['status']))
async def cmd_status(message: Message):
    """Проверка статуса авторизации OTRS (только в личных сообщениях)."""
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    # Удаляем сообщение пользователя
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.debug(f"Could not delete user message: {e}")
    
    auth_manager = get_auth_manager()
    user_name = message.from_user.full_name or message.from_user.first_name
    
    if auth_manager.is_authenticated(user_id):
        user_info = auth_manager.get_user_info(user_id)
        email = user_info.get('otrs_email', 'Unknown')
        verified_at = user_info.get('verified_at', '')
        
        # Форматируем дату
        if verified_at:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
                verified_at = dt.strftime('%d.%m.%Y %H:%M')
            except:
                pass
        
        text = (
            f"✅ <b>Статус авторизации</b>\n\n"
            f"👤 {user_name}\n"
            f"📧 <code>{email}</code>\n"
            f"🕐 Авторизован: {verified_at}"
        )
        
        # Обновляем главное сообщение
        main_msg_id = user_main_messages.get(user_id)
        if main_msg_id:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
            ])
            
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                return
            except Exception as e:
                logger.debug(f"Could not edit status message: {e}")
        
        # Если не удалось отредактировать - отправляем новое (но это не должно происходить)
        await message.answer(text, parse_mode="HTML")
    else:
        text = (
            f"❌ <b>Вы не авторизованы</b>\n\n"
            f"Отправьте корпоративный email для авторизации."
        )
        await message.answer(text, parse_mode="HTML")


@dp.message(Command(commands=['mystats']))
async def cmd_mystats(message: Message):
    """Показывает личную статистику пользователя по OTRS."""
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    
    # Удаляем сообщение пользователя
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.debug(f"Could not delete user message: {e}")
    
    auth_manager = get_auth_manager()
    db = get_db()
    
    if not auth_manager.is_authenticated(user_id):
        await message.answer(
            "❌ Вы не авторизованы.\n"
            "Отправьте email для авторизации.",
            parse_mode="HTML"
        )
        return
    
    stats = db.get_user_otrs_stats(user_id)
    user_info = auth_manager.get_user_info(user_id)
    email = user_info.get('otrs_email', 'Unknown')
    
    text = (
        f"📊 <b>Ваша статистика OTRS</b>\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"📧 {email}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Закрыто заявок: <b>{stats['closed']}</b>\n"
        f"❌ Отклонено: <b>{stats['rejected']}</b>\n"
        f"👤 Взято в работу: <b>{stats['assigned']}</b>\n"
        f"💬 Комментариев: <b>{stats['commented']}</b>\n\n"
        f"📈 <b>Всего действий: {stats['total']}</b>"
    )
    
    # Добавляем последние действия
    if stats['recent_actions']:
        text += "\n\n━━━━━━━━━━━━━━━━━━\n\n"
        text += "🕐 <b>Последние действия:</b>\n"
        
        action_emoji = {
            'closed': '✅',
            'rejected': '❌',
            'assigned': '👤',
            'commented': '💬'
        }
        
        for action in stats['recent_actions'][:5]:
            emoji = action_emoji.get(action['action_type'], '📋')
            ticket_num = action.get('ticket_number', action['ticket_id'])
            action_time = action.get('action_time', '')[:16]  # Обрезаем до минут
            text += f"{emoji} #{ticket_num} — {action_time}\n"
    
    # Обновляем главное сообщение
    main_msg_id = user_main_messages.get(user_id)
    if main_msg_id:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
        ])
        
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
        except Exception as e:
            logger.debug(f"Could not edit mystats message: {e}")
    
    # Если не удалось отредактировать - отправляем новое (но это не должно происходить)
    await message.answer(text, parse_mode="HTML")


@dp.message(Command(commands=['otrs_leaders']))
async def cmd_otrs_leaders(message: Message):
    """Показывает таблицу лидеров OTRS."""
    db = get_db()
    
    # Получаем статистику за неделю
    week_stats = db.get_otrs_stats_period(days=7)
    leaderboard = db.get_otrs_leaderboard(action_type="closed", limit=5)
    
    text = (
        f"🏆 <b>Топ по закрытым заявкам</b>\n\n"
        f"📅 За последние 7 дней:\n"
        f"✅ Закрыто: {week_stats['closed']}\n"
        f"❌ Отклонено: {week_stats['rejected']}\n"
        f"👤 Назначено: {week_stats['assigned']}\n"
        f"💬 Комментариев: {week_stats['commented']}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if leaderboard:
        text += "🥇 <b>Лидеры по закрытию:</b>\n\n"
        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        
        for i, leader in enumerate(leaderboard):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            name = leader.get('telegram_username') or leader.get('otrs_email', 'Unknown')
            count = leader['count']
            text += f"{medal} {name}: <b>{count}</b>\n"
    else:
        text += "📭 Пока нет данных"
    
    await message.answer(text, parse_mode="HTML")
    
    # Удаляем команду если в группе
    if message.chat.type != "private":
        asyncio.create_task(
            delete_message_later(message.chat.id, message.message_id, USER_MESSAGE_DELETE_DELAY, message.message_thread_id)
        )


def build_weekly_report(report_data: dict) -> str:
    """Форматирует еженедельный отчёт."""
    start = report_data['start_date'].strftime('%d.%m.%Y')
    end = report_data['end_date'].strftime('%d.%m.%Y')
    totals = report_data['totals']
    users = report_data['users']
    
    text = (
        f"📊 <b>ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ OTRS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Период: <b>{start} — {end}</b>\n\n"
    )
    
    # Общая статистика
    text += (
        f"📈 <b>Общая статистика:</b>\n"
        f"┌─────────────────────\n"
        f"│ ✅ Закрыто:     <b>{totals['closed']}</b>\n"
        f"│ ❌ Отклонено:   <b>{totals['rejected']}</b>\n"
        f"│ 👤 Назначено:   <b>{totals['assigned']}</b>\n"
        f"│ 💬 Комментариев: <b>{totals['commented']}</b>\n"
        f"└─────────────────────\n"
        f"📊 Всего действий: <b>{totals['total']}</b>\n\n"
    )
    
    # Топ по закрытым заявкам
    if users:
        text += f"🏆 <b>Рейтинг по закрытым заявкам:</b>\n\n"
        
        medals = ['🥇', '🥈', '🥉']
        
        for i, user in enumerate(users[:10]):
            if user['closed'] == 0:
                continue
                
            if i < 3:
                medal = medals[i]
            else:
                medal = f"  {i+1}."
            
            name = user['username']
            if len(name) > 15:
                name = name[:12] + "..."
            
            # Формируем строку с деталями
            details = []
            if user['closed'] > 0:
                details.append(f"✅{user['closed']}")
            if user['rejected'] > 0:
                details.append(f"❌{user['rejected']}")
            if user['commented'] > 0:
                details.append(f"💬{user['commented']}")
            
            details_str = " ".join(details)
            text += f"{medal} <b>{name}</b>: {details_str}\n"
        
        if not any(u['closed'] > 0 for u in users):
            text += "   <i>Нет закрытых заявок за период</i>\n"
    else:
        text += "📭 <i>Нет данных за указанный период</i>\n"
    
    text += f"\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🤖 <i>Автоматический отчёт Telegram Bot</i>"
    
    return text


async def send_weekly_report(chat_id: int = None, topic_id: int = None):
    """Отправляет еженедельный отчёт в указанный чат."""
    db = get_db()
    report_data = db.get_weekly_report()
    
    text = build_weekly_report(report_data)
    
    # Если чат не указан - используем METRICS_TOPIC_ID
    if chat_id is None:
        chat_id = SUPERCHAT_TOKEN
    if topic_id is None:
        topic_id = METRICS_TOPIC_ID
    
    # Проверяем доступность чата перед отправкой
    if not await check_chat_availability(chat_id):
        logger.error(f"Cannot send weekly report: chat {chat_id} is not available.")
        return False
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            message_thread_id=topic_id
        )
        logger.info(f"Weekly report sent to chat {chat_id}, topic {topic_id}")
        return True
    except TelegramBadRequest as e:
        if is_chat_not_found_error(e):
            logger.error(f"Cannot send weekly report: chat {chat_id} not found.")
            _chat_availability_cache[chat_id] = (False, now_msk())
        else:
            logger.error(f"Failed to send weekly report: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send weekly report: {e}")
        return False


# Планировщик еженедельного отчёта
_weekly_report_task = None


async def weekly_report_scheduler():
    """Планировщик отправки еженедельного отчёта каждый понедельник в 9:00."""
    from assets.config import MSK_TIMEZONE
    
    while True:
        now = now_msk()
        
        # Находим следующий понедельник 9:00
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= 9:
            days_until_monday = 7  # Если сегодня понедельник после 9 - ждём следующий
        
        next_monday = now.replace(hour=9, minute=0, second=0, microsecond=0)
        next_monday += timedelta(days=days_until_monday)
        
        # Сколько ждать
        wait_seconds = (next_monday - now).total_seconds()
        
        logger.info(f"Next weekly report scheduled for: {next_monday.strftime('%d.%m.%Y %H:%M')} (in {wait_seconds/3600:.1f} hours)")
        
        await asyncio.sleep(wait_seconds)
        
        # Отправляем отчёт
        logger.info("Sending scheduled weekly report...")
        await send_weekly_report()
        
        # Ждём минуту, чтобы не отправить повторно
        await asyncio.sleep(60)


def start_weekly_report_scheduler():
    """Запускает планировщик еженедельных отчётов."""
    global _weekly_report_task
    if _weekly_report_task is None or _weekly_report_task.done():
        _weekly_report_task = asyncio.create_task(weekly_report_scheduler())
        logger.info("Weekly report scheduler started")


def stop_weekly_report_scheduler():
    """Останавливает планировщик еженедельных отчётов."""
    global _weekly_report_task
    if _weekly_report_task and not _weekly_report_task.done():
        _weekly_report_task.cancel()
        logger.info("Weekly report scheduler stopped")


@dp.message(Command(commands=['report']))
async def cmd_report(message: Message):
    """
    Показывает еженедельный отчёт OTRS.
    /report - отчёт за прошлую неделю
    /report test - отправляет отчёт в текущий чат (для теста)
    """
    user_id = message.from_user.id
    
    # Удаляем сообщение пользователя если в личном чате
    if message.chat.type == "private":
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")
    
    db = get_db()
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    report_data = db.get_weekly_report()
    text = build_weekly_report(report_data)
    
    if "test" in args:
        text = f"🧪 <b>ТЕСТОВЫЙ ОТЧЁТ</b>\n\n{text}"
    
    # В личных чатах обновляем главное сообщение
    if message.chat.type == "private":
        main_msg_id = user_main_messages.get(user_id)
        if main_msg_id:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
            ])
            
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                return
            except Exception as e:
                logger.debug(f"Could not edit report message: {e}")
    
    await message.answer(text, parse_mode="HTML")
    
    # Удаляем команду если в группе
    if message.chat.type != "private":
        asyncio.create_task(
            delete_message_later(message.chat.id, message.message_id, USER_MESSAGE_DELETE_DELAY, message.message_thread_id)
        )


@dp.message(Command(commands=['test_mdaemon']))
async def cmd_test_mdaemon(message: Message):
    """Тестирование подключения к MDaemon."""
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    auth_manager = get_auth_manager()
    
    # Только авторизованные пользователи
    if not auth_manager.is_authenticated(user_id):
        await message.answer("❌ Вы не авторизованы")
        return
    
    # Удаляем сообщение пользователя
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.debug(f"Could not delete user message: {e}")
    
    await message.answer("⏳ Тестирую подключение к MDaemon...", parse_mode="HTML")
    
    try:
        from modules.handlers.mdaemon_handler import get_mdaemon_client
        from assets.config import DOMAIN_SERVER, DOMAIN_BASE_DN
        
        client = get_mdaemon_client()
        if not client:
            await message.answer("❌ Клиент Active Directory не сконфигурирован. Проверьте настройки в .env", parse_mode="HTML")
            return
        
        method_info = "Метод: Active Directory\n"
        method_info += f"Сервер: {client.ldap_server or 'не указан'}\n"
        method_info += f"Порт: {client.ldap_port or '389'}\n"
        method_info += f"Base DN: {client.ldap_base_dn or 'не указан (будет определен автоматически)'}\n"
        method_info += f"Bind DN: {client.ldap_bind_dn or 'не указан (анонимное подключение)'}\n"
        
        # Проверяем наличие библиотеки подключения
        try:
            import ldap3
            method_info += "✅ Библиотека подключения установлена\n"
        except ImportError:
            method_info += "❌ Библиотека подключения НЕ установлена. Установите: pip install ldap3\n"
        
        # Пробуем получить информацию о пользователе
        user_info = auth_manager.get_user_info(user_id)
        email = user_info.get('otrs_email', '')
        
        if email:
            await message.answer(f"📧 Пробую получить данные для <code>{email}</code>...", parse_mode="HTML")
            mdaemon_user = await client.get_user_by_email(email)
            
            if mdaemon_user:
                result = (
                    f"✅ <b>Подключение к домену успешно!</b>\n\n"
                    f"{method_info}\n"
                    f"📧 Email: <code>{mdaemon_user.email}</code>\n"
                    f"👤 ФИО: {mdaemon_user.full_name or 'не указано'}\n"
                    f"Имя: {mdaemon_user.first_name or 'не указано'}\n"
                    f"Фамилия: {mdaemon_user.last_name or 'не указано'}\n"
                    f"Активен: {'✅' if mdaemon_user.is_active else '❌'}"
                )
            else:
                result = (
                    f"⚠️ Подключение к домену работает, но пользователь <code>{email}</code> не найден.\n\n"
                    f"{method_info}"
                )
                # Добавляем инструкцию по настройке домена
                if not client.ldap_server:
                    result += (
                        "\n\n"
                        "📋 <b>Как настроить подключение к домену (Active Directory):</b>\n\n"
                        "<b>1. Найдите контроллер домена:</b>\n"
                        "• IP адрес или FQDN (например: <code>DC01.meb52.local</code> или <code>192.168.12.110</code>)\n"
                        "• Можно узнать через <code>nslookup meb52.local</code> или <code>nslookup meb52.com</code>\n\n"
                        "<b>2. Определите Base DN:</b>\n"
                        "• Формат: <code>dc=домен,dc=зона</code>\n"
                        "• Для <code>meb52.local</code> → <code>dc=meb52,dc=local</code>\n"
                        "• Для <code>meb52.com</code> → <code>dc=meb52,dc=com</code>\n"
                        "• Можно узнать через <code>dsquery *</code> на контроллере домена\n\n"
                        "<b>3. Настройки подключения (.env):</b>\n"
                        "• <b>DOMAIN_SERVER:</b> IP или FQDN контроллера домена\n"
                        "• <b>DOMAIN_PORT:</b> 389 (стандартный) или 636 (шифрованное)\n"
                        "• <b>DOMAIN_BASE_DN:</b> <code>dc=meb52,dc=local</code> (для meb52.local, опционально - автопоиск)\n"
                        "• <b>DOMAIN_BIND_DN:</b> пусто или <code>username@meb52.local</code>\n"
                        "• <b>DOMAIN_BIND_PASSWORD:</b> пароль (если требуется)\n\n"
                        "💡 <i>Для анонимного подключения оставьте Bind DN и Password пустыми</i>"
                    )
        else:
            # Пробуем получить список всех пользователей (первые 5)
            await message.answer("📋 Пробую получить список пользователей...", parse_mode="HTML")
            users = await client.get_all_users()
            
            if users:
                result = (
                    f"✅ <b>Подключение к домену успешно!</b>\n\n"
                    f"{method_info}\n"
                    f"📊 Найдено пользователей: <b>{len(users)}</b>\n\n"
                    f"Первые 5 пользователей:\n"
                )
                for i, user in enumerate(users[:5], 1):
                    result += f"{i}. <code>{user.email}</code> - {user.full_name or 'без ФИО'}\n"
            else:
                result = (
                    f"⚠️ Подключение к домену работает, но пользователи не найдены.\n\n"
                    f"{method_info}"
                )
                # Добавляем инструкцию по настройке домена
                if not client.ldap_server:
                    result += (
                        "\n\n"
                        "📋 <b>Как настроить подключение к домену (Active Directory):</b>\n\n"
                        "<b>1. Найдите контроллер домена:</b>\n"
                        "• IP адрес или FQDN (например: <code>DC01.meb52.local</code> или <code>192.168.12.110</code>)\n"
                        "• Можно узнать через <code>nslookup meb52.local</code> или <code>nslookup meb52.com</code>\n\n"
                        "<b>2. Определите Base DN:</b>\n"
                        "• Формат: <code>dc=домен,dc=зона</code>\n"
                        "• Для <code>meb52.local</code> → <code>dc=meb52,dc=local</code>\n"
                        "• Для <code>meb52.com</code> → <code>dc=meb52,dc=com</code>\n"
                        "• Можно узнать через <code>dsquery *</code> на контроллере домена\n\n"
                        "<b>3. Настройки подключения (.env):</b>\n"
                        "• <b>DOMAIN_SERVER:</b> IP или FQDN контроллера домена\n"
                        "• <b>DOMAIN_PORT:</b> 389 (стандартный) или 636 (шифрованное)\n"
                        "• <b>DOMAIN_BASE_DN:</b> <code>dc=meb52,dc=local</code> (для meb52.local, опционально - автопоиск)\n"
                        "• <b>DOMAIN_BIND_DN:</b> пусто или <code>username@meb52.local</code>\n"
                        "• <b>DOMAIN_BIND_PASSWORD:</b> пароль (если требуется)\n\n"
                        "💡 <i>Для анонимного подключения оставьте Bind DN и Password пустыми</i>"
                    )
        
        await message.answer(result, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error testing MDaemon: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка подключения к MDaemon:\n<code>{str(e)}</code>\n\nПроверьте логи для деталей.", parse_mode="HTML")


@dp.message(Command(commands=['sync_mdaemon']))
async def cmd_sync_mdaemon(message: Message):
    """Синхронизация пользователей из MDaemon в БД бота."""
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    auth_manager = get_auth_manager()
    
    # Только авторизованные пользователи могут запускать синхронизацию
    if not auth_manager.is_authenticated(user_id):
        await message.answer("❌ Вы не авторизованы")
        return
    
    # Удаляем сообщение пользователя
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.debug(f"Could not delete user message: {e}")
    
    status_msg = await message.answer("⏳ Начинаю синхронизацию пользователей из Active Directory...")
    
    try:
        from modules.handlers.mdaemon_handler import sync_mdaemon_users_to_db
        result = await sync_mdaemon_users_to_db()
        
        if result:
            await status_msg.edit_text(
                f"✅ Синхронизация завершена!\n"
                f"📊 Всего пользователей в AD: {result.get('total', 0)}\n"
                f"➕ Добавлено новых: {result.get('added', 0)}\n"
                f"🔄 Обновлено: {result.get('updated', 0)}\n"
                f"⚠️ Ошибок: {result.get('errors', 0)}"
            )
        else:
            await status_msg.edit_text("❌ Синхронизация не выполнена. Проверьте настройки Active Directory в .env")
    except Exception as e:
        logger.error(f"Ошибка синхронизации пользователей из AD: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ошибка синхронизации: {str(e)}")
        except:
            await message.answer(f"❌ Ошибка синхронизации: {str(e)}")


@dp.message(Command(commands=['botexec']))
async def cmd_botexec(message: Message):
    """
    Обработчик команды /botexec.
    Отправляет сообщение с кнопкой для показа времени работы.
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Показать время работы", callback_data="runtime")]
    ])
    escaped_bot_startup_msg = escape_markdown_v2_advanced(BOT_STARTUP_MESSAGE)
    sent = await message.answer(
        escaped_bot_startup_msg,
        reply_markup=keyboard,
        parse_mode='MarkdownV2'
    )
    logger.info(f"Sent startup message ID={sent.message_id} to topic ID={BOT_TOPIC_ID}.")

    # Планируем удаление сообщения команды
    asyncio.create_task(
        delete_message_later(
            message.chat.id,
            message.message_id,
            USER_MESSAGE_DELETE_DELAY,
            topic_id=message.message_thread_id
        )
    )

def create_uptime_message() -> str:
    """
    Возвращает сообщение о времени работы бота, обёрнутое в кодовый блок.
    """
    if BOT_START_TIME is None:
        return "```time\nВремя запуска бота неизвестно.\n```"
    uptime_delta = now_msk() - BOT_START_TIME
    s = int(uptime_delta.total_seconds())
    hours = s // 3600
    minutes = (s % 3600) // 60
    seconds = s % 60
    uptime_text = f"Бот работает уже: {hours}ч {minutes}м {seconds}с."
    return f"```time\n{uptime_text}\n```"

@dp.message(Command(commands=['monitor']))
async def cmd_monitor(message: Message):
    """
    Управление мониторингом: /monitor start|stop|status
    """
    args = message.text.split()
    action = args[1].lower() if len(args) > 1 else "status"
    
    chat_id = int(SUPERCHAT_TOKEN)
    monitor = get_monitor()
    
    if action == "start":
        if monitor and monitor.state.is_running:
            await message.reply("⚠️ Мониторинг уже запущен", parse_mode="HTML")
        else:
            await start_monitoring(
                bot=bot,
                chat_id=chat_id,
                topic_id=PING_TOPIC_ID,
                ip_addresses_path=IP_ADDRESSES_PATH,
                check_interval=MONITOR_CHECK_INTERVAL
            )
            await message.reply("✅ Мониторинг запущен", parse_mode="HTML")
            
    elif action == "stop":
        if monitor and monitor.state.is_running:
            await stop_monitoring()
            await message.reply("🛑 Мониторинг остановлен", parse_mode="HTML")
        else:
            await message.reply("⚠️ Мониторинг не был запущен", parse_mode="HTML")
            
    else:  # status
        if monitor and monitor.state.is_running:
            online = sum(1 for s in monitor.state.servers.values() if s.is_alive)
            total = len(monitor.state.servers)
            await message.reply(
                f"📊 <b>Статус мониторинга:</b> ✅ Активен\n"
                f"Серверов онлайн: {online}/{total}\n"
                f"Интервал: {monitor.check_interval}с",
                parse_mode="HTML"
            )
        else:
            await message.reply("📊 <b>Статус мониторинга:</b> ❌ Не активен", parse_mode="HTML")
    
    # Удаляем команду
    asyncio.create_task(
        delete_message_later(message.chat.id, message.message_id, USER_MESSAGE_DELETE_DELAY, message.message_thread_id)
    )


@dp.callback_query(F.data == "start_auth")
async def callback_start_auth(query: CallbackQuery):
    """Обработчик нажатия кнопки 'Авторизоваться'."""
    if query.message.chat.type != "private":
        await query.answer("Эта функция доступна только в личных сообщениях", show_alert=True)
        return
    
    user_id = query.from_user.id
    user_name = query.from_user.full_name or query.from_user.first_name
    
    # Проверяем, что пользователь ещё не авторизован
    auth_manager = get_auth_manager()
    if auth_manager.is_authenticated(user_id):
        await query.answer("Вы уже авторизованы", show_alert=True)
        return
    
    await query.answer()
    
    # Очищаем старую верификацию при повторном нажатии кнопки
    if auth_manager.has_pending_verification(user_id):
        auth_manager.cancel_verification(user_id)
        logger.debug(f"Cancelled pending verification for user {user_id} on auth button press")
    
    # Устанавливаем флаг, что кнопка нажата
    user_auth_button_pressed[user_id] = True
    
    # Редактируем главное сообщение на форму ввода email
    main_msg_id = user_main_messages.get(user_id)
    if main_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=main_msg_id,
                text=(
                    f"<b>Здравствуйте, {user_name}!</b>👋\n"
                    f"\n"
                    f"Я бот технической поддержки ГК \"МОБИ\".\n"
                    f"\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"\n"
                    f"🔐 <b>Авторизация в системе заявок</b>\n"
                    f"\n"
                    f"<i>Отправьте ваш корпоративный email адрес:</i>"
                ),
                parse_mode="HTML",
                reply_markup=None  # Убираем кнопку
            )
            logger.debug(f"Successfully edited message {main_msg_id} to email prompt for user {user_id}")
        except Exception as e:
            logger.error(f"Error editing message {main_msg_id} for auth start: {e}")
            # Если не удалось отредактировать (сообщение удалено), удаляем из кеша
            # НЕ создаём новое сообщение здесь - пусть пользователь использует /start
            del user_main_messages[user_id]
    else:
        # Если нет главного сообщения - создаём новое
        sent_msg = await query.message.answer(
            f"<b>Здравствуйте, {user_name}!</b>👋\n"
            f"\n"
            f"Я бот технической поддержки ГК \"МОБИ\".\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"🔐 <b>Авторизация в системе заявок</b>\n"
            f"\n"
            f"<i>Отправьте ваш корпоративный email адрес:</i>",
            parse_mode="HTML"
        )
        user_main_messages[user_id] = sent_msg.message_id
        logger.debug(f"Created new auth message (ID={sent_msg.message_id}) for user {user_id}")
    
    logger.info(f"User {user_id} started authentication via button")


@dp.callback_query(F.data == "change_email")
async def callback_change_email(query: CallbackQuery):
    """Обработчик кнопки 'Изменить email' - позволяет ввести другой email."""
    if query.message.chat.type != "private":
        await query.answer("Эта функция доступна только в личных сообщениях", show_alert=True)
        return
    
    user_id = query.from_user.id
    user_name = query.from_user.full_name or query.from_user.first_name
    auth_manager = get_auth_manager()
    
    if auth_manager.is_authenticated(user_id):
        await query.answer("Вы уже авторизованы", show_alert=True)
        return
    
    await query.answer()
    
    # Отменяем текущую верификацию
    if auth_manager.has_pending_verification(user_id):
        auth_manager.cancel_verification(user_id)
        logger.debug(f"Cancelled verification for user {user_id} to change email")
    
    # Редактируем главное сообщение обратно на форму ввода email
    main_msg_id = user_main_messages.get(user_id)
    if main_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=main_msg_id,
                text=(
                    f"<b>Здравствуйте, {user_name}!</b>👋\n"
                    f"\n"
                    f"Я бот технической поддержки ГК \"МОБИ\".\n"
                    f"\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"\n"
                    f"🔐 <b>Авторизация в системе заявок</b>\n"
                    f"\n"
                    f"<i>Отправьте ваш корпоративный email адрес:</i>"
                ),
                parse_mode="HTML",
                reply_markup=None
            )
            logger.debug(f"Changed email form shown for user {user_id}")
        except Exception as e:
            logger.error(f"Error editing message for change email: {e}")


@dp.callback_query(F.data == "lobby_back")
async def callback_lobby_back(query: CallbackQuery):
    """Обработчик кнопки 'Назад в меню' - возвращает в лобби."""
    if query.message.chat.type != "private":
        await query.answer("Эта функция доступна только в личных сообщениях", show_alert=True)
        return
    
    user_id = query.from_user.id
    auth_manager = get_auth_manager()
    
    if not auth_manager.is_authenticated(user_id):
        await query.answer("Вы не авторизованы", show_alert=True)
        return
    
    await query.answer()
    
    user_info = auth_manager.get_user_info(user_id)
    user_name = query.from_user.full_name or query.from_user.first_name
    email = user_info.get('otrs_email', 'Unknown')
    
    await show_lobby(user_id, query.message.chat.id, user_name, email)


@dp.callback_query(F.data == "lobby_mystats")
async def callback_lobby_mystats(query: CallbackQuery):
    """Обработчик кнопки 'Моя статистика' в лобби."""
    if query.message.chat.type != "private":
        await query.answer("Эта функция доступна только в личных сообщениях", show_alert=True)
        return
    
    user_id = query.from_user.id
    auth_manager = get_auth_manager()
    db = get_db()
    
    if not auth_manager.is_authenticated(user_id):
        await query.answer("Вы не авторизованы", show_alert=True)
        return
    
    await query.answer("📊 Загружаю статистику...")
    
    try:
        stats = db.get_user_otrs_stats(user_id)
        user_info = auth_manager.get_user_info(user_id)
        email = user_info.get('otrs_email', 'Unknown')
        user_name = query.from_user.full_name or query.from_user.first_name
        
        text = (
            f"📊 <b>Ваша статистика OTRS</b>\n\n"
            f"👤 {user_name}\n"
            f"📧 {email}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ Закрыто заявок: <b>{stats['closed']}</b>\n"
            f"❌ Отклонено: <b>{stats['rejected']}</b>\n"
            f"👤 Взято в работу: <b>{stats['assigned']}</b>\n"
            f"💬 Комментариев: <b>{stats['commented']}</b>\n\n"
            f"📈 <b>Всего действий: {stats['total']}</b>"
        )
        
        # Добавляем последние действия
        if stats.get('recent_actions'):
            text += "\n\n━━━━━━━━━━━━━━━━━━\n\n"
            text += "🕐 <b>Последние действия:</b>\n"
            
            action_emoji = {
                'closed': '✅',
                'rejected': '❌',
                'assigned': '👤',
                'commented': '💬'
            }
            
            for action in stats['recent_actions'][:5]:
                emoji = action_emoji.get(action.get('action_type'), '📋')
                ticket_num = action.get('ticket_number') or action.get('ticket_id', 'N/A')
                action_time = action.get('action_time', '')[:16] if action.get('action_time') else 'N/A'
                text += f"{emoji} #{ticket_num} — {action_time}\n"
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
        ])
        
        main_msg_id = user_main_messages.get(user_id)
        if main_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=query.message.chat.id,
                    message_id=main_msg_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                logger.debug(f"Successfully edited mystats message for user {user_id}")
            except Exception as e:
                logger.error(f"Error editing mystats message (ID={main_msg_id}): {e}", exc_info=True)
                # Если не удалось отредактировать - отправляем новое сообщение
                try:
                    sent_msg = await query.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
                    user_main_messages[user_id] = sent_msg.message_id
                    logger.info(f"Sent new mystats message for user {user_id}, ID={sent_msg.message_id}")
                except Exception as e2:
                    logger.error(f"Failed to send new mystats message: {e2}", exc_info=True)
        else:
            # Если нет главного сообщения - отправляем новое
            try:
                sent_msg = await query.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
                user_main_messages[user_id] = sent_msg.message_id
                logger.info(f"Sent new mystats message (no main_msg_id) for user {user_id}, ID={sent_msg.message_id}")
            except Exception as e:
                logger.error(f"Failed to send mystats message: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in callback_lobby_mystats for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Ошибка при загрузке статистики", show_alert=True)


@dp.callback_query(F.data == "lobby_status")
async def callback_lobby_status(query: CallbackQuery):
    """Обработчик кнопки 'Статус авторизации' в лобби."""
    if query.message.chat.type != "private":
        await query.answer("Эта функция доступна только в личных сообщениях", show_alert=True)
        return
    
    user_id = query.from_user.id
    auth_manager = get_auth_manager()
    
    if not auth_manager.is_authenticated(user_id):
        await query.answer("Вы не авторизованы", show_alert=True)
        return
    
    await query.answer()
    
    user_info = auth_manager.get_user_info(user_id)
    email = user_info.get('otrs_email', 'Unknown')
    verified_at = user_info.get('verified_at', '')
    user_name = query.from_user.full_name or query.from_user.first_name
    
    # Форматируем дату
    if verified_at:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
            verified_at = dt.strftime('%d.%m.%Y %H:%M')
        except:
            pass
    
    text = (
        f"✅ <b>Статус авторизации</b>\n\n"
        f"👤 {user_name}\n"
        f"📧 <code>{email}</code>\n"
        f"🕐 Авторизован: {verified_at}"
    )
    
    main_msg_id = user_main_messages.get(user_id)
    if main_msg_id:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
        ])
        
        try:
            await bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=main_msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error editing status message: {e}")


@dp.callback_query(F.data == "lobby_report")
async def callback_lobby_report(query: CallbackQuery):
    """Обработчик кнопки 'Еженедельный отчёт' в лобби."""
    if query.message.chat.type != "private":
        await query.answer("Эта функция доступна только в личных сообщениях", show_alert=True)
        return
    
    user_id = query.from_user.id
    auth_manager = get_auth_manager()
    
    if not auth_manager.is_authenticated(user_id):
        await query.answer("Вы не авторизованы", show_alert=True)
        return
    
    await query.answer("📈 Загружаю отчёт...")
    
    db = get_db()
    report_data = db.get_weekly_report()
    text = build_weekly_report(report_data)
    
    main_msg_id = user_main_messages.get(user_id)
    if main_msg_id:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="lobby_back")]
        ])
        
        try:
            await bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=main_msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error editing report message: {e}")


@dp.callback_query(F.data == "runtime")
async def callback_runtime(query: CallbackQuery):
    """
    Обработчик нажатия на кнопку "Показать время работы".
    """
    await query.answer()
    try:
        uptime_text = create_uptime_message()
        # Отправляем результат без дополнительного экранирования
        new_msg = await send_message_with_deletion(
            chat_id=query.message.chat.id,
            text=uptime_text,
            delay=UPTIME_NEW_MESSAGE_DELETE_DELAY,
            topic_id=query.message.message_thread_id
        )
        if new_msg:
            logger.info(f"Sent uptime message ID={new_msg.message_id}, will be deleted in {UPTIME_NEW_MESSAGE_DELETE_DELAY} seconds.")
    except Exception as e:
        logger.error(f"Error sending uptime message: {e}")


# ===== OTRS Callback Handlers =====

# Хранилище для ожидания ввода от пользователя
otrs_pending_actions: Dict[int, Dict] = {}  # user_id -> {action, ticket_id, message_id}


@dp.callback_query(F.data.startswith("otrs_"))
async def callback_otrs_action(query: CallbackQuery):
    """Обработчик кнопок OTRS."""
    action_data = query.data.split(":")
    action = action_data[0].replace("otrs_", "")
    ticket_id = int(action_data[1]) if len(action_data) > 1 else None
    
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    
    client = get_otrs_client()
    manager = get_otrs_manager()
    auth_manager = get_auth_manager()
    
    if not client or not manager:
        await query.answer("❌ OTRS интеграция не активна", show_alert=True)
        return
    
    # Действия, требующие авторизации
    actions_requiring_auth = ["assign", "close", "reject", "comment", "reassign"]
    
    if action in actions_requiring_auth:
        if not auth_manager.is_authenticated(user_id):
            await query.answer(
                "🔐 Для этого действия необходима авторизация.\n"
                "Напишите боту в личные сообщения для авторизации.",
                show_alert=True
            )
            return
        
        # Получаем email авторизованного пользователя для логирования
        user_email = auth_manager.get_user_email(user_id)
        user_name = f"{user_name} ({user_email})"
    
    if action == "refresh":
        # Обновить информацию о тикете (не требует авторизации)
        await query.answer("🔄 Обновляю...")
        ticket = await client.get_ticket(ticket_id)
        if ticket:
            await manager.update_ticket_message(ticket)
            await query.answer("✅ Обновлено")
        else:
            await query.answer("❌ Не удалось получить тикет", show_alert=True)
    
    elif action == "refresh_private":
        # Обновить личное сообщение о тикете
        await query.answer("🔄 Обновляю...")
        ticket = await client.get_ticket(ticket_id)
        if ticket:
            try:
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                
                private_text = manager.build_ticket_message(ticket)
                private_text = f"📌 <b>Ваша заявка в работе:</b>\n\n{private_text}"
                
                private_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Закрыть",
                            callback_data=f"otrs_close:{ticket_id}"
                        ),
                        InlineKeyboardButton(
                            text="📝 Комментарий", 
                            callback_data=f"otrs_comment:{ticket_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔄 Обновить",
                            callback_data=f"otrs_refresh_private:{ticket_id}"
                        ),
                        InlineKeyboardButton(
                            text="🌐 Открыть в OTRS",
                            url=f"{client.base_url}/otrs/index.pl?Action=AgentTicketZoom;TicketID={ticket_id}"
                        )
                    ]
                ])
                
                await query.message.edit_text(
                    text=private_text,
                    parse_mode="HTML",
                    reply_markup=private_kb
                )
                await query.answer("✅ Обновлено")
            except Exception as e:
                logger.error(f"Failed to update private ticket: {e}")
                await query.answer("❌ Ошибка обновления", show_alert=True)
        else:
            await query.answer("❌ Тикет не найден (возможно закрыт)", show_alert=True)
    
    elif action == "assign":
        # Взять тикет в работу - назначить на пользователя
        await query.answer("⏳ Ищу агента в OTRS...")
        
        # Получаем email авторизованного пользователя
        user_email = auth_manager.get_user_email(user_id)
        if not user_email:
            await query.answer("❌ Не найден email для назначения", show_alert=True)
            return
        
        # Ищем агента в OTRS по email
        otrs_login = await client.get_agent_login_by_email(user_email)
        
        if not otrs_login:
            await query.answer(
                f"❌ Агент с email {user_email} не найден в OTRS!\n\n"
                "Убедитесь, что ваш email зарегистрирован в OTRS как агент.",
                show_alert=True
            )
            return
        
        # Назначаем тикет на найденного агента (Owner) и меняем статус на "open"
        success, error_msg = await client.update_ticket(
            ticket_id=ticket_id,
            state="open",
            owner=otrs_login,
            article_body=f"Заявка назначена на агента {otrs_login} ({user_email}) через Telegram Bot"
        )
        
        if success:
            ticket = await client.get_ticket(ticket_id)
            if ticket:
                await manager.update_ticket_message(ticket)
                
                # Записываем метрику
                db = get_db()
                db.record_otrs_action(
                    telegram_id=user_id,
                    telegram_username=query.from_user.username or query.from_user.full_name,
                    otrs_email=user_email,
                    action_type="assigned",
                    ticket_id=ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title
                )
                logger.info(f"Ticket #{ticket.ticket_number} assigned to OTRS agent: {otrs_login}")
                
                # Отправляем дубликат в личку пользователю
                try:
                    private_text = manager.build_ticket_message(ticket)
                    private_text = f"📌 <b>Вы взяли заявку в работу:</b>\n\n{private_text}"
                    
                    # Кнопки для личного сообщения
                    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                    private_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ Закрыть",
                                callback_data=f"otrs_close:{ticket_id}"
                            ),
                            InlineKeyboardButton(
                                text="📝 Комментарий", 
                                callback_data=f"otrs_comment:{ticket_id}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="🔄 Обновить",
                                callback_data=f"otrs_refresh_private:{ticket_id}"
                            ),
                            InlineKeyboardButton(
                                text="🌐 Открыть в OTRS",
                                url=f"{client.base_url}/otrs/index.pl?Action=AgentTicketZoom;TicketID={ticket_id}"
                            )
                        ]
                    ])
                    
                    private_msg = await bot.send_message(
                        chat_id=user_id,
                        text=private_text,
                        parse_mode="HTML",
                        reply_markup=private_kb
                    )
                    
                    # Сохраняем ID сообщения в БД
                    db.save_private_ticket(
                        telegram_id=user_id,
                        ticket_id=ticket_id,
                        ticket_number=ticket.ticket_number,
                        message_id=private_msg.message_id
                    )
                    logger.info(f"Sent private ticket message to user {user_id}: msg_id={private_msg.message_id}")
                    
                except Exception as e:
                    logger.warning(f"Failed to send private ticket message: {e}")
            
            await query.answer(f"✅ Заявка назначена на {otrs_login}")
        else:
            await query.answer(
                f"❌ Ошибка назначения в OTRS:\n{error_msg[:150]}",
                show_alert=True
            )
    
    elif action == "close":
        # Проверяем, что заявка назначена на этого пользователя
        ticket = await client.get_ticket(ticket_id)
        if ticket:
            user_email = auth_manager.get_user_email(user_id)
            user_otrs_login = await client.get_agent_login_by_email(user_email) if user_email else None
            ticket_owner = ticket.owner.lower() if ticket.owner else ""
            
            # Проверяем совпадение владельца (если заявка назначена)
            if user_otrs_login and ticket_owner and ticket_owner not in ["", "telegram_bot", "root@localhost"]:
                if user_otrs_login.lower() != ticket_owner:
                    await query.answer(
                        f"❌ Эта заявка назначена на {ticket.owner}.\n"
                        f"Только исполнитель может закрыть заявку.",
                        show_alert=True
                    )
                    return
        
        # Запрашиваем причину закрытия
        await query.answer()
        otrs_pending_actions[user_id] = {
            "action": "close",
            "ticket_id": ticket_id,
            "message_id": query.message.message_id,
            "chat_id": query.message.chat.id,
            "topic_id": query.message.message_thread_id
        }
        sent_msg = await bot.send_message(
            chat_id=query.message.chat.id,
            text=f"✏️ <b>Закрытие заявки #{ticket_id}</b>\n\nНапишите причину закрытия:",
            parse_mode="HTML",
            message_thread_id=query.message.message_thread_id,
            reply_to_message_id=query.message.message_id
        )
        # Удаляем промежуточное сообщение через 30 секунд, особенно в топике заявок
        if query.message.message_thread_id == TASKS_TOPIC_ID:
            asyncio.create_task(delete_message_later(
                query.message.chat.id, 
                sent_msg.message_id, 
                30, 
                query.message.message_thread_id
            ))
    
    elif action == "reject":
        # Проверяем, что заявка назначена на этого пользователя (или не назначена)
        ticket = await client.get_ticket(ticket_id)
        if ticket:
            user_email = auth_manager.get_user_email(user_id)
            user_otrs_login = await client.get_agent_login_by_email(user_email) if user_email else None
            ticket_owner = ticket.owner.lower() if ticket.owner else ""
            
            # Если заявка назначена на кого-то другого - запрещаем
            if user_otrs_login and ticket_owner and ticket_owner not in ["", "telegram_bot", "root@localhost"]:
                if user_otrs_login.lower() != ticket_owner:
                    await query.answer(
                        f"❌ Эта заявка назначена на {ticket.owner}.\n"
                        f"Только исполнитель может отклонить заявку.",
                        show_alert=True
                    )
                    return
        
        # Запрашиваем причину отклонения
        await query.answer()
        otrs_pending_actions[user_id] = {
            "action": "reject",
            "ticket_id": ticket_id,
            "message_id": query.message.message_id,
            "chat_id": query.message.chat.id,
            "topic_id": query.message.message_thread_id
        }
        sent_msg = await bot.send_message(
            chat_id=query.message.chat.id,
            text=f"✏️ <b>Отклонение заявки #{ticket_id}</b>\n\nНапишите причину отклонения:",
            parse_mode="HTML",
            message_thread_id=query.message.message_thread_id,
            reply_to_message_id=query.message.message_id
        )
        # Удаляем промежуточное сообщение через 30 секунд, особенно в топике заявок
        if query.message.message_thread_id == TASKS_TOPIC_ID:
            asyncio.create_task(delete_message_later(
                query.message.chat.id, 
                sent_msg.message_id, 
                30, 
                query.message.message_thread_id
            ))
    
    elif action == "reassign":
        # Переназначить тикет на бота (освободить для других агентов)
        await query.answer("⏳ Освобождаю заявку...")
        
        # Назначаем на telegram_bot - это означает "свободна"
        success, error_msg = await client.update_ticket(
            ticket_id=ticket_id,
            owner="telegram_bot",  # Назначаем на бота = "свободна для взятия"
            state="new",  # Возвращаем статус "new"
            article_body=f"Заявка освобождена через Telegram Bot (пользователь: {user_name})"
        )
        
        if success:
            ticket = await client.get_ticket(ticket_id)
            if ticket:
                await manager.update_ticket_message(ticket)
            await query.answer("✅ Заявка освобождена. Теперь её может взять другой агент.")
        else:
            await query.answer(f"❌ Ошибка: {error_msg[:100]}", show_alert=True)
    
    elif action == "comment":
        # Запрашиваем комментарий
        await query.answer()
        otrs_pending_actions[user_id] = {
            "action": "comment",
            "ticket_id": ticket_id,
            "message_id": query.message.message_id,
            "chat_id": query.message.chat.id,
            "topic_id": query.message.message_thread_id
        }
        sent_msg = await bot.send_message(
            chat_id=query.message.chat.id,
            text=f"✏️ <b>Комментарий к заявке #{ticket_id}</b>\n\nНапишите ваш комментарий:",
            parse_mode="HTML",
            message_thread_id=query.message.message_thread_id,
            reply_to_message_id=query.message.message_id
        )
        # Удаляем промежуточное сообщение через 30 секунд, особенно в топике заявок
        if query.message.message_thread_id == TASKS_TOPIC_ID:
            asyncio.create_task(delete_message_later(
                query.message.chat.id, 
                sent_msg.message_id, 
                30, 
                query.message.message_thread_id
            ))


@dp.message(F.text)
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    # ===== Если сообщение в топике заявок и не связано с OTRS - удаляем через 30 секунд =====
    # В топике заявок должны быть только заявки OTRS, остальные сообщения удаляются
    is_in_tasks_topic = message.chat.type != "private" and message.message_thread_id == TASKS_TOPIC_ID
    
    # ===== СНАЧАЛА проверяем ожидающие действия OTRS (в любом чате) =====
    if user_id in otrs_pending_actions:
        pending = otrs_pending_actions.pop(user_id)
        action = pending["action"]
        ticket_id = pending["ticket_id"]
        ticket_msg_id = pending.get("message_id")
        pending_chat_id = pending.get("chat_id")  # Чат где ожидается ответ
        user_name = message.from_user.full_name
        reason = message.text
        
        client = get_otrs_client()
        manager = get_otrs_manager()
        auth_manager = get_auth_manager()
        db = get_db()
        
        # Получаем email для логирования
        user_email = auth_manager.get_user_email(user_id) or ""
        if user_email:
            user_name_full = f"{user_name} ({user_email})"
        else:
            user_name_full = user_name
        
        if client and manager:
            success = False
            error_msg = ""
            action_type = None
            
            if action == "close":
                success, error_msg = await client.update_ticket(
                    ticket_id=ticket_id,
                    state="closed successful",
                    article_body=f"Закрыто: {user_name_full} (Telegram)\n\nПричина: {reason}"
                )
                status_text = "✅ Заявка закрыта"
                action_type = "closed"
            
            elif action == "reject":
                success, error_msg = await client.update_ticket(
                    ticket_id=ticket_id,
                    state="closed unsuccessful",
                    article_body=f"Отклонено: {user_name_full} (Telegram)\n\nПричина: {reason}"
                )
                status_text = "❌ Заявка отклонена"
                action_type = "rejected"
            
            elif action == "comment":
                success, error_msg = await client.update_ticket(
                    ticket_id=ticket_id,
                    article_body=f"Комментарий: {user_name_full} (Telegram)\n\n{reason}"
                )
                status_text = "💬 Комментарий добавлен"
                action_type = "commented"
            
            if success:
                # Получаем информацию о тикете для метрик
                ticket = await client.get_ticket(ticket_id)
                ticket_number = ticket.ticket_number if ticket else str(ticket_id)
                ticket_title = ticket.title if ticket else ""
                
                # Записываем метрику
                db.record_otrs_action(
                    telegram_id=user_id,
                    telegram_username=message.from_user.username or user_name,
                    otrs_email=user_email,
                    action_type=action_type,
                    ticket_id=ticket_id,
                    ticket_number=ticket_number,
                    ticket_title=ticket_title,
                    details=reason
                )
                logger.info(f"Recorded OTRS metric: {action_type} by {user_id} on #{ticket_number}")
                
                # Если заявка закрыта или отклонена - удаляем сообщения
                if action_type in ["closed", "rejected"]:
                    # Удаляем из группового чата
                    if ticket_msg_id and manager.topic_id:
                        try:
                            await bot.delete_message(
                                chat_id=manager.chat_id,
                                message_id=ticket_msg_id
                            )
                            logger.info(f"Deleted closed ticket message: {ticket_msg_id}")
                            
                            if ticket_id in manager.ticket_messages:
                                del manager.ticket_messages[ticket_id]
                            if ticket_id in manager.known_tickets:
                                del manager.known_tickets[ticket_id]
                            db.delete_ticket_message(ticket_id, manager.chat_id, manager.topic_id)
                        except Exception as e:
                            logger.error(f"Failed to delete ticket message: {e}")
                    
                    # Удаляем личные сообщения о тикете
                    try:
                        private_tickets = db.get_private_ticket_by_ticket_id(ticket_id)
                        for pt in private_tickets:
                            try:
                                await bot.delete_message(
                                    chat_id=pt['telegram_id'],
                                    message_id=pt['message_id']
                                )
                                db.delete_private_ticket(pt['telegram_id'], ticket_id)
                                logger.info(f"Deleted private ticket msg for user {pt['telegram_id']}")
                            except Exception as e:
                                logger.warning(f"Failed to delete private msg: {e}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup private tickets: {e}")
                else:
                    # Для комментариев - обновляем сообщение
                    if ticket:
                        await manager.update_ticket_message(ticket)
                
                # Отправляем статусное сообщение
                status_msg = await message.reply(status_text, parse_mode="HTML")
                
                # Удаляем статусное сообщение через 30 секунд, особенно в топике заявок
                if message.message_thread_id == TASKS_TOPIC_ID:
                    asyncio.create_task(delete_message_later(
                        message.chat.id, 
                        status_msg.message_id, 
                        30, 
                        message.message_thread_id
                    ))
            else:
                error_text = f"❌ Ошибка при выполнении действия"
                if error_msg:
                    error_text += f"\n\n<i>{error_msg[:200]}</i>"
                error_msg_obj = await message.reply(error_text, parse_mode="HTML")
                
                # Удаляем сообщение об ошибке через 30 секунд в топике заявок
                if message.message_thread_id == TASKS_TOPIC_ID:
                    asyncio.create_task(delete_message_later(
                        message.chat.id, 
                        error_msg_obj.message_id, 
                        30, 
                        message.message_thread_id
                    ))
        
        # Удаляем сообщения пользователей через 30 секунд (только в группах)
        # Особенно важно в топике заявок - там должны быть только заявки
        if message.chat.type != "private":
            asyncio.create_task(delete_message_later(
                message.chat.id, 
                message.message_id, 
                30, 
                message.message_thread_id
            ))
        return
    
    # ===== Если сообщение в топике заявок и не связано с OTRS - удаляем =====
    if is_in_tasks_topic:
        # Это случайное сообщение в топике заявок - удаляем через 30 секунд
        asyncio.create_task(delete_message_later(
            message.chat.id, 
            message.message_id, 
            30, 
            message.message_thread_id
        ))
        # Можно опционально показать предупреждение, но лучше просто удалить
        logger.info(f"Non-OTRS message in tasks topic {TASKS_TOPIC_ID}, will be deleted in 30s")
        return
    
    # ===== Обработка личных сообщений =====
    if message.chat.type == "private":
        auth_manager = get_auth_manager()
        user_name = message.from_user.full_name or message.from_user.first_name
        allowed_domains = get_allowed_domains_text()
        
        # Если пользователь не авторизован и не нажал кнопку "Авторизоваться"
        # - просто удаляем все его сообщения без ответа
        if not auth_manager.is_authenticated(user_id) and not user_auth_button_pressed.get(user_id, False):
            # Удаляем сообщение пользователя, если он ещё не нажал кнопку авторизации
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
            return
        
        # Проверяем, авторизован ли пользователь
        if auth_manager.is_authenticated(user_id):
            # Проверяем, является ли пользователь агентом OTRS
            user_info = auth_manager.get_user_info(user_id)
            email = user_info.get('otrs_email', '')
            client = get_otrs_client()
            is_agent = False
            if client and email:
                try:
                    otrs_login = await client.get_agent_login_by_email(email)
                    is_agent = otrs_login is not None
                except Exception as e:
                    logger.warning(f"Failed to check if user is agent: {e}")
            
            # Если не агент - обрабатываем кнопки для обычных пользователей
            if not is_agent:
                if user_text == "📝 Написать заявку":
                    await message.answer(
                        "📝 <b>Создание новой заявки</b>\n\n"
                        "Опишите вашу проблему или запрос.\n"
                        "Пожалуйста, укажите:\n"
                        "• Краткое описание проблемы\n"
                        "• Детали (если необходимо)\n"
                        "• Контактные данные (если нужен звонок)",
                        parse_mode="HTML"
                    )
                    # TODO: Реализовать создание заявки в OTRS
                    logger.info(f"User {user_id} requested to create ticket")
                    return
                
                elif user_text == "📋 Посмотреть мои заявки":
                    # TODO: Реализовать получение заявок пользователя
                    await message.answer(
                        "📋 <b>Ваши заявки</b>\n\n"
                        "Функционал просмотра заявок будет добавлен в ближайшее время.",
                        parse_mode="HTML"
                    )
                    logger.info(f"User {user_id} requested to view tickets")
                    return
                
                # Для обычных пользователей игнорируем случайный текст (не кнопки)
                return
        
        # Проверяем, есть ли ожидающая верификация (ввод кода)
        if auth_manager.has_pending_verification(user_id):
            # Удаляем сообщение пользователя с кодом
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
            
            # Это должен быть код подтверждения
            if user_text.isdigit() and len(user_text) == 6:
                success, result_msg = await auth_manager.verify_code(
                    user_id, user_text, 
                    message.from_user.username,
                    message.from_user.full_name  # Сохраняем ФИО
                )
                if success:
                    # После успешной авторизации определяем тип пользователя
                    user_info = auth_manager.get_user_info(user_id)
                    email = user_info.get('otrs_email', '')
                    
                    # Проверяем, является ли пользователь агентом OTRS
                    client = get_otrs_client()
                    is_agent = False
                    if client and email:
                        try:
                            otrs_login = await client.get_agent_login_by_email(email)
                            is_agent = otrs_login is not None
                        except Exception as e:
                            logger.warning(f"Failed to check if user is agent: {e}")
                    
                    # Редактируем главное сообщение при успешной авторизации
                    main_msg_id = user_main_messages.get(user_id)
                    
                    if is_agent:
                        # Агент OTRS - показываем лобби с кнопками
                        await show_lobby(user_id, message.chat.id, user_name, email)
                    else:
                        # Обычный пользователь - редактируем главное сообщение
                        # TODO: Получить ФИО из MDaemon
                        full_name = user_info.get('full_name') or user_name
                        
                        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
                        
                        keyboard = ReplyKeyboardMarkup(
                            keyboard=[
                                [KeyboardButton(text="📝 Написать заявку")],
                                [KeyboardButton(text="📋 Посмотреть мои заявки")]
                            ],
                            resize_keyboard=True
                        )
                        
                        if main_msg_id:
                            try:
                                await bot.edit_message_text(
                                    chat_id=message.chat.id,
                                    message_id=main_msg_id,
                                    text=(
                                        f"✅ <b>Авторизация успешна!</b>\n\n"
                                        f"Здравствуйте, {full_name}!👋\n"
                                        f"Я бот технической поддержки ГК \"МОБИ\".\n"
                                        f"\n"
                                        f"Выберите действие:"
                                    ),
                                    parse_mode="HTML",
                                    reply_markup=keyboard
                                )
                            except Exception as e:
                                logger.error(f"Error editing message: {e}")
                                # Если не удалось отредактировать - отправляем новое
                                await message.answer(
                                    f"✅ <b>Авторизация успешна!</b>\n\n"
                                    f"Здравствуйте, {full_name}!👋\n"
                                    f"Я бот технической поддержки ГК \"МОБИ\".\n"
                                    f"\n"
                                    f"Выберите действие:",
                                    parse_mode="HTML",
                                    reply_markup=keyboard
                                )
                        else:
                            await message.answer(
                                f"✅ <b>Авторизация успешна!</b>\n\n"
                                f"Здравствуйте, {full_name}!👋\n"
                                f"Я бот технической поддержки ГК \"МОБИ\".\n"
                                f"\n"
                                f"Выберите действие:",
                                parse_mode="HTML",
                                reply_markup=keyboard
                            )
                    
                    # НЕ очищаем главное сообщение - оно теперь используется как лобби
                    # if user_id in user_main_messages:
                    #     del user_main_messages[user_id]
                else:
                    # Неверный код - отправляем новое сообщение с ошибкой (не редактируем главное)
                    error_msg = await message.answer(result_msg, parse_mode="HTML")
                    # Удаляем сообщение об ошибке через 10 секунд
                    asyncio.create_task(delete_private_message_later(
                        message.chat.id, 
                        error_msg.message_id, 
                        10
                    ))
            else:
                # Неверный формат кода - отправляем новое сообщение с ошибкой (не редактируем главное)
                error_msg = await message.answer(
                    "❌ <b>Неверный формат кода</b>\n\n"
                    "Код должен состоять из 6 цифр.\n"
                    "Проверьте письмо на вашей почте.\n\n"
                    "<i>Введите полученный код:</i>",
                    parse_mode="HTML"
                )
                # Удаляем сообщение об ошибке через 10 секунд
                asyncio.create_task(delete_private_message_later(
                    message.chat.id, 
                    error_msg.message_id, 
                    10
                ))
            return
        
        # Если пользователь нажал кнопку "Авторизоваться", но ещё не вводит код
        # Проверяем: это должен быть валидный email с разрешённого домена
        if user_auth_button_pressed.get(user_id, False):
            # Проверяем, что это валидный email и с разрешённого домена
            if is_valid_email(user_text) and is_allowed_domain(user_text):
                # Удаляем сообщение пользователя
                try:
                    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")
                
                # Очищаем старую верификацию перед созданием новой (если пользователь ввёл другой email)
                if auth_manager.has_pending_verification(user_id):
                    auth_manager.cancel_verification(user_id)
                    logger.debug(f"Cancelled old verification before creating new one for user {user_id}")
                
                # Email корректный - отправляем код
                success, result_msg = await auth_manager.start_verification(user_id, user_text)
                
                # Редактируем главное сообщение
                main_msg_id = user_main_messages.get(user_id)
                if main_msg_id:
                    try:
                        # Форматируем имя пользователя
                        user_first_name = message.from_user.first_name or user_name.split()[0] if user_name else "Пользователь"
                        
                        # Добавляем кнопку "Изменить email" если пользователь хочет ввести другой email
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        change_email_kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📧 Изменить email", callback_data="change_email")]
                        ])
                        
                        await bot.edit_message_text(
                            chat_id=message.chat.id,
                            message_id=main_msg_id,
                            text=(
                                f"📧 {user_first_name}, ваш код был отправлен на:\n"
                                f"<code>{user_text}</code>\n"
                                f"\n"
                                f"<i>Введите полученный код:</i>"
                            ),
                            parse_mode="HTML",
                            reply_markup=change_email_kb
                        )
                        logger.debug(f"Edited main message {main_msg_id} to code prompt for user {user_id}")
                    except Exception as e:
                        logger.error(f"Error editing message {main_msg_id}: {e}")
                        # Если не удалось отредактировать - удаляем из кеша
                        # НЕ создаём новое сообщение - главное сообщение должно быть
                        del user_main_messages[user_id]
                # Если нет главного сообщения - ничего не делаем (не создаём новое)
                return
            else:
                # Это не валидный email или не разрешённый домен - удаляем сообщение
                try:
                    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
                    logger.debug(f"Deleted non-email or non-allowed domain message from user {user_id}")
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")
                # Просто удаляем сообщение, ничего не отвечаем
                return
        
        # Проверяем, это email для начала верификации (fallback для случаев без кнопки)
        if is_valid_email(user_text):
            # Удаляем сообщение пользователя
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
            
            # Проверяем домен
            if not is_allowed_domain(user_text):
                # Отправляем новое сообщение с ошибкой (не редактируем главное)
                error_msg = await message.answer(
                    f"❌ <b>Домен email не разрешён</b>\n\n"
                    f"Используйте корпоративную почту.",
                    parse_mode="HTML"
                )
                # Удаляем сообщение об ошибке через 10 секунд
                asyncio.create_task(delete_private_message_later(
                    message.chat.id, 
                    error_msg.message_id, 
                    10
                ))
                return
            
            # Email корректный - отправляем код
            success, result_msg = await auth_manager.start_verification(user_id, user_text)
            
            # Редактируем главное сообщение
            main_msg_id = user_main_messages.get(user_id)
            if main_msg_id:
                try:
                    # Форматируем имя пользователя
                    user_first_name = message.from_user.first_name or user_name.split()[0] if user_name else "Пользователь"
                    
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=main_msg_id,
                        text=(
                            f"📧 {user_first_name}, ваш код был отправлен на:\n"
                            f"<code>{user_text}</code>\n"
                            f"\n"
                            f"<i>Введите полученный код:</i>"
                        ),
                        parse_mode="HTML"
                    )
                    logger.debug(f"Edited main message {main_msg_id} to code prompt for user {user_id}")
                except Exception as e:
                    logger.error(f"Error editing message {main_msg_id}: {e}")
                    # Если не удалось отредактировать - удаляем из кеша
                    # НЕ создаём новое сообщение - главное сообщение должно быть
                    del user_main_messages[user_id]
            # Если нет главного сообщения - ничего не делаем (не создаём новое)
            return
        
        # Текст не похож на email - удаляем сообщение пользователя
        # НЕ создаём новых сообщений - только удаляем ввод пользователя
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")
        
        # Если главное сообщение есть и кнопка нажата - просто удаляем ввод пользователя
        # Если главного сообщения нет - оно должно появиться только при /start или нажатии кнопки
        # НЕ создаём новые сообщения здесь
        return
    
    # ===== Обработка в группах =====
    
    # Остальная обработка текстовых сообщений
    user_text = message.text
    chat_id = message.chat.id
    topic_id = message.message_thread_id

    logger.info(f"Received message from user ID={user_id}: {user_text}")
    logger.debug(f"chat_id={chat_id}, topic_id={topic_id}, user_id={user_id}")

    # Проверка темы
    if topic_id and topic_id not in ALLOWED_THREADS:
        logger.debug(f"Message in disallowed topic: {topic_id}. Ignoring.")
        return

    try:
        if str(topic_id) == str(EXCEL_TOPIC_ID):
            from modules.handlers.excel_handler import handle_excel_search
            
            db = get_db()
            delete_time = now_msk() + timedelta(seconds=EXCEL_MESSAGE_DELETE_DELAY)

            # handle_excel_search может вернуть либо одну строку, либо список строк (чанков)
            result_or_list = await handle_excel_search(user_text, EXCEL_FILE_PATH, EXCEL_PASSWORD)

            # Определяем, вернулась ли одна строка или список
            if isinstance(result_or_list, str):
                # Один блок
                chunks = [result_or_list]
            else:
                # Список чанков
                chunks = result_or_list

            # Сохраняем ID сообщения пользователя в БД и планируем удаление
            db.add_pending_deletion(chat_id, topic_id, message.message_id, delete_time)
            asyncio.create_task(
                delete_message_later(chat_id, message.message_id, EXCEL_MESSAGE_DELETE_DELAY, topic_id)
            )

            # Отправляем каждый блок БЕЗ УВЕДОМЛЕНИЯ
            for chunk in chunks:
                sent = await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode='HTML',
                    message_thread_id=topic_id,
                    reply_to_message_id=message.message_id,
                    disable_notification=True  # Без уведомления!
                )
                logger.info(f"Excel search result sent to user ID={user_id} (no notification).")

                # Сохраняем ID ответа бота в БД и планируем удаление
                db.add_pending_deletion(sent.chat.id, topic_id, sent.message_id, delete_time)
                asyncio.create_task(
                    delete_message_later(sent.chat.id, sent.message_id, EXCEL_MESSAGE_DELETE_DELAY, topic_id)
                )

        else:
            # Если не Excel-тема, просто планируем удаление исходного сообщения
            asyncio.create_task(
                delete_message_later(
                    chat_id,
                    message.message_id,
                    USER_MESSAGE_DELETE_DELAY,
                    topic_id=topic_id
                )
            )
            logger.info(f"Will delete user message ID={message.message_id} after {USER_MESSAGE_DELETE_DELAY} seconds.")

    except Exception as e:
        logger.error(f"Error in handle_text_message: {e}", exc_info=True)
        
        # Формируем понятное сообщение об ошибке для пользователя
        if "Excel" in str(e) or "excel" in str(e).lower():
            error_text = "❌ Ошибка при работе с Excel файлом. Попробуйте позже."
        elif "network" in str(e).lower() or "connection" in str(e).lower():
            error_text = "❌ Проблема с сетью. Проверьте подключение."
        else:
            error_text = "❌ Произошла ошибка. Попробуйте позже."
        
        try:
            # Отправляем ошибку в HTML, чтобы не конфликтовать с Markdown
            sent_err = await message.reply(
                f"<pre>{error_text}</pre>",
                parse_mode='HTML'
            )
            logger.info(f"Error message sent to user ID={user_id}.")

            asyncio.create_task(
                delete_message_later(
                    sent_err.chat.id,
                    sent_err.message_id,
                    BOT_MESSAGE_DELETE_DELAY,
                    topic_id=sent_err.message_thread_id
                )
            )
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}", exc_info=True)


async def cleanup_excel_topic():
    """Очищает ТОЛЬКО отслеживаемые сообщения в Excel топике при запуске."""
    db = get_db()
    
    # Получаем ID сообщения-инструкции (чтобы не удалять его)
    instruction_msg_id = db.get_message_id(int(SUPERCHAT_TOKEN), EXCEL_TOPIC_ID, 'instruction')
    
    # Получаем ТОЛЬКО сообщения из Excel топика, сохранённые в БД
    pending = db.get_pending_deletions(topic_id=EXCEL_TOPIC_ID)
    
    if not pending:
        logger.info(f"No tracked messages to cleanup in Excel topic {EXCEL_TOPIC_ID}")
        return
    
    logger.info(f"Cleaning up {len(pending)} tracked messages in Excel topic {EXCEL_TOPIC_ID}")
    deleted_count = 0
    
    for item in pending:
        # Пропускаем сообщение-инструкцию!
        if instruction_msg_id and item['message_id'] == instruction_msg_id:
            logger.debug(f"Skipping instruction message {item['message_id']}")
            db.remove_pending_deletion(item['chat_id'], item['message_id'])
            continue
            
        try:
            await bot.delete_message(
                chat_id=item['chat_id'],
                message_id=item['message_id']
            )
            deleted_count += 1
            logger.debug(f"Deleted tracked message {item['message_id']} from Excel topic")
        except Exception as e:
            logger.debug(f"Could not delete message {item['message_id']}: {e}")
        
        # Удаляем из БД в любом случае
        db.remove_pending_deletion(item['chat_id'], item['message_id'])
    
    logger.info(f"Excel topic cleanup complete: {deleted_count}/{len(pending)} messages deleted")


async def send_excel_instruction():
    """Отправляет или обновляет сообщение-инструкцию в Excel топике."""
    chat_id = int(SUPERCHAT_TOKEN)
    db = get_db()
    
    instruction_text = (
        "<b>📋 ПОИСК ИНФОРМАЦИИ О СОТРУДНИКАХ</b>\n\n"
        "Введите один из параметров для поиска:\n\n"
        "🔹 <b>ФИО</b> — поиск по имени сотрудника\n"
        "   <i>Пример: Иванов</i>\n\n"
        "🔹 <b>WS номер</b> — поиск по рабочей станции\n"
        "   <i>Пример: WS111</i>\n\n"
        "🔹 <b>IP-адрес</b> — поиск по IP\n"
        "   <i>Пример: 192.168.12.100</i>\n\n"
        "🔹 <b>Телефон</b> — поиск по номеру телефона\n"
        "   <i>Пример: 100</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⏱ <i>Сообщения автоматически удаляются через 5 минут</i>"
    )
    
    # Проверяем доступность чата перед отправкой
    if not await check_chat_availability(chat_id):
        logger.error(f"Cannot send Excel instruction: chat {chat_id} is not available. Bot may not be in the chat or chat was deleted.")
        return
    
    # Проверяем, есть ли сохранённый ID сообщения
    saved_msg_id = db.get_message_id(chat_id, EXCEL_TOPIC_ID, 'instruction')
    
    if saved_msg_id:
        # Пробуем обновить существующее сообщение
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=saved_msg_id,
                text=instruction_text,
                parse_mode="HTML"
            )
            logger.info(f"Excel instruction message updated: ID={saved_msg_id}")
            return
        except Exception as e:
            if "message is not modified" in str(e):
                logger.debug(f"Excel instruction message unchanged: ID={saved_msg_id}")
                return
            elif "message to edit not found" in str(e):
                logger.info("Excel instruction message was deleted, creating new one")
            else:
                logger.warning(f"Could not update instruction message: {e}")
    
    # Создаём новое сообщение
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=instruction_text,
            parse_mode="HTML",
            message_thread_id=EXCEL_TOPIC_ID,
            disable_notification=True
        )
        db.save_message_id(chat_id, EXCEL_TOPIC_ID, 'instruction', msg.message_id)
        logger.info(f"Excel instruction message created: ID={msg.message_id}")
    except TelegramBadRequest as e:
        if is_chat_not_found_error(e):
            logger.error(f"Cannot send Excel instruction: chat {chat_id} not found. Bot may not be in the chat or chat was deleted.")
            _chat_availability_cache[chat_id] = (False, now_msk())
        else:
            logger.error(f"Failed to send Excel instruction message: {e}")
    except Exception as e:
        logger.error(f"Failed to send Excel instruction message: {e}")


async def on_startup():
    """Выполняется при запуске бота."""
    global BOT_START_TIME
    BOT_START_TIME = now_msk()
    logger.info(f"Bot started. Startup time: {BOT_START_TIME.strftime('%Y-%m-%d %H:%M:%S')} MSK")
    
    chat_id = int(SUPERCHAT_TOKEN)
    
    # Очищаем Excel топик от старых сообщений
    try:
        await cleanup_excel_topic()
    except Exception as e:
        logger.error(f"Error during Excel topic cleanup: {e}", exc_info=True)
    
    # Отправляем/обновляем инструкцию в Excel топик
    try:
        await send_excel_instruction()
    except Exception as e:
        logger.error(f"Error sending Excel instruction: {e}", exc_info=True)
    
    # Отправляем сообщение о запуске в беседу
    try:
        # Проверяем доступность чата перед отправкой
        if not await check_chat_availability(chat_id):
            logger.error(f"Cannot send startup message: chat {chat_id} is not available. Bot may not be in the chat or chat was deleted.")
            logger.error(f"Please check that:")
            logger.error(f"  1. Bot is added to the chat with ID {chat_id}")
            logger.error(f"  2. SUPERCHAT_TOKEN in .env file is correct")
            logger.error(f"  3. Chat ID is correct (should be negative for groups/supergroups)")
        else:
            startup_msg = await send_message_with_deletion(
                chat_id=chat_id,
                text=BOT_STARTUP_MESSAGE,
                delay=BOT_MESSAGE_DELETE_DELAY,
                topic_id=BOT_TOPIC_ID
            )
            if startup_msg:
                logger.info(f"Startup message sent to chat {chat_id}, topic {BOT_TOPIC_ID}")
            else:
                logger.warning("Failed to send startup message")
    except ValueError as e:
        logger.error(f"Invalid SUPERCHAT_TOKEN format: {e}")
    except Exception as e:
        logger.error(f"Error sending startup message: {e}", exc_info=True)
    
    # Запускаем мониторинг серверов
    try:
        await start_monitoring(
            bot=bot,
            chat_id=chat_id,
            topic_id=PING_TOPIC_ID,
            ip_addresses_path=IP_ADDRESSES_PATH,
            check_interval=MONITOR_CHECK_INTERVAL,
            metrics_topic_id=METRICS_TOPIC_ID if METRICS_TOPIC_ID else None
        )
        logger.info(f"Server monitoring started for topic {PING_TOPIC_ID}, metrics topic {METRICS_TOPIC_ID}")
    except Exception as e:
        logger.error(f"Failed to start monitoring: {e}", exc_info=True)
    
    # Запускаем интеграцию с OTRS (если настроена)
    if OTRS_URL:
        try:
            otrs_manager = await start_otrs_integration(
                bot=bot,
                chat_id=chat_id,
                topic_id=TASKS_TOPIC_ID,
                check_interval=60  # Проверка каждую минуту
            )
            if otrs_manager:
                logger.info(f"OTRS integration started for topic {TASKS_TOPIC_ID}")
            else:
                logger.warning("OTRS integration failed to start (check configuration)")
        except Exception as e:
            logger.error(f"Failed to start OTRS integration: {e}", exc_info=True)
    
    # Запускаем планировщик еженедельных отчётов
    try:
        start_weekly_report_scheduler()
    except Exception as e:
        logger.error(f"Failed to start weekly report scheduler: {e}", exc_info=True)


async def on_shutdown():
    """Выполняется при остановке бота."""
    logger.info("Bot is shutting down...")
    
    # Останавливаем мониторинг
    try:
        await stop_monitoring()
        logger.info("Server monitoring stopped")
    except Exception as e:
        logger.error(f"Error stopping monitoring: {e}", exc_info=True)
    
    # Останавливаем OTRS интеграцию
    try:
        await stop_otrs_integration()
        logger.info("OTRS integration stopped")
    except Exception as e:
        logger.error(f"Error stopping OTRS integration: {e}", exc_info=True)
    
    # Останавливаем планировщик отчётов
    try:
        stop_weekly_report_scheduler()
    except Exception as e:
        logger.error(f"Error stopping weekly report scheduler: {e}", exc_info=True)
    
    # Закрываем сессию бота
    try:
        await bot.session.close()
        logger.info("Bot session closed")
    except Exception as e:
        logger.error(f"Error closing bot session: {e}", exc_info=True)


async def main():
    """Главная функция запуска бота."""
    try:
        logger.info("Starting Aiogram bot...")
        
        # Выполняем действия при запуске
        await on_startup()
        
        # Запускаем polling
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            close_bot_session=True
        )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        await on_shutdown()