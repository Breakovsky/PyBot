"""
API роуты для управления настройками
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import asyncpg

from ..dependencies import get_db_pool_dep, get_settings_dep, get_current_admin
from config.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter()


class SettingResponse(BaseModel):
    """Настройка."""
    key: str
    value: Any
    category: str
    description: Optional[str]
    is_secret: bool


class SettingUpdateRequest(BaseModel):
    """Запрос на обновление настройки."""
    value: Any
    description: Optional[str] = None


@router.get("", response_model=List[SettingResponse])
async def get_all_settings(
    category: Optional[str] = None,
    settings: Settings = Depends(get_settings_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает все настройки (только для администраторов).
    
    Args:
        category: Фильтр по категории (опционально)
        settings: Экземпляр Settings
        current_user: Текущий администратор
        
    Returns:
        Список настроек
    """
    async with settings.db_pool.acquire() as conn:
        if category:
            rows = await conn.fetch("""
                SELECT key, value, category, is_secret, description
                FROM core.settings
                WHERE category = $1
                ORDER BY key
            """, category)
        else:
            rows = await conn.fetch("""
                SELECT key, value, category, is_secret, description
                FROM core.settings
                ORDER BY category, key
            """)
        
        return [
            SettingResponse(
                key=row["key"],
                value=row["value"] if not row["is_secret"] else "***",
                category=row["category"],
                description=row["description"],
                is_secret=row["is_secret"]
            )
            for row in rows
        ]


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    settings: Settings = Depends(get_settings_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает конкретную настройку.
    
    Args:
        key: Ключ настройки
        settings: Экземпляр Settings
        current_user: Текущий администратор
        
    Returns:
        Настройка
    """
    value = await settings.get(key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting '{key}' not found"
        )
    
    async with settings.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT key, value, category, is_secret, description
            FROM core.settings
            WHERE key = $1
        """, key)
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Setting '{key}' not found"
            )
        
        return SettingResponse(
            key=row["key"],
            value=row["value"] if not row["is_secret"] else "***",
            category=row["category"],
            description=row["description"],
            is_secret=row["is_secret"]
        )


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    request: SettingUpdateRequest,
    settings: Settings = Depends(get_settings_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Обновляет настройку.
    
    Args:
        key: Ключ настройки
        request: Новое значение и описание
        settings: Экземпляр Settings
        current_user: Текущий администратор
        
    Returns:
        Обновлённая настройка
    """
    # Проверяем, что настройка не является секретом
    async with settings.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT is_secret FROM core.settings WHERE key = $1
        """, key)
        
        if row and row["is_secret"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update secret settings via API. Use .env or Windows Credential Manager."
            )
    
    # Обновляем настройку
    await settings.set(
        key=key,
        value=request.value,
        description=request.description,
        updated_by=f"web_admin:{current_user['email']}"
    )
    
    # Перезагружаем кэш
    await settings.reload_cache()
    
    # Возвращаем обновлённую настройку
    async with settings.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT key, value, category, is_secret, description
            FROM core.settings
            WHERE key = $1
        """, key)
        
        return SettingResponse(
            key=row["key"],
            value=row["value"],
            category=row["category"],
            description=row["description"],
            is_secret=row["is_secret"]
        )


@router.get("/categories/list", response_model=List[str])
async def get_categories(
    settings: Settings = Depends(get_settings_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает список всех категорий настроек.
    
    Args:
        settings: Экземпляр Settings
        current_user: Текущий администратор
        
    Returns:
        Список категорий
    """
    async with settings.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT category
            FROM core.settings
            ORDER BY category
        """)
        return [row["category"] for row in rows]

