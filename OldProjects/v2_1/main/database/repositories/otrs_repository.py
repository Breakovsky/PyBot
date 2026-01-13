"""
Репозиторий для работы с OTRS данными.
Объединяет логику из v2_0 monitor_db.py (OTRS методы).
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from utils.logger import get_logger

logger = get_logger(__name__)


class OTRSRepository:
    """Репозиторий для работы с OTRS."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    # ===== OTRS Users =====
    
    async def save_otrs_user(
        self,
        telegram_user_id: int,
        otrs_email: str,
        otrs_username: Optional[str] = None,
        verified_at: Optional[datetime] = None
    ) -> int:
        """Сохраняет авторизованного пользователя OTRS."""
        if verified_at is None:
            verified_at = datetime.now()
        
        async with self.db_pool.acquire() as conn:
            otrs_user_id = await conn.fetchval("""
                INSERT INTO otrs.otrs_users 
                    (telegram_user_id, otrs_email, otrs_username, verified_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (telegram_user_id) DO UPDATE SET
                    otrs_email = EXCLUDED.otrs_email,
                    otrs_username = EXCLUDED.otrs_username,
                    verified_at = EXCLUDED.verified_at
                RETURNING id
            """, telegram_user_id, otrs_email, otrs_username, verified_at)
            
            logger.info(f"Saved OTRS user: telegram_user_id={telegram_user_id}, email={otrs_email}")
            return otrs_user_id
    
    async def get_otrs_user(self, telegram_user_id: int) -> Optional[Dict]:
        """Получает информацию об авторизованном пользователе OTRS."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    ou.id,
                    ou.telegram_user_id,
                    tu.telegram_id,
                    tu.telegram_username,
                    tu.full_name,
                    ou.otrs_email,
                    ou.otrs_username,
                    ou.verified_at,
                    ou.created_at
                FROM otrs.otrs_users ou
                JOIN telegram.telegram_users tu ON ou.telegram_user_id = tu.id
                WHERE ou.telegram_user_id = (
                    SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                )
            """, telegram_user_id)
            return dict(row) if row else None
    
    async def delete_otrs_user(self, telegram_user_id: int) -> bool:
        """Удаляет авторизацию пользователя OTRS."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM otrs.otrs_users
                WHERE telegram_user_id = (
                    SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                )
            """, telegram_user_id)
            return result != "DELETE 0"
    
    # ===== Verification Codes =====
    
    async def save_verification_code(
        self,
        telegram_id: int,
        email: str,
        code: str,
        expires_minutes: int = 10
    ) -> None:
        """Сохраняет код верификации."""
        expires_at = datetime.now() + timedelta(minutes=expires_minutes)
        
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO telegram.verification_codes 
                    (telegram_id, email, code, expires_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    email = EXCLUDED.email,
                    code = EXCLUDED.code,
                    expires_at = EXCLUDED.expires_at,
                    created_at = NOW()
            """, telegram_id, email, code, expires_at)
            
            logger.debug(f"Saved verification code for telegram_id={telegram_id}")
    
    async def get_verification(self, telegram_id: int) -> Optional[Dict]:
        """Получает ожидающую верификацию."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM telegram.verification_codes
                WHERE telegram_id = $1
            """, telegram_id)
            return dict(row) if row else None
    
    async def verify_code(self, telegram_id: int, code: str) -> Optional[str]:
        """
        Проверяет код верификации.
        Возвращает email если код верный и не истёк, иначе None.
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT email, code, expires_at 
                FROM telegram.verification_codes 
                WHERE telegram_id = $1
            """, telegram_id)
            
            if not row:
                return None
            
            # Проверяем код
            if row['code'] != code:
                return None
            
            # Проверяем срок действия
            expires_at = row['expires_at']
            if datetime.now() > expires_at:
                # Код истёк
                await conn.execute("""
                    DELETE FROM telegram.verification_codes 
                    WHERE telegram_id = $1
                """, telegram_id)
                return None
            
            email = row['email']
            
            # Удаляем использованный код
            await conn.execute("""
                DELETE FROM telegram.verification_codes 
                WHERE telegram_id = $1
            """, telegram_id)
            
            return email
    
    async def delete_verification(self, telegram_id: int) -> None:
        """Удаляет ожидающую верификацию."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM telegram.verification_codes 
                WHERE telegram_id = $1
            """, telegram_id)
    
    # ===== Ticket Messages =====
    
    async def save_ticket_message(
        self,
        ticket_id: int,
        ticket_number: str,
        message_id: int,
        chat_id: int,
        topic_id: Optional[int],
        ticket_state: Optional[str] = None
    ) -> int:
        """Сохраняет информацию об отправленном тикете."""
        async with self.db_pool.acquire() as conn:
            msg_id = await conn.fetchval("""
                INSERT INTO otrs.otrs_ticket_messages 
                    (ticket_id, ticket_number, message_id, chat_id, topic_id, ticket_state, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (ticket_id, chat_id, topic_id) DO UPDATE SET
                    message_id = EXCLUDED.message_id,
                    ticket_state = EXCLUDED.ticket_state,
                    updated_at = NOW()
                RETURNING id
            """, ticket_id, ticket_number, message_id, chat_id, topic_id, ticket_state)
            return msg_id
    
    async def get_ticket_message(
        self,
        ticket_id: int,
        chat_id: int,
        topic_id: Optional[int]
    ) -> Optional[Dict]:
        """Получает информацию об отправленном тикете."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM otrs.otrs_ticket_messages 
                WHERE ticket_id = $1 AND chat_id = $2 AND topic_id = $3
            """, ticket_id, chat_id, topic_id)
            return dict(row) if row else None
    
    async def get_all_ticket_messages(
        self,
        chat_id: int,
        topic_id: Optional[int]
    ) -> List[Dict]:
        """Получает все отправленные тикеты для чата/топика."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM otrs.otrs_ticket_messages 
                WHERE chat_id = $1 AND topic_id = $2
                ORDER BY sent_at DESC
            """, chat_id, topic_id)
            return [dict(row) for row in rows]
    
    async def delete_ticket_message(
        self,
        ticket_id: int,
        chat_id: int,
        topic_id: Optional[int]
    ) -> bool:
        """Удаляет информацию об отправленном тикете."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM otrs.otrs_ticket_messages 
                WHERE ticket_id = $1 AND chat_id = $2 AND topic_id = $3
            """, ticket_id, chat_id, topic_id)
            return result != "DELETE 0"
    
    # ===== User Private Tickets =====
    
    async def save_private_ticket(
        self,
        telegram_user_id: int,
        ticket_id: int,
        ticket_number: str,
        message_id: int
    ) -> int:
        """Сохраняет сообщение о тикете в личке пользователя."""
        async with self.db_pool.acquire() as conn:
            # Получаем telegram_user.id из telegram_id
            tu_id = await conn.fetchval("""
                SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
            """, telegram_user_id)
            
            if not tu_id:
                raise ValueError(f"Telegram user {telegram_user_id} not found")
            
            private_id = await conn.fetchval("""
                INSERT INTO otrs.user_private_tickets 
                    (telegram_user_id, ticket_id, ticket_number, message_id, assigned_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (telegram_user_id, ticket_id) DO UPDATE SET
                    message_id = EXCLUDED.message_id,
                    assigned_at = NOW()
                RETURNING id
            """, tu_id, ticket_id, ticket_number, message_id)
            return private_id
    
    async def get_private_ticket(
        self,
        telegram_user_id: int,
        ticket_id: int
    ) -> Optional[Dict]:
        """Получает информацию о личном сообщении с тикетом."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM otrs.user_private_tickets 
                WHERE telegram_user_id = (
                    SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                ) AND ticket_id = $2
            """, telegram_user_id, ticket_id)
            return dict(row) if row else None
    
    async def get_user_private_tickets(self, telegram_user_id: int) -> List[Dict]:
        """Получает все личные тикеты пользователя."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM otrs.user_private_tickets 
                WHERE telegram_user_id = (
                    SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                )
                ORDER BY assigned_at DESC
            """, telegram_user_id)
            return [dict(row) for row in rows]
    
    async def delete_private_ticket(
        self,
        telegram_user_id: int,
        ticket_id: int
    ) -> bool:
        """Удаляет личное сообщение о тикете."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM otrs.user_private_tickets 
                WHERE telegram_user_id = (
                    SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
                ) AND ticket_id = $2
            """, telegram_user_id, ticket_id)
            return result != "DELETE 0"
    
    # ===== OTRS Metrics =====
    
    async def record_otrs_action(
        self,
        telegram_user_id: int,
        action_type: str,  # 'closed', 'rejected', 'assigned', 'commented'
        ticket_id: int,
        ticket_number: Optional[str] = None,
        ticket_title: Optional[str] = None,
        details: Optional[Dict] = None
    ) -> int:
        """Записывает действие пользователя с тикетом."""
        async with self.db_pool.acquire() as conn:
            # Получаем telegram_user.id
            tu_id = await conn.fetchval("""
                SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
            """, telegram_user_id)
            
            if not tu_id:
                raise ValueError(f"Telegram user {telegram_user_id} not found")
            
            metric_id = await conn.fetchval("""
                INSERT INTO otrs.otrs_metrics 
                    (telegram_user_id, action_type, ticket_id, ticket_number, ticket_title, details, action_time)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                RETURNING id
            """, tu_id, action_type, ticket_id, ticket_number, ticket_title, details)
            
            logger.debug(f"Recorded OTRS action: {action_type} by {telegram_user_id} on ticket {ticket_id}")
            return metric_id
    
    async def get_user_otrs_stats(self, telegram_user_id: int) -> Dict:
        """Получает статистику пользователя по OTRS."""
        async with self.db_pool.acquire() as conn:
            tu_id = await conn.fetchval("""
                SELECT id FROM telegram.telegram_users WHERE telegram_id = $1
            """, telegram_user_id)
            
            if not tu_id:
                return {
                    'closed': 0,
                    'rejected': 0,
                    'assigned': 0,
                    'commented': 0,
                    'total': 0,
                    'recent_actions': []
                }
            
            # Общее количество по типам действий
            rows = await conn.fetch("""
                SELECT action_type, COUNT(*) as count
                FROM otrs.otrs_metrics
                WHERE telegram_user_id = $1
                GROUP BY action_type
            """, tu_id)
            
            stats = {
                'closed': 0,
                'rejected': 0,
                'assigned': 0,
                'commented': 0,
                'total': 0
            }
            
            for row in rows:
                action_type = row['action_type']
                count = row['count']
                if action_type in stats:
                    stats[action_type] = count
                stats['total'] += count
            
            # Последние действия
            recent_rows = await conn.fetch("""
                SELECT * FROM otrs.otrs_metrics
                WHERE telegram_user_id = $1
                ORDER BY action_time DESC
                LIMIT 5
            """, tu_id)
            
            stats['recent_actions'] = [dict(row) for row in recent_rows]
            
            return stats
    
    async def get_otrs_leaderboard(
        self,
        action_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Получает таблицу лидеров по действиям OTRS."""
        async with self.db_pool.acquire() as conn:
            if action_type:
                rows = await conn.fetch("""
                    SELECT 
                        tu.telegram_id,
                        tu.telegram_username,
                        ou.otrs_email,
                        COUNT(*) as count
                    FROM otrs.otrs_metrics om
                    JOIN telegram.telegram_users tu ON om.telegram_user_id = tu.id
                    LEFT JOIN otrs.otrs_users ou ON tu.id = ou.telegram_user_id
                    WHERE om.action_type = $1
                    GROUP BY tu.telegram_id, tu.telegram_username, ou.otrs_email
                    ORDER BY count DESC
                    LIMIT $2
                """, action_type, limit)
            else:
                rows = await conn.fetch("""
                    SELECT 
                        tu.telegram_id,
                        tu.telegram_username,
                        ou.otrs_email,
                        COUNT(*) as count
                    FROM otrs.otrs_metrics om
                    JOIN telegram.telegram_users tu ON om.telegram_user_id = tu.id
                    LEFT JOIN otrs.otrs_users ou ON tu.id = ou.telegram_user_id
                    GROUP BY tu.telegram_id, tu.telegram_username, ou.otrs_email
                    ORDER BY count DESC
                    LIMIT $1
                """, limit)
            
            return [dict(row) for row in rows]
    
    async def get_weekly_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        Получает еженедельный отчёт по заявкам (пн-вс).
        Если даты не указаны - берёт прошлую неделю.
        """
        if start_date is None or end_date is None:
            # Находим прошлый понедельник
            today = date.today()
            days_since_monday = today.weekday()  # 0 = понедельник
            last_monday = today - timedelta(days=days_since_monday + 7)
            last_sunday = last_monday + timedelta(days=6)
            
            start_date = datetime.combine(last_monday, datetime.min.time())
            end_date = datetime.combine(last_sunday, datetime.max.time())
        
        async with self.db_pool.acquire() as conn:
            # Статистика по пользователям
            rows = await conn.fetch("""
                SELECT 
                    tu.telegram_id,
                    tu.telegram_username,
                    ou.otrs_email,
                    om.action_type,
                    COUNT(*) as count
                FROM otrs.otrs_metrics om
                JOIN telegram.telegram_users tu ON om.telegram_user_id = tu.id
                LEFT JOIN otrs.otrs_users ou ON tu.id = ou.telegram_user_id
                WHERE om.action_time >= $1 AND om.action_time <= $2
                GROUP BY tu.telegram_id, tu.telegram_username, ou.otrs_email, om.action_type
                ORDER BY count DESC
            """, start_date, end_date)
            
            user_stats: Dict[int, Dict] = {}
            for row in rows:
                uid = row['telegram_id']
                if uid not in user_stats:
                    user_stats[uid] = {
                        'telegram_id': uid,
                        'username': row['telegram_username'] or 'Unknown',
                        'email': row['otrs_email'] or '',
                        'closed': 0,
                        'rejected': 0,
                        'assigned': 0,
                        'commented': 0,
                        'total': 0
                    }
                
                action_type = row['action_type']
                count = row['count']
                if action_type in user_stats[uid]:
                    user_stats[uid][action_type] = count
                user_stats[uid]['total'] += count
            
            # Общая статистика
            total_rows = await conn.fetch("""
                SELECT action_type, COUNT(*) as count
                FROM otrs.otrs_metrics
                WHERE action_time >= $1 AND action_time <= $2
                GROUP BY action_type
            """, start_date, end_date)
            
            totals = {
                'closed': 0,
                'rejected': 0,
                'assigned': 0,
                'commented': 0,
                'total': 0
            }
            
            for row in total_rows:
                action_type = row['action_type']
                count = row['count']
                if action_type in totals:
                    totals[action_type] = count
                totals['total'] += count
            
            # Сортируем пользователей по закрытым заявкам
            sorted_users = sorted(
                user_stats.values(),
                key=lambda x: (x['closed'], x['total']),
                reverse=True
            )
            
            return {
                'start_date': start_date,
                'end_date': end_date,
                'users': sorted_users,
                'totals': totals
            }

