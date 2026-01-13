import asyncio
import logging
import os
import json
import redis.asyncio as redis
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, update

# Core imports
from src.core.database import async_session, TelegramTopic, UserRole, TelegramUser, Employee
from src.core.middlewares import RoleMiddleware
from src.core.topic_filter import require_topic, is_in_topic
from src.handlers.asset_search import handle_asset_search
from src.handlers.diagnostics import handle_test_command, set_bot_start_time

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Initialize Bot
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Redis
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# Register Middleware
dp.message.middleware(RoleMiddleware())

# --- Topic Helper ---
async def get_topic_id(session, topic_name):
    result = await session.execute(select(TelegramTopic).where(TelegramTopic.name == topic_name))
    topic = result.scalar_one_or_none()
    return topic.thread_id if topic else None

# --- Handlers ---

@dp.message(Command("start"))
async def cmd_start(message: Message, user: TelegramUser):
    """Welcome message with user info"""
    await message.answer(
        f"NetAdmin v3.0 (RBAC Enabled)\n"
        f"Welcome, {user.username or 'User'}!\n"
        f"Your Role: {user.role.value}\n\n"
        f"Use /test to check system status"
    )

@dp.message(Command("test"))
async def cmd_test(message: Message, user: TelegramUser):
    """System diagnostics command"""
    await handle_test_command(message, user, redis_client)

@dp.message(Command("admin"), flags={"role": UserRole.SENIOR_ADMIN})
async def cmd_admin(message: Message, user: TelegramUser):
    """Restricted to Senior Admin+"""
    await message.answer(f"🔧 Admin Console Active.\nWelcome, {user.username} ({user.role.value}).")

@dp.message(Command("set_topic"), flags={"role": UserRole.CTO})
async def cmd_set_topic(message: Message):
    """
    Map current thread to a logical topic.
    Usage: /set_topic tickets
    """
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /set_topic <name> (e.g., tickets, monitoring)")
        return

    topic_name = args[1]
    thread_id = message.message_thread_id or 0 # 0 for general topic/private

    async with async_session() as session:
        stmt = select(TelegramTopic).where(TelegramTopic.name == topic_name)
        result = await session.execute(stmt)
        topic = result.scalar_one_or_none()

        if topic:
            topic.thread_id = thread_id
            await message.answer(f"✅ Topic '{topic_name}' updated to Thread ID: {thread_id}")
        else:
            await message.answer(f"❌ Topic '{topic_name}' not found in DB schema.")
        
        await session.commit()

@dp.message(F.text.regexp(r"^[Ww][Ss][-\s]?\d+$")) # Workstation Pattern: WS-123, ws123, WS 123
async def handle_workstation_query(message: Message):
    """Handle workstation queries like WS-101 - ONLY in #assets topic"""
    # Topic isolation: Only allow in assets topic
    if not await is_in_topic(message, "assets"):
        logger.debug(f"🚫 Workstation query blocked: not in #assets topic")
        return
    
    query = message.text.strip()
    logger.info(f"🔍 Workstation query from {message.from_user.username} ({message.from_user.id}): '{query}'")
    await handle_asset_search(message, query)

@dp.message(F.text.regexp(r"^\d{3,}$")) # Phone Pattern: 1234 or longer
async def handle_phone_query(message: Message):
    """Handle phone number queries - ONLY in #assets topic"""
    # Topic isolation: Only allow in assets topic
    if not await is_in_topic(message, "assets"):
        logger.debug(f"🚫 Phone query blocked: not in #assets topic")
        return
    
    query = message.text.strip()
    logger.info(f"📞 Phone query from {message.from_user.username} ({message.from_user.id}): '{query}'")
    await handle_asset_search(message, query)

@dp.message(Command("search"))
async def cmd_search(message: Message):
    """Generic search command: /search <query> - ONLY in #assets topic"""
    # Topic isolation: Only allow in assets topic
    if not await is_in_topic(message, "assets"):
        await message.reply("❌ Asset search is only available in #assets topic.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Usage: /search <WS number / phone / name>")
        return
    
    query = args[1].strip()
    logger.info(f"🔎 Search command from {message.from_user.username}: '{query}'")
    await handle_asset_search(message, query)

@dp.message(Command("cookie"))
async def cmd_cookie(message: Message):
    """Give a cookie to a user (Gamification)"""
    if not message.reply_to_message:
        await message.reply("Reply to a user to give them a cookie! 🍪")
        return

    recipient_id = message.reply_to_message.from_user.id
    
    async with async_session() as session:
        # Find or create recipient
        result = await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == recipient_id))
        user = result.scalar_one_or_none()
        if not user:
            user = TelegramUser(telegram_id=recipient_id, username=message.reply_to_message.from_user.username)
            session.add(user)
        
        user.karma_points += 1
        await session.commit()
        await message.answer(f"🍪 Cookie given! {user.username} now has {user.karma_points} karma.")

