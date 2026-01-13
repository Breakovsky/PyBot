"""
Сервис для работы с персистентными сообщениями Telegram.
Чистая бизнес-логика без зависимостей от Bot.
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime

from database.connection import DatabasePool
from utils.logger import get_logger

logger = get_logger(__name__)


class TelegramMessageService:
    """Сервис для работы с персистентными сообщениями Telegram."""
    
    def __init__(self, db_pool: DatabasePool):
        """
        Инициализирует сервис сообщений.
        
        Args:
            db_pool: Пул соединений с БД
        """
        self.db_pool = db_pool
    
    async def save_message_id(
        self,
        chat_id: int,
        topic_id: Optional[int],
        message_type: str,
        message_id: int
    ) -> None:
        """
        Сохраняет ID сообщения для последующего использования.
        
        Args:
            chat_id: ID чата
            topic_id: ID топика (опционально)
            message_type: Тип сообщения (например, 'dashboard', 'metrics')
            message_id: ID сообщения в Telegram
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO telegram.telegram_messages 
                    (chat_id, topic_id, message_type, message_id, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (chat_id, topic_id, message_type) DO UPDATE SET
                    message_id = EXCLUDED.message_id,
                    updated_at = NOW()
            """, chat_id, topic_id, message_type, message_id)
            
            logger.debug(f"Saved message ID: {message_type}={message_id} for topic {topic_id}")
    
    async def get_message_id(
        self,
        chat_id: int,
        topic_id: Optional[int],
        message_type: str
    ) -> Optional[int]:
        """
        Получает сохранённый ID сообщения.
        
        Args:
            chat_id: ID чата
            topic_id: ID топика (опционально)
            message_type: Тип сообщения
            
        Returns:
            ID сообщения или None
        """
        async with self.db_pool.acquire() as conn:
            message_id = await conn.fetchval("""
                SELECT message_id FROM telegram.telegram_messages
                WHERE chat_id = $1 AND topic_id = $2 AND message_type = $3
            """, chat_id, topic_id, message_type)
            
            return message_id
    
    async def delete_message_id(
        self,
        chat_id: int,
        topic_id: Optional[int],
        message_type: str
    ) -> None:
        """
        Удаляет сохранённый ID сообщения.
        
        Args:
            chat_id: ID чата
            topic_id: ID топика (опционально)
            message_type: Тип сообщения
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM telegram.telegram_messages
                WHERE chat_id = $1 AND topic_id = $2 AND message_type = $3
            """, chat_id, topic_id, message_type)
            
            logger.debug(f"Deleted message ID: {message_type} for topic {topic_id}")

