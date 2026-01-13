# main/modules/handlers/monitor_db.py

"""
База данных для хранения метрик мониторинга серверов.
Использует SQLite - легковесная, не требует сервера.
"""

import sqlite3
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

# Добавляем корень проекта в путь для импорта
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from assets.config import now_msk

logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = Path(__file__).parent.parent.parent / "data" / "monitor.db"


@dataclass
class ServerEvent:
    """Событие сервера."""
    id: int
    server_name: str
    server_ip: str
    server_group: str
    event_type: str  # 'UP' или 'DOWN'
    event_time: datetime
    duration_seconds: Optional[int] = None  # Для DOWN - сколько был недоступен


@dataclass
class ServerMetrics:
    """Метрики сервера."""
    server_name: str
    server_ip: str
    server_group: str
    total_uptime_seconds: int
    total_downtime_seconds: int
    downtime_count: int  # Сколько раз падал
    last_up_time: Optional[datetime]
    last_down_time: Optional[datetime]
    availability_percent: float  # SLA процент
    avg_downtime_seconds: float  # Среднее время недоступности
    longest_downtime_seconds: int  # Самый долгий даунтайм
    first_seen: datetime
    last_seen: datetime


class MonitorDatabase:
    """Класс для работы с базой данных мониторинга."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Создаёт соединение с БД."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def execute_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """Выполняет произвольный SQL-запрос и возвращает результат."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def _init_db(self):
        """Инициализирует таблицы базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица серверов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    server_group TEXT NOT NULL,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, server_group)
                )
            """)
            
            # Таблица событий (UP/DOWN)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('UP', 'DOWN')),
                    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_seconds INTEGER,
                    FOREIGN KEY (server_id) REFERENCES servers(id)
                )
            """)
            
            # Таблица агрегированных метрик
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL UNIQUE,
                    total_uptime_seconds INTEGER DEFAULT 0,
                    total_downtime_seconds INTEGER DEFAULT 0,
                    downtime_count INTEGER DEFAULT 0,
                    longest_downtime_seconds INTEGER DEFAULT 0,
                    last_status TEXT DEFAULT 'UNKNOWN',
                    last_status_change TIMESTAMP,
                    FOREIGN KEY (server_id) REFERENCES servers(id)
                )
            """)
            
            # Таблица дневной статистики
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    uptime_seconds INTEGER DEFAULT 0,
                    downtime_seconds INTEGER DEFAULT 0,
                    downtime_count INTEGER DEFAULT 0,
                    UNIQUE(server_id, date),
                    FOREIGN KEY (server_id) REFERENCES servers(id)
                )
            """)
            
            # Таблица персистентных сообщений (для сохранения ID между перезапусками)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS persistent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    message_type TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chat_id, topic_id, message_type)
                )
            """)
            
            # Таблица для отслеживания сообщений на удаление (Excel topic и другие)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_deletions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    delete_after TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chat_id, message_id)
                )
            """)
            
            # ===== OTRS Tables =====
            
            # Таблица авторизованных пользователей OTRS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS otrs_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    telegram_username TEXT,
                    full_name TEXT,
                    otrs_email TEXT NOT NULL,
                    otrs_username TEXT,
                    verified_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Миграция: добавляем full_name если не существует
            try:
                cursor.execute("ALTER TABLE otrs_users ADD COLUMN full_name TEXT")
            except:
                pass  # Колонка уже существует
            
            # Таблица веб-пользователей (для веб-панели)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS web_users (
                    email TEXT PRIMARY KEY,
                    password_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    password_set_at TIMESTAMP
                )
            """)
            
            # Таблица ожидающих верификаций (коды подтверждения)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS otrs_pending_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    email TEXT NOT NULL,
                    code TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица отправленных тикетов (для защиты от дублей при перезапуске)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS otrs_ticket_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    ticket_number TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    ticket_state TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticket_id, chat_id, topic_id)
                )
            """)
            
            # Таблица метрик пользователей OTRS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS otrs_user_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    telegram_username TEXT,
                    otrs_email TEXT,
                    action_type TEXT NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    ticket_number TEXT,
                    ticket_title TEXT,
                    action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    details TEXT
                )
            """)
            
            # Таблица личных сообщений с тикетами (для дублирования в ЛС)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_private_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    ticket_number TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(telegram_id, ticket_id)
                )
            """)
            
            # Индексы для быстрого поиска метрик
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_otrs_metrics_user 
                ON otrs_user_metrics(telegram_id, action_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_otrs_metrics_time 
                ON otrs_user_metrics(action_time)
            """)
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    def get_or_create_server(self, name: str, ip: str, group: str) -> int:
        """Получает или создаёт сервер, возвращает ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Пытаемся найти существующий
            cursor.execute(
                "SELECT id FROM servers WHERE name = ? AND server_group = ?",
                (name, group)
            )
            row = cursor.fetchone()
            
            if row:
                # Обновляем last_seen и IP
                cursor.execute(
                    "UPDATE servers SET last_seen = ?, ip = ? WHERE id = ?",
                    (now_msk(), ip, row['id'])
                )
                conn.commit()
                return row['id']
            
            # Создаём новый
            cursor.execute(
                "INSERT INTO servers (name, ip, server_group) VALUES (?, ?, ?)",
                (name, ip, group)
            )
            server_id = cursor.lastrowid
            
            # Создаём запись метрик
            cursor.execute(
                "INSERT INTO metrics (server_id) VALUES (?)",
                (server_id,)
            )
            
            conn.commit()
            logger.info(f"Created new server in DB: {name} ({group})")
            return server_id
    
    def record_event(self, name: str, ip: str, group: str, 
                     event_type: str, event_time: datetime,
                     duration_seconds: Optional[int] = None) -> int:
        """Записывает событие UP или DOWN."""
        server_id = self.get_or_create_server(name, ip, group)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Записываем событие
            cursor.execute("""
                INSERT INTO events (server_id, event_type, event_time, duration_seconds)
                VALUES (?, ?, ?, ?)
            """, (server_id, event_type, event_time, duration_seconds))
            
            event_id = cursor.lastrowid
            
            # Обновляем метрики
            if event_type == 'DOWN':
                cursor.execute("""
                    UPDATE metrics SET 
                        downtime_count = downtime_count + 1,
                        last_status = 'DOWN',
                        last_status_change = ?
                    WHERE server_id = ?
                """, (event_time, server_id))
            else:  # UP
                if duration_seconds:
                    cursor.execute("""
                        UPDATE metrics SET 
                            total_downtime_seconds = total_downtime_seconds + ?,
                            longest_downtime_seconds = MAX(longest_downtime_seconds, ?),
                            last_status = 'UP',
                            last_status_change = ?
                        WHERE server_id = ?
                    """, (duration_seconds, duration_seconds, event_time, server_id))
                else:
                    cursor.execute("""
                        UPDATE metrics SET 
                            last_status = 'UP',
                            last_status_change = ?
                        WHERE server_id = ?
                    """, (event_time, server_id))
            
            # Обновляем дневную статистику
            today = event_time.date()
            cursor.execute("""
                INSERT INTO daily_stats (server_id, date, downtime_count)
                VALUES (?, ?, ?)
                ON CONFLICT(server_id, date) DO UPDATE SET
                    downtime_count = downtime_count + ?
            """, (server_id, today, 1 if event_type == 'DOWN' else 0, 
                  1 if event_type == 'DOWN' else 0))
            
            if event_type == 'UP' and duration_seconds:
                cursor.execute("""
                    UPDATE daily_stats SET downtime_seconds = downtime_seconds + ?
                    WHERE server_id = ? AND date = ?
                """, (duration_seconds, server_id, today))
            
            conn.commit()
            return event_id
    
    def get_server_metrics(self, name: str, group: str) -> Optional[ServerMetrics]:
        """Получает метрики сервера."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.*, m.*
                FROM servers s
                JOIN metrics m ON s.id = m.server_id
                WHERE s.name = ? AND s.server_group = ?
            """, (name, group))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Вычисляем время работы
            first_seen_str = row['first_seen']
            last_seen_str = row['last_seen']
            
            # Парсим даты и делаем их timezone-aware (MSK)
            first_seen = datetime.fromisoformat(first_seen_str)
            last_seen = datetime.fromisoformat(last_seen_str)
            
            # Если даты naive, добавляем MSK timezone
            from assets.config import MSK_TIMEZONE
            if first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=MSK_TIMEZONE)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=MSK_TIMEZONE)
            
            total_time = (last_seen - first_seen).total_seconds()
            
            total_downtime = row['total_downtime_seconds'] or 0
            total_uptime = max(0, total_time - total_downtime)
            
            availability = 100.0
            if total_time > 0:
                availability = (total_uptime / total_time) * 100
            
            avg_downtime = 0.0
            if row['downtime_count'] > 0:
                avg_downtime = total_downtime / row['downtime_count']
            
            return ServerMetrics(
                server_name=row['name'],
                server_ip=row['ip'],
                server_group=row['server_group'],
                total_uptime_seconds=int(total_uptime),
                total_downtime_seconds=total_downtime,
                downtime_count=row['downtime_count'] or 0,
                last_up_time=None,  # TODO: получить из events
                last_down_time=None,
                availability_percent=round(availability, 2),
                avg_downtime_seconds=round(avg_downtime, 1),
                longest_downtime_seconds=row['longest_downtime_seconds'] or 0,
                first_seen=first_seen,
                last_seen=last_seen
            )
    
    def get_all_metrics(self) -> List[ServerMetrics]:
        """Получает метрики всех серверов."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.name, s.server_group FROM servers s
                ORDER BY s.server_group, s.name
            """)
            
            results = []
            for row in cursor.fetchall():
                metrics = self.get_server_metrics(row['name'], row['server_group'])
                if metrics:
                    results.append(metrics)
            
            return results
    
    def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Получает последние события."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT e.*, s.name, s.ip, s.server_group
                FROM events e
                JOIN servers s ON e.server_id = s.id
                ORDER BY e.event_time DESC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_daily_report(self, date: Optional[datetime] = None) -> Dict:
        """Получает дневной отчёт."""
        if date is None:
            date = now_msk()
        
        target_date = date.date()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.name, s.server_group, d.*
                FROM daily_stats d
                JOIN servers s ON d.server_id = s.id
                WHERE d.date = ?
            """, (target_date,))
            
            return {
                'date': target_date,
                'servers': [dict(row) for row in cursor.fetchall()]
            }
    
    def format_duration(self, seconds: int) -> str:
        """Форматирует секунды в читаемый вид."""
        if seconds < 60:
            return f"{seconds}с"
        elif seconds < 3600:
            m = seconds // 60
            s = seconds % 60
            return f"{m}м {s}с"
        elif seconds < 86400:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}ч {m}м"
        else:
            d = seconds // 86400
            h = (seconds % 86400) // 3600
            return f"{d}д {h}ч"
    
    # ===== Методы для персистентных сообщений =====
    
    def save_message_id(self, chat_id: int, topic_id: int, message_type: str, message_id: int):
        """Сохраняет ID сообщения для последующего использования."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO persistent_messages (chat_id, topic_id, message_type, message_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, topic_id, message_type) DO UPDATE SET
                    message_id = excluded.message_id,
                    updated_at = excluded.updated_at
            """, (chat_id, topic_id, message_type, message_id, now_msk()))
            conn.commit()
            logger.debug(f"Saved message ID: {message_type}={message_id} for topic {topic_id}")
    
    def get_message_id(self, chat_id: int, topic_id: int, message_type: str) -> Optional[int]:
        """Получает сохранённый ID сообщения."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT message_id FROM persistent_messages
                WHERE chat_id = ? AND topic_id = ? AND message_type = ?
            """, (chat_id, topic_id, message_type))
            row = cursor.fetchone()
            if row:
                return row['message_id']
            return None
    
    def delete_message_id(self, chat_id: int, topic_id: int, message_type: str):
        """Удаляет сохранённый ID сообщения."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM persistent_messages
                WHERE chat_id = ? AND topic_id = ? AND message_type = ?
            """, (chat_id, topic_id, message_type))
            conn.commit()
    
    # ===== Методы для отложенного удаления сообщений =====
    
    def add_pending_deletion(self, chat_id: int, topic_id: int, message_id: int, delete_after: datetime):
        """Добавляет сообщение в очередь на удаление."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO pending_deletions (chat_id, topic_id, message_id, delete_after)
                VALUES (?, ?, ?, ?)
            """, (chat_id, topic_id, message_id, delete_after))
            conn.commit()
    
    def get_pending_deletions(self, topic_id: Optional[int] = None) -> List[Dict]:
        """Получает все сообщения на удаление (опционально по топику)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if topic_id is not None:
                cursor.execute("""
                    SELECT chat_id, topic_id, message_id, delete_after
                    FROM pending_deletions
                    WHERE topic_id = ?
                    ORDER BY created_at
                """, (topic_id,))
            else:
                cursor.execute("""
                    SELECT chat_id, topic_id, message_id, delete_after
                    FROM pending_deletions
                    ORDER BY created_at
                """)
            return [dict(row) for row in cursor.fetchall()]
    
    def remove_pending_deletion(self, chat_id: int, message_id: int):
        """Удаляет сообщение из очереди на удаление."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM pending_deletions
                WHERE chat_id = ? AND message_id = ?
            """, (chat_id, message_id))
            conn.commit()
    
    def clear_topic_deletions(self, topic_id: int):
        """Очищает все записи удаления для топика."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM pending_deletions
                WHERE topic_id = ?
            """, (topic_id,))
            conn.commit()
            logger.debug(f"Cleared all pending deletions for topic {topic_id}")
    
    # ===== OTRS User Methods =====
    
    def save_otrs_user(self, telegram_id: int, telegram_username: str, 
                       otrs_email: str, otrs_username: str = None, full_name: str = None):
        """Сохраняет авторизованного пользователя OTRS."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO otrs_users (telegram_id, telegram_username, full_name, otrs_email, otrs_username, verified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    telegram_username = excluded.telegram_username,
                    full_name = excluded.full_name,
                    otrs_email = excluded.otrs_email,
                    otrs_username = excluded.otrs_username,
                    verified_at = excluded.verified_at
            """, (telegram_id, telegram_username, full_name, otrs_email, otrs_username, now_msk()))
            conn.commit()
            logger.info(f"Saved OTRS user: telegram_id={telegram_id}, email={otrs_email}, name={full_name}")
    
    def get_otrs_user(self, telegram_id: int) -> Optional[Dict]:
        """Получает информацию об авторизованном пользователе OTRS."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM otrs_users WHERE telegram_id = ?
            """, (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def delete_otrs_user(self, telegram_id: int):
        """Удаляет авторизацию пользователя OTRS."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM otrs_users WHERE telegram_id = ?
            """, (telegram_id,))
            conn.commit()
    
    def save_verification_code(self, telegram_id: int, email: str, code: str, expires_minutes: int = 10):
        """Сохраняет код верификации."""
        from datetime import timedelta
        expires_at = now_msk() + timedelta(minutes=expires_minutes)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO otrs_pending_verifications (telegram_id, email, code, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    email = excluded.email,
                    code = excluded.code,
                    expires_at = excluded.expires_at,
                    created_at = CURRENT_TIMESTAMP
            """, (telegram_id, email, code, expires_at))
            conn.commit()
            logger.debug(f"Saved verification code for telegram_id={telegram_id}")
    
    def get_verification(self, telegram_id: int) -> Optional[Dict]:
        """Получает ожидающую верификацию."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM otrs_pending_verifications WHERE telegram_id = ?
            """, (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def verify_code(self, telegram_id: int, code: str) -> Optional[str]:
        """
        Проверяет код верификации.
        Возвращает email если код верный и не истёк, иначе None.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT email, code, expires_at FROM otrs_pending_verifications 
                WHERE telegram_id = ?
            """, (telegram_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            # Проверяем код
            if row['code'] != code:
                return None
            
            # Проверяем срок действия
            expires_at = datetime.fromisoformat(row['expires_at'])
            from assets.config import MSK_TIMEZONE
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=MSK_TIMEZONE)
            
            if now_msk() > expires_at:
                # Код истёк
                cursor.execute("""
                    DELETE FROM otrs_pending_verifications WHERE telegram_id = ?
                """, (telegram_id,))
                conn.commit()
                return None
            
            # Удаляем использованный код
            cursor.execute("""
                DELETE FROM otrs_pending_verifications WHERE telegram_id = ?
            """, (telegram_id,))
            conn.commit()
            
            return row['email']
    
    def delete_verification(self, telegram_id: int):
        """Удаляет ожидающую верификацию."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM otrs_pending_verifications WHERE telegram_id = ?
            """, (telegram_id,))
            conn.commit()
    
    # ===== OTRS Ticket Messages Methods =====
    
    def save_ticket_message(self, ticket_id: int, ticket_number: str, 
                            message_id: int, chat_id: int, topic_id: int,
                            ticket_state: str = None):
        """Сохраняет информацию об отправленном тикете."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO otrs_ticket_messages 
                    (ticket_id, ticket_number, message_id, chat_id, topic_id, ticket_state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_id, chat_id, topic_id) DO UPDATE SET
                    message_id = excluded.message_id,
                    ticket_state = excluded.ticket_state,
                    updated_at = excluded.updated_at
            """, (ticket_id, ticket_number, message_id, chat_id, topic_id, ticket_state, now_msk()))
            conn.commit()
    
    def get_ticket_message(self, ticket_id: int, chat_id: int, topic_id: int) -> Optional[Dict]:
        """Получает информацию об отправленном тикете."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM otrs_ticket_messages 
                WHERE ticket_id = ? AND chat_id = ? AND topic_id = ?
            """, (ticket_id, chat_id, topic_id))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_all_ticket_messages(self, chat_id: int, topic_id: int) -> List[Dict]:
        """Получает все отправленные тикеты для чата/топика."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM otrs_ticket_messages 
                WHERE chat_id = ? AND topic_id = ?
                ORDER BY sent_at DESC
            """, (chat_id, topic_id))
            return [dict(row) for row in cursor.fetchall()]
    
    def delete_ticket_message(self, ticket_id: int, chat_id: int, topic_id: int):
        """Удаляет информацию об отправленном тикете."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM otrs_ticket_messages 
                WHERE ticket_id = ? AND chat_id = ? AND topic_id = ?
            """, (ticket_id, chat_id, topic_id))
            conn.commit()
    
    # ===== User Private Tickets Methods =====
    
    def save_private_ticket(self, telegram_id: int, ticket_id: int, 
                            ticket_number: str, message_id: int):
        """Сохраняет сообщение о тикете в личке пользователя."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_private_tickets 
                    (telegram_id, ticket_id, ticket_number, message_id, assigned_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id, ticket_id) DO UPDATE SET
                    message_id = excluded.message_id,
                    assigned_at = excluded.assigned_at
            """, (telegram_id, ticket_id, ticket_number, message_id, now_msk()))
            conn.commit()
    
    def get_private_ticket(self, telegram_id: int, ticket_id: int) -> Optional[Dict]:
        """Получает информацию о личном сообщении с тикетом."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_private_tickets 
                WHERE telegram_id = ? AND ticket_id = ?
            """, (telegram_id, ticket_id))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_user_private_tickets(self, telegram_id: int) -> List[Dict]:
        """Получает все личные тикеты пользователя."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_private_tickets 
                WHERE telegram_id = ?
                ORDER BY assigned_at DESC
            """, (telegram_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def delete_private_ticket(self, telegram_id: int, ticket_id: int):
        """Удаляет личное сообщение о тикете."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM user_private_tickets 
                WHERE telegram_id = ? AND ticket_id = ?
            """, (telegram_id, ticket_id))
            conn.commit()
    
    def get_private_ticket_by_ticket_id(self, ticket_id: int) -> List[Dict]:
        """Получает все личные сообщения для тикета (у всех пользователей)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_private_tickets 
                WHERE ticket_id = ?
            """, (ticket_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ===== OTRS User Metrics Methods =====
    
    def record_otrs_action(
        self, 
        telegram_id: int,
        telegram_username: str,
        otrs_email: str,
        action_type: str,  # 'closed', 'rejected', 'assigned', 'commented'
        ticket_id: int,
        ticket_number: str = None,
        ticket_title: str = None,
        details: str = None
    ):
        """Записывает действие пользователя с тикетом."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO otrs_user_metrics 
                    (telegram_id, telegram_username, otrs_email, action_type, 
                     ticket_id, ticket_number, ticket_title, action_time, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, telegram_username, otrs_email, action_type,
                  ticket_id, ticket_number, ticket_title, now_msk(), details))
            conn.commit()
            logger.debug(f"Recorded OTRS action: {action_type} by {telegram_id} on ticket {ticket_id}")
    
    def get_user_otrs_stats(self, telegram_id: int) -> Dict:
        """Получает статистику пользователя по OTRS."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Общее количество по типам действий
            cursor.execute("""
                SELECT action_type, COUNT(*) as count
                FROM otrs_user_metrics
                WHERE telegram_id = ?
                GROUP BY action_type
            """, (telegram_id,))
            
            stats = {
                'closed': 0,
                'rejected': 0,
                'assigned': 0,
                'commented': 0,
                'total': 0
            }
            
            for row in cursor.fetchall():
                action_type = row['action_type']
                count = row['count']
                if action_type in stats:
                    stats[action_type] = count
                stats['total'] += count
            
            # Последние действия
            cursor.execute("""
                SELECT * FROM otrs_user_metrics
                WHERE telegram_id = ?
                ORDER BY action_time DESC
                LIMIT 5
            """, (telegram_id,))
            
            stats['recent_actions'] = [dict(row) for row in cursor.fetchall()]
            
            return stats
    
    def get_otrs_leaderboard(self, action_type: str = None, limit: int = 10) -> List[Dict]:
        """Получает таблицу лидеров по действиям OTRS."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if action_type:
                cursor.execute("""
                    SELECT telegram_id, telegram_username, otrs_email, 
                           COUNT(*) as count
                    FROM otrs_user_metrics
                    WHERE action_type = ?
                    GROUP BY telegram_id
                    ORDER BY count DESC
                    LIMIT ?
                """, (action_type, limit))
            else:
                cursor.execute("""
                    SELECT telegram_id, telegram_username, otrs_email, 
                           COUNT(*) as count
                    FROM otrs_user_metrics
                    GROUP BY telegram_id
                    ORDER BY count DESC
                    LIMIT ?
                """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_otrs_stats_period(self, days: int = 7) -> Dict:
        """Получает общую статистику OTRS за период."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            from datetime import timedelta
            start_date = now_msk() - timedelta(days=days)
            
            cursor.execute("""
                SELECT action_type, COUNT(*) as count
                FROM otrs_user_metrics
                WHERE action_time >= ?
                GROUP BY action_type
            """, (start_date,))
            
            stats = {
                'period_days': days,
                'closed': 0,
                'rejected': 0,
                'assigned': 0,
                'commented': 0,
                'total': 0
            }
            
            for row in cursor.fetchall():
                action_type = row['action_type']
                count = row['count']
                if action_type in stats:
                    stats[action_type] = count
                stats['total'] += count
            
            return stats
    
    def get_weekly_report(self, start_date: datetime = None, end_date: datetime = None) -> Dict:
        """
        Получает еженедельный отчёт по заявкам (пн-вс).
        Если даты не указаны - берёт прошлую неделю.
        """
        from datetime import timedelta
        
        if start_date is None or end_date is None:
            # Находим прошлый понедельник
            today = now_msk().date()
            days_since_monday = today.weekday()  # 0 = понедельник
            last_monday = today - timedelta(days=days_since_monday + 7)
            last_sunday = last_monday + timedelta(days=6)
            
            start_date = datetime.combine(last_monday, datetime.min.time())
            end_date = datetime.combine(last_sunday, datetime.max.time())
            
            # Добавляем timezone
            from assets.config import MSK_TIMEZONE
            start_date = start_date.replace(tzinfo=MSK_TIMEZONE)
            end_date = end_date.replace(tzinfo=MSK_TIMEZONE)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Статистика по пользователям
            cursor.execute("""
                SELECT 
                    telegram_id,
                    telegram_username,
                    otrs_email,
                    action_type,
                    COUNT(*) as count
                FROM otrs_user_metrics
                WHERE action_time >= ? AND action_time <= ?
                GROUP BY telegram_id, action_type
                ORDER BY count DESC
            """, (start_date, end_date))
            
            user_stats = {}
            for row in cursor.fetchall():
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
            cursor.execute("""
                SELECT action_type, COUNT(*) as count
                FROM otrs_user_metrics
                WHERE action_time >= ? AND action_time <= ?
                GROUP BY action_type
            """, (start_date, end_date))
            
            totals = {
                'closed': 0,
                'rejected': 0,
                'assigned': 0,
                'commented': 0,
                'total': 0
            }
            
            for row in cursor.fetchall():
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
    
    # ===== Web Users (Password) Methods =====
    
    def get_web_user(self, email: str) -> Optional[Dict]:
        """Получает информацию о веб-пользователе."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM web_users WHERE email = ?
            """, (email.lower(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def create_web_user(self, email: str) -> bool:
        """Создаёт нового веб-пользователя (без пароля)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO web_users (email) VALUES (?)
                """, (email.lower(),))
                conn.commit()
                logger.info(f"Created web user: {email}")
                return True
            except sqlite3.IntegrityError:
                # Пользователь уже существует
                return False
    
    def set_web_password(self, email: str, password_hash: str) -> bool:
        """Устанавливает пароль для веб-пользователя."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO web_users (email, password_hash, password_set_at)
                VALUES (?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    password_set_at = excluded.password_set_at
            """, (email.lower(), password_hash, now_msk()))
            conn.commit()
            logger.info(f"Password set for web user: {email}")
            return True
    
    def update_last_login(self, email: str):
        """Обновляет время последнего входа."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE web_users SET last_login = ? WHERE email = ?
            """, (now_msk(), email.lower()))
            conn.commit()
    
    def has_password(self, email: str) -> bool:
        """Проверяет, установлен ли пароль для пользователя."""
        user = self.get_web_user(email.lower())
        return user is not None and user.get('password_hash') is not None
    
    # ===== IP Groups and Devices Management Methods =====
    
    def get_all_servers_grouped(self) -> Dict[str, List[Dict]]:
        """
        Получает все серверы, сгруппированные по группам.
        Возвращает словарь: {group_name: [{'name': ..., 'ip': ...}, ...]}
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name, ip, server_group
                FROM servers
                ORDER BY server_group, name
            """)
            
            groups = {}
            for row in cursor.fetchall():
                group_name = row['server_group']
                if group_name not in groups:
                    groups[group_name] = []
                groups[group_name].append({
                    'name': row['name'],
                    'ip': row['ip']
                })
            
            return groups
    
    def get_all_servers_list(self) -> List[Dict]:
        """
        Получает все серверы в формате списка групп.
        Возвращает список: [{'name': group_name, 'devices': [{'name': ..., 'ip': ...}, ...]}, ...]
        """
        groups_dict = self.get_all_servers_grouped()
        return [
            {
                'name': group_name,
                'devices': devices
            }
            for group_name, devices in groups_dict.items()
        ]
    
    def add_server_group(self, group_name: str) -> Tuple[bool, str]:
        """Добавляет новую группу (создаёт пустую группу)."""
        if not group_name or not group_name.strip():
            return False, "Имя группы не может быть пустым"
        
        # Проверяем, есть ли уже серверы в этой группе
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM servers WHERE server_group = ?
            """, (group_name,))
            row = cursor.fetchone()
            if row and row['count'] > 0:
                return False, "Группа уже существует"
        
        # Группа создаётся автоматически при добавлении первого сервера
        # Но для совместимости с API просто возвращаем успех
        return True, ""
    
    def delete_server_group(self, group_name: str) -> Tuple[bool, str]:
        """Удаляет группу (удаляет все серверы в группе)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Получаем ID серверов в группе
            cursor.execute("""
                SELECT id FROM servers WHERE server_group = ?
            """, (group_name,))
            server_ids = [row['id'] for row in cursor.fetchall()]
            
            if not server_ids:
                return False, "Группа не найдена"
            
            # Удаляем метрики
            cursor.execute("""
                DELETE FROM metrics WHERE server_id IN ({})
            """.format(','.join('?' * len(server_ids))), server_ids)
            
            # Удаляем события
            cursor.execute("""
                DELETE FROM events WHERE server_id IN ({})
            """.format(','.join('?' * len(server_ids))), server_ids)
            
            # Удаляем дневную статистику
            cursor.execute("""
                DELETE FROM daily_stats WHERE server_id IN ({})
            """.format(','.join('?' * len(server_ids))), server_ids)
            
            # Удаляем серверы
            cursor.execute("""
                DELETE FROM servers WHERE server_group = ?
            """, (group_name,))
            
            conn.commit()
            logger.info(f"Deleted server group: {group_name}")
            return True, ""
    
    def update_server_group_name(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        """Изменяет имя группы."""
        if not new_name or not new_name.strip():
            return False, "Имя группы не может быть пустым"
        
        if old_name == new_name:
            return True, ""
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем что группа существует
            cursor.execute("""
                SELECT COUNT(*) as count FROM servers WHERE server_group = ?
            """, (old_name,))
            row = cursor.fetchone()
            if not row or row['count'] == 0:
                return False, "Группа не найдена"
            
            # Проверяем что новое имя не занято
            cursor.execute("""
                SELECT COUNT(*) as count FROM servers WHERE server_group = ?
            """, (new_name,))
            row = cursor.fetchone()
            if row and row['count'] > 0:
                return False, "Группа с таким именем уже существует"
            
            # Обновляем имя группы
            cursor.execute("""
                UPDATE servers SET server_group = ? WHERE server_group = ?
            """, (new_name, old_name))
            
            conn.commit()
            logger.info(f"Renamed server group: {old_name} -> {new_name}")
            return True, ""
    
    def add_server_device(self, group_name: str, device_name: str, device_ip: str) -> Tuple[bool, str]:
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
            server_id = self.get_or_create_server(device_name, device_ip, group_name)
            return True, ""
        except Exception as e:
            logger.error(f"Error adding server device: {e}")
            return False, f"Ошибка при добавлении устройства: {e}"
    
    def update_server_device(self, group_name: str, old_name: str, new_name: str, new_ip: str) -> Tuple[bool, str]:
        """Обновляет устройство."""
        if not new_name or not new_name.strip():
            return False, "Имя устройства не может быть пустым"
        
        if not new_ip or not new_ip.strip():
            return False, "IP-адрес не может быть пустым"
        
        # Валидация IP
        import re
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(pattern, new_ip):
            return False, "Неверный формат IP-адреса"
        
        parts = new_ip.split('.')
        if not all(0 <= int(part) <= 255 for part in parts):
            return False, "Неверный формат IP-адреса"
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем что устройство существует
            cursor.execute("""
                SELECT id FROM servers WHERE name = ? AND server_group = ?
            """, (old_name, group_name))
            row = cursor.fetchone()
            
            if not row:
                return False, "Устройство не найдено"
            
            server_id = row['id']
            
            # Если имя изменилось, проверяем уникальность нового имени в группе
            if old_name != new_name:
                cursor.execute("""
                    SELECT id FROM servers WHERE name = ? AND server_group = ? AND id != ?
                """, (new_name, group_name, server_id))
                if cursor.fetchone():
                    return False, "Устройство с таким именем уже существует в группе"
            
            # Обновляем устройство
            cursor.execute("""
                UPDATE servers SET name = ?, ip = ? WHERE id = ?
            """, (new_name, new_ip, server_id))
            
            conn.commit()
            logger.info(f"Updated server device: {old_name} -> {new_name} ({new_ip})")
            return True, ""
    
    def delete_server_device(self, group_name: str, device_name: str) -> Tuple[bool, str]:
        """Удаляет устройство из группы."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Получаем ID устройства
            cursor.execute("""
                SELECT id FROM servers WHERE name = ? AND server_group = ?
            """, (device_name, group_name))
            row = cursor.fetchone()
            
            if not row:
                return False, "Устройство не найдено"
            
            server_id = row['id']
            
            # Удаляем метрики
            cursor.execute("DELETE FROM metrics WHERE server_id = ?", (server_id,))
            
            # Удаляем события
            cursor.execute("DELETE FROM events WHERE server_id = ?", (server_id,))
            
            # Удаляем дневную статистику
            cursor.execute("DELETE FROM daily_stats WHERE server_id = ?", (server_id,))
            
            # Удаляем сервер
            cursor.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            
            conn.commit()
            logger.info(f"Deleted server device: {device_name} from group {group_name}")
            return True, ""


# Глобальный экземпляр
_db: Optional[MonitorDatabase] = None


def get_db() -> MonitorDatabase:
    """Возвращает экземпляр базы данных."""
    global _db
    if _db is None:
        _db = MonitorDatabase()
    return _db