@dp.message()
async def handle_unhandled_message(message: Message):
    """Catch-all handler for debugging unhandled messages"""
    text = message.text or "[non-text message]"
    logger.info(f"❓ Unhandled message from {message.from_user.username} ({message.from_user.id}): '{text}' (type: {message.content_type})")
    
    # Optionally reply with help
    if message.chat.type == "private":
        await message.reply(
            "ℹ️ Available commands:\n"
            "/start - Register\n"
            "/admin - Admin panel\n"
            "/search <query> - Search employees\n"
            "/cookie - Give karma\n\n"
            "Or send:\n"
            "• WS-123 (workstation)\n"
            "• 1234 (phone)\n"
            "• Name (text search)"
        )

# --- Background Worker (Redis Listener) ---

# Exponential backoff configuration
REDIS_RECONNECT_BASE_DELAY = 1  # seconds
REDIS_RECONNECT_MAX_DELAY = 60  # seconds
REDIS_HEALTH_CHECK_INTERVAL = 30  # seconds


async def redis_listener():
    """
    Redis Pub/Sub listener for alerts from Java Agent.
    
    Features:
    - Exponential backoff on connection failures
    - Periodic health checks
    - Graceful error handling
    
    Message Format: "TOPIC_NAME|MESSAGE"
    """
    reconnect_delay = REDIS_RECONNECT_BASE_DELAY
    consecutive_failures = 0
    
    while True:
        pubsub = None
        try:
            # Test connection first
            await redis_client.ping()
            logger.info("✅ Redis connection established")
            
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("bot_alerts", "netadmin_tasks")
            
            logger.info("🎧 Redis Listener Active - Subscribed to: bot_alerts, netadmin_tasks")
            
            # Reset backoff on successful connection
            reconnect_delay = REDIS_RECONNECT_BASE_DELAY
            consecutive_failures = 0
            
            # Listen with timeout for health checks
            last_health_check = asyncio.get_event_loop().time()
            
            async for message in pubsub.listen():
                # Periodic health check
                current_time = asyncio.get_event_loop().time()
                if current_time - last_health_check > REDIS_HEALTH_CHECK_INTERVAL:
                    try:
                        await redis_client.ping()
                        last_health_check = current_time
                    except Exception as ping_error:
                        logger.warning(f"Redis health check failed: {ping_error}")
                        break  # Exit loop to reconnect
                
                if message['type'] != 'message':
                    continue
                    
                channel = message['channel']
                data = message['data']
                
                logger.debug(f"📨 Received message on {channel}: {data[:100] if data else 'empty'}...")
                
                if channel == "bot_alerts":
                    await process_alert(data)
                
                elif channel == "netadmin_tasks":
                    logger.info(f"📋 Task received: {data[:100] if data else 'empty'}...")
        
        except asyncio.CancelledError:
            logger.info("🛑 Redis listener cancelled")
            raise
        
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"❌ Redis Listener error (attempt {consecutive_failures}): {e}")
            
            # Exponential backoff with max limit
            reconnect_delay = min(
                REDIS_RECONNECT_BASE_DELAY * (2 ** consecutive_failures),
                REDIS_RECONNECT_MAX_DELAY
            )
            logger.info(f"🔄 Reconnecting in {reconnect_delay} seconds...")
            await asyncio.sleep(reconnect_delay)
        
        finally:
            # Clean up pubsub connection
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass


async def process_alert(data: str):
    """Process an alert message from Redis."""
    try:
        if not data or "|" not in data:
            logger.warning(f"Invalid alert format (missing |): {data}")
            return
        
        topic_name, text = data.split("|", 1)
        topic_name = topic_name.strip()
        
        logger.info(f"🚨 Alert for topic '{topic_name}': {text[:50]}...")
        
        async with async_session() as session:
            thread_id = await get_topic_id(session, topic_name)
            
            chat_id = os.getenv("TELEGRAM_SUPERGROUP_ID")
            
            if not chat_id:
                logger.error("❌ TELEGRAM_SUPERGROUP_ID not set - cannot send alert")
                return
            
            # Send to Telegram with retry
            for attempt in range(3):
                try:
                    await bot.send_message(
                        chat_id=chat_id, 
                        text=text, 
                        message_thread_id=thread_id,
                        parse_mode="HTML"
                    )
                    logger.info(f"✅ Alert sent to topic '{topic_name}' (thread_id={thread_id})")
                    return
                except Exception as send_error:
                    logger.warning(f"Send attempt {attempt + 1} failed: {send_error}")
                    if attempt < 2:
                        await asyncio.sleep(1)
            
            # Fallback: Send to general chat without topic
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                logger.info("✅ Alert sent to general chat (fallback)")
            except Exception as fallback_error:
                logger.error(f"Fallback send also failed: {fallback_error}")
    
    except Exception as e:
        logger.error(f"❌ Alert processing error: {e}", exc_info=True)

async def main():
    """Main entry point."""
    # Set bot startup time for uptime calculation
    set_bot_start_time()
    
    # Start Redis Listener as background task
    redis_task = asyncio.create_task(redis_listener())
    
    # Add exception handler
    def handle_redis_exception(task):
        try:
            task.result()
        except Exception as e:
            logger.error(f"❌ Redis listener crashed: {e}", exc_info=True)
    
    redis_task.add_done_callback(handle_redis_exception)
    
    try:
        # Start Bot
        await dp.start_polling(bot)
    finally:
        # Cleanup on shutdown
        logger.info("Shutting down...")
        redis_task.cancel()
        try:
            await redis_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    asyncio.run(main())
