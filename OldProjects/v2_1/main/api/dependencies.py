"""
Зависимости для API роутов
"""

import logging
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from datetime import datetime, timedelta
import asyncpg

from database.connection import get_db_pool
from config.settings import get_settings
from config.security import get_security_manager, SecurityManager

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_db_pool_dep(request: Request):
    """Получает пул БД из state приложения."""
    db_pool = getattr(request.app.state, 'db_pool', None)
    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool not available"
        )
    return db_pool


async def get_settings_dep(request: Request):
    """Получает Settings из state приложения."""
    settings = getattr(request.app.state, 'settings', None)
    if settings is None:
        # Пытаемся получить из глобального состояния
        try:
            return get_settings()
        except RuntimeError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Settings not available"
            )
    return settings


async def get_security_manager_dep(request: Request) -> SecurityManager:
    """Получает SecurityManager из state приложения."""
    security_manager = getattr(request.app.state, 'security_manager', None)
    if security_manager is None:
        # Fallback на глобальный экземпляр
        return get_security_manager()
    return security_manager


def create_access_token(
    user_id: int, 
    email: str, 
    is_admin: bool = False,
    security_manager: SecurityManager = None
) -> str:
    """
    Создаёт JWT токен для пользователя.
    
    Args:
        user_id: ID пользователя
        email: Email пользователя
        is_admin: Является ли администратором
        security_manager: Экземпляр SecurityManager (опционально, для тестирования)
        
    Returns:
        JWT токен
    """
    if security_manager is None:
        security_manager = get_security_manager()
    secret_key = security_manager.get_secret("JWT_SECRET") or "your-secret-key-change-in-production"
    
    payload = {
        "user_id": user_id,
        "email": email,
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(payload, secret_key, algorithm="HS256")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    security_manager: SecurityManager = Depends(get_security_manager_dep)
) -> dict:
    """
    Получает текущего авторизованного пользователя из JWT токена.
    
    Args:
        credentials: HTTP Bearer токен
        db_pool: Пул соединений с БД
        security_manager: SecurityManager из app.state
        
    Returns:
        Информация о пользователе
        
    Raises:
        HTTPException: Если токен невалиден или пользователь не найден
    """
    token = credentials.credentials
    
    try:
        secret_key = security_manager.get_secret("JWT_SECRET") or "your-secret-key-change-in-production"
        
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        user_id = payload.get("user_id")
        email = payload.get("email")
        
        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
        
        # Проверяем, что пользователь существует и активен
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT id, email, full_name, is_active, is_admin
                FROM core.users
                WHERE id = $1 AND email = $2 AND is_active = TRUE
            """, user_id, email)
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive"
                )
            
            return {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "is_admin": user["is_admin"]
            }
            
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed"
        )


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Проверяет, что текущий пользователь является администратором.
    
    Args:
        current_user: Текущий пользователь
        
    Returns:
        Информация о пользователе-администраторе
        
    Raises:
        HTTPException: Если пользователь не является администратором
    """
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

