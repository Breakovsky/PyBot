"""
Репозиторий для отслеживания удалений сообщений.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageDeletionRepository:
    """Репозиторий для работы с отслеживанием удалений сообщений."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    async def add_pending_deletion(
        self, 
        chat_id: int, 
        message_id: int, 
        delete_after: datetime,
        topic_id: Optional[int] = None
    ):
        """Добавляет сообщение в очередь на удаление."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO telegram.pending_deletions 
                    (chat_id, topic_id, message_id, delete_after)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (chat_id, message_id) DO UPDATE SET
                    topic_id = EXCLUDED.topic_id,
                    delete_after = EXCLUDED.delete_after
            """, chat_id, topic_id, message_id, delete_after)
            logger.debug(f"Added pending deletion: chat_id={chat_id}, topic_id={topic_id}, message_id={message_id}")
    
    async def get_pending_deletions(self, topic_id: Optional[int] = None) -> List[Dict]:
        """Получает все сообщения на удаление (опционально по топику)."""
        async with self.db_pool.acquire() as conn:
            if topic_id is not None:
                rows = await conn.fetch("""
                    SELECT chat_id, topic_id, message_id, delete_after, created_at
                    FROM telegram.pending_deletions
                    WHERE topic_id = $1
                    ORDER BY created_at
                """, topic_id)
            else:
                rows = await conn.fetch("""
                    SELECT chat_id, topic_id, message_id, delete_after, created_at
                    FROM telegram.pending_deletions
                    ORDER BY created_at
                """)
            return [dict(row) for row in rows]
    
    async def remove_pending_deletion(self, chat_id: int, message_id: int):
        """Удаляет сообщение из очереди на удаление."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM telegram.pending_deletions
                WHERE chat_id = $1 AND message_id = $2
            """, chat_id, message_id)
            logger.debug(f"Removed pending deletion: chat_id={chat_id}, message_id={message_id}")
    
    async def clear_topic_deletions(self, topic_id: int):
        """Очищает все записи удаления для топика."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM telegram.pending_deletions
                WHERE topic_id = $1
            """, topic_id)
            logger.debug(f"Cleared all pending deletions for topic {topic_id}")

