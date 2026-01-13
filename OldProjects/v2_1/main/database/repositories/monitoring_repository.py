"""
Репозиторий для работы с мониторингом серверов.
Объединяет логику из v2_0 monitor_db.py.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from utils.logger import get_logger

logger = get_logger(__name__)


class MonitoringRepository:
    """Репозиторий для работы с мониторингом серверов."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    # ===== Server Groups =====
    
    async def get_or_create_server_group(self, name: str, description: Optional[str] = None) -> int:
        """Получает или создаёт группу серверов."""
        async with self.db_pool.acquire() as conn:
            # Пытаемся найти существующую
            group_id = await conn.fetchval("""
                SELECT id FROM monitoring.server_groups
                WHERE name = $1
            """, name)
            
            if group_id:
                return group_id
            
            # Создаём новую
            group_id = await conn.fetchval("""
                INSERT INTO monitoring.server_groups (name, description)
                VALUES ($1, $2)
                RETURNING id
            """, name, description)
            
            logger.info(f"Created server group: {name} (id={group_id})")
            return group_id
    
    async def get_all_server_groups(self) -> List[Dict]:
        """Получает все группы серверов."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, description, created_at, updated_at
                FROM monitoring.server_groups
                ORDER BY name
            """)
            return [dict(row) for row in rows]
    
    async def delete_server_group(self, group_id: int) -> bool:
        """Удаляет группу серверов (каскадно удаляет серверы)."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM monitoring.server_groups
                WHERE id = $1
            """, group_id)
            return result != "DELETE 0"
    
    # ===== Servers =====
    
    async def get_or_create_server(
        self, 
        name: str, 
        ip_address: str, 
        group_name: str
    ) -> int:
        """Получает или создаёт сервер."""
        group_id = await self.get_or_create_server_group(group_name)
        
        async with self.db_pool.acquire() as conn:
            # Пытаемся найти существующий
            server_id = await conn.fetchval("""
                SELECT id FROM monitoring.servers
                WHERE name = $1 AND server_group_id = $2
            """, name, group_id)
            
            if server_id:
                # Обновляем last_seen и IP
                await conn.execute("""
                    UPDATE monitoring.servers
                    SET last_seen = NOW(), ip_address = $1
                    WHERE id = $2
                """, ip_address, server_id)
                return server_id
            
            # Создаём новый
            server_id = await conn.fetchval("""
                INSERT INTO monitoring.servers (name, ip_address, server_group_id)
                VALUES ($1, $2, $3)
                RETURNING id
            """, name, ip_address, group_id)
            
            # Создаём запись метрик
            await conn.execute("""
                INSERT INTO monitoring.server_metrics (server_id)
                VALUES ($1)
            """, server_id)
            
            logger.info(f"Created server: {name} ({group_name}) id={server_id}")
            return server_id
    
    async def get_server_by_id(self, server_id: int) -> Optional[Dict]:
        """Получает сервер по ID."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    s.id,
                    s.name,
                    s.ip_address,
                    s.server_group_id,
                    sg.name as server_group_name,
                    s.first_seen,
                    s.last_seen
                FROM monitoring.servers s
                JOIN monitoring.server_groups sg ON s.server_group_id = sg.id
                WHERE s.id = $1
            """, server_id)
            return dict(row) if row else None
    
    async def get_all_servers(self) -> List[Dict]:
        """Получает все серверы."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    s.id,
                    s.name,
                    s.ip_address,
                    s.server_group_id,
                    sg.name as server_group_name,
                    s.first_seen,
                    s.last_seen
                FROM monitoring.servers s
                JOIN monitoring.server_groups sg ON s.server_group_id = sg.id
                ORDER BY sg.name, s.name
            """)
            return [dict(row) for row in rows]
    
    async def get_servers_by_group(self, group_name: str) -> List[Dict]:
        """Получает серверы по группе."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    s.id,
                    s.name,
                    s.ip_address,
                    s.server_group_id,
                    sg.name as server_group_name,
                    s.first_seen,
                    s.last_seen
                FROM monitoring.servers s
                JOIN monitoring.server_groups sg ON s.server_group_id = sg.id
                WHERE sg.name = $1
                ORDER BY s.name
            """, group_name)
            return [dict(row) for row in rows]
    
    # ===== Events =====
    
    async def record_event(
        self,
        server_id: int,
        event_type: str,  # 'UP' or 'DOWN'
        event_time: Optional[datetime] = None,
        duration_seconds: Optional[int] = None
    ) -> int:
        """Записывает событие UP или DOWN."""
        if event_time is None:
            event_time = datetime.now()
        
        async with self.db_pool.acquire() as conn:
            # Записываем событие
            event_id = await conn.fetchval("""
                INSERT INTO monitoring.server_events 
                    (server_id, event_type, event_time, duration_seconds)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, server_id, event_type, event_time, duration_seconds)
            
            # Обновляем метрики
            if event_type == 'DOWN':
                await conn.execute("""
                    UPDATE monitoring.server_metrics SET 
                        downtime_count = downtime_count + 1,
                        last_status = 'DOWN',
                        last_status_change = $1
                    WHERE server_id = $2
                """, event_time, server_id)
            else:  # UP
                if duration_seconds:
                    await conn.execute("""
                        UPDATE monitoring.server_metrics SET 
                            total_downtime_seconds = total_downtime_seconds + $1,
                            longest_downtime_seconds = GREATEST(longest_downtime_seconds, $1),
                            last_status = 'UP',
                            last_status_change = $2
                        WHERE server_id = $3
                    """, duration_seconds, event_time, server_id)
                else:
                    await conn.execute("""
                        UPDATE monitoring.server_metrics SET 
                            last_status = 'UP',
                            last_status_change = $1
                        WHERE server_id = $2
                    """, event_time, server_id)
            
            # Обновляем дневную статистику
            event_date = event_time.date()
            await conn.execute("""
                INSERT INTO monitoring.daily_stats (server_id, date, downtime_count)
                VALUES ($1, $2, $3)
                ON CONFLICT (server_id, date) DO UPDATE SET
                    downtime_count = daily_stats.downtime_count + $3
            """, server_id, event_date, 1 if event_type == 'DOWN' else 0)
            
            if event_type == 'UP' and duration_seconds:
                await conn.execute("""
                    UPDATE monitoring.daily_stats 
                    SET downtime_seconds = downtime_seconds + $1
                    WHERE server_id = $2 AND date = $3
                """, duration_seconds, server_id, event_date)
            
            return event_id
    
    async def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Получает последние события."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.server_id,
                    e.event_type,
                    e.event_time,
                    e.duration_seconds,
                    s.name as server_name,
                    s.ip_address,
                    sg.name as server_group_name
                FROM monitoring.server_events e
                JOIN monitoring.servers s ON e.server_id = s.id
                JOIN monitoring.server_groups sg ON s.server_group_id = sg.id
                ORDER BY e.event_time DESC
                LIMIT $1
            """, limit)
            return [dict(row) for row in rows]
    
    # ===== Metrics =====
    
    async def get_server_metrics(self, server_id: int) -> Optional[Dict]:
        """Получает метрики сервера."""
        async with self.db_pool.acquire() as conn:
            # Получаем сервер и метрики
            row = await conn.fetchrow("""
                SELECT 
                    s.id,
                    s.name,
                    s.ip_address,
                    sg.name as server_group_name,
                    s.first_seen,
                    s.last_seen,
                    m.total_uptime_seconds,
                    m.total_downtime_seconds,
                    m.downtime_count,
                    m.longest_downtime_seconds,
                    m.last_status,
                    m.last_status_change
                FROM monitoring.servers s
                JOIN monitoring.server_groups sg ON s.server_group_id = sg.id
                LEFT JOIN monitoring.server_metrics m ON s.id = m.server_id
                WHERE s.id = $1
            """, server_id)
            
            if not row:
                return None
            
            data = dict(row)
            
            # Вычисляем время работы
            first_seen = data['first_seen']
            last_seen = data['last_seen']
            total_time = (last_seen - first_seen).total_seconds() if first_seen and last_seen else 0
            
            total_downtime = data.get('total_downtime_seconds') or 0
            total_uptime = max(0, total_time - total_downtime)
            
            availability = 100.0
            if total_time > 0:
                availability = (total_uptime / total_time) * 100
            
            avg_downtime = 0.0
            downtime_count = data.get('downtime_count') or 0
            if downtime_count > 0:
                avg_downtime = total_downtime / downtime_count
            
            data['total_uptime_seconds'] = int(total_uptime)
            data['availability_percent'] = round(availability, 2)
            data['avg_downtime_seconds'] = round(avg_downtime, 1)
            
            return data
    
    async def get_all_metrics(self) -> List[Dict]:
        """Получает метрики всех серверов."""
        servers = await self.get_all_servers()
        metrics = []
        for server in servers:
            metric = await self.get_server_metrics(server['id'])
            if metric:
                metrics.append(metric)
        return metrics
    
    # ===== Daily Stats =====
    
    async def get_daily_report(self, target_date: Optional[date] = None) -> Dict:
        """Получает дневной отчёт."""
        if target_date is None:
            target_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    s.id,
                    s.name,
                    s.ip_address,
                    sg.name as server_group_name,
                    d.date,
                    d.uptime_seconds,
                    d.downtime_seconds,
                    d.downtime_count
                FROM monitoring.daily_stats d
                JOIN monitoring.servers s ON d.server_id = s.id
                JOIN monitoring.server_groups sg ON s.server_group_id = sg.id
                WHERE d.date = $1
                ORDER BY sg.name, s.name
            """, target_date)
            
            return {
                'date': target_date,
                'servers': [dict(row) for row in rows]
            }
    
    # ===== Server Management =====
    
    async def add_server_device(
        self, 
        group_name: str, 
        device_name: str, 
        device_ip: str
    ) -> tuple[bool, str]:
        """Добавляет устройство в группу."""
        if not device_name or not device_name.strip():
            return False, "Имя устройства не может быть пустым"
        
        if not device_ip or not device_ip.strip():
            return False, "IP-адрес не может быть пустым"
        
        # Валидация IP
        import re
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(pattern, device_ip):
            return False, "Неверный формат IP-адреса"
        
        parts = device_ip.split('.')
        if not all(0 <= int(part) <= 255 for part in parts):
            return False, "Неверный формат IP-адреса"
        
        try:
            server_id = await self.get_or_create_server(device_name, device_ip, group_name)
            return True, ""
        except Exception as e:
            logger.error(f"Error adding server device: {e}")
            return False, f"Ошибка при добавлении устройства: {e}"
    
    async def delete_server_device(self, server_id: int) -> bool:
        """Удаляет устройство."""
        async with self.db_pool.acquire() as conn:
            # Удаляем метрики, события, статистику (каскадно или вручную)
            await conn.execute("DELETE FROM monitoring.daily_stats WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM monitoring.server_events WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM monitoring.server_metrics WHERE server_id = $1", server_id)
            
            result = await conn.execute("DELETE FROM monitoring.servers WHERE id = $1", server_id)
            return result != "DELETE 0"
    
    async def get_all_servers_grouped(self) -> Dict[str, List[Dict]]:
        """Получает все серверы, сгруппированные по группам."""
        servers = await self.get_all_servers()
        groups: Dict[str, List[Dict]] = {}
        for server in servers:
            group_name = server['server_group_name']
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append({
                'name': server['name'],
                'ip': server['ip_address']
            })
        return groups

