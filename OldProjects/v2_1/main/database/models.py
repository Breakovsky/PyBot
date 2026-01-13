"""
SQLAlchemy 2.0 модели для базы данных PostgreSQL.
Объединённая схема из v2_0 и v2_1 с использованием современных фич Python 3.14.
"""

from typing import Optional, Annotated
from datetime import datetime
from sqlalchemy import (
    String, Integer, Text, Boolean, DateTime, Date, ForeignKey, 
    Numeric, JSON, Index, CheckConstraint, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

# Type aliases для читаемости
IntPK = Annotated[int, mapped_column(primary_key=True)]
Str255 = Annotated[str, mapped_column(String(255))]
Str50 = Annotated[str, mapped_column(String(50))]
Str45 = Annotated[str, mapped_column(String(45))]  # IP addresses
OptionalStr = Annotated[Optional[str], mapped_column(nullable=True)]
OptionalInt = Annotated[Optional[int], mapped_column(nullable=True)]


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


def init_models():
    """Инициализация моделей."""
    pass


# ============================================
# CORE SCHEMA
# ============================================

class Setting(Base):
    """Настройки системы."""
    __tablename__ = 'settings'
    __table_args__ = {'schema': 'core'}
    
    key: Mapped[Str255] = mapped_column(primary_key=True)
    value: Mapped[OptionalStr] = mapped_column(Text)
    category: Mapped[Str50] = mapped_column(index=True)
    is_secret: Mapped[bool] = mapped_column(default=False)
    description: Mapped[OptionalStr] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    updated_by: Mapped[OptionalStr]


class User(Base):
    """Пользователи системы (веб-панель)."""
    __tablename__ = 'users'
    __table_args__ = {'schema': 'core'}
    
    id: Mapped[IntPK]
    email: Mapped[Str255] = mapped_column(unique=True, index=True)
    password_hash: Mapped[OptionalStr]
    full_name: Mapped[OptionalStr]
    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login: Mapped[Optional[datetime]]
    password_set_at: Mapped[Optional[datetime]]
    
    # Relationships
    telegram_user: Mapped[Optional['TelegramUser']] = relationship(
        back_populates='user', uselist=False
    )
    audit_logs: Mapped[list['AuditLog']] = relationship(back_populates='user')


class AuditLog(Base):
    """Аудит действий пользователей."""
    __tablename__ = 'audit_log'
    __table_args__ = (
        {'schema': 'core'},
        Index('idx_audit_user_time', 'user_id', 'created_at'),
        Index('idx_audit_action_time', 'action_type', 'created_at'),
    )
    
    id: Mapped[IntPK]
    user_id: Mapped[OptionalInt] = mapped_column(
        ForeignKey('core.users.id'), index=True
    )
    user_email: Mapped[OptionalStr] = mapped_column(index=True)
    action_type: Mapped[Str50] = mapped_column(index=True)
    resource_type: Mapped[OptionalStr] = mapped_column(index=True)
    resource_id: Mapped[OptionalStr] = mapped_column(index=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[OptionalStr]
    user_agent: Mapped[OptionalStr] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), index=True
    )
    
    # Relationships
    user: Mapped[Optional['User']] = relationship(back_populates='audit_logs')


# ============================================
# TELEGRAM SCHEMA
# ============================================

class TelegramUser(Base):
    """Пользователи Telegram."""
    __tablename__ = 'telegram_users'
    __table_args__ = {'schema': 'telegram'}
    
    id: Mapped[IntPK]
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    telegram_username: Mapped[OptionalStr]
    full_name: Mapped[OptionalStr]
    user_id: Mapped[OptionalInt] = mapped_column(ForeignKey('core.users.id'))
    otrs_email: Mapped[OptionalStr]
    verified_at: Mapped[Optional[datetime]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    
    # Relationships
    user: Mapped[Optional['User']] = relationship(back_populates='telegram_user')
    otrs_user: Mapped[Optional['OTRSUser']] = relationship(back_populates='telegram_user')
    otrs_metrics: Mapped[list['OTRSMetric']] = relationship(back_populates='telegram_user')
    private_tickets: Mapped[list['UserPrivateTicket']] = relationship(back_populates='telegram_user')


class TelegramChat(Base):
    """Чаты и топики Telegram."""
    __tablename__ = 'telegram_chats'
    __table_args__ = (
        {'schema': 'telegram'},
        Index('idx_chat_topic', 'chat_id', 'topic_id'),
    )
    
    id: Mapped[IntPK]
    chat_id: Mapped[int] = mapped_column(index=True)
    topic_id: Mapped[OptionalInt] = mapped_column(index=True)
    chat_title: Mapped[OptionalStr]
    topic_title: Mapped[OptionalStr]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )


