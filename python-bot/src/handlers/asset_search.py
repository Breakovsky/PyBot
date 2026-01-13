"""
Asset Search Handler
Searches employees/assets in PostgreSQL and returns formatted results.
"""

import logging
import re
from typing import Optional, List
from sqlalchemy import select, or_
from aiogram.types import Message

from src.core.database import async_session, Employee

logger = logging.getLogger(__name__)


def is_workstation_query(query: str) -> bool:
    """Check if query is a workstation pattern (WS-123, ws123, etc.)"""
    return bool(re.match(r'^ws[-\s]?\d+', query.lower()))


def is_phone_query(query: str) -> bool:
    """Check if query looks like a phone number"""
    # Remove common separators
    cleaned = re.sub(r'[\s\-\(\)]+', '', query)
    return cleaned.isdigit() and len(cleaned) >= 3


async def search_employees(query: str, limit: int = 10) -> List[Employee]:
    """
    Search employees by multiple criteria.
    
    Priority:
    1. Exact workstation match (WS-101)
    2. Exact phone match
    3. Full name contains (case-insensitive)
    4. AD login contains
    5. Email contains
    """
    query = query.strip()
    
    if not query:
        return []
    
    async with async_session() as session:
        # Build search filters based on query type
        filters = []
        
        if is_workstation_query(query):
            # Extract WS number (e.g., "WS-101" or "ws 101" -> "WS-101")
            ws_number = re.sub(r'[^\d]+', '', query)
            ws_patterns = [
                f"WS-{ws_number}",
                f"WS{ws_number}",
                f"ws-{ws_number}",
                f"ws{ws_number}",
                ws_number  # Just the number
            ]
            for pattern in ws_patterns:
                filters.append(Employee.workstation.ilike(f"%{pattern}%"))
        
        elif is_phone_query(query):
            # Phone search
            cleaned_phone = re.sub(r'[\s\-\(\)]+', '', query)
            filters.append(Employee.phone.ilike(f"%{cleaned_phone}%"))
        
        else:
            # General text search (name, ad_login, email)
            search_pattern = f"%{query}%"
            filters.append(Employee.full_name.ilike(search_pattern))
            filters.append(Employee.ad_login.ilike(search_pattern))
            filters.append(Employee.email.ilike(search_pattern))
            filters.append(Employee.department.ilike(search_pattern))
        
        # Execute query
        stmt = select(Employee).where(
            Employee.is_active == True,  # Only active employees
            or_(*filters)
        ).limit(limit)
        
        result = await session.execute(stmt)
        employees = result.scalars().all()
        
        logger.info(f"Search '{query}' returned {len(employees)} results")
        return employees


def format_employee_card(employee: Employee) -> str:
    """
    Format employee data as a nice card.
    
    Returns HTML-formatted string for Telegram.
    """
    lines = []
    lines.append("<b>🔍 Employee Information</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    
    # Name (bold)
    if employee.full_name:
        lines.append(f"<b>👤 ФИО:</b> {employee.full_name}")
    
    # Department
    if employee.department:
        lines.append(f"<b>🏢 Подразделение:</b> {employee.department}")
    
    # Workstation
    if employee.workstation:
        lines.append(f"<b>🖥 WorkStation:</b> <code>{employee.workstation}</code>")
    
    # Phone
    if employee.phone:
        lines.append(f"<b>📞 Телефон:</b> <code>{employee.phone}</code>")
    
    # AD Login
    if employee.ad_login:
        lines.append(f"<b>🔑 AD Login:</b> <code>{employee.ad_login}</code>")
    
    # Email
    if employee.email:
        lines.append(f"<b>📧 Email:</b> {employee.email}")
    
    # Notes
    if employee.notes:
        lines.append(f"<b>📝 Примечание:</b> {employee.notes}")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    
    return "\n".join(lines)


def format_multiple_results(employees: List[Employee], query: str) -> str:
    """
    Format multiple search results as a compact list.
    """
    if not employees:
        return f"❌ Не найдено результатов для запроса: <b>{query}</b>"
    
    if len(employees) == 1:
        # Single result - show full card
        return format_employee_card(employees[0])
    
    # Multiple results - show compact list
    lines = []
    lines.append(f"<b>🔍 Найдено {len(employees)} результатов</b>")
    lines.append(f"Запрос: <code>{query}</code>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    
    for idx, emp in enumerate(employees, 1):
        # Compact format: #. Name | WS | Phone
        parts = [f"{idx}. <b>{emp.full_name or 'N/A'}</b>"]
        
        if emp.workstation:
            parts.append(f"WS: <code>{emp.workstation}</code>")
        if emp.phone:
            parts.append(f"📞 <code>{emp.phone}</code>")
        if emp.department:
            parts.append(f"({emp.department})")
        
        lines.append(" | ".join(parts))
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>Для детальной информации используйте точный WS номер</i>")
    
    return "\n".join(lines)


async def handle_asset_search(message: Message, query: str):
    """
    Main handler for asset search queries.
    Called when user sends WS-* or text query.
    """
    try:
        # Search in database
        employees = await search_employees(query, limit=10)
        
        # Format and send response
        response = format_multiple_results(employees, query)
        await message.reply(response, parse_mode="HTML")
        
        logger.info(f"Asset search by {message.from_user.id}: '{query}' -> {len(employees)} results")
        
    except Exception as e:
        logger.error(f"Error in asset search: {e}", exc_info=True)
        await message.reply(
            "❌ Произошла ошибка при поиске. Попробуйте позже.",
            parse_mode="HTML"
        )

