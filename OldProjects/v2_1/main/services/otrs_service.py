"""
Сервис для работы с OTRS.
Чистая бизнес-логика без зависимостей от Telegram.
"""

import logging
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from database.repositories.otrs_repository import OTRSRepository
from utils.logger import get_logger

logger = get_logger(__name__)


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


class OTRSService:
    """Сервис для работы с OTRS API."""
    
    def __init__(
        self,
        otrs_repo: OTRSRepository,
        base_url: str,
        username: str,
        password: str,
        webservice: str = "TelegramBot"
    ):
        """
        Инициализирует OTRS сервис.
        
        Args:
            otrs_repo: Репозиторий для работы с OTRS данными
            base_url: Базовый URL OTRS
            username: Имя пользователя OTRS API
            password: Пароль OTRS API
            webservice: Имя Web Service в OTRS
        """
        self.repo = otrs_repo
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
    
    async def close(self):
        """Закрывает HTTP сессию."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _auth_params(self) -> Dict[str, str]:
        """Возвращает параметры авторизации для запросов."""
        return {
            "UserLogin": self.username,
            "Password": self.password
        }
    
    def _api_url(self, operation: str) -> str:
        """Формирует URL для API запроса."""
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
        """
        Ищет тикеты по параметрам, возвращает список ID.
        
        Args:
            states: Список состояний тикетов
            queues: Список очередей
            limit: Максимальное количество результатов
            
        Returns:
            Список ID тикетов
        """
        session = await self._get_session()
        
        params = {
            **self._auth_params(),
            "Limit": limit
        }
        
        if states:
            params["States"] = states
        if queues:
            params["Queues"] = queues
        
        try:
            url = self._api_url("TicketSearch")
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    if "TicketID" in result:
                        return result["TicketID"] if isinstance(result["TicketID"], list) else [result["TicketID"]]
                    return []
                else:
                    logger.error(f"OTRS search failed: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"OTRS search error: {e}")
            return []
    
    async def get_ticket(self, ticket_id: int) -> Optional[OTRSTicket]:
        """
        Получает информацию о тикете.
        
        Args:
            ticket_id: ID тикета
            
        Returns:
            Объект OTRSTicket или None
        """
        session = await self._get_session()
        
        data = {
            **self._auth_params(),
            "TicketID": ticket_id
        }
        
        try:
            url = self._api_url("TicketGet")
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    if "Error" in result:
                        logger.error(f"OTRS get ticket error: {result['Error']}")
                        return None
                    
                    ticket_data = result.get("Ticket", {})[0] if result.get("Ticket") else {}
                    article_data = result.get("Article", [])
                    
                    # Парсим дату создания
                    created_str = ticket_data.get("Created", "")
                    try:
                        created = datetime.fromisoformat(created_str.replace(" ", "T"))
                    except:
                        created = datetime.now()
                    
                    return OTRSTicket(
                        ticket_id=ticket_id,
                        ticket_number=ticket_data.get("TicketNumber", ""),
                        title=ticket_data.get("Title", ""),
                        state=ticket_data.get("State", ""),
                        priority=ticket_data.get("Priority", ""),
                        queue=ticket_data.get("Queue", ""),
                        owner=ticket_data.get("Owner", ""),
                        customer=ticket_data.get("CustomerUser", ""),
                        created=created,
                        body=article_data[0].get("Body", "") if article_data else "",
                        articles=article_data
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
    ) -> Tuple[bool, str]:
        """
        Обновляет тикет в OTRS.
        
        Args:
            ticket_id: ID тикета
            state: Новое состояние
            owner: Новый владелец
            priority: Новый приоритет
            article_body: Текст комментария
            article_subject: Тема комментария
            
        Returns:
            Tuple[success, error_message]
        """
        session = await self._get_session()
        
        data = {
            **self._auth_params(),
            "TicketID": ticket_id,
            "Ticket": {}
        }
        
        if state:
            data["Ticket"]["State"] = state
        if owner:
            data["Ticket"]["Owner"] = owner
        if priority:
            data["Ticket"]["Priority"] = priority
        
        if not data["Ticket"]:
            del data["Ticket"]
        
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
    
    async def create_ticket(
        self,
        title: str,
        body: str,
        queue: str = "Raw",
        customer: str = "telegram@bot.local",
        priority: str = "3 normal"
    ) -> Optional[int]:
        """
        Создаёт новый тикет.
        
        Args:
            title: Заголовок тикета
            body: Текст тикета
            queue: Очередь
            customer: Пользователь-заказчик
            priority: Приоритет
            
        Returns:
            ID созданного тикета или None
        """
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
    
    async def get_agent_login_by_email(self, email: str) -> Optional[str]:
        """
        Получает логин агента OTRS по email.
        
        Args:
            email: Email адрес
            
        Returns:
            Логин агента или None
        """
        email_local = email.split('@')[0]
        
        login_variants = [
            email_local.split('.')[0],
            email_local,
            email_local.replace('.', ''),
            email_local.replace('.', '_'),
            email,
        ]
        
        login_variants = list(dict.fromkeys(login_variants))
        
        logger.debug(f"Trying OTRS login variants for {email}: {login_variants}")
        
        for login in login_variants:
            if await self._verify_agent_login(login):
                logger.info(f"Found OTRS agent: {email} -> {login}")
                return login
        
        logger.warning(f"Could not find OTRS agent for email: {email}")
        return None
    
    async def _verify_agent_login(self, login: str) -> bool:
        """
        Проверяет существование агента в OTRS.
        
        Args:
            login: Логин для проверки
            
        Returns:
            True если агент существует
        """
        session = await self._get_session()
        
        params = {
            **self._auth_params(),
            "Owners": login,
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
                    
                    if "Error" in result:
                        error_msg = result.get("Error", {}).get("ErrorMessage", "").lower()
                        if "user" in error_msg or "owner" in error_msg or "invalid" in error_msg:
                            logger.debug(f"Agent {login} not found: {error_msg}")
                            return False
                    
                    logger.debug(f"Agent {login} verified OK")
                    return True
        except Exception as e:
            logger.debug(f"Verify agent {login} error: {e}")
        
        return False
    
    def get_state_emoji(self, state: str) -> str:
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
    
    def get_priority_emoji(self, priority: str) -> str:
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
    
    def format_ticket_message(self, ticket: OTRSTicket) -> str:
        """
        Форматирует сообщение для тикета.
        
        Args:
            ticket: Объект тикета
            
        Returns:
            HTML текст сообщения
        """
        state_emoji = self.get_state_emoji(ticket.state)
        priority_emoji = self.get_priority_emoji(ticket.priority)
        
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
    
    def is_ticket_assigned(self, ticket: OTRSTicket) -> bool:
        """
        Проверяет, назначен ли тикет на конкретного исполнителя.
        
        Args:
            ticket: Объект тикета
            
        Returns:
            True если тикет назначен
        """
        owner = ticket.owner.lower().strip() if ticket.owner else ""
        
        empty_owners = [
            "", "root@localhost", "root", "admin", "admin@localhost",
            "-", "none", "не назначен", "не назначено",
            "telegram_bot", "telegram-bot", "telegrambot", "bot"
        ]
        
        return owner not in empty_owners