class TelegramMessage(Base):
    """Сообщения Telegram для персистентности."""
    __tablename__ = 'telegram_messages'
    __table_args__ = (
        {'schema': 'telegram'},
        UniqueConstraint('chat_id', 'topic_id', 'message_type', name='uq_message_chat_topic_type'),
    )
    
    id: Mapped[IntPK]
    chat_id: Mapped[int] = mapped_column(index=True)
    topic_id: Mapped[OptionalInt] = mapped_column(index=True)
    message_type: Mapped[Str50]
    message_id: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )


class VerificationCode(Base):
    """Коды верификации для авторизации через email."""
    __tablename__ = 'verification_codes'
    __table_args__ = (
        {'schema': 'telegram'},
        Index('idx_verification_telegram_id', 'telegram_id'),
        Index('idx_verification_expires_at', 'expires_at'),
    )
    
    id: Mapped[IntPK]
    telegram_id: Mapped[int] = mapped_column(unique=True)
    email: Mapped[Str255]
    code: Mapped[str] = mapped_column(String(6))
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PendingDeletion(Base):
    """Очередь удаления сообщений."""
    __tablename__ = 'pending_deletions'
    __table_args__ = (
        {'schema': 'telegram'},
        UniqueConstraint('chat_id', 'message_id', name='uq_pending_deletion_chat_message'),
    )
    
    id: Mapped[IntPK]
    chat_id: Mapped[int] = mapped_column(index=True)
    topic_id: Mapped[OptionalInt] = mapped_column(index=True)
    message_id: Mapped[int]
    delete_after: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ============================================
# EMPLOYEES SCHEMA
# ============================================

class Department(Base):
    """Подразделения."""
    __tablename__ = 'departments'
    __table_args__ = {'schema': 'employees'}
    
    id: Mapped[IntPK]
    name: Mapped[Str255] = mapped_column(unique=True)
    description: Mapped[OptionalStr] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationships
    employees: Mapped[list['Employee']] = relationship(back_populates='department')


class Workstation(Base):
    """Рабочие станции."""
    __tablename__ = 'workstations'
    __table_args__ = (
        {'schema': 'employees'},
        Index('idx_workstations_name', 'name'),
        Index('idx_workstations_ip', 'ip_address'),
    )
    
    id: Mapped[IntPK]
    name: Mapped[Str255] = mapped_column(unique=True)
    ip_address: Mapped[OptionalStr] = mapped_column(index=True)
    description: Mapped[OptionalStr] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationships
    employees: Mapped[list['Employee']] = relationship(back_populates='workstation')


class Employee(Base):
    """Сотрудники (данные из Excel)."""
    __tablename__ = 'employees'
    __table_args__ = (
        {'schema': 'employees'},
        Index('idx_employee_name', 'full_name'),
        Index('idx_employee_phone', 'phone'),
        Index('idx_employee_department', 'department_id'),
    )
    
    id: Mapped[IntPK]
    full_name: Mapped[Str255] = mapped_column(index=True)
    department_id: Mapped[OptionalInt] = mapped_column(
        ForeignKey('employees.departments.id'), index=True
    )
    workstation_id: Mapped[OptionalInt] = mapped_column(
        ForeignKey('employees.workstations.id'), index=True
    )
    phone: Mapped[OptionalStr] = mapped_column(String(50), index=True)
    ad_account: Mapped[OptionalStr]  # Email/AD account
    notes: Mapped[OptionalStr] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    updated_by: Mapped[OptionalStr]
    
    # Relationships
    department: Mapped[Optional['Department']] = relationship(back_populates='employees')
    workstation: Mapped[Optional['Workstation']] = relationship(back_populates='employees')


