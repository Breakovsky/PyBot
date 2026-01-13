"""
Репозиторий для работы с тикетами OTRS в Telegram.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class TicketRepository:
    """Репозиторий для работы с тикетами OTRS в Telegram."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    async def save_ticket_message(
        self,
        ticket_id: int,
        ticket_number: str,
        message_id: int,
        chat_id: int,
        topic_id: int,
        ticket_state: str
    ):
        """Сохраняет связь между тикетом и сообщением в Telegram."""
        async with self.db_pool.acquire() as conn:
            # Сначала получаем или создаём запись в otrs.otrs_tickets
            ticket_row = await conn.fetchrow("""
                SELECT id FROM otrs.otrs_tickets WHERE ticket_id = $1
            """, ticket_id)
            
            if not ticket_row:
                # Создаём запись о тикете
                await conn.execute("""
                    INSERT INTO otrs.otrs_tickets (ticket_id, ticket_number, state, last_seen_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (ticket_id) DO UPDATE SET
                        ticket_number = EXCLUDED.ticket_number,
                        state = EXCLUDED.state,
                        last_seen_at = NOW()
                """, ticket_id, ticket_number, ticket_state)
                ticket_row = await conn.fetchrow("""
                    SELECT id FROM otrs.otrs_tickets WHERE ticket_id = $1
                """, ticket_id)
            
            otrs_ticket_id = ticket_row['id']
            
            # Сохраняем связь с сообщением
            await conn.execute("""
                INSERT INTO telegram.ticket_messages 
                    (ticket_id, ticket_number, chat_id, topic_id, message_id, ticket_state)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (ticket_id, chat_id, topic_id) DO UPDATE SET
                    message_id = EXCLUDED.message_id,
                    ticket_state = EXCLUDED.ticket_state,
                    updated_at = NOW()
            """, otrs_ticket_id, ticket_number, chat_id, topic_id, message_id, ticket_state)
            logger.debug(f"Saved ticket message: ticket_id={ticket_id}, message_id={message_id}")
    
    async def get_all_ticket_messages(self, chat_id: int, topic_id: int) -> List[Dict]:
        """Получает все сообщения о тикетах для указанного чата и топика."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    ot.ticket_id,
                    tm.ticket_number,
                    tm.message_id,
                    tm.ticket_state
                FROM telegram.ticket_messages tm
                JOIN otrs.otrs_tickets ot ON tm.ticket_id = ot.id
                WHERE tm.chat_id = $1 AND tm.topic_id = $2
            """, chat_id, topic_id)
            return [dict(row) for row in rows]
    
    async def delete_ticket_message(self, ticket_id: int, chat_id: int, topic_id: int):
        """Удаляет связь между тикетом и сообщением."""
        async with self.db_pool.acquire() as conn:
            # Получаем otrs_ticket_id
            ticket_row = await conn.fetchrow("""
                SELECT id FROM otrs.otrs_tickets WHERE ticket_id = $1
            """, ticket_id)
            
            if ticket_row:
                await conn.execute("""
                    DELETE FROM telegram.ticket_messages
                    WHERE ticket_id = $1 AND chat_id = $2 AND topic_id = $3
                """, ticket_row['id'], chat_id, topic_id)
                logger.debug(f"Deleted ticket message: ticket_id={ticket_id}")
    
    async def save_private_ticket(
        self,
        telegram_id: int,
        ticket_id: int,
        ticket_number: str,
        message_id: int
    ):
        """Сохраняет личное сообщение о тикете."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO telegram.private_ticket_messages 
                    (telegram_id, ticket_id, ticket_number, message_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (telegram_id, ticket_id) DO UPDATE SET
                    message_id = EXCLUDED.message_id
            """, telegram_id, ticket_id, ticket_number, message_id)
            logger.debug(f"Saved private ticket: telegram_id={telegram_id}, ticket_id={ticket_id}")
    
    async def get_private_ticket_by_ticket_id(self, ticket_id: int) -> List[Dict]:
        """Получает все личные сообщения для тикета."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT telegram_id, ticket_id, ticket_number, message_id
                FROM telegram.private_ticket_messages
                WHERE ticket_id = $1
            """, ticket_id)
            return [dict(row) for row in rows]
    
    async def delete_private_ticket(self, telegram_id: int, ticket_id: int):
        """Удаляет личное сообщение о тикете."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM telegram.private_ticket_messages
                WHERE telegram_id = $1 AND ticket_id = $2
            """, telegram_id, ticket_id)
            logger.debug(f"Deleted private ticket: telegram_id={telegram_id}, ticket_id={ticket_id}")
    
    async def record_otrs_action(
        self,
        telegram_user_id: int,
        action_type: str,
        ticket_id: int,
        ticket_number: str = None,
        ticket_title: str = None,
        details: Dict = None
    ):
        """Записывает действие пользователя с тикетом."""
        async with self.db_pool.acquire() as conn:
            # Получаем otrs_ticket_id
            ticket_row = await conn.fetchrow("""
                SELECT id FROM otrs.otrs_tickets WHERE ticket_id = $1
            """, ticket_id)
            
            if not ticket_row:
                # Создаём запись о тикете если её нет
                await conn.execute("""
                    INSERT INTO otrs.otrs_tickets (ticket_id, ticket_number, title, last_seen_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (ticket_id) DO UPDATE SET
                        ticket_number = EXCLUDED.ticket_number,
                        title = EXCLUDED.title,
                        last_seen_at = NOW()
                """, ticket_id, ticket_number or str(ticket_id), ticket_title or "")
                ticket_row = await conn.fetchrow("""
                    SELECT id FROM otrs.otrs_tickets WHERE ticket_id = $1
                """, ticket_id)
            
            otrs_ticket_id = ticket_row['id']
            
            # Записываем метрику
            await conn.execute("""
                INSERT INTO otrs.otrs_metrics 
                    (telegram_user_id, action_type, ticket_id, ticket_number, ticket_title, details, action_time)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
            """, telegram_user_id, action_type, otrs_ticket_id, ticket_number, ticket_title, details)
            logger.debug(f"Recorded OTRS action: {action_type} by user_id={telegram_user_id} on ticket_id={ticket_id}")

