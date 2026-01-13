"""
Обработчик мониторинга серверов.
Использует MonitoringService для бизнес-логики.
"""

import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from database.connection import DatabasePool
from database.repositories.monitoring_repository import MonitoringRepository
from services.monitoring_service import MonitoringService
from services.telegram_message_service import TelegramMessageService
from utils.logger import get_logger

logger = get_logger(__name__)


class ServerMonitorHandler:
    """Обработчик мониторинга серверов."""
    
    def __init__(
        self,
        db_pool: DatabasePool,
        bot: Bot,
        chat_id: int,
        topic_id: int,
        check_interval: int = 30,
        ping_timeout: int = 2,
        metrics_topic_id: Optional[int] = None
    ):
        """
        Инициализирует обработчик мониторинга.
        
        Args:
            db_pool: Пул соединений с БД
            bot: Экземпляр бота
            chat_id: ID чата
            topic_id: ID топика для дашборда
            check_interval: Интервал проверки в секундах
            ping_timeout: Таймаут ping в секундах
            metrics_topic_id: ID топика для метрик (опционально)
        """
        self.db_pool = db_pool
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id
        self.check_interval = check_interval
        self.metrics_topic_id = metrics_topic_id
        
        # Инициализируем репозиторий и сервисы
        self.monitoring_repo = MonitoringRepository(db_pool)
        self.monitoring_service = MonitoringService(self.monitoring_repo, ping_timeout)
        self.message_service = TelegramMessageService(db_pool)
        
        # Состояние
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.dashboard_message_id: Optional[int] = None
        self.metrics_message_id: Optional[int] = None
        
        # Загружаем сохранённые ID сообщений
        self._load_persistent_messages()
    
    def _load_persistent_messages(self):
        """Загружает сохранённые ID сообщений из БД."""
        # Загружаем асинхронно
        async def load():
            dashboard_id = await self.message_service.get_message_id(
                self.chat_id, self.topic_id, 'dashboard'
            )
            if dashboard_id:
                self.dashboard_message_id = dashboard_id
                logger.info(f"Loaded dashboard message ID: {dashboard_id}")
            
            if self.metrics_topic_id:
                metrics_id = await self.message_service.get_message_id(
                    self.chat_id, self.metrics_topic_id, 'metrics'
                )
                if metrics_id:
                    self.metrics_message_id = metrics_id
                    logger.info(f"Loaded metrics message ID: {metrics_id}")
        
        # Запускаем синхронно через asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если loop уже запущен, создаём задачу
                asyncio.create_task(load())
            else:
                loop.run_until_complete(load())
        except RuntimeError:
            # Если нет event loop, создаём новый
            asyncio.run(load())
    
    async def start(self):
        """Запускает мониторинг."""
        if self.is_running:
            logger.warning("Monitoring already running")
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("Server monitoring started")
    
    async def stop(self):
        """Останавливает мониторинг."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Server monitoring stopped")
    
    async def _monitoring_loop(self):
        """Основной цикл мониторинга."""
        while self.is_running:
            try:
                check_time = datetime.now()
                self.monitoring_service.servers = {}  # Очищаем перед проверкой
                
                # Проверяем все серверы
                await self.monitoring_service.check_all_servers()
                
                # Обновляем дашборд
                await self.send_dashboard(check_time)
                
                # Отправляем уведомления об изменениях
                await self._check_and_send_alerts()
                
                # Ждём до следующей проверки
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def _check_and_send_alerts(self):
        """Проверяет изменения статусов и отправляет уведомления."""
        # TODO: Реализовать логику отправки уведомлений
        # Это требует сохранения предыдущего состояния
        pass
    
    async def send_dashboard(self, check_time: Optional[datetime] = None) -> Optional[int]:
        """
        Отправляет или обновляет дашборд.
        
        Args:
            check_time: Время проверки
            
        Returns:
            ID сообщения или None
        """
        message_text = self.monitoring_service.build_dashboard_message(check_time)
        
        try:
            if self.dashboard_message_id:
                # Редактируем существующее сообщение
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.dashboard_message_id,
                        text=message_text,
                        parse_mode="HTML"
                    )
                    return self.dashboard_message_id
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        return self.dashboard_message_id
                    elif "message to edit not found" in str(e):
                        # Сообщение удалено, создаём новое
                        self.dashboard_message_id = None
                    else:
                        raise
            
            # Создаём новое сообщение (без уведомления)
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=message_text,
                parse_mode="HTML",
                message_thread_id=self.topic_id,
                disable_notification=True
            )
            self.dashboard_message_id = msg.message_id
            
            # Сохраняем в БД для персистентности
            await self.message_service.save_message_id(
                self.chat_id, self.topic_id, 'dashboard', msg.message_id
            )
            
            logger.info(f"Dashboard message created: ID={msg.message_id}")
            return msg.message_id
            
        except TelegramBadRequest as e:
            error_str = str(e).lower()
            if "chat not found" in error_str or "chat_id is empty" in error_str:
                logger.error(f"Cannot send/update dashboard: chat {self.chat_id} not found")
            else:
                logger.error(f"Failed to send/update dashboard: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to send/update dashboard: {e}")
            return None
    
    async def get_all_servers(self) -> List[Dict]:
        """Получает список всех серверов."""
        return await self.monitoring_repo.get_all_servers()
    
    async def check_server(self, server_id: int) -> Dict:
        """
        Проверяет доступность сервера.
        
        Args:
            server_id: ID сервера
            
        Returns:
            Словарь с результатом проверки
        """
        server = await self.monitoring_repo.get_server_by_id(server_id)
        if not server:
            return {'error': 'Server not found'}
        
        is_alive, _ = await self.monitoring_service.check_server(
            name=server['name'],
            ip=server['ip_address'],
            group=server['server_group_name'],
            server_id=server_id
        )
        
        return {
            'server_id': server_id,
            'name': server['name'],
            'ip': server['ip_address'],
            'is_alive': is_alive,
            'checked_at': datetime.now().isoformat()
        }
    
    async def get_server_metrics(self, server_id: int) -> Optional[Dict]:
        """Получает метрики сервера."""
        return await self.monitoring_service.get_server_metrics(server_id)
    
    async def get_all_metrics(self) -> List[Dict]:
        """Получает метрики всех серверов."""
        return await self.monitoring_service.get_all_metrics()
    
    async def get_daily_report(self, target_date: Optional[datetime] = None) -> Dict:
        """Получает дневной отчёт."""
        return await self.monitoring_service.get_daily_report(target_date)
