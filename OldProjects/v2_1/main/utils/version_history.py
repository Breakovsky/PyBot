"""
Система версий как в Google Sheets - автоматическое создание версий при изменениях.
"""

import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, List
import asyncpg
from utils.logger import get_logger

logger = get_logger(__name__)


async def create_version_snapshot(
    db_pool: asyncpg.Pool,
    change_type: str,
    changed_by: str,
    description: Optional[str] = None,
    employee_id: Optional[int] = None
) -> Optional[int]:
    """
    Создаёт автоматическую версию (снапшот) при изменении данных.
    Аналогично Google Sheets - каждая версия сохраняется автоматически.
    
    Args:
        db_pool: Пул соединений с БД
        change_type: Тип изменения ('create', 'update', 'delete', 'bulk_update')
        changed_by: Кто сделал изменение
        description: Описание изменения (опционально)
        employee_id: ID сотрудника (для одиночных операций)
        
    Returns:
        ID созданного снапшота или None при ошибке
    """
    try:
        from database.repositories.employee_repository import EmployeeRepository
        
        # Получаем все данные сотрудников
        repo = EmployeeRepository(db_pool)
        employees = await repo.get_all(limit=10000, offset=0)
        
        # Формируем описание версии
        if not description:
            if change_type == 'create':
                description = f"Создан сотрудник #{employee_id}" if employee_id else "Создан новый сотрудник"
            elif change_type == 'update':
                description = f"Обновлён сотрудник #{employee_id}" if employee_id else "Обновление сотрудника"
            elif change_type == 'delete':
                description = f"Удалён сотрудник #{employee_id}" if employee_id else "Удаление сотрудника"
            elif change_type == 'bulk_update':
                description = "Массовое обновление"
            else:
                description = f"Изменение: {change_type}"
        
        # Сериализуем данные
        def serialize_employee(emp):
            serialized = {}
            for key, value in emp.items():
                if value is None:
                    serialized[key] = None
                elif isinstance(value, datetime):
                    serialized[key] = value.isoformat()
                elif hasattr(value, 'isoformat'):
                    try:
                        serialized[key] = value.isoformat()
                    except:
                        serialized[key] = str(value)
                elif isinstance(value, (int, float, str, bool)):
                    serialized[key] = value
                else:
                    serialized[key] = str(value)
            return serialized
        
        employees_serialized = [serialize_employee(emp) for emp in employees]
        employees_json = json.dumps(employees_serialized, ensure_ascii=False, default=str)
        
        # Создаём версию
        version_name = f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        async with db_pool.acquire() as conn:
            snapshot_id = await conn.fetchval("""
                INSERT INTO backups.employee_snapshots 
                    (snapshot_name, snapshot_type, created_by, employees_data, notes)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                RETURNING id
            """, version_name, 'auto', changed_by, employees_json, description)
            
            if snapshot_id:
                logger.info(f"Version snapshot created: {version_name}", 
                           context={'snapshot_id': snapshot_id, 
                                   'change_type': change_type,
                                   'changed_by': changed_by,
                                   'employees_count': len(employees)})
            
            return snapshot_id
            
    except Exception as e:
        logger.error(f"Error creating version snapshot: {e}", exc_info=True,
                   context={'change_type': change_type, 'changed_by': changed_by})
        return None


async def get_version_history(
    db_pool: asyncpg.Pool,
    limit: int = 50
) -> List[Dict]:
    """
    Получает историю версий (как в Google Sheets).
    
    Args:
        db_pool: Пул соединений с БД
        limit: Максимальное количество версий
        
    Returns:
        Список версий с информацией
    """
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    id,
                    snapshot_name,
                    snapshot_type,
                    created_by,
                    created_at,
                    COALESCE(notes, '') as notes,
                    jsonb_array_length(employees_data) as employees_count
                FROM backups.employee_snapshots
                ORDER BY created_at DESC
                LIMIT $1
            """, limit)
            
            versions = []
            for row in rows:
                try:
                    created_at = row["created_at"]
                    if created_at:
                        if isinstance(created_at, str):
                            created_at_str = created_at
                        else:
                            created_at_str = created_at.isoformat()
                    else:
                        created_at_str = ""
                    
                    versions.append({
                        "id": row["id"],
                        "name": row["snapshot_name"],
                        "type": row["snapshot_type"],
                        "created_by": row["created_by"],
                        "created_at": created_at_str,
                        "description": row.get("notes") or "",
                        "employees_count": row.get("employees_count", 0)
                    })
                except Exception as e:
                    logger.warning(f"Error processing version row: {e}", 
                                 context={'version_id': row.get('id')})
                    continue
            
            return versions
            
    except Exception as e:
        logger.error(f"Error getting version history: {e}", exc_info=True)
        return []


async def create_version_async(
    db_pool: asyncpg.Pool,
    change_type: str,
    changed_by: str,
    description: Optional[str] = None,
    employee_id: Optional[int] = None
):
    """
    Создаёт версию асинхронно (не блокирует основной поток).
    """
    asyncio.create_task(
        create_version_snapshot(db_pool, change_type, changed_by, description, employee_id)
    )