# ============================================
# MONITORING SCHEMA
# ============================================

class ServerGroup(Base):
    """Группы серверов."""
    __tablename__ = 'server_groups'
    __table_args__ = {'schema': 'monitoring'}
    
    id: Mapped[IntPK]
    name: Mapped[Str255] = mapped_column(unique=True)
    description: Mapped[OptionalStr] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationships
    servers: Mapped[list['Server']] = relationship(back_populates='server_group')


class Server(Base):
    """Серверы для мониторинга."""
    __tablename__ = 'servers'
    __table_args__ = (
        {'schema': 'monitoring'},
        UniqueConstraint('server_group_id', 'name', name='uq_server_group_name'),
        Index('idx_servers_name', 'name'),
        Index('idx_servers_ip', 'ip_address'),
        Index('idx_servers_group', 'server_group_id'),
    )
    
    id: Mapped[IntPK]
    name: Mapped[Str255] = mapped_column(index=True)
    ip_address: Mapped[Str45] = mapped_column(index=True)
    server_group_id: Mapped[int] = mapped_column(
        ForeignKey('monitoring.server_groups.id'), index=True
    )
    first_seen: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(server_default=func.now())
    
    # Relationships
    server_group: Mapped['ServerGroup'] = relationship(back_populates='servers')
    events: Mapped[list['ServerEvent']] = relationship(back_populates='server')
    metrics: Mapped[Optional['ServerMetric']] = relationship(
        back_populates='server', uselist=False
    )
    daily_stats: Mapped[list['DailyStat']] = relationship(back_populates='server')


class ServerEvent(Base):
    """События серверов (UP/DOWN)."""
    __tablename__ = 'server_events'
    __table_args__ = (
        {'schema': 'monitoring'},
        CheckConstraint("event_type IN ('UP', 'DOWN')", name='chk_event_type'),
        Index('idx_event_server_id', 'server_id'),
        Index('idx_event_time', 'event_time'),
        Index('idx_event_server_time', 'server_id', 'event_time'),
    )
    
    id: Mapped[IntPK]
    server_id: Mapped[int] = mapped_column(
        ForeignKey('monitoring.servers.id'), index=True
    )
    event_type: Mapped[str] = mapped_column(String(10))  # 'UP' or 'DOWN'
    event_time: Mapped[datetime] = mapped_column(
        server_default=func.now(), index=True
    )
    duration_seconds: Mapped[OptionalInt]
    
    # Relationships
    server: Mapped['Server'] = relationship(back_populates='events')


class ServerMetric(Base):
    """Агрегированные метрики серверов."""
    __tablename__ = 'server_metrics'
    __table_args__ = (
        {'schema': 'monitoring'},
        CheckConstraint("last_status IN ('UP', 'DOWN', 'UNKNOWN')", name='chk_last_status'),
    )
    
    id: Mapped[IntPK]
    server_id: Mapped[int] = mapped_column(
        ForeignKey('monitoring.servers.id'), unique=True
    )
    total_uptime_seconds: Mapped[int] = mapped_column(default=0)
    total_downtime_seconds: Mapped[int] = mapped_column(default=0)
    downtime_count: Mapped[int] = mapped_column(default=0)
    longest_downtime_seconds: Mapped[int] = mapped_column(default=0)
    last_status: Mapped[str] = mapped_column(String(10), default='UNKNOWN')
    last_status_change: Mapped[Optional[datetime]]
    
    # Relationships
    server: Mapped['Server'] = relationship(back_populates='metrics')


