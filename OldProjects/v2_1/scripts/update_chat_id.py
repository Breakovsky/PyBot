"""
Скрипт для обновления ID чата и топиков.
"""

import asyncio
import sys
import os
import io
from pathlib import Path
from urllib.parse import quote_plus

# Настройка кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, ValueError):
        pass

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent / "main"))

from dotenv import load_dotenv
from database.connection import init_db_pool, close_db_pool
from config.settings import init_settings
from config.security import get_security_manager


async def update_chat_settings():
    """Обновляет настройки чата и топиков."""
    
    # Загружаем .env если есть
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env from: {env_path}")
    else:
        print("⚠️  .env file not found, using environment variables and defaults")
    
    # Подключаемся к БД
    security = get_security_manager()
    db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    db_user_escaped = quote_plus(db_user)
    if db_password:
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user_escaped}@{db_host}:{db_port}/{db_name}"
    
    db_pool = init_db_pool(dsn, min_size=2, max_size=5)
    await db_pool.initialize()
    
    settings = init_settings(db_pool)
    
    print("\n" + "=" * 60)
    print("Обновление настроек чата и топиков")
    print("=" * 60 + "\n")
    
    # Показываем текущие настройки
    print("📋 Текущие настройки:")
    current_chat_id = await settings.get("TELEGRAM_CHAT_ID", "-1")
    current_excel_topic = await settings.get("EXCEL_TOPIC_ID", "0")
    current_ping_topic = await settings.get("PING_TOPIC_ID", "0")
    current_bot_topic = await settings.get("BOT_TOPIC_ID", "0")
    current_metrics_topic = await settings.get("METRICS_TOPIC_ID", "0")
    current_tasks_topic = await settings.get("TASKS_TOPIC_ID", "0")
    
    print(f"   TELEGRAM_CHAT_ID: {current_chat_id}")
    print(f"   EXCEL_TOPIC_ID: {current_excel_topic}")
    print(f"   PING_TOPIC_ID: {current_ping_topic}")
    print(f"   BOT_TOPIC_ID: {current_bot_topic}")
    print(f"   METRICS_TOPIC_ID: {current_metrics_topic}")
    print(f"   TASKS_TOPIC_ID: {current_tasks_topic}")
    print()
    
    # Запрашиваем новые значения
    print("Введите новые значения (Enter для пропуска):")
    
    new_chat_id = input(f"TELEGRAM_CHAT_ID [{current_chat_id}]: ").strip()
    if new_chat_id:
        await settings.set("TELEGRAM_CHAT_ID", new_chat_id, category="telegram", 
                          description="ID группового чата (отрицательное число)", updated_by="user")
        print(f"✅ Обновлено: TELEGRAM_CHAT_ID = {new_chat_id}")
    
    new_excel_topic = input(f"EXCEL_TOPIC_ID [{current_excel_topic}]: ").strip()
    if new_excel_topic:
        await settings.set("EXCEL_TOPIC_ID", new_excel_topic, category="telegram",
                          description="ID топика для поиска сотрудников (Excel)", updated_by="user")
        print(f"✅ Обновлено: EXCEL_TOPIC_ID = {new_excel_topic}")
    
    new_ping_topic = input(f"PING_TOPIC_ID [{current_ping_topic}]: ").strip()
    if new_ping_topic:
        await settings.set("PING_TOPIC_ID", new_ping_topic, category="telegram",
                          description="ID топика для мониторинга серверов", updated_by="user")
        print(f"✅ Обновлено: PING_TOPIC_ID = {new_ping_topic}")
    
    new_bot_topic = input(f"BOT_TOPIC_ID [{current_bot_topic}]: ").strip()
    if new_bot_topic:
        await settings.set("BOT_TOPIC_ID", new_bot_topic, category="telegram",
                          description="ID топика для сообщений бота", updated_by="user")
        print(f"✅ Обновлено: BOT_TOPIC_ID = {new_bot_topic}")
    
    new_metrics_topic = input(f"METRICS_TOPIC_ID [{current_metrics_topic}]: ").strip()
    if new_metrics_topic:
        await settings.set("METRICS_TOPIC_ID", new_metrics_topic, category="telegram",
                          description="ID топика для метрик мониторинга", updated_by="user")
        print(f"✅ Обновлено: METRICS_TOPIC_ID = {new_metrics_topic}")
    
    new_tasks_topic = input(f"TASKS_TOPIC_ID [{current_tasks_topic}]: ").strip()
    if new_tasks_topic:
        await settings.set("TASKS_TOPIC_ID", new_tasks_topic, category="telegram",
                          description="ID топика для заявок OTRS", updated_by="user")
        print(f"✅ Обновлено: TASKS_TOPIC_ID = {new_tasks_topic}")
    
    print("\n" + "=" * 60)
    print("✅ Настройки обновлены!")
    print("=" * 60)
    print("\n⚠️  Не забудьте перезапустить бота: .\\bot.ps1 restart")
    
    await db_pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(update_chat_settings())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

