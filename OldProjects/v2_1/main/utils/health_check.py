"""
Health check утилиты.
"""

import logging
from typing import Dict, List, Callable, Awaitable

logger = logging.getLogger(__name__)


class HealthChecker:
    """Класс для проверки здоровья сервисов."""
    
    def __init__(self):
        self.checks: Dict[str, Callable[[], Awaitable[bool]]] = {}
    
    def register_check(self, name: str, check_func: Callable[[], Awaitable[bool]]):
        """Регистрирует проверку здоровья."""
        self.checks[name] = check_func
    
    async def check_all(self) -> Dict:
        """Выполняет все проверки здоровья."""
        results = {}
        all_healthy = True
        
        for name, check_func in self.checks.items():
            try:
                is_healthy = await check_func()
                results[name] = 'healthy' if is_healthy else 'unhealthy'
                if not is_healthy:
                    all_healthy = False
            except Exception as e:
                logger.error(f"Health check {name} failed: {e}")
                results[name] = 'error'
                all_healthy = False
        
        return {
            'status': 'healthy' if all_healthy else 'unhealthy',
            'checks': results
        }
    
    async def check_database(self, db_pool) -> bool:
        """Проверяет подключение к БД."""
        try:
            async with db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    async def check_redis(self, redis_client) -> bool:
        """Проверяет подключение к Redis."""
        try:
            await redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False


# Глобальный экземпляр
_health_checker: HealthChecker = None


def get_health_checker() -> HealthChecker:
    """Получить глобальный экземпляр HealthChecker."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker
