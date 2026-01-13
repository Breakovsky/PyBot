"""
API роуты для управления сотрудниками (список ПК)
"""

import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
import asyncpg

from ..dependencies import get_db_pool_dep, get_current_admin
from database.repositories.employee_repository import EmployeeRepository
from utils.logger import get_logger
from utils.version_history import create_version_async

logger = get_logger(__name__)

router = APIRouter()


class EmployeeResponse(BaseModel):
    """Информация о сотруднике."""
    id: int
    full_name: str
    workstation_id: Optional[int] = None
    workstation_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    created_at: str
    updated_at: str


class EmployeeCreateRequest(BaseModel):
    """Запрос на создание сотрудника."""
    full_name: str
    workstation_id: Optional[int] = None
    workstation_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class EmployeeUpdateRequest(BaseModel):
    """Запрос на обновление сотрудника."""
    full_name: Optional[str] = None
    workstation_id: Optional[int] = None
    workstation_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class DepartmentResponse(BaseModel):
    """Информация об отделе."""
    id: int
    name: str
    created_at: str


class WorkstationResponse(BaseModel):
    """Информация о рабочей станции."""
    id: int
    name: str
    created_at: str


@router.get("", response_model=List[EmployeeResponse])
async def get_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = Query(None),
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает список сотрудников с пагинацией и поиском.
    
    Args:
        skip: Количество записей для пропуска
        limit: Максимальное количество записей
        search: Поисковый запрос (поиск по ФИО, телефону, email)
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Список сотрудников
    """
    repo = EmployeeRepository(db_pool)
    
    logger.api_request(
        "GET", "/api/v1/employees",
        user_id=current_user.get('id'),
        search=search,
        limit=limit,
        offset=skip
    )
    
    if search:
        # Поиск по запросу
        employees = await repo.search(query=search, limit=limit, offset=skip)
        logger.info(f"Found {len(employees)} employees matching '{search}'", 
                   context={'search_query': search, 'results_count': len(employees)})
    else:
        # Получение всех с пагинацией
        employees = await repo.get_all(limit=limit, offset=skip)
        logger.info(f"Retrieved {len(employees)} employees",
                   context={'limit': limit, 'offset': skip, 'results_count': len(employees)})
    
    return [
        EmployeeResponse(
            id=emp["id"],
            full_name=emp["full_name"],
            workstation_id=emp.get("workstation_id"),
            workstation_name=emp.get("workstation_name"),
            department_id=emp.get("department_id"),
            department_name=emp.get("department_name"),
            phone=emp.get("phone"),
            email=emp.get("email") or emp.get("ad_account"),  # email может быть в ad_account
            created_at=emp["created_at"].isoformat() if emp.get("created_at") else "",
            updated_at=emp["updated_at"].isoformat() if emp.get("updated_at") else ""
        )
        for emp in employees
    ]


@router.get("/versions", response_model=List[dict])
async def get_version_history(
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает историю версий (как в Google Sheets).
    
    Args:
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Список версий
    """
    from utils.version_history import get_version_history
    
    logger.api_request("GET", "/api/v1/employees/versions",
                      user_id=current_user.get('id'))
    
    try:
        versions = await get_version_history(db_pool, limit=100)
        logger.info(f"Retrieved {len(versions)} versions", 
                   context={'versions_count': len(versions)})
        return versions
    except Exception as e:
        logger.error(f"Error getting version history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting version history: {str(e)}"
        )


@router.get("/versions/{version_id}", response_model=dict)
async def get_version(
    version_id: int,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает конкретную версию по ID для сравнения.
    
    Args:
        version_id: ID версии
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Данные версии с сотрудниками
    """
    logger.api_request("GET", f"/api/v1/employees/versions/{version_id}",
                      user_id=current_user.get('id'),
                      version_id=version_id)
    
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    id,
                    snapshot_name,
                    snapshot_type,
                    created_by,
                    created_at,
                    COALESCE(notes, '') as notes,
                    employees_data
                FROM backups.employee_snapshots
                WHERE id = $1
            """, version_id)
            
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Version with ID {version_id} not found"
                )
            
            created_at = row["created_at"]
            if created_at:
                if isinstance(created_at, str):
                    created_at_str = created_at
                else:
                    created_at_str = created_at.isoformat()
            else:
                created_at_str = ""
            
            employees_data = row["employees_data"]
            if isinstance(employees_data, str):
                import json
                employees_data = json.loads(employees_data)
            
            return {
                "id": row["id"],
                "name": row["snapshot_name"],
                "type": row["snapshot_type"],
                "created_by": row["created_by"],
                "created_at": created_at_str,
                "description": row.get("notes", ""),
                "employees": employees_data,
                "employees_count": len(employees_data) if isinstance(employees_data, list) else 0
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting version: {e}", exc_info=True, context={'version_id': version_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting version: {str(e)}"
        )


