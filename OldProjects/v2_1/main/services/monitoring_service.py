"""
Сервис мониторинга серверов.
Чистая бизнес-логика без зависимостей от Telegram.
"""

import asyncio
import logging
import subprocess
import socket
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from database.repositories.monitoring_repository import MonitoringRepository
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ServerStatus:
    """Статус сервера."""
    name: str
    ip: str
    group: str
    is_alive: bool = False
    last_check: Optional[datetime] = None
    last_state_change: Optional[datetime] = None
    consecutive_failures: int = 0
    first_check_done: bool = False
    alerted_down: bool = False
    last_alert_time: Optional[datetime] = None
    alert_message_ids: List[int] = field(default_factory=list)


class MonitoringService:
    """Сервис для мониторинга серверов."""
    
    def __init__(self, monitoring_repo: MonitoringRepository, ping_timeout: int = 2):
        """
        Инициализирует сервис мониторинга.
        
        Args:
            monitoring_repo: Репозиторий для работы с мониторингом
            ping_timeout: Таймаут ping в секундах
        """
        self.repo = monitoring_repo
        self.ping_timeout = ping_timeout
        self.servers: Dict[str, ServerStatus] = {}
    
    def resolve_hostname(self, target: str) -> str:
        """Резолвит hostname в IP адрес."""
        try:
            resolved_ip = socket.gethostbyname(target)
            return resolved_ip
        except socket.gaierror:
            return target
    
    def ping_host(self, ip: str) -> bool:
        """
        Пингует хост и возвращает результат.
        
        Args:
            ip: IP адрес для проверки
            
        Returns:
            True если хост доступен, False иначе
        """
        param = "-n" if os.name == "nt" else "-c"
        timeout_param = "-w" if os.name == "nt" else "-W"
        timeout_val = str(self.ping_timeout * 1000) if os.name == "nt" else str(self.ping_timeout)
        
        command = ["ping", param, "1", timeout_param, timeout_val, ip]
        
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.ping_timeout + 2
            )
            return result.returncode == 0 and ("TTL=" in result.stdout or "ttl=" in result.stdout)
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"Ping failed for {ip}: {e}")
            return False
    
    async def check_server(
        self,
        name: str,
        ip: str,
        group: str,
        server_id: Optional[int] = None
    ) -> Tuple[bool, Optional[int]]:
        """
        Проверяет доступность сервера.
        
        Args:
            name: Имя сервера
            ip: IP адрес
            group: Группа сервера
            server_id: ID сервера в БД (опционально)
            
        Returns:
            Tuple[is_alive, server_id]
        """
        # Резолвим hostname если нужно
        resolved_ip = self.resolve_hostname(ip)
        
        # Пингуем
        is_alive = self.ping_host(resolved_ip)
        
        # Получаем или создаём сервер в БД
        if server_id is None:
            server_id = await self.repo.get_or_create_server(name, resolved_ip, group)
        
        # Обновляем статус в памяти
        server_key = f"{group}:{name}"
        if server_key not in self.servers:
            self.servers[server_key] = ServerStatus(
                name=name,
                ip=resolved_ip,
                group=group
            )
        
        server = self.servers[server_key]
        now = datetime.now()
        
        # Обновляем статус
        was_alive = server.is_alive
        server.is_alive = is_alive
        server.last_check = now
        
        # Отслеживаем изменение статуса
        if was_alive != is_alive:
            server.last_state_change = now
            server.consecutive_failures = 0 if is_alive else 1
        elif not is_alive:
            server.consecutive_failures += 1
        
        server.first_check_done = True
        
        # Записываем событие в БД
        event_type = 'UP' if is_alive else 'DOWN'
        duration_seconds = None
        
        if not is_alive and server.last_state_change:
            # Вычисляем длительность простоя
            duration_seconds = int((now - server.last_state_change).total_seconds())
        
        await self.repo.record_event(
            server_id=server_id,
            event_type=event_type,
            event_time=now,
            duration_seconds=duration_seconds
        )
        
        return is_alive, server_id
    
    async def check_all_servers(self) -> Dict[str, bool]:
        """
        Проверяет все серверы из БД.
        
        Returns:
            Словарь {server_key: is_alive}
        """
        servers = await self.repo.get_all_servers()
        results = {}
        
        for server in servers:
            server_key = f"{server['server_group_name']}:{server['name']}"
            is_alive, _ = await self.check_server(
                name=server['name'],
                ip=server['ip_address'],
                group=server['server_group_name'],
                server_id=server['id']
            )
            results[server_key] = is_alive
        
        return results
    
    def format_duration(self, delta: timedelta) -> str:
        """
        Форматирует длительность в читаемый вид.
        
        Args:
            delta: Разница во времени
            
        Returns:
            Отформатированная строка
        """
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds}с"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}м {seconds}с"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}ч {minutes}м"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}д {hours}ч"
    
    def build_dashboard_message(self, check_time: Optional[datetime] = None) -> str:
        """
        Создаёт сообщение-дашборд со статусами.
        
        Args:
            check_time: Время проверки (по умолчанию текущее)
            
        Returns:
            HTML текст дашборда
        """
        if check_time is None:
            check_time = datetime.now()
        
        lines = [f"<b>📊 Мониторинг серверов</b>"]
        lines.append(f"<i>Обновлено: {check_time.strftime('%H:%M:%S')}</i>")
        lines.append("")
        
        # Группируем по группам
        groups: Dict[str, List[ServerStatus]] = {}
        for server in self.servers.values():
            if server.group not in groups:
                groups[server.group] = []
            groups[server.group].append(server)
        
        online_count = sum(1 for s in self.servers.values() if s.is_alive)
        total_count = len(self.servers)
        
        lines.append(f"<b>Всего:</b> {online_count}/{total_count} онлайн")
        lines.append("")
        
        now = datetime.now()
        for group_name, servers in sorted(groups.items()):
            lines.append(f"<b>━━ {group_name} ━━</b>")
            
            for server in sorted(servers, key=lambda x: x.name):
                status_icon = "🟢" if server.is_alive else "🔴"
                
                # Время с последнего изменения статуса
                if server.last_state_change:
                    duration = self.format_duration(now - server.last_state_change)
                    time_info = f"({duration})"
                else:
                    time_info = "(--)"
                
                # Показываем IP только если отличается от имени
                if server.ip != server.name and not server.ip.startswith(server.name):
                    ip_display = f" <code>{server.ip}</code>"
                else:
                    ip_display = ""
                
                lines.append(f"{status_icon} <b>{server.name}</b>{ip_display} {time_info}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    async def get_server_metrics(self, server_id: int) -> Optional[Dict]:
        """
        Получает метрики сервера.
        
        Args:
            server_id: ID сервера
            
        Returns:
            Словарь с метриками или None
        """
        return await self.repo.get_server_metrics(server_id)
    
    async def get_all_metrics(self) -> List[Dict]:
        """
        Получает метрики всех серверов.
        
        Returns:
            Список метрик
        """
        return await self.repo.get_all_metrics()
    
    async def get_daily_report(self, target_date: Optional[datetime] = None) -> Dict:
        """
        Получает дневной отчёт.
        
        Args:
            target_date: Дата отчёта (по умолчанию сегодня)
            
        Returns:
            Словарь с отчётом
        """
        date_obj = target_date.date() if target_date else None
        return await self.repo.get_daily_report(date_obj)
    
    def should_send_alert(self, server: ServerStatus, went_down: bool) -> bool:
        """
        Определяет, нужно ли отправлять уведомление.
        
        Args:
            server: Статус сервера
            went_down: Сервер упал (True) или поднялся (False)
            
        Returns:
            True если нужно отправить уведомление
        """
        if went_down:
            # Отправляем уведомление только при первом падении
            return not server.alerted_down
        else:
            # При поднятии всегда отправляем
            return True
    
    def format_alert_message(
        self,
        server: ServerStatus,
        went_down: bool,
        is_reminder: bool = False
    ) -> str:
        """
        Форматирует сообщение об изменении статуса.
        
        Args:
            server: Статус сервера
            went_down: Сервер упал
            is_reminder: Это напоминание
            
        Returns:
            HTML текст уведомления
        """
        now = datetime.now()
        duration_seconds = None
        
        if server.last_state_change:
            duration_seconds = int((now - server.last_state_change).total_seconds())
        
        if went_down:
            if is_reminder:
                duration_str = self.format_duration(timedelta(seconds=duration_seconds)) if duration_seconds else "неизвестно"
                return (
                    f"⚠️ <b>Напоминание:</b> Сервер <b>{server.name}</b> "
                    f"({server.ip}) недоступен уже {duration_str}\n"
                    f"Группа: <b>{server.group}</b>"
                )
            else:
                return (
                    f"🔴 <b>Сервер недоступен!</b>\n\n"
                    f"<b>Сервер:</b> {server.name}\n"
                    f"<b>IP:</b> <code>{server.ip}</code>\n"
                    f"<b>Группа:</b> {server.group}\n"
                    f"<b>Время:</b> {now.strftime('%H:%M:%S')}"
                )
        else:
            duration_str = self.format_duration(timedelta(seconds=duration_seconds)) if duration_seconds else "неизвестно"
            return (
                f"🟢 <b>Сервер восстановлен!</b>\n\n"
                f"<b>Сервер:</b> {server.name}\n"
                f"<b>IP:</b> <code>{server.ip}</code>\n"
                f"<b>Группа:</b> {server.group}\n"
                f"<b>Простой:</b> {duration_str}\n"
                f"<b>Время:</b> {now.strftime('%H:%M:%S')}"
            )

