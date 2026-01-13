"""
Репозитории для работы с базой данных.
"""

from .employee_repository import EmployeeRepository
from .monitoring_repository import MonitoringRepository
from .otrs_repository import OTRSRepository
from .message_deletion_repository import MessageDeletionRepository
from .ticket_repository import TicketRepository

__all__ = [
    'EmployeeRepository',
    'MonitoringRepository',
    'OTRSRepository',
    'MessageDeletionRepository',
    'TicketRepository',
]
