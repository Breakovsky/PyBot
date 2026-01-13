"""
Репозиторий для работы с данными сотрудников (бывший Excel).
"""

import logging
import re
from typing import List, Optional, Dict
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)


class EmployeeRepository:
    """Репозиторий для работы с сотрудниками."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    async def search_by_name(self, query: str, limit: int = 100) -> List[Dict]:
        """
        Поиск сотрудников по имени (частичное совпадение).
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            
        Returns:
            Список сотрудников
        """
        search_pattern = f"%{query.lower()}%"
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    w.ip_address,
                    e.phone,
                    e.ad_account,
                    e.notes
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE LOWER(e.full_name) LIKE $1
                ORDER BY e.full_name
                LIMIT $2
            """, search_pattern, limit)
            
            return [dict(row) for row in rows]
    
    async def search_by_phone(self, phone: str) -> List[Dict]:
        """
        Поиск сотрудника по телефону.
        Сначала ищет точное совпадение, затем частичное.
        """
        # Нормализуем телефон (убираем пробелы, дефисы и т.д.)
        phone_normalized = re.sub(r'[\s\-\(\)]', '', phone)
        
        async with self.db_pool.acquire() as conn:
            # Сначала пробуем точное совпадение (с нормализацией)
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    w.ip_address,
                    e.phone,
                    e.ad_account,
                    e.notes
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE REGEXP_REPLACE(e.phone, '[\\s\\-\\(\\)]', '', 'g') = $1
                   OR e.phone = $2
            """, phone_normalized, phone)
            
            # Если нашли точное совпадение, возвращаем
            if rows:
                return [dict(row) for row in rows]
            
            # Если не нашли, ищем частичное совпадение
            search_pattern = f"%{phone_normalized}%"
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    w.ip_address,
                    e.phone,
                    e.ad_account,
                    e.notes
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE REGEXP_REPLACE(e.phone, '[\\s\\-\\(\\)]', '', 'g') LIKE $1
                   OR e.phone LIKE $2
                ORDER BY e.phone
            """, search_pattern, f"%{phone}%")
            
            return [dict(row) for row in rows]
    
    async def search_by_workstation_exact(self, workstation: str) -> List[Dict]:
        """Поиск сотрудника по рабочей станции (точное совпадение)."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    w.ip_address,
                    e.phone,
                    e.ad_account,
                    e.notes
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE LOWER(w.name) = LOWER($1)
            """, workstation)
            
            return [dict(row) for row in rows]
    
    async def search_by_workstation(self, workstation: str) -> List[Dict]:
        """Поиск сотрудника по рабочей станции (частичное совпадение)."""
        if not workstation:
            # Если пусто, возвращаем пустой список
            return []
        
        search_pattern = f"%{workstation.lower()}%"
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    w.ip_address,
                    e.phone,
                    e.ad_account,
                    e.notes
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE LOWER(w.name) LIKE $1
                ORDER BY w.name
            """, search_pattern)
            
            return [dict(row) for row in rows]
    
    async def search_by_ip(self, ip: str) -> List[Dict]:
        """Поиск сотрудника по IP-адресу."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    w.ip_address,
                    e.phone,
                    e.ad_account,
                    e.notes
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE w.ip_address = $1
            """, ip)
            
            return [dict(row) for row in rows]
    
    async def get_all_departments(self) -> List[Dict]:
        """Получить все подразделения."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, description
                FROM employees.departments
                ORDER BY name
            """)
            
            return [dict(row) for row in rows]
    
    async def create_employee(
        self,
        full_name: str,
        department_id: Optional[int] = None,
        workstation_id: Optional[int] = None,
        phone: Optional[str] = None,
        ad_account: Optional[str] = None,
        notes: Optional[str] = None,
        updated_by: str = "system"
    ) -> int:
        """Создать нового сотрудника."""
        async with self.db_pool.acquire() as conn:
            employee_id = await conn.fetchval("""
                INSERT INTO employees.employees 
                    (full_name, department_id, workstation_id, phone, ad_account, notes, updated_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            """, full_name, department_id, workstation_id, phone, ad_account, notes, updated_by)
            
            logger.db_operation("CREATE", "employees.employees", record_id=employee_id,
                               context={'full_name': full_name, 'department_id': department_id,
                                       'workstation_id': workstation_id, 'updated_by': updated_by})
            return employee_id
    
    async def update_employee(
        self,
        employee_id: int,
        full_name: Optional[str] = None,
        department_id: Optional[int] = None,
        workstation_id: Optional[int] = None,
        phone: Optional[str] = None,
        ad_account: Optional[str] = None,
        notes: Optional[str] = None,
        updated_by: str = "system"
    ) -> bool:
        """Обновить данные сотрудника."""
        # Формируем динамический UPDATE запрос
        updates = []
        params = []
        param_num = 1
        
        if full_name is not None:
            updates.append(f"full_name = ${param_num}")
            params.append(full_name)
            param_num += 1
        
        if department_id is not None:
            updates.append(f"department_id = ${param_num}")
            params.append(department_id)
            param_num += 1
        
        if workstation_id is not None:
            updates.append(f"workstation_id = ${param_num}")
            params.append(workstation_id)
            param_num += 1
        
        if phone is not None:
            updates.append(f"phone = ${param_num}")
            params.append(phone)
            param_num += 1
        
        if ad_account is not None:
            updates.append(f"ad_account = ${param_num}")
            params.append(ad_account)
            param_num += 1
        
        if notes is not None:
            updates.append(f"notes = ${param_num}")
            params.append(notes)
            param_num += 1
        
        if not updates:
            return False
        
        updates.append(f"updated_by = ${param_num}")
        params.append(updated_by)
        param_num += 1
        
        updates.append("updated_at = NOW()")
        params.append(employee_id)
        
        query = f"""
            UPDATE employees.employees
            SET {', '.join(updates)}
            WHERE id = ${param_num}
        """
        
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(query, *params)
            success = result != "UPDATE 0"
            
            if success:
                # Формируем контекст обновленных полей
                updated_fields = {}
                if full_name is not None:
                    updated_fields['full_name'] = full_name
                if department_id is not None:
                    updated_fields['department_id'] = department_id
                if workstation_id is not None:
                    updated_fields['workstation_id'] = workstation_id
                if phone is not None:
                    updated_fields['phone'] = phone
                
                logger.db_operation("UPDATE", "employees.employees", record_id=employee_id,
                                   context={'updated_fields': list(updated_fields.keys()),
                                           'updated_by': updated_by})
            
            return success
    
    async def delete_employee(self, employee_id: int) -> bool:
        """Удалить сотрудника."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM employees.employees
                WHERE id = $1
            """, employee_id)
            
            success = result != "DELETE 0"
            
            if success:
                logger.db_operation("DELETE", "employees.employees", record_id=employee_id,
                                   context={'operation': 'delete'})
            
            return success
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Получить всех сотрудников с пагинацией.
        
        Args:
            limit: Максимальное количество записей
            offset: Смещение
            
        Returns:
            Список сотрудников
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    e.phone,
                    e.ad_account as email,
                    e.created_at,
                    e.updated_at,
                    e.department_id,
                    e.workstation_id,
                    d.name as department_name,
                    w.name as workstation_name
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                ORDER BY e.id ASC
                LIMIT $1 OFFSET $2
            """, limit, offset)
            
            return [dict(row) for row in rows]
    
    async def get_by_id(self, employee_id: int) -> Optional[Dict]:
        """
        Получить сотрудника по ID.
        
        Args:
            employee_id: ID сотрудника
            
        Returns:
            Информация о сотруднике или None
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    e.id,
                    e.full_name,
                    e.phone,
                    e.ad_account as email,
                    e.created_at,
                    e.updated_at,
                    e.department_id,
                    e.workstation_id,
                    d.name as department_name,
                    w.name as workstation_name
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE e.id = $1
            """, employee_id)
            
            return dict(row) if row else None
    
    async def search(self, query: str, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Универсальный поиск сотрудников.
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            offset: Смещение
            
        Returns:
            Список найденных сотрудников
        """
        query_lower = query.lower().strip()
        search_pattern = f"%{query_lower}%"
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    e.phone,
                    e.ad_account as email,
                    e.created_at,
                    e.updated_at,
                    e.department_id,
                    e.workstation_id,
                    d.name as department_name,
                    w.name as workstation_name
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                WHERE 
                    LOWER(e.full_name) LIKE $1
                    OR LOWER(e.phone) LIKE $1
                    OR LOWER(e.ad_account) LIKE $1
                    OR LOWER(d.name) LIKE $1
                    OR LOWER(w.name) LIKE $1
                ORDER BY e.id ASC
                LIMIT $2 OFFSET $3
            """, search_pattern, limit, offset)
            
            return [dict(row) for row in rows]
    
    async def create(
        self,
        full_name: str,
        workstation_id: Optional[int] = None,
        department_id: Optional[int] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        updated_by: str = "web_api"
    ) -> int:
        """
        Создать нового сотрудника (упрощённая версия для API).
        
        Args:
            full_name: ФИО сотрудника
            workstation_id: ID рабочей станции
            department_id: ID отдела
            phone: Телефон
            email: Email (сохраняется в ad_account)
            updated_by: Кто создал запись
            
        Returns:
            ID созданного сотрудника
        """
        return await self.create_employee(
            full_name=full_name,
            department_id=department_id,
            workstation_id=workstation_id,
            phone=phone,
            ad_account=email,
            updated_by=updated_by
        )
    
    async def update(
        self,
        employee_id: int,
        full_name: Optional[str] = None,
        workstation_id: Optional[int] = None,
        department_id: Optional[int] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        updated_by: str = "web_api"
    ) -> bool:
        """
        Обновить сотрудника (упрощённая версия для API).
        
        Args:
            employee_id: ID сотрудника
            full_name: ФИО
            workstation_id: ID рабочей станции
            department_id: ID отдела
            phone: Телефон
            email: Email (сохраняется в ad_account)
            
        Returns:
            True если обновлено успешно
        """
        return await self.update_employee(
            employee_id=employee_id,
            full_name=full_name,
            department_id=department_id,
            workstation_id=workstation_id,
            phone=phone,
            ad_account=email,
            updated_by=updated_by
        )



