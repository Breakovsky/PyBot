"""
Сервис поиска сотрудников.
Чистая бизнес-логика без зависимостей от Telegram/Excel.
"""

import logging
import re
from typing import List, Dict, Optional
from tabulate import tabulate

from database.repositories.employee_repository import EmployeeRepository
from utils.logger import get_logger
from utils.formatters import escape_html

logger = get_logger(__name__)


class EmployeeSearchService:
    """Сервис для поиска сотрудников."""
    
    def __init__(self, employee_repo: EmployeeRepository):
        """
        Инициализирует сервис поиска сотрудников.
        
        Args:
            employee_repo: Репозиторий для работы с сотрудниками
        """
        self.repo = employee_repo
    
    @staticmethod
    def is_ip(value: str) -> bool:
        """
        Проверяет, является ли значение IP-адресом.
        
        Args:
            value: Значение для проверки
            
        Returns:
            True если это IP-адрес
        """
        pattern = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
        if pattern.match(value.strip()):
            return all(0 <= int(part) <= 255 for part in value.split("."))
        return False
    
    @staticmethod
    def is_ws(value: str) -> bool:
        """
        Проверяет, является ли значение рабочей станцией (начинается с 'ws').
        
        Args:
            value: Значение для проверки
            
        Returns:
            True если это рабочая станция
        """
        return value.lower().strip().startswith('ws')
    
    @staticmethod
    def is_digit(value: str) -> bool:
        """
        Проверяет, является ли значение числом.
        
        Args:
            value: Значение для проверки
            
        Returns:
            True если это число
        """
        return value.strip().isdigit()
    
    def _format_results_as_html_table(self, results: List[Dict]) -> str:
        """
        Форматирует результаты поиска в HTML таблицу.
        
        Args:
            results: Список результатов поиска
            
        Returns:
            HTML строка с таблицей
        """
        headers = ["ФИО", "Подразделение", "WS/WorkStation", "Телефон", "Email", "Примечание"]
        table_data = []
        
        for r in results:
            table_data.append([
                escape_html(r.get("full_name", "")),
                escape_html(r.get("department_name", "")),
                escape_html(r.get("workstation_name", "")),
                escape_html(r.get("phone", "")),
                escape_html(r.get("email", "") or r.get("ad_account", "")),
                escape_html(r.get("notes", "")),
            ])
        
        tbl = tabulate(table_data, headers=headers, tablefmt="github", colalign=("left",) * 6)
        return f"<pre>{tbl}</pre>"
    
    def _split_html_table(self, table_html: str, max_len: int = 4000) -> List[str]:
        """
        Разбивает HTML таблицу на части если она слишком длинная.
        
        Args:
            table_html: HTML таблица
            max_len: Максимальная длина части
            
        Returns:
            Список частей таблицы
        """
        if len(table_html) <= max_len:
            return [table_html]
        
        chunks = []
        current = "<pre>\n"
        lines = table_html.replace("<pre>", "").replace("</pre>", "").split("\n")
        
        for line in lines:
            if len(current) + len(line) + 1 > max_len - len("</pre>"):
                current += "</pre>"
                chunks.append(current)
                current = "<pre>\n" + line + "\n"
            else:
                current += line + "\n"
        
        current += "</pre>"
        chunks.append(current)
        return chunks
    
    async def search(self, query: str, limit: int = 100) -> List[str]:
        """
        Выполняет поиск сотрудников по запросу.
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            
        Returns:
            Список HTML строк с результатами (может быть разбит на части)
        """
        query = query.strip()
        if not query:
            return ["<pre>❌ Пустой запрос.</pre>"]
        
        query_lower = query.lower()
        results: List[Dict] = []
        
        try:
            # Определяем тип запроса и выполняем соответствующий поиск
            if self.is_ip(query_lower) or self.is_digit(query_lower):
                # Поиск по телефону
                results = await self.repo.search_by_phone(query)
            elif self.is_ws(query_lower):
                # Поиск по рабочей станции
                results = await self.repo.search_by_workstation(query)
            else:
                # Поиск по имени (частичное совпадение)
                results = await self.repo.search_by_name(query, limit)
            
            if not results:
                return ["<pre>Значение не найдено.</pre>"]
            
            # Форматируем результаты
            html_table = self._format_results_as_html_table(results)
            return self._split_html_table(html_table)
            
        except Exception as e:
            logger.error(f"Error during employee search: {e}", exc_info=True)
            return ["<pre>❌ Ошибка при поиске в базе данных.</pre>"]
    
    async def search_by_name(self, name: str, limit: int = 100) -> List[Dict]:
        """
        Поиск сотрудников по имени.
        
        Args:
            name: Имя для поиска
            limit: Максимальное количество результатов
            
        Returns:
            Список найденных сотрудников
        """
        return await self.repo.search_by_name(name, limit)
    
    async def search_by_phone(self, phone: str) -> List[Dict]:
        """
        Поиск сотрудника по телефону.
        
        Args:
            phone: Телефон для поиска
            
        Returns:
            Список найденных сотрудников
        """
        return await self.repo.search_by_phone(phone)
    
    async def search_by_workstation(self, workstation: str) -> List[Dict]:
        """
        Поиск сотрудников по рабочей станции.
        
        Args:
            workstation: Название рабочей станции
            
        Returns:
            Список найденных сотрудников
        """
        return await self.repo.search_by_workstation(workstation)
    
    async def search_by_ip(self, ip: str) -> List[Dict]:
        """
        Поиск сотрудника по IP-адресу.
        
        Args:
            ip: IP-адрес
            
        Returns:
            Список найденных сотрудников
        """
        return await self.repo.search_by_ip(ip)

