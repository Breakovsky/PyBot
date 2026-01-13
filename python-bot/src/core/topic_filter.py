"""
Topic Filter for isolating handlers to specific Telegram Topics.
"""

import os
import logging
from typing import Optional
from aiogram.types import Message
from sqlalchemy import select
from .database import async_session, TelegramTopic

logger = logging.getLogger(__name__)


async def get_topic_thread_id(topic_name: str) -> Optional[int]:
    """Get thread_id for a topic name from database."""
    async with async_session() as session:
        result = await session.execute(
            select(TelegramTopic).where(TelegramTopic.name == topic_name)
        )
        topic = result.scalar_one_or_none()
        return topic.thread_id if topic else None


async def is_in_topic(message: Message, topic_name: str) -> bool:
    """
    Check if message is in the specified topic.
    
    Rules:
    1. Must be in supergroup (chat.id == TELEGRAM_SUPERGROUP_ID)
    2. message_thread_id must match configured topic thread_id
    3. If topic not configured (thread_id=0), allow general topic (thread_id=None or 0)
    
    Returns:
        True if message is in correct topic, False otherwise
    """
    supergroup_id = os.getenv("TELEGRAM_SUPERGROUP_ID")
    
    # If not in supergroup, deny
    if not supergroup_id or str(message.chat.id) != supergroup_id:
        logger.debug(f"❌ Not in supergroup: chat_id={message.chat.id}, expected={supergroup_id}")
        return False
    
    # Get configured thread_id for topic
    thread_id = await get_topic_thread_id(topic_name)
    
    # If topic not configured (thread_id=0), allow general topic
    if thread_id == 0 or thread_id is None:
        # Allow if in general topic (no thread_id) or thread_id=0
        if message.message_thread_id is None or message.message_thread_id == 0:
            logger.debug(f"✅ In general topic (topic '{topic_name}' not configured)")
            return True
        return False
    
    # Topic is configured - must match exactly
    message_thread_id = message.message_thread_id or 0
    is_match = message_thread_id == thread_id
    
    if is_match:
        logger.debug(f"✅ In topic '{topic_name}': thread_id={message_thread_id}")
    else:
        logger.debug(
            f"❌ Wrong topic: message_thread_id={message_thread_id}, "
            f"expected={thread_id} for topic '{topic_name}'"
        )
    
    return is_match


def require_topic(topic_name: str):
    """
    Decorator to restrict handler to specific topic.
    
    Usage:
        @dp.message(Command("search"))
        @require_topic("assets")
        async def handle_search(message: Message):
            ...
    """
    def decorator(handler):
        async def wrapper(message: Message, *args, **kwargs):
            if not await is_in_topic(message, topic_name):
                logger.warning(
                    f"🚫 Handler blocked: {handler.__name__} requires topic '{topic_name}', "
                    f"but message is in thread_id={message.message_thread_id}"
                )
                # Silent ignore - don't spam user
                return
            
            return await handler(message, *args, **kwargs)
        
        return wrapper
    return decorator