@router.get("/versions/current", response_model=dict)
async def get_current_version(
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает текущую версию (актуальное состояние таблицы).
    
    Args:
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Текущие данные сотрудников
    """
    logger.api_request("GET", "/api/v1/employees/versions/current",
                      user_id=current_user.get('id'))
    
    try:
        repo = EmployeeRepository(db_pool)
        employees = await repo.get_all(limit=10000, offset=0)
        
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
        
        return {
            "id": None,
            "name": "Текущая версия",
            "type": "current",
            "created_by": "system",
            "created_at": datetime.now().isoformat(),
            "description": "Актуальное состояние таблицы",
            "employees": employees_serialized,
            "employees_count": len(employees_serialized)
        }
    except Exception as e:
        logger.error(f"Error getting current version: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting current version: {str(e)}"
        )


@router.get("/snapshots", response_model=List[dict])
async def list_snapshots(
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает список всех снапшотов.
    
    Args:
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Список снапшотов
    """
    logger.api_request("GET", "/api/v1/employees/snapshots",
                      user_id=current_user.get('id'))
    
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    id, 
                    snapshot_name, 
                    snapshot_type, 
                    created_by, 
                    created_at,
                    COALESCE(notes, '') as notes
                FROM backups.employee_snapshots
                ORDER BY created_at DESC
                LIMIT 100
            """)
            
            snapshots = []
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
                    
                    snapshots.append({
                        "id": row["id"],
                        "snapshot_name": row["snapshot_name"],
                        "snapshot_type": row["snapshot_type"],
                        "created_by": row["created_by"],
                        "created_at": created_at_str,
                        "notes": row.get("notes", "")
                    })
                except Exception as e:
                    logger.error(f"Error processing snapshot row: {e}", 
                               context={'snapshot_id': row.get('id')})
                    continue
            
            logger.info(f"Retrieved {len(snapshots)} snapshots", 
                       context={'snapshots_count': len(snapshots)})
            return snapshots
    except Exception as e:
        logger.error(f"Error loading snapshots: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error loading snapshots: {str(e)}"
        )


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: int,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает информацию о конкретном сотруднике.
    
    Args:
        employee_id: ID сотрудника
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Информация о сотруднике
    """
    logger.api_request("GET", f"/api/v1/employees/{employee_id}",
                      user_id=current_user.get('id'),
                      employee_id=employee_id)
    
    repo = EmployeeRepository(db_pool)
    employee = await repo.get_by_id(employee_id)
    
    if not employee:
        logger.warning("Employee not found", context={'employee_id': employee_id, 'status_code': 404})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee with ID {employee_id} not found"
        )
    
    return EmployeeResponse(
        id=employee["id"],
        full_name=employee["full_name"],
        workstation_id=employee.get("workstation_id"),
        workstation_name=employee.get("workstation_name"),
        department_id=employee.get("department_id"),
        department_name=employee.get("department_name"),
        phone=employee.get("phone"),
        email=employee.get("email") or employee.get("ad_account"),  # email может быть в ad_account
        created_at=employee["created_at"].isoformat() if employee.get("created_at") else "",
        updated_at=employee["updated_at"].isoformat() if employee.get("updated_at") else ""
    )


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    request: EmployeeCreateRequest,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Создаёт нового сотрудника.
    
    Args:
        request: Данные сотрудника
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Созданный сотрудник
    """
    logger.api_request("POST", "/api/v1/employees",
                      user_id=current_user.get('id'),
                      employee_name=request.full_name)
    
    repo = EmployeeRepository(db_pool)
    
    # Обрабатываем workstation_name и department_name
    workstation_id = request.workstation_id
    department_id = request.department_id
    
    if request.workstation_name and not workstation_id:
        # Находим или создаём рабочую станцию по имени
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM employees.workstations WHERE name = $1",
                request.workstation_name.strip()
            )
            if row:
                workstation_id = row["id"]
            else:
                # Создаём новую рабочую станцию
                row = await conn.fetchrow(
                    "INSERT INTO employees.workstations (name) VALUES ($1) RETURNING id",
                    request.workstation_name.strip()
                )
                workstation_id = row["id"]
    
    if request.department_name and not department_id:
        # Находим или создаём отдел по имени
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM employees.departments WHERE name = $1",
                request.department_name.strip()
            )
            if row:
                department_id = row["id"]
            else:
                # Создаём новый отдел
                row = await conn.fetchrow(
                    "INSERT INTO employees.departments (name) VALUES ($1) RETURNING id",
                    request.department_name.strip()
                )
                department_id = row["id"]
    
    # В БД email хранится в ad_account
    created_by = f"web_user_{current_user['id']}_{current_user.get('email', 'unknown')}"
    employee_id = await repo.create(
        full_name=request.full_name,
        workstation_id=workstation_id,
        department_id=department_id,
        phone=request.phone,
        email=request.email,  # Будет сохранено в ad_account
        updated_by=created_by
    )
    
    logger.db_operation("CREATE", "employees.employees", record_id=employee_id,
                       context={'full_name': request.full_name, 'created_by': created_by})
    
    # Создаём автоматическую версию (как в Google Sheets)
    await create_version_async(db_pool, 'create', created_by, 
                              f"Создан сотрудник: {request.full_name}", employee_id)
    
    employee = await repo.get_by_id(employee_id)
    return EmployeeResponse(
        id=employee["id"],
        full_name=employee["full_name"],
        workstation_id=employee.get("workstation_id"),
        workstation_name=employee.get("workstation_name"),
        department_id=employee.get("department_id"),
        department_name=employee.get("department_name"),
        phone=employee.get("phone"),
        email=employee.get("email") or employee.get("ad_account"),  # email может быть в ad_account
        created_at=employee["created_at"].isoformat() if employee.get("created_at") else "",
        updated_at=employee["updated_at"].isoformat() if employee.get("updated_at") else ""
    )


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    request: EmployeeUpdateRequest,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Обновляет информацию о сотруднике.
    
    Args:
        employee_id: ID сотрудника
        request: Новые данные
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Обновлённый сотрудник
    """
    logger.api_request("PUT", f"/api/v1/employees/{employee_id}",
                      user_id=current_user.get('id'),
                      employee_id=employee_id)
    
    repo = EmployeeRepository(db_pool)
    
    # Проверяем существование
    existing = await repo.get_by_id(employee_id)
    if not existing:
        logger.warning(f"Employee not found for update", context={'employee_id': employee_id, 'status_code': 404})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee with ID {employee_id} not found"
        )
    
    # Обрабатываем workstation_name и department_name
    workstation_id = request.workstation_id if request.workstation_id is not None else existing.get("workstation_id")
    department_id = request.department_id if request.department_id is not None else existing.get("department_id")
    
    if request.workstation_name and not workstation_id:
        # Находим или создаём рабочую станцию по имени
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM employees.workstations WHERE name = $1",
                request.workstation_name.strip()
            )
            if row:
                workstation_id = row["id"]
            else:
                # Создаём новую рабочую станцию
                row = await conn.fetchrow(
                    "INSERT INTO employees.workstations (name) VALUES ($1) RETURNING id",
                    request.workstation_name.strip()
                )
                workstation_id = row["id"]
    
    if request.department_name and not department_id:
        # Находим или создаём отдел по имени
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM employees.departments WHERE name = $1",
                request.department_name.strip()
            )
            if row:
                department_id = row["id"]
            else:
                # Создаём новый отдел
                row = await conn.fetchrow(
                    "INSERT INTO employees.departments (name) VALUES ($1) RETURNING id",
                    request.department_name.strip()
                )
                department_id = row["id"]
    
    # Обновляем
    # В БД email хранится в ad_account
    updated_by = f"web_user_{current_user['id']}_{current_user.get('email', 'unknown')}"
    await repo.update(
        employee_id=employee_id,
        full_name=request.full_name if request.full_name is not None else existing["full_name"],
        workstation_id=workstation_id,
        department_id=department_id,
        phone=request.phone if request.phone is not None else existing.get("phone"),
        email=request.email if request.email is not None else existing.get("ad_account"),  # Будет сохранено в ad_account
        updated_by=updated_by
    )
    
    logger.db_operation("UPDATE", "employees.employees", record_id=employee_id,
                       context={'updated_by': updated_by})
    
    # Создаём автоматическую версию (как в Google Sheets)
    await create_version_async(db_pool, 'update', updated_by, 
                              f"Обновлён сотрудник #{employee_id}", employee_id)
    
    employee = await repo.get_by_id(employee_id)
    return EmployeeResponse(
        id=employee["id"],
        full_name=employee["full_name"],
        workstation_id=employee.get("workstation_id"),
        workstation_name=employee.get("workstation_name"),
        department_id=employee.get("department_id"),
        department_name=employee.get("department_name"),
        phone=employee.get("phone"),
        email=employee.get("email") or employee.get("ad_account"),  # email может быть в ad_account
        created_at=employee["created_at"].isoformat() if employee.get("created_at") else "",
        updated_at=employee["updated_at"].isoformat() if employee.get("updated_at") else ""
    )


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    employee_id: int,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Удаляет сотрудника.
    
    Args:
        employee_id: ID сотрудника
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
    """
    logger.api_request("DELETE", f"/api/v1/employees/{employee_id}",
                      user_id=current_user.get('id'),
                      employee_id=employee_id)
    
    repo = EmployeeRepository(db_pool)
    
    existing = await repo.get_by_id(employee_id)
    if not existing:
        logger.warning(f"Employee not found for deletion", context={'employee_id': employee_id, 'status_code': 404})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee with ID {employee_id} not found"
        )
    
    employee_name = existing.get('full_name', 'Unknown')
    await repo.delete_employee(employee_id)
    
    logger.db_operation("DELETE", "employees.employees", record_id=employee_id,
                       context={'employee_name': employee_name})
    
    # Создаём автоматическую версию (как в Google Sheets)
    deleted_by = f"web_user_{current_user['id']}_{current_user.get('email', 'unknown')}"
    await create_version_async(db_pool, 'delete', deleted_by, 
                              f"Удалён сотрудник: {employee_name}", employee_id)


@router.get("/departments/list", response_model=List[DepartmentResponse])
async def get_departments(
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает список всех отделов.
    
    Args:
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Список отделов
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, created_at
            FROM employees.departments
            ORDER BY name
        """)
        return [
            DepartmentResponse(
                id=row["id"],
                name=row["name"],
                created_at=row["created_at"].isoformat() if row.get("created_at") else ""
            )
            for row in rows
        ]


