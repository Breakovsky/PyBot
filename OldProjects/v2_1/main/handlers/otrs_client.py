"""
Клиент для работы с OTRS REST API.
"""

import asyncio
import logging
import aiohttp
import json
from datetime import datetime
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field

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
        
        params = {
            "UserLogin": self.username,
            "Password": self.password,
            "Limit": limit,
            "SortBy": "Created",
            "OrderBy": "Down",
            "StateType": ["new", "open", "pending reminder", "pending auto close"]
        }
        
        try:
            url = self._api_url("TicketSearch")
            logger.debug(f"OTRS search URL: {url}")
            
            async with session.get(url, params=params) as response:
                text = await response.text()
                logger.debug(f"OTRS search response: {text[:200]}")
                
                if response.status == 200:
                    data = json.loads(text) if text else {}
                    if "Error" in data:
                        logger.error(f"OTRS search error: {data['Error']}")
                        return []
                    ticket_ids = data.get("TicketID", [])
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
                    
                    body = ""
                    articles = ticket_data.get("Article", [])
                    if articles:
                        body = articles[0].get("Body", "")
                    
                    created_str = ticket_data.get("Created", "")
                    try:
                        created = datetime.fromisoformat(created_str.replace(" ", "T"))
                    except:
                        created = datetime.now()
                    
                    return OTRSTicket(
                        ticket_id=ticket_data.get("TicketID"),
                        ticket_number=ticket_data.get("TicketNumber", ""),
                        title=ticket_data.get("Title", ""),
                        state=ticket_data.get("State", ""),
                        priority=ticket_data.get("Priority", ""),
                        queue=ticket_data.get("Queue", ""),
                        owner=ticket_data.get("Owner", ""),
                        customer=ticket_data.get("CustomerUserID", ""),
                        created=created,
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
        """Обновляет тикет в OTRS. Возвращает (success, error_message)."""
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
        """Получает логин агента OTRS по email."""
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
        """Проверяет существование агента в OTRS."""
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

