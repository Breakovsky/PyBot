"""
Diagnostics handler for system status checks.
"""

import os
import time
import logging
import html
import redis.asyncio as redis
from datetime import datetime, timedelta
from aiogram.types import Message
from sqlalchemy import select, func
from src.core.database import async_session, TelegramUser, Employee

logger = logging.getLogger(__name__)

# Bot startup time (global)
_bot_start_time = time.time()

def set_bot_start_time():
    """Set bot startup timestamp."""
    global _bot_start_time
    _bot_start_time = time.time()


async def get_redis_status(redis_client) -> dict:
    """Check Redis connection status."""
    try:
        start = time.time()
        await redis_client.ping()
        ping_ms = int((time.time() - start) * 1000)
        return {"status": "✅ Connected", "ping_ms": ping_ms}
    except Exception as e:
        logger.error(f"Redis check failed: {e}")
        return {"status": "❌ Error", "error": str(e)}


async def get_db_status() -> dict:
    """Check database status and get counts."""
    try:
        async with async_session() as session:
            # Count users
            user_count = await session.scalar(
                select(func.count()).select_from(TelegramUser)
            )
            
            # Count employees
            employee_count = await session.scalar(
                select(func.count()).select_from(Employee)
            )
            
            return {
                "status": "✅ Connected",
                "users": user_count or 0,
                "employees": employee_count or 0
            }
    except Exception as e:
        logger.error(f"DB check failed: {e}")
        return {"status": "❌ Error", "error": str(e)}


def format_uptime(seconds: float) -> str:
    """Format uptime as human-readable string."""
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    
    return " ".join(parts) if parts else "<1m"


async def handle_test_command(message: Message, user: TelegramUser, redis_client):
    """
    Handle /test command - show system diagnostics.
    """
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    logger.info(f"🔧 /test command from {username} ({user_id})")
    
    try:
        # Get user info
        user_info = f"{username} (ID: {user_id})"
        role_info = f"{user.role.value}"
        
        # Get bot uptime
        uptime_seconds = time.time() - _bot_start_time
        uptime_str = format_uptime(uptime_seconds)
        
        # Check Redis
        redis_status = await get_redis_status(redis_client)
        
        # Check DB
        db_status = await get_db_status()
        
        # Build response (escape user data, keep HTML tags)
        # Escape user-provided data to prevent HTML injection
        safe_user_info = html.escape(user_info)
        safe_role_info = html.escape(role_info)
        safe_uptime = html.escape(uptime_str)
        
        response_lines = [
            "🛠 <b>NetAdmin System Status</b>",
            "════════════════════════════",
            f"👤 <b>You:</b> {safe_user_info}",
            f"👑 <b>Role:</b> {safe_role_info} (Verified from DB)",
            "",
            f"🤖 <b>Bot Uptime:</b> {safe_uptime}",
            "",
            f"📡 <b>Redis:</b> {redis_status['status']}",
        ]
        
        if "ping_ms" in redis_status:
            response_lines.append(f"   • Ping: {redis_status['ping_ms']}ms")
        elif "error" in redis_status:
            error_msg = html.escape(str(redis_status['error']))
            response_lines.append(f"   • Error: {error_msg}")
        
        response_lines.append("")
        response_lines.append(f"🐘 <b>DB:</b> {db_status['status']}")
        
        if "users" in db_status:
            response_lines.append(f"   • Users: {db_status['users']}")
            response_lines.append(f"   • Assets: {db_status['employees']}")
        elif "error" in db_status:
            error_msg = html.escape(str(db_status['error']))
            response_lines.append(f"   • Error: {error_msg}")
        
        response_lines.append("")
        response_lines.append("════════════════════════════")
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        response_lines.append(f"⏰ <i>Checked at: {timestamp}</i>")
        
        response = "\n".join(response_lines)
        await message.reply(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error in /test command: {e}", exc_info=True)
        await message.reply(
            f"❌ Error generating status report:\n<code>{str(e)}</code>",
            parse_mode="HTML"
        )

