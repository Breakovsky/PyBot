# main/modules/handlers/monitor_handler.py

"""
Модуль мониторинга серверов с live-обновлением статусов.
- Одно сообщение-дашборд с постоянным обновлением (персистентный ID)
- Уведомления при изменении статуса сервера (авто-удаление)
- Метрики в отдельном топике (персистентное сообщение)
"""

import asyncio
import logging
import subprocess
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from modules.handlers.monitor_db import get_db, MonitorDatabase
from assets.config import now_msk, MSK_TIMEZONE

logger = logging.getLogger(__name__)

# Время жизни уведомлений (в секундах)
# 30 секунд для теста, потом поменять на 600 (10 минут)
ALERT_LIFETIME_SECONDS = 30


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
    first_check_done: bool = False  # Флаг первой проверки
    alerted_down: bool = False  # Флаг что уведомление об оффлайне отправлено
    last_alert_time: Optional[datetime] = None  # Время последнего уведомления
    alert_message_ids: List[int] = None  # ID сообщений о недоступности для удаления
    
    def __post_init__(self):
        if self.alert_message_ids is None:
            self.alert_message_ids = []


@dataclass 
class MonitorState:
    """Состояние монитора."""
    servers: Dict[str, ServerStatus] = field(default_factory=dict)
    dashboard_message_id: Optional[int] = None
    metrics_message_id: Optional[int] = None  # Сообщение в METRICS_TOPIC
    is_running: bool = False
    last_check_start_time: Optional[datetime] = None  # Время начала последней проверки
    # Очередь сообщений на удаление: (message_id, delete_time)
    messages_to_delete: List[tuple] = field(default_factory=list)


