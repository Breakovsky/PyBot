# main/modules/handlers/otrs_handler.py

"""
Модуль интеграции с OTRS Community Edition.
- Отображение активных заявок
- Создание/обновление/закрытие тикетов
- Уведомления о новых заявках
- Поиск по заявкам
"""

import asyncio
import logging
import aiohttp
from datetime import datetime
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from assets.config import (
    OTRS_URL, OTRS_USERNAME, OTRS_PASSWORD, OTRS_WEBSERVICE, now_msk
)
from modules.handlers.monitor_db import get_db

logger = logging.getLogger(__name__)


@dataclass
class OTRSTicket:
    """Представление тикета OTRS."""
    ticket_id: int
    ticket_number: str
    title: str
    state: str
    priority: str
    queue: str
    owner: str
    customer: str
    created: datetime
    body: str = ""
    articles: List[Dict] = field(default_factory=list)


class OTRSClient:
    """Клиент для работы с OTRS REST API."""
    
    def __init__(self, base_url: str, username: str, password: str, webservice: str = "TelegramBot"):
        self.base_url = base_url.rstrip('/').replace('/index.pl', '')
        self.username = username
        self.password = password
        self.webservice = webservice
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создаёт HTTP сессию."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _auth_params(self) -> Dict[str, str]:
        """Возвращает параметры авторизации для запросов."""
        return {
            "UserLogin": self.username,
            "Password": self.password
        }
    
    async def close(self):
        """Закрывает HTTP сессию."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _api_url(self, operation: str) -> str:
        """Формирует URL для API запроса."""
        # OTRS GenericInterface REST endpoint
        # base_url уже содержит /otrs если был указан полный путь
        base = self.base_url
        if "/otrs" in base:
            return f"{base}/nph-genericinterface.pl/Webservice/{self.webservice}/{operation}"
        else:
            return f"{base}/otrs/nph-genericinterface.pl/Webservice/{self.webservice}/{operation}"
    
    async def test_connection(self) -> bool:
        """Тестирует соединение с OTRS."""
        try:
            tickets = await self.search_tickets(limit=1)
            return True
        except Exception as e:
            logger.error(f"OTRS connection test failed: {e}")
            return False
    
    async def search_tickets(
        self,
        states: Optional[List[str]] = None,
        queues: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[int]:
        """Ищет тикеты по параметрам, возвращает список ID."""
        session = await self._get_session()
        
        # Базовые параметры
        params = {
            "UserLogin": self.username,
            "Password": self.password,
            "Limit": limit,
            "SortBy": "Created",
            "OrderBy": "Down",
            # Фильтр по типу состояния (new, open) - не включает closed
            "StateType": ["new", "open", "pending reminder", "pending auto close"]
        }
        
        try:
            url = self._api_url("TicketSearch")
            logger.debug(f"OTRS search URL: {url}")
            logger.debug(f"OTRS search params count: {len(params)}")
            
            async with session.get(url, params=params) as response:
                text = await response.text()
                logger.debug(f"OTRS search response: {text[:200]}")
                
                if response.status == 200:
                    import json
                    data = json.loads(text) if text else {}
                    if "Error" in data:
                        logger.error(f"OTRS search error: {data['Error']}")
                        return []
                    ticket_ids = data.get("TicketID", [])
                    # Конвертируем в int если строки
                    return [int(tid) for tid in ticket_ids] if ticket_ids else []
                else:
                    logger.error(f"OTRS search failed: {response.status} - {text}")
                    return []
        except Exception as e:
            logger.error(f"OTRS search error: {e}", exc_info=True)
            return []
    
    async def get_ticket(self, ticket_id: int, with_articles: bool = True) -> Optional[OTRSTicket]:
        """Получает информацию о тикете."""
        session = await self._get_session()
        
        params = {
            **self._auth_params(),
            "TicketID": ticket_id,
            "AllArticles": 1 if with_articles else 0,
            "DynamicFields": 1
        }
        
        try:
            url = self._api_url("TicketGet")
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if "Error" in data:
                        logger.error(f"OTRS get ticket error: {data['Error']}")
                        return None
                    
                    tickets = data.get("Ticket", [])
                    ticket_data = tickets[0] if tickets else {}
                    
                    if not ticket_data:
                        return None
                    
                    # Получаем текст первой статьи
                    body = ""
                    articles = ticket_data.get("Article", [])
                    if articles:
                        body = articles[0].get("Body", "")
                    
                    return OTRSTicket(
                        ticket_id=ticket_data.get("TicketID"),
                        ticket_number=ticket_data.get("TicketNumber", ""),
                        title=ticket_data.get("Title", ""),
                        state=ticket_data.get("State", ""),
                        priority=ticket_data.get("Priority", ""),
                        queue=ticket_data.get("Queue", ""),
                        owner=ticket_data.get("Owner", ""),
                        customer=ticket_data.get("CustomerUserID", ""),
                        created=datetime.fromisoformat(ticket_data.get("Created", "").replace(" ", "T")),
                        body=body,
                        articles=articles
                    )
                else:
                    logger.error(f"OTRS get ticket failed: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"OTRS get ticket error: {e}")
            return None
    
    async def update_ticket(
        self,
        ticket_id: int,
        state: Optional[str] = None,
        owner: Optional[str] = None,
        priority: Optional[str] = None,
        article_body: Optional[str] = None,
        article_subject: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Обновляет тикет в OTRS.
        Возвращает (success, error_message).
        """
        session = await self._get_session()
        
        # Формируем данные для OTRS API
        data = {
            **self._auth_params(),
            "TicketID": ticket_id,
            "Ticket": {}  # Параметры тикета внутри объекта Ticket
        }
        
        # Параметры тикета
        if state:
            data["Ticket"]["State"] = state
        if owner:
            data["Ticket"]["Owner"] = owner
        if priority:
            data["Ticket"]["Priority"] = priority
        
        # Если нет изменений в тикете - убираем пустой объект
        if not data["Ticket"]:
            del data["Ticket"]
        
        # Добавляем статью (комментарий) если есть
        if article_body:
            data["Article"] = {
                "Subject": article_subject or "Telegram Bot Update",
                "Body": article_body,
                "ContentType": "text/plain; charset=utf8",
                "CommunicationChannel": "Internal",
                "SenderType": "agent",
                "IsVisibleForCustomer": 0
            }
        
        try:
            url = self._api_url("TicketUpdate")
            logger.debug(f"OTRS TicketUpdate {ticket_id}: {data}")
            
            async with session.post(url, json=data) as response:
                text = await response.text()
                logger.debug(f"OTRS TicketUpdate response: {text[:500]}")
                
                if response.status == 200:
                    import json
                    result = json.loads(text) if text else {}
                    
                    if "Error" in result:
                        error_msg = result.get("Error", {}).get("ErrorMessage", "Unknown error")
                        logger.error(f"OTRS update ticket error: {error_msg}")
                        return (False, error_msg)
                    
                    logger.info(f"Ticket {ticket_id} updated: state={state}, owner={owner}")
                    return (True, "")
                else:
                    error_msg = f"HTTP {response.status}: {text[:200]}"
                    logger.error(f"OTRS update ticket failed: {error_msg}")
                    return (False, error_msg)
                    
        except Exception as e:
            logger.error(f"OTRS update ticket error: {e}")
            return (False, str(e))
    
    async def get_agent_login_by_email(self, email: str) -> Optional[str]:
        """
        Получает логин агента OTRS по email.
        Пробует разные варианты логина и проверяет их через OTRS API.
        """
        email_local = email.split('@')[0]  # rodionov.sa
        
        # Варианты логинов для проверки (в порядке приоритета)
        login_variants = [
            email_local.split('.')[0],           # rodionov (самый частый вариант)
            email_local,                         # rodionov.sa
            email_local.replace('.', ''),        # rodionovsa
            email_local.replace('.', '_'),       # rodionov_sa
            email,                               # rodionov.sa@meb52.com (полный email)
        ]
        
        # Убираем дубликаты сохраняя порядок
        login_variants = list(dict.fromkeys(login_variants))
        
        logger.debug(f"Trying OTRS login variants for {email}: {login_variants}")
        
        # Пробуем каждый вариант
        for login in login_variants:
            if await self._verify_agent_login(login):
                logger.info(f"Found OTRS agent: {email} -> {login}")
                return login
        
        logger.warning(f"Could not find OTRS agent for email: {email}")
        return None
    
    async def _verify_agent_login(self, login: str) -> bool:
        """
        Проверяет существование агента в OTRS.
        Использует поиск тикетов с Owners - если агент не существует, OTRS вернёт ошибку.
        """
        session = await self._get_session()
        
        # Используем POST с параметром Owners для проверки
        params = {
            **self._auth_params(),
            "Owners": login,  # Если пользователь не существует - будет ошибка
            "Limit": 1
        }
        
        try:
            url = self._api_url("TicketSearch")
            logger.debug(f"Verifying OTRS agent: {login}")
            
            async with session.get(url, params=params) as response:
                text = await response.text()
                
                if response.status == 200:
                    import json
                    result = json.loads(text) if text else {}
                    
                    # Проверяем на ошибки
                    if "Error" in result:
                        error_msg = result.get("Error", {}).get("ErrorMessage", "").lower()
                        # Если ошибка связана с пользователем - он не существует
                        if "user" in error_msg or "owner" in error_msg or "invalid" in error_msg:
                            logger.debug(f"Agent {login} not found: {error_msg}")
                            return False
                    
                    # Если нет ошибки - агент существует (независимо от количества тикетов)
                    logger.debug(f"Agent {login} verified OK")
                    return True
                    
        except Exception as e:
            logger.debug(f"Verify agent {login} error: {e}")
        
        return False
    
    async def create_ticket(
        self,
        title: str,
        body: str,
        queue: str = "Raw",
        customer: str = "telegram@bot.local",
        priority: str = "3 normal"
    ) -> Optional[int]:
        """Создаёт новый тикет."""
        session = await self._get_session()
        
        data = {
            **self._auth_params(),
            "Ticket": {
                "Title": title,
                "Queue": queue,
                "State": "new",
                "Priority": priority,
                "CustomerUser": customer
            },
            "Article": {
                "Subject": title,
                "Body": body,
                "ContentType": "text/plain; charset=utf8",
                "ArticleType": "note-internal"
            }
        }
        
        try:
            url = self._api_url("TicketCreate")
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    ticket_id = result.get("TicketID")
                    logger.info(f"Ticket created: ID={ticket_id}")
                    return ticket_id
                else:
                    logger.error(f"OTRS create ticket failed: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"OTRS create ticket error: {e}")
            return None


class OTRSManager:
    """Менеджер интеграции OTRS с Telegram."""
    
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        topic_id: int,
        otrs_client: OTRSClient,
        check_interval: int = 60
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id
        self.client = otrs_client
        self.check_interval = check_interval
        self.db = get_db()
        
        # Состояние
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.known_tickets: Dict[int, str] = {}  # ticket_id -> state
        self.ticket_messages: Dict[int, int] = {}  # ticket_id -> message_id
        
        # Загружаем уже отправленные тикеты из БД
        self._load_known_tickets()
    
    def _load_known_tickets(self):
        """Загружает известные тикеты из БД для защиты от дублирования."""
        try:
            saved_tickets = self.db.get_all_ticket_messages(self.chat_id, self.topic_id)
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
        
        # Обрезаем тело если слишком длинное
        body = ticket.body
        if len(body) > 500:
            body = body[:500] + "..."
        
        # Экранируем HTML
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
        
        # Список "пустых" владельцев (не назначено / доступно для взятия)
        # telegram_bot - это бот, через которого работает интеграция
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
        
        # Кнопки зависят от состояния и назначения
        if "closed" not in state_lower:
            
            if not is_assigned:
                # Тикет НЕ назначен - показываем "Взять в работу"
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
                # Тикет НАЗНАЧЕН - показываем кнопки для работы
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
                disable_notification=False  # Уведомления для новых тикетов
            )
            self.ticket_messages[ticket.ticket_id] = msg.message_id
            
            # Сохраняем в БД для защиты от дублирования при перезапуске
            self.db.save_ticket_message(
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
                logger.error(f"Cannot send ticket message: chat {self.chat_id} not found. Bot may not be in the chat or chat was deleted.")
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
            
            # Обновляем состояние в БД
            self.db.save_ticket_message(
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
                # Сообщение удалено, отправим новое
                del self.ticket_messages[ticket.ticket_id]
                self.db.delete_ticket_message(ticket.ticket_id, self.chat_id, self.topic_id)
                await self.send_ticket_message(ticket)
                return True
            raise
    
    async def check_tickets(self):
        """Проверяет тикеты и отправляет/обновляет сообщения."""
        try:
            # Получаем открытые тикеты
            ticket_ids = await self.client.search_tickets()
            logger.info(f"OTRS check: found {len(ticket_ids)} open tickets")
            
            new_count = 0
            for ticket_id in ticket_ids:
                ticket = await self.client.get_ticket(ticket_id)
                if not ticket:
                    continue
                
                # Новый тикет?
                if ticket_id not in self.known_tickets:
                    # Ограничиваем количество новых сообщений при первой загрузке
                    if new_count >= 5:
                        logger.debug(f"Skipping ticket #{ticket.ticket_number} to avoid flood")
                        self.known_tickets[ticket_id] = ticket.state
                        continue
                    
                    await self.send_ticket_message(ticket)
                    self.known_tickets[ticket_id] = ticket.state
                    logger.info(f"New ticket detected: #{ticket.ticket_number}")
                    new_count += 1
                    
                    # Задержка между сообщениями для избежания flood control
                    await asyncio.sleep(1.5)
                
                # Изменился статус?
                elif self.known_tickets[ticket_id] != ticket.state:
                    await self.update_ticket_message(ticket)
                    self.known_tickets[ticket_id] = ticket.state
                    logger.info(f"Ticket status changed: #{ticket.ticket_number} -> {ticket.state}")
            
            # Удаляем закрытые тикеты из отслеживания
            current_ids = set(ticket_ids)
            for tid in list(self.known_tickets.keys()):
                if tid not in current_ids:
                    # Тикет закрыт или удалён - удаляем из памяти и БД
                    del self.known_tickets[tid]
                    if tid in self.ticket_messages:
                        del self.ticket_messages[tid]
                    self.db.delete_ticket_message(tid, self.chat_id, self.topic_id)
                    logger.debug(f"Removed closed ticket {tid} from tracking")
                        
        except Exception as e:
            logger.error(f"Error checking tickets: {e}")
    
    async def run(self):
        """Запускает цикл проверки тикетов."""
        self.is_running = True
        logger.info(f"OTRS Manager started. Check interval: {self.check_interval}s")
        
        try:
            # Первичная загрузка
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


# Глобальный экземпляр
_otrs_manager: Optional[OTRSManager] = None
_otrs_client: Optional[OTRSClient] = None


def get_otrs_manager() -> Optional[OTRSManager]:
    """Возвращает текущий менеджер OTRS."""
    return _otrs_manager


def get_otrs_client() -> Optional[OTRSClient]:
    """Возвращает клиент OTRS."""
    return _otrs_client


async def start_otrs_integration(
    bot: Bot,
    chat_id: int,
    topic_id: int,
    check_interval: int = 60
) -> Optional[OTRSManager]:
    """Запускает интеграцию с OTRS."""
    global _otrs_manager, _otrs_client
    
    if not OTRS_URL or not OTRS_USERNAME:
        logger.warning("OTRS integration disabled: missing configuration")
        return None
    
    # Создаём клиент
    _otrs_client = OTRSClient(
        base_url=OTRS_URL,
        username=OTRS_USERNAME,
        password=OTRS_PASSWORD,
        webservice=OTRS_WEBSERVICE
    )
    
    # Тестируем соединение
    if not await _otrs_client.test_connection():
        logger.error("OTRS connection failed, integration disabled")
        await _otrs_client.close()
        _otrs_client = None
        return None
    
    # Создаём менеджер
    _otrs_manager = OTRSManager(
        bot=bot,
        chat_id=chat_id,
        topic_id=topic_id,
        otrs_client=_otrs_client,
        check_interval=check_interval
    )
    
    _otrs_manager.start()
    logger.info(f"OTRS integration started for topic {topic_id}")
    
    return _otrs_manager


async def stop_otrs_integration():
    """Останавливает интеграцию с OTRS."""
    global _otrs_manager, _otrs_client
    
    if _otrs_manager:
        await _otrs_manager.stop()
        _otrs_manager = None
    
    if _otrs_client:
        await _otrs_client.close()
        _otrs_client = None

