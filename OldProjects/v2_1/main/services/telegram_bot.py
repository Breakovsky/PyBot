"""
Telegram Bot Service для TBot v2.1
Обработка команд и сообщений Telegram.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import get_settings
from config.security import get_security_manager
from database.connection import get_db_pool
from handlers.employee_search import EmployeeSearchHandler
from handlers.server_monitor import ServerMonitorHandler
from handlers.otrs_handler import OTRSHandler
from handlers.auth_handler import AuthHandler
from database.repositories.message_deletion_repository import MessageDeletionRepository
from utils.formatters import escape_html
from utils.logger import get_logger

logger = get_logger(__name__)


class TelegramBotService:
    """Сервис для работы с Telegram ботом."""
    
    def __init__(self, db_pool, cluster_coordinator=None):
        """
        Инициализирует Telegram Bot Service.
        
        Args:
            db_pool: Пул соединений с БД
            cluster_coordinator: Координатор кластера (опционально)
        """
        self.db_pool = db_pool
        self.cluster_coordinator = cluster_coordinator
        
        # Получаем токен из Windows Credential Manager или переменных окружения
        import os
        security = get_security_manager()
        token = security.get_secret("TOKEN") or os.getenv("TOKEN")
        if not token:
            raise ValueError("TOKEN not found in Windows Credential Manager or environment variables")
        
        # Инициализируем бота
        default_props = DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
        self.bot = Bot(token=token, default=default_props)
        storage = MemoryStorage()  # FSM storage
        self.dp = Dispatcher(storage=storage)
        
        # Инициализируем обработчики
        # Settings будет инициализирован позже, используем временные значения
        self.settings = None  # Будет установлен после инициализации Settings
        
        # Пытаемся получить settings сразу, если возможно
        try:
            self.settings = get_settings()
            logger.debug("Settings loaded during initialization")
        except RuntimeError:
            # Settings еще не инициализирован - это нормально
            logger.debug("Settings not yet initialized, will load later")
        
        self.employee_handler = EmployeeSearchHandler(db_pool)
        self.server_handler = ServerMonitorHandler(db_pool, self.bot)
        self.otrs_handler = OTRSHandler(db_pool, self.bot)
        self.auth_handler = AuthHandler(db_pool, self.bot, self.otrs_handler)
        self.deletion_repo = MessageDeletionRepository(db_pool)
        
        # Кэш доступности чатов
        self._chat_availability_cache: Dict[int, tuple] = {}
        
        # Ожидающие действия OTRS (когда пользователь должен ввести причину/комментарий)
        self.otrs_pending_actions: Dict[int, Dict] = {}  # user_id -> {action, ticket_id, message_id, chat_id, topic_id}
        
        # Регистрируем обработчики
        self._register_handlers()
        
        # Время запуска
        self.start_time = datetime.now()
    
    def _register_handlers(self):
        """Регистрирует все обработчики команд и сообщений."""
        
        # Команды (работают везде)
        self.dp.message.register(self.cmd_start, Command(commands=['start']))
        self.dp.message.register(self.cmd_botexec, Command(commands=['botexec']))
        self.dp.message.register(self.cmd_status, Command(commands=['status']))
        self.dp.message.register(self.cmd_mystats, Command(commands=['mystats']))
        self.dp.message.register(self.cmd_chatinfo, Command(commands=['chatinfo']))
        self.dp.message.register(self.cmd_testmsg, Command(commands=['testmsg']))
        self.dp.message.register(self.cmd_logout, Command(commands=['logout']))
        self.dp.message.register(self.cmd_otrs_leaders, Command(commands=['otrs_leaders']))
        self.dp.message.register(self.cmd_report, Command(commands=['report']))
        self.dp.message.register(self.cmd_monitor, Command(commands=['monitor']))
        
        # Callback queries
        self.dp.callback_query.register(self.handle_callback)
        
        # Обработка сообщений в топиках (регистрируем ПЕРВЫМИ, чтобы они обрабатывались раньше)
        # Регистрируем для всех групп, проверка chat_id будет внутри обработчиков
        # Это нужно, так как settings может быть еще не инициализирован при регистрации
        self.dp.message.register(self.handle_excel_topic_message, F.chat.type.in_(["group", "supergroup"]), F.text)
        self.dp.message.register(self.handle_ping_topic_message, F.chat.type.in_(["group", "supergroup"]), F.text)
        
        # Текстовые сообщения (для авторизации и других целей)
        # Регистрируем ПОСЛЕ обработчиков топиков, чтобы они не перехватывали сообщения в группах
        self.dp.message.register(self.handle_text_message, F.text)
        
        # Логирование всех входящих сообщений (для отладки)
        self.dp.message.register(self._log_incoming_message)
    
    async def start(self):
        """Запускает бота."""
        logger.info("Starting Telegram Bot Service...")
        
        # Инициализируем settings если еще не инициализирован
        if not self.settings:
            self.settings = get_settings()
        
        # Очищаем Excel топик от старых сообщений
        try:
            await self.cleanup_excel_topic()
        except Exception as e:
            logger.error(f"Error during Excel topic cleanup: {e}", exc_info=True)
        
        # Отправляем сообщение о запуске
        await self._send_startup_message()
        
        # Запускаем OTRS интеграцию (если настроена)
        chat_id = await self._get_setting_int("TELEGRAM_CHAT_ID", -1)
        tasks_topic_id = await self._get_setting_int("TASKS_TOPIC_ID", 0)
        otrs_check_interval = await self._get_setting_int("OTRS_CHECK_INTERVAL", 60)
        
        if chat_id != -1 and tasks_topic_id > 0:
            try:
                success = await self.otrs_handler.start_integration(
                    chat_id=chat_id,
                    topic_id=tasks_topic_id,
                    check_interval=otrs_check_interval
                )
                if success:
                    logger.info(f"OTRS integration started for topic {tasks_topic_id}")
                else:
                    logger.warning("OTRS integration failed to start (check configuration)")
            except Exception as e:
                logger.error(f"Failed to start OTRS integration: {e}", exc_info=True)
        
        # Запускаем polling в фоне (не блокируем)
        logger.info("Starting polling...")
        try:
            await self.dp.start_polling(self.bot, skip_updates=True)
        except Exception as e:
            logger.error(f"Error in polling: {e}", exc_info=True)
            raise
        finally:
            logger.info("Telegram Bot Service polling stopped")
    
    async def stop(self):
        """Останавливает бота."""
        logger.info("Stopping Telegram Bot Service...")
        
        # Останавливаем OTRS интеграцию
        try:
            await self.otrs_handler.stop_integration()
            logger.info("OTRS integration stopped")
        except Exception as e:
            logger.error(f"Error stopping OTRS integration: {e}", exc_info=True)
        
        await self.dp.stop_polling()
        await self.bot.session.close()
        logger.info("Telegram Bot Service stopped")
    
    async def _send_startup_message(self):
        """Отправляет сообщение о запуске бота."""
        try:
            chat_id = await self._get_setting_int("TELEGRAM_CHAT_ID", -1)
            topic_id = await self._get_setting_int("BOT_TOPIC_ID", 0)
            startup_msg = await self._get_setting("BOT_STARTUP_MESSAGE", "🤖 Бот включился и готов к работе!")
            
            # Отправляем только если указан chat_id
            if chat_id != -1:
                # Экранируем специальные символы для Markdown V2
                from utils.formatters import escape_markdown_v2
                escaped_msg = escape_markdown_v2(startup_msg)
                
                try:
                    if topic_id > 0:
                        # Пытаемся отправить в топик
                        await self.bot.send_message(
                            chat_id=chat_id,
                            message_thread_id=topic_id,
                            text=escaped_msg,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        logger.info(f"Startup message sent to chat {chat_id}, topic {topic_id}")
                    else:
                        # Отправляем без топика
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=escaped_msg,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        logger.info(f"Startup message sent to chat {chat_id} (no topic)")
                except TelegramBadRequest as e:
                    if "message thread not found" in str(e):
                        # Топик не найден, отправляем без топика
                        logger.warning(f"Topic {topic_id} not found, sending startup message without topic")
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=escaped_msg,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        logger.info(f"Startup message sent to chat {chat_id} (topic {topic_id} not found)")
                    else:
                        raise
            else:
                logger.debug(f"Skipping startup message: chat_id={chat_id}, topic_id={topic_id}")
        except Exception as e:
            logger.warning(f"Failed to send startup message: {e}")
    
    # ============== Command Handlers ==============
    
    async def cmd_start(self, message: Message):
        """Обработчик команды /start."""
        logger.user_action(
            "cmd_start",
            user_id=message.from_user.id,
            username=message.from_user.username,
            chat_id=message.chat.id,
            chat_type=message.chat.type,
            chat_title=getattr(message.chat, 'title', None)
        )
        
        if message.chat.type == "private":
            await self.auth_handler.handle_start(message)
        else:
            await message.answer("Привет! Я бот технической поддержки.")
    
    async def cmd_botexec(self, message: Message):
        """Обработчик команды /botexec."""
        logger.user_action(
            "cmd_botexec",
            user_id=message.from_user.id,
            username=message.from_user.username,
            chat_id=message.chat.id,
            chat_type=message.chat.type,
            chat_title=getattr(message.chat, 'title', None),
            topic_id=message.message_thread_id
        )
        
        uptime = datetime.now() - self.start_time
        uptime_str = self._format_uptime(uptime)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Показать время работы", callback_data="show_uptime")]
        ])
        
        # Экранируем для Markdown V2
        from utils.formatters import escape_markdown_v2
        text = f"🤖 *Бот работает*\n\n⏱ Время работы: {escape_markdown_v2(uptime_str)}"
        await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    
    async def cmd_status(self, message: Message):
        """Обработчик команды /status (только в личных сообщениях)."""
        if message.chat.type != "private":
            return
        
        user_id = message.from_user.id
        user_info = await self.auth_handler.get_user_info(user_id)
        
        if not user_info:
            await message.answer("❌ Вы не авторизованы. Используйте /start для авторизации.")
            return
        
        email = user_info.get('otrs_email', 'Unknown')
        full_name = user_info.get('full_name', 'Unknown')
        verified_at = user_info.get('verified_at', 'Unknown')
        
        text = (
            f"✅ *Статус авторизации*\n\n"
            f"📧 Email: `{email}`\n"
            f"👤 ФИО: `{full_name}`\n"
            f"🕐 Авторизован: `{verified_at}`"
        )
        
        await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)
    
    async def cmd_mystats(self, message: Message):
        """Обработчик команды /mystats."""
        if message.chat.type != "private":
            return
        
        user_id = message.from_user.id
        stats = await self.otrs_handler.get_user_stats(user_id)
        
        if not stats:
            await message.answer("❌ Статистика недоступна.")
            return
        
        text = (
            f"📊 *Ваша статистика*\n\n"
            f"✅ Закрыто: `{stats.get('closed', 0)}`\n"
            f"❌ Отклонено: `{stats.get('rejected', 0)}`\n"
            f"📌 Назначено: `{stats.get('assigned', 0)}`\n"
            f"💬 Комментариев: `{stats.get('commented', 0)}`\n"
            f"📈 Всего: `{stats.get('total', 0)}`"
        )
        
        await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)
    
    async def cmd_chatinfo(self, message: Message):
        """Обработчик команды /chatinfo - показывает информацию о текущем чате."""
        import os
        from utils.formatters import escape_markdown_v2
        
        chat = message.chat
        
        # Формируем сообщение с правильным экранированием
        parts = [
            "📋 *Информация о чате*",
            "",
            f"🆔 Chat ID: `{chat.id}`",
            f"📝 Тип: `{escape_markdown_v2(chat.type)}`"
        ]
        
        if hasattr(chat, 'title') and chat.title:
            parts.append(f"📌 Название: `{escape_markdown_v2(chat.title)}`")
        
        if message.message_thread_id:
            parts.append(f"💬 Topic ID: `{message.message_thread_id}`")
        
        # Получаем настройки из БД
        if self.settings:
            target_chat_id = await self.settings.get("TELEGRAM_CHAT_ID", "-1")
            excel_topic_id = await self.settings.get("EXCEL_TOPIC_ID", "0")
            ping_topic_id = await self.settings.get("PING_TOPIC_ID", "0")
            bot_topic_id = await self.settings.get("BOT_TOPIC_ID", "0")
        else:
            target_chat_id = os.getenv("TELEGRAM_CHAT_ID", "-1")
            excel_topic_id = os.getenv("EXCEL_TOPIC_ID", "0")
            ping_topic_id = os.getenv("PING_TOPIC_ID", "0")
            bot_topic_id = os.getenv("BOT_TOPIC_ID", "0")
        
        parts.extend([
            "",
            "⚙️ *Настройки бота:*",
            f"🎯 Целевой Chat ID: `{escape_markdown_v2(str(target_chat_id))}`",
            f"📊 Excel Topic ID: `{escape_markdown_v2(str(excel_topic_id))}`",
            f"🏓 Ping Topic ID: `{escape_markdown_v2(str(ping_topic_id))}`",
            f"🤖 Bot Topic ID: `{escape_markdown_v2(str(bot_topic_id))}`"
        ])
        
        # Проверяем совпадение
        if str(chat.id) == str(target_chat_id):
            parts.append("")
            parts.append("✅ *Это целевой чат\\!*")
        else:
            parts.append("")
            parts.append("⚠️ *Это НЕ целевой чат*")
        
        if message.message_thread_id:
            topic_id = str(message.message_thread_id)
            parts.append("")
            if topic_id == str(excel_topic_id):
                parts.append("✅ *Это топик Excel \\(поиск сотрудников\\)*")
            elif topic_id == str(ping_topic_id):
                parts.append("✅ *Это топик Ping \\(мониторинг\\)*")
            elif topic_id == str(bot_topic_id):
                parts.append("✅ *Это топик Bot \\(сообщения бота\\)*")
        
        chat_info = "\n".join(parts)
        await message.answer(chat_info, parse_mode=ParseMode.MARKDOWN_V2)
    
    async def cmd_testmsg(self, message: Message):
        """Обработчик команды /testmsg - отправляет тестовое сообщение в целевой чат."""
        import os
        from utils.formatters import escape_markdown_v2
        
        if message.chat.type == "private":
            # В личных сообщениях отправляем в целевой чат
            if self.settings:
                target_chat_id = int(await self.settings.get("TELEGRAM_CHAT_ID", "-1"))
                bot_topic_id = int(await self.settings.get("BOT_TOPIC_ID", "0"))
            else:
                target_chat_id = int(os.getenv("TELEGRAM_CHAT_ID", "-1"))
                bot_topic_id = int(os.getenv("BOT_TOPIC_ID", "0"))
            
            if target_chat_id == -1:
                await message.answer("❌ TELEGRAM_CHAT_ID не настроен в БД")
                return
            
            try:
                user_name = message.from_user.full_name or message.from_user.username or "Unknown"
                time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                test_msg_text = f"🧪 Тестовое сообщение от {user_name}\n⏰ Время: {time_str}"
                test_msg_escaped = escape_markdown_v2(test_msg_text)
                
                # Пытаемся отправить в топик, если указан
                if bot_topic_id > 0:
                    try:
                        await self.bot.send_message(
                            chat_id=target_chat_id,
                            message_thread_id=bot_topic_id,
                            text=f"🧪 *Тестовое сообщение*\n\n{test_msg_escaped}",
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        response = f"✅ Сообщение отправлено в чат `{target_chat_id}`, топик `{bot_topic_id}`"
                    except TelegramBadRequest as e:
                        if "message thread not found" in str(e):
                            # Топик не найден, отправляем без топика
                            logger.warning(f"Topic {bot_topic_id} not found, sending without topic")
                            await self.bot.send_message(
                                chat_id=target_chat_id,
                                text=f"🧪 *Тестовое сообщение*\n\n{test_msg_escaped}",
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            response = f"✅ Сообщение отправлено в чат `{target_chat_id}` \\(топик не найден, отправлено без топика\\)"
                        else:
                            raise
                else:
                    await self.bot.send_message(
                        chat_id=target_chat_id,
                        text=f"🧪 *Тестовое сообщение*\n\n{test_msg_escaped}",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    response = f"✅ Сообщение отправлено в чат `{target_chat_id}` \\(без топика\\)"
                
                await message.answer(response, parse_mode=ParseMode.MARKDOWN_V2)
                logger.info("Test message sent", context={
                    'chat_id': target_chat_id,
                    'topic_id': bot_topic_id,
                    'user_id': message.from_user.id,
                    'username': message.from_user.username
                })
            except Exception as e:
                error_msg = f"❌ Ошибка отправки: {escape_markdown_v2(str(e)[:100])}"
                logger.error(f"Failed to send test message: {e}", exc_info=True)
                try:
                    await message.answer(error_msg, parse_mode=ParseMode.MARKDOWN_V2)
                except:
                    # Если не получается с Markdown, отправляем без форматирования
                    await message.answer(f"❌ Ошибка отправки: {str(e)[:200]}")
        else:
            # В группе просто подтверждаем
            await message.answer("✅ Команда получена! Используйте /testmsg в личных сообщениях для отправки тестового сообщения.")
    
    async def cmd_logout(self, message: Message):
        """Обработчик команды /logout - выход из системы (только в личных сообщениях)."""
        if message.chat.type != "private":
            return
        
        user_id = message.from_user.id
        user_name = message.from_user.full_name or message.from_user.first_name
        
        # Проверяем, авторизован ли пользователь
        user_info = await self.auth_handler.get_user_info(user_id)
        if not user_info:
            await message.answer("ℹ️ Вы не авторизованы.")
            return
        
        # Выходим из системы
        await self.auth_handler.logout(user_id)
        
        await message.answer(
            f"👋 *До свидания, {user_name}*\n\n"
            f"Вы вышли из системы заявок\\.\n\n"
            f"Для повторной авторизации отправьте корпоративный email\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    
    async def cmd_otrs_leaders(self, message: Message):
        """Обработчик команды /otrs_leaders - показывает таблицу лидеров OTRS."""
        from datetime import timedelta
        
        async with self.db_pool.acquire() as conn:
            # Получаем статистику за неделю
            week_ago = datetime.now() - timedelta(days=7)
            
            week_stats_row = await conn.fetchrow("""
                SELECT 
                    COUNT(*) FILTER (WHERE action_type = 'closed') as closed,
                    COUNT(*) FILTER (WHERE action_type = 'rejected') as rejected,
                    COUNT(*) FILTER (WHERE action_type = 'assigned') as assigned,
                    COUNT(*) FILTER (WHERE action_type = 'commented') as commented,
                    COUNT(*) as total
                FROM otrs.otrs_metrics
                WHERE action_time >= $1
            """, week_ago)
            
            week_stats = {
                'closed': week_stats_row['closed'] if week_stats_row else 0,
                'rejected': week_stats_row['rejected'] if week_stats_row else 0,
                'assigned': week_stats_row['assigned'] if week_stats_row else 0,
                'commented': week_stats_row['commented'] if week_stats_row else 0,
            }
            
            # Получаем лидеров по закрытым заявкам
            leaderboard_rows = await conn.fetch("""
                SELECT 
                    tu.telegram_id,
                    tu.telegram_username,
                    ou.otrs_email,
                    COUNT(*) as count
                FROM otrs.otrs_metrics om
                JOIN telegram.telegram_users tu ON om.telegram_user_id = tu.id
                LEFT JOIN otrs.otrs_users ou ON ou.telegram_user_id = tu.id
                WHERE om.action_type = 'closed' AND om.action_time >= $1
                GROUP BY tu.telegram_id, tu.telegram_username, ou.otrs_email
                ORDER BY count DESC
                LIMIT 5
            """, week_ago)
        
        text_parts = [
            "🏆 *Топ по закрытым заявкам*",
            "",
            f"📅 За последние 7 дней:",
            f"✅ Закрыто: `{week_stats['closed']}`",
            f"❌ Отклонено: `{week_stats['rejected']}`",
            f"👤 Назначено: `{week_stats['assigned']}`",
            f"💬 Комментариев: `{week_stats['commented']}`",
            "",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        if leaderboard_rows:
            text_parts.append("🥇 *Лидеры по закрытию:*")
            text_parts.append("")
            medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
            
            from utils.formatters import escape_markdown_v2
            for i, leader in enumerate(leaderboard_rows):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                name = leader['telegram_username'] or leader['otrs_email'] or 'Unknown'
                name_escaped = escape_markdown_v2(name)
                count = leader['count']
                text_parts.append(f"{medal} {name_escaped}: `{count}`")
        else:
            text_parts.append("📭 Пока нет данных")
        
        text = "\n".join(text_parts)
        await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)
        
        # Удаляем команду если в группе
        if message.chat.type != "private":
            topic_id = message.message_thread_id
            if self.settings:
                user_delete_delay = int(await self.settings.get("USER_MESSAGE_DELETE_DELAY", "30"))
            else:
                import os
                user_delete_delay = int(os.getenv("USER_MESSAGE_DELETE_DELAY", "30"))
            
            asyncio.create_task(self._delete_message_later(
                message.chat.id, message.message_id, topic_id, user_delete_delay
            ))
    
    async def cmd_report(self, message: Message):
        """Обработчик команды /report - показывает еженедельный отчёт OTRS."""
        from datetime import timedelta
        
        # Определяем период (прошлая неделя: понедельник-воскресенье)
        today = datetime.now().date()
        days_since_monday = today.weekday()  # 0 = понедельник
        last_monday = today - timedelta(days=days_since_monday + 7)
        last_sunday = last_monday + timedelta(days=6)
        
        start_date = datetime.combine(last_monday, datetime.min.time())
        end_date = datetime.combine(last_sunday, datetime.max.time())
        
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
        from utils.formatters import escape_markdown_v2
        
        start_str = start_date.strftime('%d.%m.%Y')
        end_str = end_date.strftime('%d.%m.%Y')
        
        text_parts = [
            "📊 *ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ OTRS*",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📅 Период: *{start_str} — {end_str}*",
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
            "📈 *Общая статистика:*",
            "┌─────────────────────",
            f"│ ✅ Закрыто:     *{totals['closed']}*",
            f"│ ❌ Отклонено:   *{totals['rejected']}*",
            f"│ 👤 Назначено:   *{totals['assigned']}*",
            f"│ 💬 Комментариев: *{totals['commented']}*",
            "└─────────────────────",
            f"📊 Всего действий: *{totals['total']}*",
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
            text_parts.append("🏆 *Рейтинг по закрытым заявкам:*")
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
                name_escaped = escape_markdown_v2(name)
                
                details = []
                if user['closed'] > 0:
                    details.append(f"✅{user['closed']}")
                if user['rejected'] > 0:
                    details.append(f"❌{user['rejected']}")
                if user['commented'] > 0:
                    details.append(f"💬{user['commented']}")
                
                details_str = " ".join(details)
                text_parts.append(f"{medal} *{name_escaped}*: {details_str}")
            
            if not any(u['closed'] > 0 for u in sorted_users):
                text_parts.append("   _Нет закрытых заявок за период_")
        else:
            text_parts.append("📭 _Нет данных за указанный период_")
        
        text_parts.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "🤖 _Автоматический отчёт Telegram Bot_"
        ])
        
        text = "\n".join(text_parts)
        
        # В личных чатах отправляем напрямую
        if message.chat.type == "private":
            await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)
            # Удаляем команду
            topic_id = message.message_thread_id
            if self.settings:
                user_delete_delay = int(await self.settings.get("USER_MESSAGE_DELETE_DELAY", "30"))
            else:
                import os
                user_delete_delay = int(os.getenv("USER_MESSAGE_DELETE_DELAY", "30"))
            
            asyncio.create_task(self._delete_message_later(
                message.chat.id, message.message_id, topic_id, user_delete_delay
            ))
    
    async def cmd_monitor(self, message: Message):
        """Обработчик команды /monitor - управление мониторингом: /monitor start|stop|status."""
        args = message.text.split()
        action = args[1].lower() if len(args) > 1 else "status"
        
        # TODO: Реализовать управление мониторингом через ServerMonitorHandler
        if action == "start":
            await message.reply("⚠️ Мониторинг будет запущен автоматически при старте бота", parse_mode="HTML")
        elif action == "stop":
            await message.reply("⚠️ Мониторинг будет остановлен при остановке бота", parse_mode="HTML")
        else:  # status
            await message.reply("📊 *Статус мониторинга:* ⚠️ В разработке", parse_mode=ParseMode.MARKDOWN_V2)
        
        # Удаляем команду
        if message.chat.type != "private":
            topic_id = message.message_thread_id
            if self.settings:
                user_delete_delay = int(await self.settings.get("USER_MESSAGE_DELETE_DELAY", "30"))
            else:
                import os
                user_delete_delay = int(os.getenv("USER_MESSAGE_DELETE_DELAY", "30"))
            
            asyncio.create_task(self._delete_message_later(
                message.chat.id, message.message_id, topic_id, user_delete_delay
            ))
    
    async def _log_incoming_message(self, message: Message):
        """Логирует все входящие сообщения для отладки (только для групп)."""
        # Логируем только сообщения в группах, не команды
        try:
            if message.chat.type in ["group", "supergroup"]:
                if not (message.text and message.text.startswith('/')):
                    # Логируем только некомандные сообщения в группах
                    logger.debug(
                        f"Group message: chat_id={message.chat.id}, "
                        f"topic_id={message.message_thread_id}, "
                        f"text={message.text[:50] if message.text else 'N/A'}"
                    )
        except Exception as e:
            logger.debug(f"Error logging message: {e}")
    
    # ============== Callback Handlers ==============
    
    async def handle_callback(self, callback: CallbackQuery):
        """Обработчик callback queries."""
        data = callback.data
        
        if data == "show_uptime":
            uptime = datetime.now() - self.start_time
            uptime_str = self._format_uptime(uptime)
            await callback.answer(f"Время работы: {uptime_str}", show_alert=False)
            await callback.message.edit_text(
                f"🤖 *Бот работает*\n\n⏱ Время работы: {uptime_str}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        elif data.startswith("auth_") or data.startswith("lobby_"):
            await self.auth_handler.handle_callback(callback)
        elif data.startswith("otrs_"):
            await self.handle_otrs_callback(callback)
        else:
            await callback.answer("Неизвестная команда")
    
    async def handle_otrs_callback(self, callback: CallbackQuery):
        """Обработчик callback queries для OTRS действий."""
        action_data = callback.data.split(":")
        action = action_data[0].replace("otrs_", "")
        ticket_id = int(action_data[1]) if len(action_data) > 1 else None
        
        user_id = callback.from_user.id
        user_name = callback.from_user.full_name or callback.from_user.first_name
        
        # Получаем клиент и менеджер OTRS
        otrs_client = self.otrs_handler.get_client()
        otrs_manager = self.otrs_handler.get_manager()
        
        if not otrs_client or not otrs_manager:
            await callback.answer("❌ OTRS интеграция не активна", show_alert=True)
            return
        
        # Действия, требующие авторизации
        actions_requiring_auth = ["assign", "close", "reject", "comment", "reassign"]
        
        if action in actions_requiring_auth:
            if not await self.auth_handler.is_authenticated(user_id):
                await callback.answer(
                    "🔐 Для этого действия необходима авторизация.\n"
                    "Напишите боту в личные сообщения для авторизации.",
                    show_alert=True
                )
                return
        
        # Получаем email авторизованного пользователя для логирования
        user_email = ""
        if action in actions_requiring_auth:
            user_info = await self.auth_handler.get_user_info(user_id)
            user_email = user_info.get('otrs_email', '') if user_info else ''
            if user_email:
                user_name = f"{user_name} ({user_email})"
        
        if action == "refresh":
            # Обновить информацию о тикете (не требует авторизации)
            await callback.answer("🔄 Обновляю...")
            ticket = await otrs_client.get_ticket(ticket_id)
            if ticket:
                await otrs_manager.update_ticket_message(ticket)
                await callback.answer("✅ Обновлено")
            else:
                await callback.answer("❌ Не удалось получить тикет", show_alert=True)
        
        elif action == "refresh_private":
            # Обновить личное сообщение о тикете
            await callback.answer("🔄 Обновляю...")
            ticket = await otrs_client.get_ticket(ticket_id)
            if ticket:
                try:
                    from handlers.otrs_manager import OTRSManager
                    private_text = otrs_manager.build_ticket_message(ticket)
                    private_text = f"📌 <b>Ваша заявка в работе:</b>\n\n{private_text}"
                    
                    private_kb = otrs_manager.build_ticket_keyboard(ticket)
                    
                    await callback.message.edit_text(
                        text=private_text,
                        parse_mode="HTML",
                        reply_markup=private_kb
                    )
                    await callback.answer("✅ Обновлено")
                except Exception as e:
                    logger.error(f"Failed to update private ticket: {e}")
                    await callback.answer("❌ Ошибка обновления", show_alert=True)
            else:
                await callback.answer("❌ Тикет не найден (возможно закрыт)", show_alert=True)
        
        elif action == "assign":
            # Взять тикет в работу - назначить на пользователя
            await callback.answer("⏳ Ищу агента в OTRS...")
            
            if not user_email:
                await callback.answer("❌ Не найден email для назначения", show_alert=True)
                return
            
            # Ищем агента в OTRS по email
            otrs_login = await otrs_client.get_agent_login_by_email(user_email)
            
            if not otrs_login:
                await callback.answer(
                    f"❌ Агент с email {user_email} не найден в OTRS!\n\n"
                    "Убедитесь, что ваш email зарегистрирован в OTRS как агент.",
                    show_alert=True
                )
                return
            
            # Назначаем тикет на найденного агента
            success, error_msg = await otrs_client.update_ticket(
                ticket_id=ticket_id,
                state="open",
                owner=otrs_login,
                article_body=f"Заявка назначена на агента {otrs_login} ({user_email}) через Telegram Bot"
            )
            
            if success:
                ticket = await otrs_client.get_ticket(ticket_id)
                if ticket:
                    await otrs_manager.update_ticket_message(ticket)
                    
                    # Записываем метрику
                    async with self.db_pool.acquire() as conn:
                        telegram_user_row = await conn.fetchrow("""
                            SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                        """, user_id)
                        if telegram_user_row:
                            telegram_user_id = telegram_user_row['id']
                            from database.repositories.ticket_repository import TicketRepository
                            ticket_repo = TicketRepository(self.db_pool)
                            await ticket_repo.record_otrs_action(
                                telegram_user_id=telegram_user_id,
                                action_type="assigned",
                                ticket_id=ticket_id,
                                ticket_number=ticket.ticket_number,
                                ticket_title=ticket.title
                            )
                    
                    logger.info(f"Ticket #{ticket.ticket_number} assigned to OTRS agent: {otrs_login}")
                    
                    # Отправляем дубликат в личку пользователю
                    try:
                        private_text = otrs_manager.build_ticket_message(ticket)
                        private_text = f"📌 <b>Вы взяли заявку в работу:</b>\n\n{private_text}"
                        
                        private_kb = otrs_manager.build_ticket_keyboard(ticket)
                        
                        private_msg = await self.bot.send_message(
                            chat_id=user_id,
                            text=private_text,
                            parse_mode="HTML",
                            reply_markup=private_kb
                        )
                        
                        # Сохраняем ID сообщения в БД
                        from database.repositories.ticket_repository import TicketRepository
                        ticket_repo = TicketRepository(self.db_pool)
                        await ticket_repo.save_private_ticket(
                            telegram_id=user_id,
                            ticket_id=ticket_id,
                            ticket_number=ticket.ticket_number,
                            message_id=private_msg.message_id
                        )
                        logger.info(f"Sent private ticket message to user {user_id}: msg_id={private_msg.message_id}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to send private ticket message: {e}")
                
                await callback.answer(f"✅ Заявка назначена на {otrs_login}")
            else:
                await callback.answer(
                    f"❌ Ошибка назначения в OTRS:\n{error_msg[:150]}",
                    show_alert=True
                )
        
        elif action == "close":
            # Проверяем, что заявка назначена на этого пользователя
            ticket = await otrs_client.get_ticket(ticket_id)
            if ticket:
                user_otrs_login = await otrs_client.get_agent_login_by_email(user_email) if user_email else None
                ticket_owner = ticket.owner.lower() if ticket.owner else ""
                
                if user_otrs_login and ticket_owner and ticket_owner not in ["", "telegram_bot", "root@localhost"]:
                    if user_otrs_login.lower() != ticket_owner:
                        await callback.answer(
                            f"❌ Эта заявка назначена на {ticket.owner}.\n"
                            f"Только исполнитель может закрыть заявку.",
                            show_alert=True
                        )
                        return
            
            # Запрашиваем причину закрытия
            await callback.answer()
            import os
            if self.settings:
                tasks_topic_id = int(await self.settings.get("TASKS_TOPIC_ID", "0"))
            else:
                tasks_topic_id = int(os.getenv("TASKS_TOPIC_ID", "0"))
            
            self.otrs_pending_actions[user_id] = {
                "action": "close",
                "ticket_id": ticket_id,
                "message_id": callback.message.message_id,
                "chat_id": callback.message.chat.id,
                "topic_id": callback.message.message_thread_id
            }
            sent_msg = await self.bot.send_message(
                chat_id=callback.message.chat.id,
                text=f"✏️ <b>Закрытие заявки #{ticket_id}</b>\n\nНапишите причину закрытия:",
                parse_mode="HTML",
                message_thread_id=callback.message.message_thread_id,
                reply_to_message_id=callback.message.message_id
            )
            # Удаляем промежуточное сообщение через 30 секунд
            if callback.message.message_thread_id == tasks_topic_id:
                asyncio.create_task(self._delete_message_later(
                    callback.message.chat.id, 
                    sent_msg.message_id, 
                    callback.message.message_thread_id,
                    30
                ))
        
        elif action == "reject":
            # Проверяем, что заявка назначена на этого пользователя (или не назначена)
            ticket = await otrs_client.get_ticket(ticket_id)
            if ticket:
                user_otrs_login = await otrs_client.get_agent_login_by_email(user_email) if user_email else None
                ticket_owner = ticket.owner.lower() if ticket.owner else ""
                
                if user_otrs_login and ticket_owner and ticket_owner not in ["", "telegram_bot", "root@localhost"]:
                    if user_otrs_login.lower() != ticket_owner:
                        await callback.answer(
                            f"❌ Эта заявка назначена на {ticket.owner}.\n"
                            f"Только исполнитель может отклонить заявку.",
                            show_alert=True
                        )
                        return
            
            # Запрашиваем причину отклонения
            await callback.answer()
            import os
            if self.settings:
                tasks_topic_id = int(await self.settings.get("TASKS_TOPIC_ID", "0"))
            else:
                tasks_topic_id = int(os.getenv("TASKS_TOPIC_ID", "0"))
            
            self.otrs_pending_actions[user_id] = {
                "action": "reject",
                "ticket_id": ticket_id,
                "message_id": callback.message.message_id,
                "chat_id": callback.message.chat.id,
                "topic_id": callback.message.message_thread_id
            }
            sent_msg = await self.bot.send_message(
                chat_id=callback.message.chat.id,
                text=f"✏️ <b>Отклонение заявки #{ticket_id}</b>\n\nНапишите причину отклонения:",
                parse_mode="HTML",
                message_thread_id=callback.message.message_thread_id,
                reply_to_message_id=callback.message.message_id
            )
            # Удаляем промежуточное сообщение через 30 секунд
            if callback.message.message_thread_id == tasks_topic_id:
                asyncio.create_task(self._delete_message_later(
                    callback.message.chat.id, 
                    sent_msg.message_id, 
                    callback.message.message_thread_id,
                    30
                ))
        
        elif action == "reassign":
            # Переназначить тикет на бота (освободить для других агентов)
            await callback.answer("⏳ Освобождаю заявку...")
            
            success, error_msg = await otrs_client.update_ticket(
                ticket_id=ticket_id,
                owner="telegram_bot",
                state="new",
                article_body=f"Заявка освобождена через Telegram Bot (пользователь: {user_name})"
            )
            
            if success:
                ticket = await otrs_client.get_ticket(ticket_id)
                if ticket:
                    await otrs_manager.update_ticket_message(ticket)
                await callback.answer("✅ Заявка освобождена. Теперь её может взять другой агент.")
            else:
                await callback.answer(f"❌ Ошибка: {error_msg[:100]}", show_alert=True)
        
        elif action == "comment":
            # Запрашиваем комментарий
            await callback.answer()
            import os
            if self.settings:
                tasks_topic_id = int(await self.settings.get("TASKS_TOPIC_ID", "0"))
            else:
                tasks_topic_id = int(os.getenv("TASKS_TOPIC_ID", "0"))
            
            self.otrs_pending_actions[user_id] = {
                "action": "comment",
                "ticket_id": ticket_id,
                "message_id": callback.message.message_id,
                "chat_id": callback.message.chat.id,
                "topic_id": callback.message.message_thread_id
            }
            sent_msg = await self.bot.send_message(
                chat_id=callback.message.chat.id,
                text=f"✏️ <b>Комментарий к заявке #{ticket_id}</b>\n\nНапишите ваш комментарий:",
                parse_mode="HTML",
                message_thread_id=callback.message.message_thread_id,
                reply_to_message_id=callback.message.message_id
            )
            # Удаляем промежуточное сообщение через 30 секунд
            if callback.message.message_thread_id == tasks_topic_id:
                asyncio.create_task(self._delete_message_later(
                    callback.message.chat.id, 
                    sent_msg.message_id, 
                    callback.message.message_thread_id,
                    30
                ))
        
        else:
            await callback.answer("❌ Неизвестное действие OTRS", show_alert=True)
    
    # ============== Topic Message Handlers ==============
    
    async def handle_excel_topic_message(self, message: Message):
        """Обработчик сообщений в топике Excel (поиск сотрудников)."""
        import os
        from datetime import timedelta
        
        # Логируем все сообщения в группах для отладки
        chat_id = message.chat.id
        topic_id = message.message_thread_id
        user_id = message.from_user.id if message.from_user else None
        username = message.from_user.username if message.from_user else None
        
        logger.debug("Excel handler: Received message", context={
            'chat_id': chat_id,
            'topic_id': topic_id,
            'chat_type': message.chat.type,
            'user_id': user_id,
            'username': username,
            'message_preview': message.text[:50] if message.text else None
        })
        
        # Проверяем, что это нужный чат
        if self.settings:
            target_chat_id = int(await self.settings.get("TELEGRAM_CHAT_ID", "-1"))
            excel_delete_delay = int(await self.settings.get("EXCEL_MESSAGE_DELETE_DELAY", "300"))
        else:
            target_chat_id = int(os.getenv("TELEGRAM_CHAT_ID", "-1"))
            excel_delete_delay = int(os.getenv("EXCEL_MESSAGE_DELETE_DELAY", "300"))
        
        if chat_id != target_chat_id:
            logger.debug("Excel topic: Skipping message - wrong chat", context={
                'received_chat_id': chat_id,
                'expected_chat_id': target_chat_id
            })
            return
        
        # Проверяем, что это нужный топик
        if self.settings:
            excel_topic_id = int(await self.settings.get("EXCEL_TOPIC_ID", "0"))
        else:
            excel_topic_id = int(os.getenv("EXCEL_TOPIC_ID", "0"))
        
        if topic_id != excel_topic_id:
            logger.debug("Excel topic: Skipping message - wrong topic", context={
                'received_topic_id': topic_id,
                'expected_topic_id': excel_topic_id
            })
            return
        
        logger.info("Excel topic: Processing message", context={
            'chat_id': chat_id,
            'topic_id': topic_id,
            'user_id': user_id,
            'username': username
        })
        
        # Игнорируем команды
        if message.text and message.text.startswith('/'):
            logger.debug(f"Excel topic: Ignoring command: {message.text}")
            return
        
        # Сохраняем сообщение пользователя в БД и планируем удаление через 5 минут
        delete_time = datetime.now() + timedelta(seconds=excel_delete_delay)
        await self.deletion_repo.add_pending_deletion(chat_id, message.message_id, delete_time, topic_id=topic_id)
        asyncio.create_task(self._delete_message_later(
            chat_id, message.message_id, topic_id, excel_delete_delay
        ))
        logger.info(f"Will delete user message ID={message.message_id} after {excel_delete_delay} seconds.")
        
        # Обрабатываем поиск
        query = message.text
        if not query:
            logger.debug("Excel topic: Empty query, skipping")
            return
        
        try:
            logger.info("Excel topic: Starting employee search", context={
                'query': query,
                'user_id': user_id,
                'chat_id': chat_id,
                'topic_id': topic_id
            })
            results = await self.employee_handler.search(query)
            
            logger.info("Excel topic: Search completed", context={
                'query': query,
                'results_count': len(results),
                'user_id': user_id
            })
            
            if not results:
                response = "❌ Совпадений не найдено.\n\n⚠️ Возможно, в базе данных нет данных сотрудников. Проверьте: `python scripts\\check_employees.py`"
            else:
                response = self._format_employee_results(results)
            
            # Отправляем ответ БЕЗ УВЕДОМЛЕНИЯ (silent)
            sent_msg = await self.bot.send_message(
                chat_id=chat_id,
                text=response,
                parse_mode=ParseMode.HTML,
                message_thread_id=topic_id,
                reply_to_message_id=message.message_id,
                disable_notification=True  # Без уведомления!
            )
            logger.info("Excel search result sent", context={
                'query': query,
                'results_count': len(results),
                'message_id': sent_msg.message_id if sent_msg else None
            })
            
            # Сохраняем ID ответа бота в БД и планируем удаление
            if sent_msg:
                await self.deletion_repo.add_pending_deletion(
                    sent_msg.chat.id, sent_msg.message_id, delete_time, topic_id=topic_id
                )
                asyncio.create_task(self._delete_message_later(
                    sent_msg.chat.id, sent_msg.message_id, topic_id, excel_delete_delay
                ))
        
        except Exception as e:
            logger.error(f"Error handling Excel topic message: {e}", exc_info=True)
            try:
                error_msg = await message.reply("❌ Ошибка при поиске. Попробуйте позже.")
                if error_msg:
                    asyncio.create_task(self._delete_message_later(
                        error_msg.chat.id, error_msg.message_id, topic_id, excel_delete_delay
                    ))
            except:
                pass
    
    async def handle_ping_topic_message(self, message: Message):
        """Обработчик сообщений в топике мониторинга."""
        import os
        
        # Проверяем, что это нужный чат
        chat_id = message.chat.id
        if self.settings:
            target_chat_id = int(await self.settings.get("TELEGRAM_CHAT_ID", "-1"))
        else:
            target_chat_id = int(os.getenv("TELEGRAM_CHAT_ID", "-1"))
        
        if chat_id != target_chat_id:
            logger.debug(f"Skipping message from chat {chat_id}, expected {target_chat_id}")
            return
        
        # Проверяем, что это нужный топик
        topic_id = message.message_thread_id
        
        if self.settings:
            ping_topic_id = int(await self.settings.get("PING_TOPIC_ID", "0"))
        else:
            ping_topic_id = int(os.getenv("PING_TOPIC_ID", "0"))
        
        if topic_id != ping_topic_id:
            logger.debug(f"Skipping message from topic {topic_id}, expected {ping_topic_id}")
            return
        
        # Здесь можно добавить обработку команд для мониторинга
        pass
    
    # ============== Helper Methods ==============
    
    async def _get_setting(self, key: str, default: Any = None, env_key: Optional[str] = None) -> Any:
        """
        Получает настройку из БД или .env.
        
        Args:
            key: Ключ настройки в БД
            default: Значение по умолчанию
            env_key: Ключ в .env (если отличается от key)
            
        Returns:
            Значение настройки
        """
        import os
        env_key = env_key or key
        
        # Пытаемся прочитать из БД
        if self.settings:
            try:
                value = await self.settings.get(key, None)
                if value is not None:
                    return value
            except Exception as e:
                logger.debug(f"Failed to read {key} from DB: {e}, falling back to .env")
        
        # Fallback на .env
        return os.getenv(env_key, default)
    
    async def _get_setting_int(self, key: str, default: int = 0, env_key: Optional[str] = None) -> int:
        """Получает целочисленную настройку из БД или .env."""
        value = await self._get_setting(key, default, env_key)
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"Invalid integer value for {key}: {value}, using default: {default}")
            return default
    
    def _format_uptime(self, uptime: datetime) -> str:
        """Форматирует время работы."""
        total_seconds = int(uptime.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        if days > 0:
            return f"{days}д {hours}ч {minutes}м"
        elif hours > 0:
            return f"{hours}ч {minutes}м"
        else:
            return f"{minutes}м"
    
    def _format_employee_results(self, results: list) -> str:
        """Форматирует результаты поиска сотрудников."""
        if not results:
            return "❌ Совпадений не найдено."
        
        # Ограничиваем количество результатов
        max_results = 20
        if len(results) > max_results:
            results = results[:max_results]
            warning = f"⚠️ Показано первых {max_results} из {len(results)} результатов.\n\n"
        else:
            warning = ""
        
        # Формируем таблицу
        table_rows = []
        for emp in results:
            row = (
                f"👤 <b>{escape_html(emp.get('full_name', 'N/A'))}</b>\n"
                f"   📁 {escape_html(emp.get('department', 'N/A'))}\n"
                f"   💻 {escape_html(emp.get('workstation', 'N/A'))}\n"
                f"   📞 {escape_html(emp.get('phone', 'N/A'))}\n"
                f"   🔐 {escape_html(emp.get('ad_account', 'N/A'))}\n"
            )
            if emp.get('notes'):
                row += f"   📝 {escape_html(emp.get('notes', ''))}\n"
            table_rows.append(row)
        
        return warning + "\n".join(table_rows)
    
    async def _delete_message_later(self, chat_id: int, message_id: int, topic_id: Optional[int], delay: int):
        """
        Удаляет сообщение через указанное время.
        Как в старом боте - проверяет topic_id и удаляет из БД после удаления.
        """
        if delay <= 0:
            return
        
        await asyncio.sleep(delay)
        
        try:
            # Проверяем, что topic_id разрешен (если указан)
            if topic_id is not None:
                # Получаем список разрешенных топиков из настроек
                import os
                if self.settings:
                    allowed_threads_str = await self.settings.get("ALLOWED_THREADS", "")
                else:
                    allowed_threads_str = os.getenv("ALLOWED_THREADS", "")
                
                if allowed_threads_str:
                    try:
                        allowed_threads = [int(x.strip()) for x in allowed_threads_str.split(',') if x.strip()]
                        if topic_id not in allowed_threads:
                            logger.debug(f"Topic {topic_id} not in ALLOWED_THREADS, skipping deletion of message ID={message_id}.")
                            await self.deletion_repo.remove_pending_deletion(chat_id, message_id)
                            return
                    except (ValueError, AttributeError):
                        pass  # Если не удалось распарсить, продолжаем
            
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Deleted message ID={message_id} in chat ID={chat_id}, topic {topic_id}.")
            
            # Удаляем из БД если было в очереди
            await self.deletion_repo.remove_pending_deletion(chat_id, message_id)
        except TelegramBadRequest as e:
            if "message to delete not found" in str(e).lower():
                logger.debug(f"Could not delete message {message_id}: {e}")
            else:
                logger.error(f"Error deleting message ID={message_id} in chat ID={chat_id}, topic {topic_id}: {e}")
            # Удаляем из БД в любом случае
            await self.deletion_repo.remove_pending_deletion(chat_id, message_id)
        except Exception as e:
            logger.error(f"Error deleting message ID={message_id} in chat ID={chat_id}, topic {topic_id}: {e}")
            # Удаляем из БД в любом случае
            await self.deletion_repo.remove_pending_deletion(chat_id, message_id)
    
    async def handle_text_message(self, message: Message):
        """Обработчик текстовых сообщений."""
        user_id = message.from_user.id
        user_text = message.text.strip() if message.text else ""
        
        # СНАЧАЛА проверяем ожидающие действия OTRS (в любом чате)
        if user_id in self.otrs_pending_actions:
            pending = self.otrs_pending_actions.pop(user_id)
            action = pending["action"]
            ticket_id = pending["ticket_id"]
            ticket_msg_id = pending.get("message_id")
            pending_chat_id = pending.get("chat_id")
            pending_topic_id = pending.get("topic_id")
            
            user_name = message.from_user.full_name or message.from_user.first_name
            reason = user_text
            
            otrs_client = self.otrs_handler.get_client()
            otrs_manager = self.otrs_handler.get_manager()
            
            # Получаем email для логирования
            user_info = await self.auth_handler.get_user_info(user_id)
            user_email = user_info.get('otrs_email', '') if user_info else ''
            if user_email:
                user_name_full = f"{user_name} ({user_email})"
            else:
                user_name_full = user_name
            
            if otrs_client and otrs_manager:
                success = False
                error_msg = ""
                action_type = None
                
                if action == "close":
                    success, error_msg = await otrs_client.update_ticket(
                        ticket_id=ticket_id,
                        state="closed successful",
                        article_body=f"Закрыто: {user_name_full} (Telegram)\n\nПричина: {reason}"
                    )
                    status_text = "✅ Заявка закрыта"
                    action_type = "closed"
                
                elif action == "reject":
                    success, error_msg = await otrs_client.update_ticket(
                        ticket_id=ticket_id,
                        state="closed unsuccessful",
                        article_body=f"Отклонено: {user_name_full} (Telegram)\n\nПричина: {reason}"
                    )
                    status_text = "❌ Заявка отклонена"
                    action_type = "rejected"
                
                elif action == "comment":
                    success, error_msg = await otrs_client.update_ticket(
                        ticket_id=ticket_id,
                        article_body=f"Комментарий: {user_name_full} (Telegram)\n\n{reason}"
                    )
                    status_text = "💬 Комментарий добавлен"
                    action_type = "commented"
                
                if success:
                    # Получаем информацию о тикете для метрик
                    ticket = await otrs_client.get_ticket(ticket_id)
                    ticket_number = ticket.ticket_number if ticket else str(ticket_id)
                    ticket_title = ticket.title if ticket else ""
                    
                    # Записываем метрику
                    async with self.db_pool.acquire() as conn:
                        telegram_user_row = await conn.fetchrow("""
                            SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                        """, user_id)
                        if telegram_user_row:
                            telegram_user_id = telegram_user_row['id']
                            from database.repositories.ticket_repository import TicketRepository
                            ticket_repo = TicketRepository(self.db_pool)
                            await ticket_repo.record_otrs_action(
                                telegram_user_id=telegram_user_id,
                                action_type=action_type,
                                ticket_id=ticket_id,
                                ticket_number=ticket_number,
                                ticket_title=ticket_title,
                                details={"reason": reason}
                            )
                    
                    logger.info(f"Recorded OTRS metric: {action_type} by {user_id} on #{ticket_number}")
                    
                    # Если заявка закрыта или отклонена - удаляем сообщения
                    if action_type in ["closed", "rejected"]:
                        # Удаляем из группового чата
                        if ticket_msg_id and pending_topic_id:
                            try:
                                await self.bot.delete_message(
                                    chat_id=pending_chat_id,
                                    message_id=ticket_msg_id
                                )
                                logger.info(f"Deleted closed ticket message: {ticket_msg_id}")
                                
                                from database.repositories.ticket_repository import TicketRepository
                                ticket_repo = TicketRepository(self.db_pool)
                                await ticket_repo.delete_ticket_message(ticket_id, pending_chat_id, pending_topic_id)
                            except Exception as e:
                                logger.error(f"Failed to delete ticket message: {e}")
                        
                        # Удаляем личные сообщения о тикете
                        try:
                            from database.repositories.ticket_repository import TicketRepository
                            ticket_repo = TicketRepository(self.db_pool)
                            private_tickets = await ticket_repo.get_private_ticket_by_ticket_id(ticket_id)
                            for pt in private_tickets:
                                try:
                                    await self.bot.delete_message(
                                        chat_id=pt['telegram_id'],
                                        message_id=pt['message_id']
                                    )
                                    await ticket_repo.delete_private_ticket(pt['telegram_id'], ticket_id)
                                    logger.info(f"Deleted private ticket msg for user {pt['telegram_id']}")
                                except Exception as e:
                                    logger.warning(f"Failed to delete private msg: {e}")
                        except Exception as e:
                            logger.warning(f"Failed to cleanup private tickets: {e}")
                    else:
                        # Для комментариев - обновляем сообщение
                        if ticket:
                            await otrs_manager.update_ticket_message(ticket)
                    
                    # Отправляем статусное сообщение
                    import os
                    if self.settings:
                        tasks_topic_id = int(await self.settings.get("TASKS_TOPIC_ID", "0"))
                        user_delete_delay = int(await self.settings.get("USER_MESSAGE_DELETE_DELAY", "30"))
                    else:
                        tasks_topic_id = int(os.getenv("TASKS_TOPIC_ID", "0"))
                        user_delete_delay = int(os.getenv("USER_MESSAGE_DELETE_DELAY", "30"))
                    
                    status_msg = await message.reply(status_text, parse_mode="HTML")
                    
                    # Удаляем статусное сообщение через 30 секунд, особенно в топике заявок
                    if message.message_thread_id == tasks_topic_id:
                        asyncio.create_task(self._delete_message_later(
                            message.chat.id, 
                            status_msg.message_id, 
                            message.message_thread_id,
                            user_delete_delay
                        ))
                else:
                    error_text = f"❌ Ошибка при выполнении действия"
                    if error_msg:
                        error_text += f"\n\n<i>{error_msg[:200]}</i>"
                    error_msg_obj = await message.reply(error_text, parse_mode="HTML")
                    
                    # Удаляем сообщение об ошибке через 30 секунд в топике заявок
                    import os
                    if self.settings:
                        tasks_topic_id = int(await self.settings.get("TASKS_TOPIC_ID", "0"))
                    else:
                        tasks_topic_id = int(os.getenv("TASKS_TOPIC_ID", "0"))
                    if message.message_thread_id == tasks_topic_id:
                        asyncio.create_task(self._delete_message_later(
                            message.chat.id, 
                            error_msg_obj.message_id, 
                            message.message_thread_id,
                            30
                        ))
            
            # Удаляем сообщения пользователей через 30 секунд (только в группах)
            if message.chat.type != "private":
                import os
                if self.settings:
                    user_delete_delay = int(await self.settings.get("USER_MESSAGE_DELETE_DELAY", "30"))
                else:
                    user_delete_delay = int(os.getenv("USER_MESSAGE_DELETE_DELAY", "30"))
                asyncio.create_task(self._delete_message_later(
                    message.chat.id, 
                    message.message_id, 
                    message.message_thread_id,
                    user_delete_delay
                ))
            return
        
        # Если это личное сообщение - передаём в auth_handler
        if message.chat.type == "private":
            await self.auth_handler.handle_text_message(message)
            return
        
        # Для групп: если это не Excel топик, планируем удаление через 30 секунд (как в старом боте)
        import os
        if message.chat.type in ["group", "supergroup"]:
            # Проверяем, что это не Excel топик (он обрабатывается отдельно)
            if self.settings:
                excel_topic_id = int(await self.settings.get("EXCEL_TOPIC_ID", "0"))
                user_delete_delay = int(await self.settings.get("USER_MESSAGE_DELETE_DELAY", "30"))
            else:
                excel_topic_id = int(os.getenv("EXCEL_TOPIC_ID", "0"))
                user_delete_delay = int(os.getenv("USER_MESSAGE_DELETE_DELAY", "30"))
            
            topic_id = message.message_thread_id
            if topic_id != excel_topic_id:
                # Это не Excel топик - планируем удаление через 30 секунд
                asyncio.create_task(self._delete_message_later(
                    message.chat.id,
                    message.message_id,
                    topic_id,
                    delay=user_delete_delay
                ))
                logger.info(f"Will delete user message ID={message.message_id} after {user_delete_delay} seconds.")
    
    async def check_chat_availability(self, chat_id: int) -> bool:
        """Проверяет доступность чата."""
        # Проверяем кэш
        if chat_id in self._chat_availability_cache:
            is_available, last_check = self._chat_availability_cache[chat_id]
            if (datetime.now() - last_check).total_seconds() < 300:  # 5 минут
                return is_available
        
        # Проверяем доступность
        try:
            chat = await self.bot.get_chat(chat_id)
            is_available = True
        except TelegramBadRequest:
            is_available = False
        except Exception as e:
            logger.warning(f"Error checking chat {chat_id}: {e}")
            is_available = True  # В случае ошибки считаем доступным
        
        # Обновляем кэш
        self._chat_availability_cache[chat_id] = (is_available, datetime.now())
        return is_available
    
    async def cleanup_excel_topic(self):
        """Очищает ТОЛЬКО отслеживаемые сообщения в Excel топике при запуске."""
        import os
        
        # Получаем настройки
        if self.settings:
            excel_topic_id = int(await self.settings.get("EXCEL_TOPIC_ID", "0"))
            target_chat_id = int(await self.settings.get("TELEGRAM_CHAT_ID", "-1"))
        else:
            excel_topic_id = int(os.getenv("EXCEL_TOPIC_ID", "0"))
            target_chat_id = int(os.getenv("TELEGRAM_CHAT_ID", "-1"))
        
        if excel_topic_id == 0 or target_chat_id == -1:
            logger.info("Excel topic not configured, skipping cleanup")
            return
        
        # Получаем ТОЛЬКО сообщения из Excel топика, сохранённые в БД
        pending = await self.deletion_repo.get_pending_deletions(topic_id=excel_topic_id)
        
        if not pending:
            logger.info(f"No tracked messages to cleanup in Excel topic {excel_topic_id}")
            return
        
        logger.info(f"Cleaning up {len(pending)} tracked messages in Excel topic {excel_topic_id}")
        deleted_count = 0
        
        for item in pending:
            try:
                await self.bot.delete_message(
                    chat_id=item['chat_id'],
                    message_id=item['message_id']
                )
                deleted_count += 1
                logger.debug(f"Deleted tracked message {item['message_id']} from Excel topic")
            except Exception as e:
                logger.debug(f"Could not delete message {item['message_id']}: {e}")
            
            # Удаляем из БД в любом случае
            await self.deletion_repo.remove_pending_deletion(item['chat_id'], item['message_id'])
        
        logger.info(f"Excel topic cleanup complete: {deleted_count}/{len(pending)} messages deleted")

