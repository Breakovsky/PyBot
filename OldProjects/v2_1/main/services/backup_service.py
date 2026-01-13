"""
Сервис для автоматического создания бэкапов таблицы сотрудников.
"""

import asyncio
import logging
import json
from datetime import datetime, time
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class BackupService:
    """Сервис для управления бэкапами."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._running = False
        self._task = None
    
    async def create_daily_backup(self):
        """Создаёт ежедневный бэкап в 00:00."""
        from database.repositories.employee_repository import EmployeeRepository
        
        try:
            repo = EmployeeRepository(self.db_pool)
            employees = await repo.get_all(limit=10000, offset=0)
            
            snapshot_name = f"daily_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            async with self.db_pool.acquire() as conn:
                snapshot_id = await conn.fetchval("""
                    INSERT INTO backups.employee_snapshots 
                        (snapshot_name, snapshot_type, created_by, employees_data)
                    VALUES ($1, $2, $3, $4::jsonb)
                    RETURNING id
                """, snapshot_name, 'daily', 'system', json.dumps(employees))
                
                logger.operation("Daily backup creation", "completed", 
                               context={'snapshot_name': snapshot_name, 
                                       'snapshot_id': snapshot_id, 
                                       'employees_count': len(employees)})
                return snapshot_id
        except Exception as e:
            logger.error(f"Error creating daily backup: {e}", exc_info=True)
    
    async def wait_until_midnight(self):
        """Ждёт до следующей полуночи."""
        from datetime import timedelta
        
        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Если уже прошла полночь сегодня, ждём до полуночи завтра
        if now >= midnight:
            midnight = midnight + timedelta(days=1)
        
        wait_seconds = (midnight - now).total_seconds()
        wait_hours = wait_seconds / 3600
        logger.info(f"Next backup scheduled in {wait_hours:.1f} hours (at midnight)", 
                   context={'wait_seconds': int(wait_seconds)})
        await asyncio.sleep(wait_seconds)
    
    async def daily_backup_loop(self):
        """Цикл ежедневного создания бэкапов."""
        logger.info("Daily backup service started")
        
        while self._running:
            try:
                await self.wait_until_midnight()
                if self._running:  # Проверяем, что сервис ещё работает
                    await self.create_daily_backup()
            except asyncio.CancelledError:
                logger.info("Daily backup service cancelled")
                break
            except Exception as e:
                logger.error(f"Error in daily backup loop: {e}", exc_info=True)
                # Ждём 1 час перед повтором при ошибке
                await asyncio.sleep(3600)
    
    async def start(self):
        """Запускает сервис бэкапов."""
        if self._running:
            logger.warning("Backup service is already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self.daily_backup_loop())
        logger.info("Backup service started")
    
    async def stop(self):
        """Останавливает сервис бэкапов."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Backup service stopped")

