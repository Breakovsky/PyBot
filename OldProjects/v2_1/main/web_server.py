"""
Веб-сервер для TBot v2.1 Admin Panel
"""

import asyncio
import logging
import os
from pathlib import Path
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from api.app import create_app
from database.connection import init_db_pool, close_db_pool
from config.settings import init_settings
from config.security import get_security_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Startup
    logger.info("Starting web server...")
    
    # Инициализация БД
    security = get_security_manager()
    db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    from urllib.parse import quote_plus
    db_user_escaped = quote_plus(db_user)
    if db_password:
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user_escaped}@{db_host}:{db_port}/{db_name}"
    
    db_pool = init_db_pool(dsn, min_size=5, max_size=20)
    await db_pool.initialize()
    logger.info("Database pool initialized")
    
    # Инициализация Settings
    settings = init_settings(db_pool)
    logger.info("Settings initialized")
    
    # Сохраняем в state приложения
    app.state.db_pool = db_pool
    app.state.settings = settings
    app.state.security_manager = security
    
    yield
    
    # Shutdown
    logger.info("Stopping web server...")
    await close_db_pool()
    logger.info("Web server stopped")


def create_web_app():
    """Создаёт веб-приложение."""
    app = create_app(lifespan=lifespan)
    return app


def run_web_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """
    Запускает веб-сервер.
    
    Args:
        host: Хост для прослушивания
        port: Порт для прослушивания
        reload: Автоперезагрузка при изменении кода (для разработки)
    """
    app = create_web_app()
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload
    )


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    
    # Загружаем .env
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    
    # Настраиваем логирование
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))
    reload = os.getenv("WEB_RELOAD", "false").lower() == "true"
    
    logger.info(f"Starting web server on {host}:{port}")
    run_web_server(host=host, port=port, reload=reload)

