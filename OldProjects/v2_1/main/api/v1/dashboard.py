"""
API роуты для дашборда (статистика, мониторинг)
"""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel
import asyncpg

from ..dependencies import get_db_pool_dep, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class DashboardStatsResponse(BaseModel):
    """Статистика для дашборда."""
    employees_count: int
    departments_count: int
    workstations_count: int
    telegram_users_count: int
    otrs_tickets_today: int
    otrs_actions_today: int


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_user)
):
    """
    Получает статистику для дашборда.
    
    Args:
        db_pool: Пул соединений с БД
        current_user: Текущий пользователь
        
    Returns:
        Статистика
    """
    async with db_pool.acquire() as conn:
        # Количество сотрудников
        employees_count = await conn.fetchval("""
            SELECT COUNT(*) FROM employees.employees
        """) or 0
        
        # Количество отделов
        departments_count = await conn.fetchval("""
            SELECT COUNT(*) FROM employees.departments
        """) or 0
        
        # Количество рабочих станций
        workstations_count = await conn.fetchval("""
            SELECT COUNT(*) FROM employees.workstations
        """) or 0
        
        # Количество пользователей Telegram
        telegram_users_count = await conn.fetchval("""
            SELECT COUNT(*) FROM telegram.telegram_users
        """) or 0
        
        # Тикеты OTRS за сегодня
        otrs_tickets_today = await conn.fetchval("""
            SELECT COUNT(DISTINCT ticket_id)
            FROM otrs.otrs_metrics
            WHERE DATE(action_time) = CURRENT_DATE
        """) or 0
        
        # Действия OTRS за сегодня
        otrs_actions_today = await conn.fetchval("""
            SELECT COUNT(*)
            FROM otrs.otrs_metrics
            WHERE DATE(action_time) = CURRENT_DATE
        """) or 0
        
        return DashboardStatsResponse(
            employees_count=employees_count,
            departments_count=departments_count,
            workstations_count=workstations_count,
            telegram_users_count=telegram_users_count,
            otrs_tickets_today=otrs_tickets_today,
            otrs_actions_today=otrs_actions_today
        )

