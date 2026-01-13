"""
Обработчик интеграции с OTRS.
Использует OTRSService для бизнес-логики.
"""

import logging
import os
import asyncio
from typing import Optional, Dict, List, Tuple
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.connection import DatabasePool
from database.repositories.otrs_repository import OTRSRepository
from services.otrs_service import OTRSService, OTRSTicket
from config.settings import get_settings
from config.security import get_security_manager
from utils.logger import get_logger

logger = get_logger(__name__)


class OTRSHandler:
    """Обработчик интеграции с OTRS."""
    
    def __init__(self, db_pool: DatabasePool, bot: Bot):
        """
        Инициализирует обработчик OTRS.
        
        Args:
            db_pool: Пул соединений с БД
            bot: Экземпляр бота
        """
        self.db_pool = db_pool
        self.bot = bot
        self.otrs_repo = OTRSRepository(db_pool)
        self.otrs_service: Optional[OTRSService] = None
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.known_tickets: Dict[int, str] = {}  # ticket_id -> state
        self.ticket_messages: Dict[int, int] = {}  # ticket_id -> message_id
    
    async def _initialize_otrs_service(self) -> bool:
        """Инициализирует OTRS сервис из настроек."""
        try:
            settings = get_settings()
            security = get_security_manager()
            
            # Читаем настройки из БД
            otrs_url = await settings.get("OTRS_URL", "")
            otrs_username = await settings.get("OTRS_USERNAME", "")
            otrs_webservice = await settings.get("OTRS_WEBSERVICE", "TelegramBot")
            
            # Пароль читаем из Windows Credential Manager или .env (секрет)
            otrs_password = security.get_secret("OTRS_PASSWORD") or os.getenv("OTRS_PASSWORD", "")
            
            if not otrs_url or not otrs_username:
                logger.warning("OTRS integration disabled: missing configuration")
                return False
            
            self.otrs_service = OTRSService(
                otrs_repo=self.otrs_repo,
                base_url=otrs_url,
                username=otrs_username,
                password=otrs_password,
                webservice=otrs_webservice
            )
            
            # Тестируем соединение
            if await self.otrs_service.test_connection():
                logger.info("OTRS service initialized successfully")
                return True
            else:
                logger.error("OTRS connection test failed")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize OTRS service: {e}")
            return False
    
    async def get_user_stats(self, telegram_id: int) -> Dict:
        """
        Получает статистику пользователя по OTRS.
        
        Args:
            telegram_id: ID пользователя в Telegram
            
        Returns:
            Словарь со статистикой
        """
        return await self.otrs_repo.get_user_otrs_stats(telegram_id)
    
    async def start_integration(
        self,
        chat_id: int,
        topic_id: int,
        check_interval: int = 60
    ) -> bool:
        """
        Запускает интеграцию с OTRS.
        
        Args:
            chat_id: ID чата
            topic_id: ID топика
            check_interval: Интервал проверки в секундах
            
        Returns:
            True если интеграция запущена успешно
        """
        if not await self._initialize_otrs_service():
            return False
        
        if self.is_running:
            logger.warning("OTRS integration already running")
            return True
        
        # Загружаем известные тикеты из БД
        await self._load_known_tickets(chat_id, topic_id)
        
        self.is_running = True
        self._task = asyncio.create_task(self._otrs_loop(chat_id, topic_id, check_interval))
        logger.info("OTRS integration started")
        return True
    
    async def stop_integration(self):
        """Останавливает интеграцию с OTRS."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self.otrs_service:
            await self.otrs_service.close()
        
        logger.info("OTRS integration stopped")
    
    async def _load_known_tickets(self, chat_id: int, topic_id: int):
        """Загружает известные тикеты из БД для защиты от дублирования."""
        try:
            saved_tickets = await self.otrs_repo.get_all_ticket_messages(chat_id, topic_id)
            for ticket_data in saved_tickets:
                tid = ticket_data['ticket_id']
                self.known_tickets[tid] = ticket_data.get('ticket_state', 'unknown')
                self.ticket_messages[tid] = ticket_data['message_id']
            
            if saved_tickets:
                logger.info(f"Loaded {len(saved_tickets)} known tickets from DB")
        except Exception as e:
            logger.error(f"Failed to load known tickets: {e}")
    
    async def _otrs_loop(self, chat_id: int, topic_id: int, check_interval: int):
        """Основной цикл проверки тикетов OTRS."""
        while self.is_running:
            try:
                if not self.otrs_service:
                    await asyncio.sleep(check_interval)
                    continue
                
                # Ищем активные тикеты
                ticket_ids = await self.otrs_service.search_tickets(
                    states=["new", "open", "pending"],
                    limit=50
                )
                
                # Обрабатываем каждый тикет
                for ticket_id in ticket_ids:
                    if ticket_id in self.known_tickets:
                        # Проверяем изменение состояния
                        ticket = await self.otrs_service.get_ticket(ticket_id)
                        if ticket and ticket.state != self.known_tickets[ticket_id]:
                            # Обновляем сообщение
                            await self._update_ticket_message(chat_id, topic_id, ticket)
                    else:
                        # Новый тикет - отправляем сообщение
                        ticket = await self.otrs_service.get_ticket(ticket_id)
                        if ticket:
                            await self._send_ticket_message(chat_id, topic_id, ticket)
                
                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in OTRS loop: {e}", exc_info=True)
                await asyncio.sleep(check_interval)
    
    async def _send_ticket_message(
        self,
        chat_id: int,
        topic_id: int,
        ticket: OTRSTicket
    ):
        """Отправляет сообщение о тикете."""
        if not self.otrs_service:
            return
        
        message_text = self.otrs_service.format_ticket_message(ticket)
        keyboard = self._build_ticket_keyboard(ticket)
        
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode="HTML",
                message_thread_id=topic_id,
                reply_markup=keyboard
            )
            
            # Сохраняем в БД
            await self.otrs_repo.save_ticket_message(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                message_id=msg.message_id,
                chat_id=chat_id,
                topic_id=topic_id,
                ticket_state=ticket.state
            )
            
            self.known_tickets[ticket.ticket_id] = ticket.state
            self.ticket_messages[ticket.ticket_id] = msg.message_id
            
            logger.info(f"Sent ticket message: {ticket.ticket_number} (ID={ticket.ticket_id})")
            
        except Exception as e:
            logger.error(f"Failed to send ticket message: {e}")
    
    async def _update_ticket_message(
        self,
        chat_id: int,
        topic_id: int,
        ticket: OTRSTicket
    ):
        """Обновляет сообщение о тикете."""
        if ticket.ticket_id not in self.ticket_messages:
            return
        
        message_id = self.ticket_messages[ticket.ticket_id]
        message_text = self.otrs_service.format_ticket_message(ticket)
        keyboard = self._build_ticket_keyboard(ticket)
        
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
            # Обновляем в БД
            await self.otrs_repo.save_ticket_message(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                message_id=message_id,
                chat_id=chat_id,
                topic_id=topic_id,
                ticket_state=ticket.state
            )
            
            self.known_tickets[ticket.ticket_id] = ticket.state
            
        except Exception as e:
            logger.error(f"Failed to update ticket message: {e}")
    
    def _build_ticket_keyboard(self, ticket: OTRSTicket) -> InlineKeyboardMarkup:
        """Создаёт клавиатуру действий для тикета."""
        buttons = []
        
        state_lower = ticket.state.lower()
        is_assigned = self.otrs_service.is_ticket_assigned(ticket) if self.otrs_service else False
        
        # Кнопка "Взять в работу" (если не назначен)
        if not is_assigned and "new" in state_lower:
            buttons.append([InlineKeyboardButton(
                text="📌 Взять в работу",
                callback_data=f"otrs_assign_{ticket.ticket_id}"
            )])
        
        # Кнопка "Закрыть" (если открыт)
        if "open" in state_lower or "pending" in state_lower:
            buttons.append([InlineKeyboardButton(
                text="✅ Закрыть",
                callback_data=f"otrs_close_{ticket.ticket_id}"
            )])
        
        # Кнопка "Отклонить" (если открыт)
        if "open" in state_lower:
            buttons.append([InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"otrs_reject_{ticket.ticket_id}"
            )])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    
    async def update_ticket(
        self,
        ticket_id: int,
        state: Optional[str] = None,
        owner: Optional[str] = None,
        priority: Optional[str] = None,
        article_body: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Обновляет тикет в OTRS.
        
        Args:
            ticket_id: ID тикета
            state: Новое состояние
            owner: Новый владелец
            priority: Новый приоритет
            article_body: Текст комментария
            
        Returns:
            Tuple[success, error_message]
        """
        if not self.otrs_service:
            if not await self._initialize_otrs_service():
                return (False, "OTRS service not initialized")
        
        return await self.otrs_service.update_ticket(
            ticket_id=ticket_id,
            state=state,
            owner=owner,
            priority=priority,
            article_body=article_body
        )
    
    async def get_ticket(self, ticket_id: int) -> Optional[OTRSTicket]:
        """Получает информацию о тикете."""
        if not self.otrs_service:
            if not await self._initialize_otrs_service():
                return None
        
        return await self.otrs_service.get_ticket(ticket_id)
