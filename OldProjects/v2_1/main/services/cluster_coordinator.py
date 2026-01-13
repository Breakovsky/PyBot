"""
Координация кластера для распределенной работы.
Использует Redis для leader election и PostgreSQL для блокировок.
"""

import asyncio
import logging
import socket
from datetime import datetime, timedelta
from typing import Optional
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class ClusterCoordinator:
    """Координатор кластера для распределенной работы."""
    
    def __init__(
        self,
        node_id: str,
        node_type: str,
        redis_client: aioredis.Redis,
        db_pool,
        heartbeat_interval: int = 30,
        leader_ttl: int = 60
    ):
        """
        Инициализирует координатор кластера.
        
        Args:
            node_id: Уникальный ID узла
            node_type: Тип узла ('bot', 'web', 'worker')
            redis_client: Redis клиент для координации
            db_pool: Пул БД для регистрации узла
            heartbeat_interval: Интервал heartbeat в секундах
            leader_ttl: TTL для лидерства в секундах
        """
        self.node_id = node_id
        self.node_type = node_type
        self.redis = redis_client
        self.db_pool = db_pool
        self.heartbeat_interval = heartbeat_interval
        self.leader_ttl = leader_ttl
        
        self.is_leader = False
        self.is_running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._leader_check_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Запускает координатор."""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Регистрируем узел в БД
        await self._register_node()
        
        # Запускаем heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Запускаем проверку лидерства
        self._leader_check_task = asyncio.create_task(self._leader_check_loop())
        
        logger.info(f"Cluster coordinator started for node {self.node_id}")
    
    async def stop(self):
        """Останавливает координатор."""
        self.is_running = False
        
        # Отменяем задачи
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._leader_check_task:
            self._leader_check_task.cancel()
        
        # Освобождаем лидерство
        if self.is_leader:
            await self._release_leadership()
        
        # Удаляем узел из БД
        await self._unregister_node()
        
        logger.info(f"Cluster coordinator stopped for node {self.node_id}")
    
    async def _register_node(self):
        """Регистрирует узел в БД."""
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO cluster.cluster_nodes (node_id, node_type, hostname, ip_address, is_active, last_heartbeat)
                VALUES ($1, $2, $3, $4, TRUE, NOW())
                ON CONFLICT (node_id) DO UPDATE SET
                    node_type = EXCLUDED.node_type,
                    hostname = EXCLUDED.hostname,
                    ip_address = EXCLUDED.ip_address,
                    is_active = TRUE,
                    last_heartbeat = NOW()
            """, self.node_id, self.node_type, hostname, ip_address)
    
    async def _unregister_node(self):
        """Удаляет узел из БД."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE cluster.cluster_nodes
                SET is_active = FALSE
                WHERE node_id = $1
            """, self.node_id)
    
    async def _heartbeat_loop(self):
        """Цикл отправки heartbeat."""
        while self.is_running:
            try:
                # Обновляем heartbeat в Redis
                await self.redis.setex(
                    f"cluster:node:{self.node_id}:heartbeat",
                    self.heartbeat_interval * 2,
                    datetime.now().isoformat()
                )
                
                # Обновляем heartbeat в БД
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE cluster.cluster_nodes
                        SET last_heartbeat = NOW()
                        WHERE node_id = $1
                    """, self.node_id)
                
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _leader_check_loop(self):
        """Цикл проверки и получения лидерства."""
        while self.is_running:
            try:
                await self._try_become_leader()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in leader check loop: {e}")
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _try_become_leader(self) -> bool:
        """
        Пытается стать лидером для типа узла.
        
        Returns:
            True если стал лидером, False если нет
        """
        leader_key = f"cluster:leader:{self.node_type}"
        
        # Пытаемся установить лидерство через Redis SET NX
        result = await self.redis.set(
            leader_key,
            self.node_id,
            ex=self.leader_ttl,
            nx=True
        )
        
        if result:
            # Стали лидером
            if not self.is_leader:
                self.is_leader = True
                await self._update_leader_in_db(True)
                logger.info(f"Node {self.node_id} became leader for {self.node_type}")
            else:
                # Продлеваем лидерство
                await self.redis.expire(leader_key, self.leader_ttl)
            return True
        else:
            # Проверяем, кто лидер
            current_leader = await self.redis.get(leader_key)
            if current_leader and current_leader.decode() == self.node_id:
                # Мы лидер, продлеваем
                await self.redis.expire(leader_key, self.leader_ttl)
                if not self.is_leader:
                    self.is_leader = True
                    await self._update_leader_in_db(True)
            else:
                # Не лидер
                if self.is_leader:
                    self.is_leader = False
                    await self._update_leader_in_db(False)
                    logger.info(f"Node {self.node_id} lost leadership for {self.node_type}")
            return False
    
    async def _update_leader_in_db(self, is_leader: bool):
        """Обновляет статус лидерства в БД."""
        async with self.db_pool.acquire() as conn:
            # Сбрасываем все лидеры этого типа
            await conn.execute("""
                UPDATE cluster.cluster_nodes
                SET is_leader = FALSE
                WHERE node_type = $1
            """, self.node_type)
            
            # Устанавливаем текущего лидера
            if is_leader:
                await conn.execute("""
                    UPDATE cluster.cluster_nodes
                    SET is_leader = TRUE
                    WHERE node_id = $1
                """, self.node_id)
    
    async def _release_leadership(self):
        """Освобождает лидерство."""
        leader_key = f"cluster:leader:{self.node_type}"
        await self.redis.delete(leader_key)
        await self._update_leader_in_db(False)
    
    async def acquire_lock(self, lock_name: str, ttl: int = 60) -> bool:
        """
        Получить блокировку для выполнения задачи.
        
        Args:
            lock_name: Имя блокировки
            ttl: Время жизни блокировки в секундах
            
        Returns:
            True если получили блокировку, False если нет
        """
        lock_key = f"cluster:lock:{lock_name}"
        
        # Пытаемся получить блокировку через Redis
        result = await self.redis.set(
            lock_key,
            self.node_id,
            ex=ttl,
            nx=True
        )
        
        if result:
            # Сохраняем в БД для аудита
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO cluster.cluster_locks (lock_name, node_id, expires_at)
                    VALUES ($1, $2, NOW() + INTERVAL '%s seconds')
                    ON CONFLICT (lock_name) DO UPDATE SET
                        node_id = EXCLUDED.node_id,
                        acquired_at = NOW(),
                        expires_at = NOW() + INTERVAL '%s seconds'
                """ % (ttl, ttl), lock_name, self.node_id)
            
            return True
        
        return False
    
    async def release_lock(self, lock_name: str):
        """Освободить блокировку."""
        lock_key = f"cluster:lock:{lock_name}"
        await self.redis.delete(lock_key)
        
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM cluster.cluster_locks
                WHERE lock_name = $1 AND node_id = $2
            """, lock_name, self.node_id)
    
    async def is_task_locked(self, task_name: str) -> bool:
        """Проверить, заблокирована ли задача."""
        lock_key = f"cluster:lock:{task_name}"
        return await self.redis.exists(lock_key) > 0



