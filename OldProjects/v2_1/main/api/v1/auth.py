"""
API роуты для аутентификации
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
import asyncpg
import bcrypt

from ..dependencies import get_db_pool_dep, create_access_token, get_current_user, get_security_manager_dep
from config.security import SecurityManager

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Запрос на вход."""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Ответ на вход."""
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    """Информация о пользователе."""
    id: int
    email: str
    full_name: Optional[str]
    is_admin: bool


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    security_manager: SecurityManager = Depends(get_security_manager_dep)
):
    """
    Аутентификация пользователя.
    
    Args:
        request: Email и пароль
        db_pool: Пул соединений с БД
        security_manager: SecurityManager из app.state
        
    Returns:
        JWT токен и информация о пользователе
    """
    async with db_pool.acquire() as conn:
        # Ищем пользователя
        user = await conn.fetchrow("""
            SELECT id, email, password_hash, full_name, is_active, is_admin
            FROM core.users
            WHERE email = $1
        """, request.email.lower())
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled"
            )
        
        # Проверяем пароль
        if not user["password_hash"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password not set. Please contact administrator."
            )
        
        if not bcrypt.checkpw(
            request.password.encode('utf-8'),
            user["password_hash"].encode('utf-8')
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Обновляем время последнего входа
        await conn.execute("""
            UPDATE core.users
            SET last_login = NOW()
            WHERE id = $1
        """, user["id"])
        
        # Создаём токен
        access_token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            is_admin=user["is_admin"],
            security_manager=security_manager
        )
        
        return LoginResponse(
            access_token=access_token,
            user={
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "is_admin": user["is_admin"]
            }
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user)
):
    """
    Получает информацию о текущем пользователе.
    
    Args:
        current_user: Текущий пользователь из токена
        
    Returns:
        Информация о пользователе
    """
    return UserResponse(**current_user)


@router.post("/logout")
async def logout():
    """
    Выход пользователя (на клиенте нужно удалить токен).
    
    Returns:
        Сообщение об успешном выходе
    """
    return {"message": "Logged out successfully"}