class ServerMonitor:
    """Класс мониторинга серверов."""
    
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        topic_id: int,
        ip_addresses_path: str,
        check_interval: int = 30,
        ping_timeout: int = 2,
        metrics_topic_id: Optional[int] = None
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id
        self.ip_addresses_path = ip_addresses_path
        self.check_interval = check_interval
        self.ping_timeout = ping_timeout
        self.metrics_topic_id = metrics_topic_id  # Топик для метрик
        self.state = MonitorState()
        self._task: Optional[asyncio.Task] = None
        self._deletion_task: Optional[asyncio.Task] = None  # Задача удаления сообщений
        self.db = get_db()  # База данных
        
        # Загружаем сохранённые ID сообщений из БД
        self._load_persistent_messages()
    
    def _load_persistent_messages(self):
        """Загружает сохранённые ID сообщений из базы данных."""
        # Dashboard в PING_TOPIC
        dashboard_id = self.db.get_message_id(self.chat_id, self.topic_id, 'dashboard')
        if dashboard_id:
            self.state.dashboard_message_id = dashboard_id
            logger.info(f"Loaded dashboard message ID: {dashboard_id}")
        
        # Metrics message в METRICS_TOPIC
        if self.metrics_topic_id:
            metrics_id = self.db.get_message_id(self.chat_id, self.metrics_topic_id, 'metrics')
            if metrics_id:
                self.state.metrics_message_id = metrics_id
                logger.info(f"Loaded metrics message ID: {metrics_id}")
    
    def _save_dashboard_message_id(self, message_id: int):
        """Сохраняет ID dashboard сообщения в БД."""
        self.db.save_message_id(self.chat_id, self.topic_id, 'dashboard', message_id)
    
    def _save_metrics_message_id(self, message_id: int):
        """Сохраняет ID metrics сообщения в БД."""
        if self.metrics_topic_id:
            self.db.save_message_id(self.chat_id, self.metrics_topic_id, 'metrics', message_id)
        
    def resolve_hostname(self, target: str) -> str:
        """Резолвит hostname в IP адрес."""
        try:
            resolved_ip = socket.gethostbyname(target)
            return resolved_ip
        except socket.gaierror:
            return target
    
    def ping_host(self, ip: str) -> bool:
        """Пингует хост и возвращает результат."""
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
    
    def load_servers(self) -> Dict[str, List[dict]]:
        """Загружает список серверов из базы данных."""
        try:
            from modules.handlers.monitor_db import get_db
            db = get_db()
            groups = db.get_all_servers_grouped()
            logger.debug(f"Loaded {len(groups)} server groups from database")
            return groups
        except Exception as e:
            logger.error(f"Error loading servers from database: {e}")
            return {}
    
    def format_duration(self, delta) -> str:
        """Форматирует длительность в читаемый вид."""
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
    
    def build_dashboard_message(self) -> str:
        """Создаёт сообщение-дашборд со статусами."""
        now = now_msk()
        # Используем время начала проверки, а не текущее время
        check_time = self.state.last_check_start_time or now
        lines = [f"<b>📊 Мониторинг серверов</b>"]
        lines.append(f"<i>Обновлено: {check_time.strftime('%H:%M:%S')}</i>")
        lines.append("")
        
        # Группируем по группам
        groups: Dict[str, List[ServerStatus]] = {}
        for server in self.state.servers.values():
            if server.group not in groups:
                groups[server.group] = []
            groups[server.group].append(server)
        
        online_count = sum(1 for s in self.state.servers.values() if s.is_alive)
        total_count = len(self.state.servers)
        
        lines.append(f"<b>Всего:</b> {online_count}/{total_count} онлайн")
        lines.append("")
        
        for group_name, servers in groups.items():
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
    
    async def send_dashboard(self) -> Optional[int]:
        """Отправляет или обновляет дашборд."""
        message_text = self.build_dashboard_message()
        
        try:
            if self.state.dashboard_message_id:
                # Редактируем существующее сообщение
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.state.dashboard_message_id,
                        text=message_text,
                        parse_mode="HTML"
                    )
                    return self.state.dashboard_message_id
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        return self.state.dashboard_message_id
                    elif "message to edit not found" in str(e):
                        # Сообщение удалено, создаём новое
                        self.state.dashboard_message_id = None
                    else:
                        raise
            
            # Создаём новое сообщение (без уведомления)
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=message_text,
                parse_mode="HTML",
                message_thread_id=self.topic_id,
                disable_notification=True  # Без уведомления!
            )
            self.state.dashboard_message_id = msg.message_id
            # Сохраняем в БД для персистентности
            self._save_dashboard_message_id(msg.message_id)
            logger.info(f"Dashboard message created: ID={msg.message_id}")
            return msg.message_id
            
        except TelegramBadRequest as e:
            error_str = str(e).lower()
            if "chat not found" in error_str or "chat_id is empty" in error_str:
                logger.error(f"Cannot send/update dashboard: chat {self.chat_id} not found. Bot may not be in the chat or chat was deleted.")
            else:
                logger.error(f"Failed to send/update dashboard: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to send/update dashboard: {e}")
            return None
    
    async def delete_alert_messages(self, server: ServerStatus):
        """Удаляет все сообщения о недоступности сервера."""
        if not server.alert_message_ids:
            return
        
        for msg_id in server.alert_message_ids:
            try:
                await self.bot.delete_message(
                    chat_id=self.chat_id,
                    message_id=msg_id
                )
                logger.info(f"Deleted alert message {msg_id} for {server.name}")
            except Exception as e:
                logger.debug(f"Could not delete message {msg_id}: {e}")
        
        server.alert_message_ids.clear()
    
    async def send_alert(self, server: ServerStatus, went_down: bool, is_reminder: bool = False):
        """Отправляет уведомление об изменении статуса."""
        now = now_msk()
        duration_seconds = None
        
        if server.last_state_change:
            duration_seconds = int((now - server.last_state_change).total_seconds())
        
        if went_down:
            # Сервер упал или напоминание
            if is_reminder:
                downtime = ""
                if duration_seconds:
                    downtime = f"\nНедоступен уже: {self.format_duration(timedelta(seconds=duration_seconds))}"
                
                text = (
                    f"⚠️ <b>НАПОМИНАНИЕ: СЕРВЕР ВСЁ ЕЩЁ НЕДОСТУПЕН</b>\n\n"
                    f"<b>{server.name}</b>\n"
                    f"IP: <code>{server.ip}</code>\n"
                    f"Группа: {server.group}"
                    f"{downtime}"
                )
            else:
                text = (
                    f"🔴 <b>СЕРВЕР НЕДОСТУПЕН</b>\n\n"
                    f"<b>{server.name}</b>\n"
                    f"IP: <code>{server.ip}</code>\n"
                    f"Группа: {server.group}\n"
                    f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                # Записываем событие DOWN в БД
                self.db.record_event(
                    name=server.name,
                    ip=server.ip,
                    group=server.group,
                    event_type='DOWN',
                    event_time=now
                )
            disable_notification = False
        else:
            # Сервер поднялся
            downtime_text = ""
            if duration_seconds:
                downtime_text = f"\nБыл недоступен: {self.format_duration(timedelta(seconds=duration_seconds))}"
            
            text = (
                f"🟢 <b>СЕРВЕР СНОВА ДОСТУПЕН</b>\n\n"
                f"<b>{server.name}</b>\n"
                f"IP: <code>{server.ip}</code>\n"
                f"Группа: {server.group}\n"
                f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                f"{downtime_text}"
            )
            
            # Записываем событие UP в БД с продолжительностью
            self.db.record_event(
                name=server.name,
                ip=server.ip,
                group=server.group,
                event_type='UP',
                event_time=now,
                duration_seconds=duration_seconds
            )
            disable_notification = False
        
        try:
            # Отправляем в основной топик пингов
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                message_thread_id=self.topic_id,
                disable_notification=disable_notification
            )
            server.last_alert_time = now
            
            # Сохраняем ID сообщения о недоступности для последующего удаления
            if went_down:
                server.alert_message_ids.append(msg.message_id)
            
            # Планируем удаление сообщения через ALERT_LIFETIME_SECONDS
            delete_time = now + timedelta(seconds=ALERT_LIFETIME_SECONDS)
            self.state.messages_to_delete.append((msg.message_id, delete_time))
            logger.debug(f"Scheduled deletion of message {msg.message_id} at {delete_time}")
            
            alert_type = 'REMINDER' if is_reminder else ('DOWN' if went_down else 'UP')
            logger.info(f"Alert sent for {server.name}: {alert_type} (msg_id={msg.message_id})")
            
            # Обновляем сообщение метрик (если настроен топик)
            if self.metrics_topic_id and not is_reminder:
                await self.update_metrics_message()
                
        except Exception as e:
            logger.error(f"Failed to send alert for {server.name}: {e}")
    
    def build_metrics_message(self) -> str:
        """Создаёт сообщение с метриками всех серверов."""
        now = now_msk()
        all_metrics = self.db.get_all_metrics()
        recent_events = self.db.get_recent_events(limit=10)
        
        lines = [
            f"<b>📊 МЕТРИКИ МОНИТОРИНГА</b>",
            f"<i>Обновлено: {now.strftime('%Y-%m-%d %H:%M:%S')}</i>",
            ""
        ]
        
        # Текущий статус серверов
        online = sum(1 for s in self.state.servers.values() if s.is_alive)
        total = len(self.state.servers)
        lines.append(f"<b>🖥 Статус:</b> {online}/{total} онлайн")
        lines.append("")
        
        # Недоступные серверы
        offline_servers = [s for s in self.state.servers.values() if not s.is_alive]
        if offline_servers:
            lines.append("<b>🔴 Недоступны сейчас:</b>")
            for s in offline_servers:
                downtime = ""
                if s.last_state_change:
                    downtime = f" ({self.format_duration(now - s.last_state_change)})"
                lines.append(f"  • {s.name} <code>{s.ip}</code>{downtime}")
            lines.append("")
        
        # Статистика по серверам
        if all_metrics:
            lines.append("<b>📈 Статистика:</b>")
            for m in all_metrics[:10]:  # Топ 10
                if m.downtime_count > 0:
                    lines.append(
                        f"  • {m.server_name}: {m.downtime_count} падений, "
                        f"SLA {m.availability_percent}%"
                    )
            lines.append("")
        
        # Последние события
        if recent_events:
            lines.append("<b>📋 Последние события:</b>")
            for e in recent_events[:5]:
                event_time = datetime.fromisoformat(e['event_time'])
                # Если дата naive, добавляем MSK timezone
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=MSK_TIMEZONE)
                icon = "🟢" if e['event_type'] == 'UP' else "🔴"
                duration_text = ""
                if e['event_type'] == 'UP' and e.get('duration_seconds'):
                    duration_text = f" (был недоступен {self.db.format_duration(e['duration_seconds'])})"
                lines.append(
                    f"  {icon} {event_time.strftime('%H:%M:%S')} "
                    f"{e['name']}{duration_text}"
                )
        
        return "\n".join(lines)
    
    async def update_metrics_message(self):
        """Обновляет или создаёт сообщение с метриками в METRICS_TOPIC."""
        if not self.metrics_topic_id:
            return
        
        message_text = self.build_metrics_message()
        
        try:
            if self.state.metrics_message_id:
                # Пытаемся обновить существующее сообщение
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.state.metrics_message_id,
                        text=message_text,
                        parse_mode="HTML"
                    )
                    logger.debug(f"Metrics message updated: ID={self.state.metrics_message_id}")
                    return
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        return
                    elif "message to edit not found" in str(e):
                        # Сообщение удалено, создаём новое
                        logger.info("Metrics message was deleted, creating new one")
                        self.state.metrics_message_id = None
                    else:
                        raise
            
            # Создаём новое сообщение
            try:
                msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message_text,
                    parse_mode="HTML",
                    message_thread_id=self.metrics_topic_id,
                    disable_notification=True
                )
                self.state.metrics_message_id = msg.message_id
                self._save_metrics_message_id(msg.message_id)
                logger.info(f"Metrics message created: ID={msg.message_id}")
            except TelegramBadRequest as e:
                error_str = str(e).lower()
                if "chat not found" in error_str or "chat_id is empty" in error_str:
                    logger.error(f"Cannot update metrics message: chat {self.chat_id} not found. Bot may not be in the chat or chat was deleted.")
                else:
                    logger.error(f"Failed to update metrics message: {e}")
            except Exception as e:
                logger.error(f"Failed to update metrics message: {e}")
            
        except Exception as e:
            logger.error(f"Failed to update metrics message: {e}")
    
    async def process_message_deletions(self):
        """Обрабатывает очередь сообщений на удаление."""
        now = now_msk()
        to_keep = []
        
        for msg_id, delete_time in self.state.messages_to_delete:
            if now >= delete_time:
                # Время удалять
                try:
                    await self.bot.delete_message(
                        chat_id=self.chat_id,
                        message_id=msg_id
                    )
                    logger.info(f"Auto-deleted alert message {msg_id}")
                except Exception as e:
                    logger.debug(f"Could not delete message {msg_id}: {e}")
            else:
                # Ещё не время
                to_keep.append((msg_id, delete_time))
        
        self.state.messages_to_delete = to_keep
    
    async def check_all_servers(self):
        """Проверяет все серверы и обновляет статусы."""
        now = now_msk()
        self.state.last_check_start_time = now  # Сохраняем время начала проверки
        logger.info(f"Checking servers at {now.strftime('%H:%M:%S')}")
        groups = self.load_servers()
        
        if not groups:
            logger.warning("No servers loaded from config")
            return
        
        # Проверяем каждый сервер
        for group_name, devices in groups.items():
            for device in devices:
                name = device["name"]
                ip_raw = device["ip"]
                ip = self.resolve_hostname(ip_raw)
                
                server_key = f"{group_name}:{name}"
                
                # Получаем или создаём статус сервера
                if server_key not in self.state.servers:
                    self.state.servers[server_key] = ServerStatus(
                        name=name,
                        ip=ip,
                        group=group_name,
                        last_state_change=now
                    )
                
                server = self.state.servers[server_key]
                server.ip = ip  # Обновляем IP если изменился
                
                # Пингуем
                was_alive = server.is_alive
                is_alive = self.ping_host(ip)
                
                server.last_check = now
                server.is_alive = is_alive
                
                # Первая проверка сервера
                if not server.first_check_done:
                    server.first_check_done = True
                    server.last_state_change = now
                    
                    if not is_alive:
                        # Сервер недоступен при первой проверке - уведомляем
                        await self.send_alert(server, went_down=True)
                        server.alerted_down = True
                        logger.info(f"Server {server.name} is DOWN on first check")
                    else:
                        logger.info(f"Server {server.name} is UP on first check")
                    continue
                
                # Проверяем изменение статуса
                if was_alive and not is_alive:
                    # Сервер упал
                    server.consecutive_failures += 1
                    if server.consecutive_failures >= 2 and not server.alerted_down:
                        await self.send_alert(server, went_down=True)
                        server.last_state_change = now
                        server.alerted_down = True
                        server.consecutive_failures = 0
                elif not was_alive and is_alive:
                    # Сервер поднялся
                    # Удаляем сообщения о недоступности
                    await self.delete_alert_messages(server)
                    
                    if server.alerted_down:
                        await self.send_alert(server, went_down=False)
                    server.last_state_change = now
                    server.consecutive_failures = 0
                    server.alerted_down = False
                elif is_alive:
                    server.consecutive_failures = 0
                elif not is_alive:
                    if not server.alerted_down:
                        # Сервер всё ещё оффлайн, но уведомление ещё не отправлено
                        server.consecutive_failures += 1
                        if server.consecutive_failures >= 2:
                            await self.send_alert(server, went_down=True)
                            server.last_state_change = now
                            server.alerted_down = True
                            server.consecutive_failures = 0
                    else:
                        # Сервер оффлайн и уведомление уже отправлено
                        # Проверяем нужно ли напоминание (каждые 2 минуты)
                        if server.last_alert_time:
                            time_since_alert = (now - server.last_alert_time).total_seconds()
                            if time_since_alert >= 120:  # 2 минуты
                                await self.send_alert(server, went_down=True, is_reminder=True)
        
        # Обновляем дашборд
        await self.send_dashboard()
    
    def _seconds_until_next_interval(self) -> float:
        """Вычисляет секунды до следующего ровного интервала (00 или 30 секунд)."""
        now = now_msk()
        current_second = now.second + now.microsecond / 1_000_000
        
        # Находим следующую точку: 0 или 30 секунд
        if current_second < 30:
            next_point = 30
        else:
            next_point = 60
        
        wait_seconds = next_point - current_second
        return max(wait_seconds, 0.1)  # Минимум 0.1 секунды
    
    async def run(self):
        """Запускает цикл мониторинга."""
        self.state.is_running = True
        logger.info(f"Monitor started. Interval: {self.check_interval}s")
        
        try:
            # Первичная проверка сразу при старте
            await self.check_all_servers()
            
            # Обновляем метрики при старте
            if self.metrics_topic_id:
                await self.update_metrics_message()
            
            while self.state.is_running:
                # Вычисляем время до следующего интервала
                wait_time = self._seconds_until_next_interval()
                
                # Ждём с проверкой удалений каждые 5 секунд
                while wait_time > 0 and self.state.is_running:
                    sleep_chunk = min(wait_time, 5.0)
                    await asyncio.sleep(sleep_chunk)
                    wait_time -= sleep_chunk
                    
                    # Обрабатываем очередь удалений
                    await self.process_message_deletions()
                
                if not self.state.is_running:
                    break
                
                # Проверяем серверы ровно в :00 или :30
                await self.check_all_servers()
                
                # Обновляем метрики после каждой проверки
                if self.metrics_topic_id:
                    await self.update_metrics_message()
                
        except asyncio.CancelledError:
            logger.info("Monitor task cancelled")
        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
        finally:
            self.state.is_running = False
    
    def start(self) -> asyncio.Task:
        """Запускает мониторинг в фоновой задаче."""
        if self._task and not self._task.done():
            logger.warning("Monitor is already running")
            return self._task
        
        self._task = asyncio.create_task(self.run())
        return self._task
    
    async def stop(self):
        """Останавливает мониторинг."""
        self.state.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Monitor stopped")


# Глобальный экземпляр монитора
_monitor: Optional[ServerMonitor] = None


def get_monitor() -> Optional[ServerMonitor]:
    """Возвращает текущий экземпляр монитора."""
    return _monitor


async def start_monitoring(
    bot: Bot,
    chat_id: int,
    topic_id: int,
    ip_addresses_path: str,
    check_interval: int = 30,
    metrics_topic_id: Optional[int] = None
) -> ServerMonitor:
    """Запускает мониторинг серверов."""
    global _monitor
    
    if _monitor and _monitor.state.is_running:
        logger.warning("Monitor already running, stopping old instance")
        await _monitor.stop()
    
    _monitor = ServerMonitor(
        bot=bot,
        chat_id=chat_id,
        topic_id=topic_id,
        ip_addresses_path=ip_addresses_path,
        check_interval=check_interval,
        metrics_topic_id=metrics_topic_id
    )
    
    _monitor.start()
    logger.info(f"Monitoring started for chat {chat_id}, topic {topic_id}, metrics_topic {metrics_topic_id}")
    
    return _monitor


async def stop_monitoring():
    """Останавливает мониторинг."""
    global _monitor
    
    if _monitor:
        await _monitor.stop()
        _monitor = None