class DailyStat(Base):
    """Дневная статистика серверов."""
    __tablename__ = 'daily_stats'
    __table_args__ = (
        {'schema': 'monitoring'},
        UniqueConstraint('server_id', 'date', name='uq_daily_stat_server_date'),
        Index('idx_daily_stat_date', 'date'),
    )
    
    id: Mapped[IntPK]
    server_id: Mapped[int] = mapped_column(
        ForeignKey('monitoring.servers.id'), index=True
    )
    date: Mapped[Date]
    uptime_seconds: Mapped[int] = mapped_column(default=0)
    downtime_seconds: Mapped[int] = mapped_column(default=0)
    downtime_count: Mapped[int] = mapped_column(default=0)
    
    # Relationships
    server: Mapped['Server'] = relationship(back_populates='daily_stats')


# ============================================
# OTRS SCHEMA
# ============================================

class OTRSUser(Base):
    """Авторизованные пользователи OTRS."""
    __tablename__ = 'otrs_users'
    __table_args__ = (
        {'schema': 'otrs'},
        Index('idx_otrs_users_email', 'otrs_email'),
    )
    
    id: Mapped[IntPK]
    telegram_user_id: Mapped[int] = mapped_column(
        ForeignKey('telegram.telegram_users.id'), unique=True
    )
    otrs_email: Mapped[Str255] = mapped_column(index=True)
    otrs_username: Mapped[OptionalStr]
    verified_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    
    # Relationships
    telegram_user: Mapped['TelegramUser'] = relationship(back_populates='otrs_user')


class OTRSTicket(Base):
    """Тикеты OTRS."""
    __tablename__ = 'otrs_tickets'
    __table_args__ = (
        {'schema': 'otrs'},
        Index('idx_otrs_tickets_id', 'ticket_id'),
        Index('idx_otrs_tickets_number', 'ticket_number'),
    )
    
    id: Mapped[IntPK]
    ticket_id: Mapped[int] = mapped_column(unique=True, index=True)
    ticket_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[OptionalStr] = mapped_column(String(500))
    state: Mapped[OptionalStr] = mapped_column(String(50))
    priority: Mapped[OptionalInt]
    created_at: Mapped[Optional[datetime]]
    updated_at: Mapped[Optional[datetime]]
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    
    # Relationships
    ticket_messages: Mapped[list['OTRSTicketMessage']] = relationship(back_populates='ticket')
    otrs_metrics: Mapped[list['OTRSMetric']] = relationship(back_populates='ticket')
    private_tickets: Mapped[list['UserPrivateTicket']] = relationship(back_populates='ticket')


class OTRSTicketMessage(Base):
    """Отправленные тикеты в чаты/топики."""
    __tablename__ = 'otrs_ticket_messages'
    __table_args__ = (
        {'schema': 'otrs'},
        UniqueConstraint('ticket_id', 'chat_id', 'topic_id', name='uq_ticket_chat_topic'),
        Index('idx_ticket_message_chat_topic', 'chat_id', 'topic_id'),
    )
    
    id: Mapped[IntPK]
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('otrs.otrs_tickets.id'), index=True
    )
    ticket_number: Mapped[str] = mapped_column(String(50))
    message_id: Mapped[int]
    chat_id: Mapped[int] = mapped_column(index=True)
    topic_id: Mapped[OptionalInt] = mapped_column(index=True)
    ticket_state: Mapped[OptionalStr] = mapped_column(String(50))
    sent_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationships
    ticket: Mapped['OTRSTicket'] = relationship(back_populates='ticket_messages')


class UserPrivateTicket(Base):
    """Личные сообщения с тикетами (дублирование в ЛС)."""
    __tablename__ = 'user_private_tickets'
    __table_args__ = (
        {'schema': 'otrs'},
        UniqueConstraint('telegram_user_id', 'ticket_id', name='uq_user_private_ticket'),
        Index('idx_private_ticket_user', 'telegram_user_id'),
        Index('idx_private_ticket_ticket', 'ticket_id'),
    )
    
    id: Mapped[IntPK]
    telegram_user_id: Mapped[int] = mapped_column(
        ForeignKey('telegram.telegram_users.id'), index=True
    )
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('otrs.otrs_tickets.id'), index=True
    )
    ticket_number: Mapped[str] = mapped_column(String(50))
    message_id: Mapped[int]
    assigned_at: Mapped[datetime] = mapped_column(server_default=func.now())
    
    # Relationships
    telegram_user: Mapped['TelegramUser'] = relationship(back_populates='private_tickets')
    ticket: Mapped['OTRSTicket'] = relationship(back_populates='private_tickets')


