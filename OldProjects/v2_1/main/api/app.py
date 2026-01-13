"""
Основное FastAPI приложение для веб-интерфейса TBot v2.1
"""

import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


def create_app(db_pool=None, settings=None, security_manager=None, lifespan=None) -> FastAPI:
    """
    Создаёт и настраивает FastAPI приложение.
    
    Args:
        db_pool: Пул соединений с БД
        settings: Экземпляр Settings
        security_manager: Экземпляр SecurityManager
        lifespan: Lifespan контекст (опционально)
        
    Returns:
        Настроенное FastAPI приложение
    """
    app_kwargs = {
        "title": "TBot v2.1 Admin Panel",
        "description": "Веб-интерфейс для управления Telegram ботом",
        "version": "2.1.0",
        "docs_url": "/api/docs",
        "redoc_url": "/api/redoc"
    }
    
    if lifespan:
        app_kwargs["lifespan"] = lifespan
    
    app = FastAPI(**app_kwargs)
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # В production заменить на конкретные домены
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Статические файлы
    static_dir = Path(__file__).parent.parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    # Шаблоны
    templates_dir = Path(__file__).parent.parent.parent / "web" / "templates"
    if templates_dir.exists():
        jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))
        templates = jinja_env
    else:
        templates = None
    
    # Сохраняем зависимости в state (правильный паттерн FastAPI)
    app.state.db_pool = db_pool
    app.state.settings = settings
    app.state.security_manager = security_manager
    
    # Подключаем роуты
    from .v1 import auth, settings as settings_api, employees, dashboard
    
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
    app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["Settings"])
    app.include_router(employees.router, prefix="/api/v1/employees", tags=["Employees"])
    app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
    
    # Главная страница
    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        """Главная страница веб-интерфейса."""
        if templates:
            template = templates.get_template("index.html")
            return HTMLResponse(template.render(request=request))
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>TBot v2.1 Admin Panel</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <h1>TBot v2.1 Admin Panel</h1>
            <p>Веб-интерфейс находится в разработке.</p>
            <p><a href="/api/docs">API Documentation</a></p>
        </body>
        </html>
        """)
    
    logger.info("FastAPI application created")
    return app

