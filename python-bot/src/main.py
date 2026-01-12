import asyncio
import logging
import os
import json
import redis.asyncio as redis
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")  # Default to 'redis' for Docker
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Initialize Redis with connection pool
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
    retry_on_timeout=True
)

# Initialize Bot and Dispatcher
if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set!")
    exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """
    Handle /start command.
    """
    await message.answer("NetAdmin Bot v2.0 (LTS) Online.\nUse /test_mail to simulate MDaemon user creation.")

@dp.message(Command("test_mail"))
async def cmd_test_mail(message: Message):
    """
    Test MDaemon integration.
    Sends a 'CREATE_USER' task to the Java backend.
    """
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    task_payload = {
        "action": "CREATE_USER",
        "user_id": user_id,
        "username": username,
        "payload": {
            "email": f"{username}@example.com",
            "domain": "example.com"
        }
    }
    
    try:
        # Publish to Redis channel
        await redis_client.publish("netadmin_tasks", json.dumps(task_payload))
        logger.info(f"Published CREATE_USER task to Redis: {task_payload}")
        await message.answer(f"Command sent to backend!\nCreating user: {username}@example.com")
    except Exception as e:
        logger.error(f"Failed to publish to Redis: {e}")
        await message.answer("Error connecting to backend system.")

async def check_redis_connection():
    """Check Redis connection before starting bot"""
    max_retries = 5
    for i in range(max_retries):
        try:
            await redis_client.ping()
            logger.info(f"✓ Redis connected at {REDIS_HOST}:{REDIS_PORT}")
            return True
        except Exception as e:
            logger.warning(f"Redis connection attempt {i+1}/{max_retries} failed: {e}")
            if i < max_retries - 1:
                await asyncio.sleep(2)
            else:
                logger.error("Failed to connect to Redis after all retries")
                return False
    return False

async def main():
    logger.info("Starting NetAdmin Bot LTS...")
    
    # Check Redis connection first
    if not await check_redis_connection():
        logger.error("Cannot start bot without Redis connection")
        exit(1)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot execution failed: {e}")
    finally:
        await redis_client.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