@router.get("/workstations/list", response_model=List[WorkstationResponse])
async def get_workstations(
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Получает список всех рабочих станций.
    
    Args:
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Список рабочих станций
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, created_at
            FROM employees.workstations
            ORDER BY name
        """)
        return [
            WorkstationResponse(
                id=row["id"],
                name=row["name"],
                created_at=row["created_at"].isoformat() if row.get("created_at") else ""
            )
            for row in rows
        ]


@router.post("/snapshots", status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    snapshot_name: Optional[str] = Query(None),
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Создаёт снапшот текущего состояния таблицы сотрудников.
    
    Args:
        snapshot_name: Имя снапшота (опционально)
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Информация о созданном снапшоте
    """
    import json
    from datetime import datetime
    
    logger.api_request("POST", "/api/v1/employees/snapshots",
                      user_id=current_user.get('id'),
                      snapshot_name=snapshot_name)
    
    try:
        repo = EmployeeRepository(db_pool)
        employees = await repo.get_all(limit=10000, offset=0)
        
        if not snapshot_name:
            snapshot_name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        created_by = f"web_user_{current_user['id']}_{current_user.get('email', 'unknown')}"
        
        # Сериализуем данные сотрудников, обрабатывая datetime и другие типы
        def serialize_employee(emp):
            """Сериализует данные сотрудника для JSON."""
            serialized = {}
            for key, value in emp.items():
                if value is None:
                    serialized[key] = None
                elif isinstance(value, datetime):
                    serialized[key] = value.isoformat()
                elif hasattr(value, 'isoformat'):  # Для date и других типов
                    try:
                        serialized[key] = value.isoformat()
                    except:
                        serialized[key] = str(value)
                elif isinstance(value, (int, float, str, bool)):
                    serialized[key] = value
                else:
                    # Для всех остальных типов преобразуем в строку
                    serialized[key] = str(value)
            return serialized
        
        try:
            employees_serialized = [serialize_employee(emp) for emp in employees]
            
            # Преобразуем в JSON строку
            employees_json = json.dumps(employees_serialized, ensure_ascii=False, default=str)
        except Exception as json_error:
            logger.error(f"Error serializing employees data: {json_error}", 
                       exc_info=True,
                       context={'employees_count': len(employees)})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error serializing employees data: {str(json_error)}"
            )
        
        async with db_pool.acquire() as conn:
            try:
                snapshot_id = await conn.fetchval("""
                    INSERT INTO backups.employee_snapshots 
                        (snapshot_name, snapshot_type, created_by, employees_data, notes)
                    VALUES ($1, $2, $3, $4::jsonb, $5)
                    RETURNING id
                """, snapshot_name, 'manual', created_by, employees_json, f"Ручной бэкап: {snapshot_name}")
                
                if not snapshot_id:
                    raise ValueError("Failed to create snapshot - no ID returned")
                
                logger.db_operation("CREATE", "backups.employee_snapshots", record_id=snapshot_id,
                                   context={'snapshot_name': snapshot_name, 'employees_count': len(employees),
                                           'created_by': created_by})
                
                return {
                    "id": snapshot_id,
                    "snapshot_name": snapshot_name,
                    "created_at": datetime.now().isoformat(),
                    "employees_count": len(employees)
                }
            except Exception as db_error:
                logger.error(f"Database error creating snapshot: {db_error}", 
                           exc_info=True,
                           context={'snapshot_name': snapshot_name, 'employees_count': len(employees)})
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Database error creating snapshot: {str(db_error)}"
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating snapshot: {e}", exc_info=True,
                   context={'snapshot_name': snapshot_name})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating snapshot: {str(e)}"
        )


