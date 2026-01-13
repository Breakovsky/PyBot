"""
Обработчик поиска сотрудников.
Использует EmployeeSearchService для бизнес-логики.
"""

import logging
from typing import List, Dict

from database.connection import DatabasePool
from database.repositories.employee_repository import EmployeeRepository
from services.employee_search_service import EmployeeSearchService
from utils.logger import get_logger

logger = get_logger(__name__)


class EmployeeSearchHandler:
    """Обработчик поиска сотрудников в БД."""
    
    def __init__(self, db_pool: DatabasePool):
        """
        Инициализирует обработчик.
        
        Args:
            db_pool: Пул соединений с БД
        """
        self.employee_repo = EmployeeRepository(db_pool)
        self.search_service = EmployeeSearchService(self.employee_repo)
    
    async def search(self, query: str, limit: int = 100) -> List[str]:
        """
        Выполняет поиск сотрудников по запросу.
        Возвращает HTML строки с результатами (может быть разбит на части).
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            
        Returns:
            Список HTML строк с результатами
        """
        return await self.search_service.search(query, limit)
    
    async def search_raw(self, query: str, limit: int = 100) -> List[Dict]:
        """
        Выполняет поиск сотрудников и возвращает сырые данные.
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            
        Returns:
            Список найденных сотрудников
        """
        query = query.strip()
        if not query:
            return []
        
        query_lower = query.lower()
        
        # Определяем тип поиска
        if EmployeeSearchService.is_ip(query):
            # Поиск по IP-адресу
            return await self.search_service.search_by_ip(query)
        elif EmployeeSearchService.is_digit(query):
            # Поиск по телефону
            return await self.search_service.search_by_phone(query)
        elif EmployeeSearchService.is_ws(query_lower):
            # Поиск по рабочей станции
            ws_name = query_lower.replace('ws', '').strip()
            if ws_name:
                # Сначала пробуем точное совпадение
                results = await self.employee_repo.search_by_workstation_exact(query_lower)
                if not results:
                    results = await self.search_service.search_by_workstation(ws_name)
                return results
            else:
                return await self.search_service.search_by_workstation("")
        else:
            # Поиск по имени (частичное совпадение)
            return await self.search_service.search_by_name(query, limit)
