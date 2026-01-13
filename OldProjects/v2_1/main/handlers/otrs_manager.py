"""
Менеджер интеграции OTRS с Telegram.
"""

import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from handlers.otrs_client import OTRSClient, OTRSTicket
from database.repositories.ticket_repository import TicketRepository

logger = logging.getLogger(__name__)


class OTRSManager:
    """Менеджер интеграции OTRS с Telegram."""
    
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        topic_id: int,
        otrs_client: OTRSClient,
        ticket_repo: TicketRepository,
        check_interval: int = 60
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id
        self.client = otrs_client
        self.ticket_repo = ticket_repo
        self.check_interval = check_interval
        
        # Состояние
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.known_tickets: Dict[int, str] = {}  # ticket_id -> state
        self.ticket_messages: Dict[int, int] = {}  # ticket_id -> message_id
        
        # Загружаем уже отправленные тикеты из БД
        asyncio.create_task(self._load_known_tickets())
    
    async def _load_known_tickets(self):
        """Загружает известные тикеты из БД для защиты от дублирования."""
        try:
            saved_tickets = await self.ticket_repo.get_all_ticket_messages(self.chat_id, self.topic_id)
            for ticket_data in saved_tickets:
                tid = ticket_data['ticket_id']
                self.known_tickets[tid] = ticket_data.get('ticket_state', 'unknown')
                self.ticket_messages[tid] = ticket_data['message_id']
            
            if saved_tickets:
                logger.info(f"Loaded {len(saved_tickets)} known tickets from DB")
        except Exception as e:
            logger.error(f"Failed to load known tickets: {e}")
    
    def _get_state_emoji(self, state: str) -> str:
        """Возвращает эмодзи для состояния тикета."""
        state_lower = state.lower()
        if "new" in state_lower:
            return "🆕"
        elif "open" in state_lower:
            return "📂"
        elif "pending" in state_lower:
            return "⏳"
        elif "closed" in state_lower:
            return "✅"
        elif "merged" in state_lower:
            return "🔗"
        else:
            return "📋"
    
    def _get_priority_emoji(self, priority: str) -> str:
        """Возвращает эмодзи для приоритета."""
        priority_lower = priority.lower()
        if "very high" in priority_lower or "5" in priority:
            return "🔴"
        elif "high" in priority_lower or "4" in priority:
            return "🟠"
        elif "normal" in priority_lower or "3" in priority:
            return "🟡"
        elif "low" in priority_lower or "2" in priority:
            return "🟢"
        else:
            return "⚪"
    
    def build_ticket_message(self, ticket: OTRSTicket) -> str:
        """Создаёт текст сообщения для тикета."""
        state_emoji = self._get_state_emoji(ticket.state)
        priority_emoji = self._get_priority_emoji(ticket.priority)
        
        body = ticket.body
        if len(body) > 500:
            body = body[:500] + "..."
        
        body = body.replace("<", "&lt;").replace(">", "&gt;")
        
        text = (
            f"{state_emoji} <b>Заявка #{ticket.ticket_number}</b>\n\n"
            f"📝 <b>Тема:</b> {ticket.title}\n"
            f"👤 <b>Создал:</b> {ticket.customer}\n"
            f"📁 <b>Очередь:</b> {ticket.queue}\n"
            f"👨‍💼 <b>Исполнитель:</b> {ticket.owner}\n"
            f"{priority_emoji} <b>Приоритет:</b> {ticket.priority}\n"
            f"📊 <b>Статус:</b> {ticket.state}\n"
            f"🕐 <b>Создана:</b> {ticket.created.strftime('%d.%m.%Y %H:%M')}\n"
            f"\n━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>{body}</blockquote>"
        )
        
        return text
    
    def _is_ticket_assigned(self, ticket: OTRSTicket) -> bool:
        """Проверяет, назначен ли тикет на конкретного исполнителя."""
        owner = ticket.owner.lower().strip() if ticket.owner else ""
        
        empty_owners = [
            "", "root@localhost", "root", "admin", "admin@localhost",
            "-", "none", "не назначен", "не назначено",
            "telegram_bot", "telegram-bot", "telegrambot", "bot"
        ]
        
        return owner not in empty_owners
    
    def build_ticket_keyboard(self, ticket: OTRSTicket) -> InlineKeyboardMarkup:
        """Создаёт клавиатуру действий для тикета."""
        buttons = []
        
        state_lower = ticket.state.lower()
        is_assigned = self._is_ticket_assigned(ticket)
        
        if "closed" not in state_lower:
            if not is_assigned:
                buttons.append([
                    InlineKeyboardButton(
                        text="👤 Взять в работу",
                        callback_data=f"otrs_assign:{ticket.ticket_id}"
                    ),
                    InlineKeyboardButton(
                        text="📝 Комментарий",
                        callback_data=f"otrs_comment:{ticket.ticket_id}"
                    )
                ])
                buttons.append([
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"otrs_reject:{ticket.ticket_id}"
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        text="✅ Закрыть",
                        callback_data=f"otrs_close:{ticket.ticket_id}"
                    ),
                    InlineKeyboardButton(
                        text="📝 Комментарий",
                        callback_data=f"otrs_comment:{ticket.ticket_id}"
                    )
                ])
                buttons.append([
                    InlineKeyboardButton(
                        text="🔄 Переназначить",
                        callback_data=f"otrs_reassign:{ticket.ticket_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"otrs_reject:{ticket.ticket_id}"
                    )
                ])
        
        buttons.append([
            InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data=f"otrs_refresh:{ticket.ticket_id}"
            ),
            InlineKeyboardButton(
                text="🌐 Открыть в OTRS",
                url=f"{self.client.base_url}/otrs/index.pl?Action=AgentTicketZoom;TicketID={ticket.ticket_id}"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    async def send_ticket_message(self, ticket: OTRSTicket) -> Optional[int]:
        """Отправляет сообщение о тикете."""
        text = self.build_ticket_message(ticket)
        keyboard = self.build_ticket_keyboard(ticket)
        
        try:
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                message_thread_id=self.topic_id,
                reply_markup=keyboard,
                disable_notification=False
            )
            self.ticket_messages[ticket.ticket_id] = msg.message_id
            
            await self.ticket_repo.save_ticket_message(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                message_id=msg.message_id,
                chat_id=self.chat_id,
                topic_id=self.topic_id,
                ticket_state=ticket.state
            )
            
            logger.info(f"Sent ticket message: #{ticket.ticket_number} (msg_id={msg.message_id})")
            return msg.message_id
        except TelegramBadRequest as e:
            error_str = str(e).lower()
            if "chat not found" in error_str or "chat_id is empty" in error_str:
                logger.error(f"Cannot send ticket message: chat {self.chat_id} not found.")
            else:
                logger.error(f"Failed to send ticket message: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to send ticket message: {e}")
            return None
    
    async def update_ticket_message(self, ticket: OTRSTicket) -> bool:
        """Обновляет сообщение о тикете."""
        if ticket.ticket_id not in self.ticket_messages:
            return False
        
        msg_id = self.ticket_messages[ticket.ticket_id]
        text = self.build_ticket_message(ticket)
        keyboard = self.build_ticket_keyboard(ticket)
        
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
            await self.ticket_repo.save_ticket_message(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                message_id=msg_id,
                chat_id=self.chat_id,
                topic_id=self.topic_id,
                ticket_state=ticket.state
            )
            
            return True
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return True
            elif "message to edit not found" in str(e):
                del self.ticket_messages[ticket.ticket_id]
                await self.ticket_repo.delete_ticket_message(ticket.ticket_id, self.chat_id, self.topic_id)
                await self.send_ticket_message(ticket)
                return True
            raise
    
    async def check_tickets(self):
        """Проверяет тикеты и отправляет/обновляет сообщения."""
        try:
            ticket_ids = await self.client.search_tickets()
            logger.info(f"OTRS check: found {len(ticket_ids)} open tickets")
            
            new_count = 0
            for ticket_id in ticket_ids:
                ticket = await self.client.get_ticket(ticket_id)
                if not ticket:
                    continue
                
                if ticket_id not in self.known_tickets:
                    if new_count >= 5:
                        logger.debug(f"Skipping ticket #{ticket.ticket_number} to avoid flood")
                        self.known_tickets[ticket_id] = ticket.state
                        continue
                    
                    await self.send_ticket_message(ticket)
                    self.known_tickets[ticket_id] = ticket.state
                    logger.info(f"New ticket detected: #{ticket.ticket_number}")
                    new_count += 1
                    
                    await asyncio.sleep(1.5)
                
                elif self.known_tickets[ticket_id] != ticket.state:
                    await self.update_ticket_message(ticket)
                    self.known_tickets[ticket_id] = ticket.state
                    logger.info(f"Ticket status changed: #{ticket.ticket_number} -> {ticket.state}")
            
            current_ids = set(ticket_ids)
            for tid in list(self.known_tickets.keys()):
                if tid not in current_ids:
                    del self.known_tickets[tid]
                    if tid in self.ticket_messages:
                        del self.ticket_messages[tid]
                    await self.ticket_repo.delete_ticket_message(tid, self.chat_id, self.topic_id)
                    logger.debug(f"Removed closed ticket {tid} from tracking")
                        
        except Exception as e:
            logger.error(f"Error checking tickets: {e}")
    
    async def run(self):
        """Запускает цикл проверки тикетов."""
        self.is_running = True
        logger.info(f"OTRS Manager started. Check interval: {self.check_interval}s")
        
        try:
            await self._load_known_tickets()
            await self.check_tickets()
            
            while self.is_running:
                await asyncio.sleep(self.check_interval)
                
                if not self.is_running:
                    break
                
                await self.check_tickets()
                
        except asyncio.CancelledError:
            logger.info("OTRS Manager task cancelled")
        except Exception as e:
            logger.error(f"OTRS Manager error: {e}", exc_info=True)
        finally:
            self.is_running = False
    
    def start(self) -> asyncio.Task:
        """Запускает менеджер в фоновой задаче."""
        if self._task and not self._task.done():
            logger.warning("OTRS Manager is already running")
            return self._task
        
        self._task = asyncio.create_task(self.run())
        return self._task
    
    async def stop(self):
        """Останавливает менеджер."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.client.close()
        logger.info("OTRS Manager stopped")