@router.post("/snapshots/{snapshot_id}/restore", status_code=status.HTTP_200_OK)
async def restore_snapshot(
    snapshot_id: int,
    db_pool: asyncpg.Pool = Depends(get_db_pool_dep),
    current_user: dict = Depends(get_current_admin)
):
    """
    Восстанавливает данные сотрудников из снапшота.
    
    Args:
        snapshot_id: ID снапшота
        db_pool: Пул соединений с БД
        current_user: Текущий администратор
        
    Returns:
        Результат восстановления
    """
    import json
    
    logger.api_request("POST", f"/api/v1/employees/snapshots/{snapshot_id}/restore",
                      user_id=current_user.get('id'),
                      snapshot_id=snapshot_id)
    
    try:
        async with db_pool.acquire() as conn:
            # Получаем снапшот
            snapshot = await conn.fetchrow("""
                SELECT employees_data, snapshot_name
                FROM backups.employee_snapshots
                WHERE id = $1
            """, snapshot_id)
            
            if not snapshot:
                logger.warning("Snapshot not found", context={'snapshot_id': snapshot_id, 'status_code': 404})
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Snapshot with ID {snapshot_id} not found"
                )
            
            employees_data = snapshot["employees_data"]
            if isinstance(employees_data, str):
                try:
                    employees_data = json.loads(employees_data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in snapshot: {e}", context={'snapshot_id': snapshot_id})
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid snapshot data: {str(e)}"
                    )
            
            if not isinstance(employees_data, list):
                logger.error("Snapshot data is not a list", context={'snapshot_id': snapshot_id, 'data_type': type(employees_data).__name__})
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Snapshot data must be a list"
                )
            
            repo = EmployeeRepository(db_pool)
            restored_by = f"web_user_{current_user['id']}_{current_user.get('email', 'unknown')}"
            
            # Получаем список ID из снапшота
            snapshot_ids = set()
            for emp_data in employees_data:
                if isinstance(emp_data, dict) and emp_data.get("id"):
                    snapshot_ids.add(emp_data.get("id"))
            
            # Получаем список всех текущих сотрудников
            all_current = await repo.get_all(limit=10000, offset=0)
            current_ids = {emp.get("id") for emp in all_current if emp.get("id")}
            
            # Определяем, кого нужно удалить (есть в БД, но нет в снапшоте)
            ids_to_delete = current_ids - snapshot_ids
            
            # Удаляем сотрудников, которых нет в снапшоте
            deleted_count = 0
            for emp_id in ids_to_delete:
                try:
                    await repo.delete_employee(emp_id)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Error deleting employee during restore: {e}", 
                                 context={'snapshot_id': snapshot_id, 'employee_id': emp_id})
            
            # Восстанавливаем каждого сотрудника из снапшота
            restored_count = 0
            created_count = 0
            updated_count = 0
            errors = []
            
            async with db_pool.acquire() as conn:
                for idx, emp_data in enumerate(employees_data):
                    try:
                        if not isinstance(emp_data, dict):
                            errors.append(f"Row {idx}: not a dict")
                            continue
                        
                        emp_id = emp_data.get("id")
                        if not emp_id:
                            errors.append(f"Row {idx}: missing ID")
                            continue
                        
                        # Получаем данные для восстановления
                        full_name = emp_data.get("full_name") or emp_data.get("full_name", "")
                        workstation_id = emp_data.get("workstation_id")
                        department_id = emp_data.get("department_id")
                        phone = emp_data.get("phone")
                        email = emp_data.get("email") or emp_data.get("ad_account")
                        
                        # Проверяем существование сотрудника
                        existing = await repo.get_by_id(emp_id)
                        
                        if existing:
                            # Обновляем существующего сотрудника
                            await repo.update(
                                employee_id=emp_id,
                                full_name=full_name,
                                workstation_id=workstation_id,
                                department_id=department_id,
                                phone=phone,
                                email=email,
                                updated_by=restored_by
                            )
                            updated_count += 1
                        else:
                            # Создаём нового сотрудника с оригинальным ID
                            # Используем прямой SQL для установки ID
                            try:
                                await conn.execute("""
                                    INSERT INTO employees.employees 
                                        (id, full_name, department_id, workstation_id, phone, ad_account, updated_by)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                                """, emp_id, full_name, department_id, workstation_id, phone, email, restored_by)
                                created_count += 1
                            except Exception as insert_error:
                                # Если не удалось вставить с оригинальным ID (например, конфликт),
                                # создаём с автоинкрементом
                                logger.warning(f"Could not restore employee with original ID {emp_id}, creating new: {insert_error}",
                                            context={'snapshot_id': snapshot_id, 'employee_id': emp_id})
                                await repo.create(
                                    full_name=full_name,
                                    workstation_id=workstation_id,
                                    department_id=department_id,
                                    phone=phone,
                                    email=email,
                                    updated_by=restored_by
                                )
                                created_count += 1
                        
                        restored_count += 1
                    except Exception as e:
                        errors.append(f"Row {idx} (ID: {emp_data.get('id', 'unknown')}): {str(e)}")
                        logger.warning(f"Error restoring employee from snapshot: {e}", 
                                     context={'snapshot_id': snapshot_id, 'employee_id': emp_data.get('id')})
            
            # Создаём автоматическую версию после восстановления
            await create_version_async(db_pool, 'restore', restored_by, 
                                      f"Восстановлен бэкап: {snapshot['snapshot_name']}", None)
            
            logger.db_operation("RESTORE", "backups.employee_snapshots", record_id=snapshot_id,
                               context={'snapshot_name': snapshot["snapshot_name"], 
                                       'restored_count': restored_count,
                                       'updated_count': updated_count,
                                       'created_count': created_count,
                                       'deleted_count': deleted_count,
                                       'total_count': len(employees_data),
                                       'errors_count': len(errors),
                                       'restored_by': restored_by})
            
            result = {
                "success": True,
                "snapshot_name": snapshot["snapshot_name"],
                "restored_count": restored_count,
                "updated_count": updated_count,
                "created_count": created_count,
                "deleted_count": deleted_count,
                "total_count": len(employees_data),
                "restored_by": restored_by
            }
            
            if errors:
                result["errors"] = errors[:10]  # Первые 10 ошибок
                result["errors_count"] = len(errors)
            
            return result
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring snapshot: {e}", exc_info=True, context={'snapshot_id': snapshot_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error restoring snapshot: {str(e)}"
        )