class OTRSMetric(Base):
    """Метрики действий пользователей с тикетами."""
    __tablename__ = 'otrs_metrics'
    __table_args__ = (
        {'schema': 'otrs'},
        CheckConstraint(
            "action_type IN ('closed', 'rejected', 'assigned', 'commented')",
            name='chk_action_type'
        ),
        Index('idx_otrs_metrics_user_id', 'telegram_user_id'),
        Index('idx_otrs_metrics_action_time', 'action_time'),
        Index('idx_otrs_metrics_user_action_time', 'telegram_user_id', 'action_type', 'action_time'),
    )
    
    id: Mapped[IntPK]
    telegram_user_id: Mapped[int] = mapped_column(
        ForeignKey('telegram.telegram_users.id'), index=True
    )
    action_type: Mapped[Str50]  # 'closed', 'rejected', 'assigned', 'commented'
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('otrs.otrs_tickets.id'), index=True
    )
    ticket_number: Mapped[OptionalStr] = mapped_column(String(50))
    ticket_title: Mapped[OptionalStr] = mapped_column(String(500))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    action_time: Mapped[datetime] = mapped_column(
        server_default=func.now(), index=True
    )
    
    # Relationships
    telegram_user: Mapped['TelegramUser'] = relationship(back_populates='otrs_metrics')
    ticket: Mapped['OTRSTicket'] = relationship(back_populates='otrs_metrics')


# ============================================
# CLUSTER SCHEMA
# ============================================

class ClusterNode(Base):
    """Узлы кластера."""
    __tablename__ = 'cluster_nodes'
    __table_args__ = (
        {'schema': 'cluster'},
        Index('idx_cluster_nodes_node_id', 'node_id'),
        Index('idx_cluster_nodes_active', 'is_active'),
    )
    
    id: Mapped[IntPK]
    node_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    node_type: Mapped[OptionalStr] = mapped_column(String(50))  # 'bot', 'web', 'worker'
    hostname: Mapped[OptionalStr]
    ip_address: Mapped[OptionalStr]
    is_active: Mapped[bool] = mapped_column(default=True)
    is_leader: Mapped[bool] = mapped_column(default=False)
    last_heartbeat: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ClusterLock(Base):
    """Блокировки для координации задач."""
    __tablename__ = 'cluster_locks'
    __table_args__ = (
        {'schema': 'cluster'},
        Index('idx_cluster_locks_name', 'lock_name'),
        Index('idx_cluster_locks_expires', 'expires_at'),
    )
    
    id: Mapped[IntPK]
    lock_name: Mapped[Str255] = mapped_column(unique=True, index=True)
    node_id: Mapped[str] = mapped_column(String(100))
    acquired_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)


# ============================================
# BACKUPS SCHEMA
# ============================================

class EmployeeSnapshot(Base):
    """Снапшоты сотрудников (версии)."""
    __tablename__ = 'employee_snapshots'
    __table_args__ = (
        {'schema': 'backups'},
        Index('idx_snapshot_created_at', 'created_at'),
        Index('idx_snapshot_type', 'snapshot_type'),
    )
    
    id: Mapped[IntPK]
    snapshot_name: Mapped[Str255]
    snapshot_type: Mapped[Str50]  # 'manual', 'auto', 'create', 'update', 'delete'
    employees_data: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[Str255]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    notes: Mapped[OptionalStr] = mapped_column(Text)


# ============================================
# ACTIVE DIRECTORY SCHEMA (опционально)
# ============================================

class ADUser(Base):
    """Пользователи из Active Directory (синхронизация)."""
    __tablename__ = 'ad_users'
    __table_args__ = {'schema': 'core'}
    
    email: Mapped[Str255] = mapped_column(primary_key=True)
    full_name: Mapped[OptionalStr]
    first_name: Mapped[OptionalStr]
    last_name: Mapped[OptionalStr]
    is_active: Mapped[bool] = mapped_column(default=True)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())
