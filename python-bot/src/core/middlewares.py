from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message
from sqlalchemy import select, update
import logging
from .database import async_session, TelegramUser, UserRole

logger = logging.getLogger(__name__)

class RoleMiddleware(BaseMiddleware):
    """
    RBAC Middleware that:
    1. Always ensures user exists in DB
    2. Updates username if changed (but NEVER overwrites role)
    3. Checks role permissions for protected handlers
    4. Injects user object into handler data
    """
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        username = event.from_user.username or "Unknown"

        async with async_session() as session:
            # Fetch user from DB
            result = await session.execute(
                select(TelegramUser).where(TelegramUser.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()

            # Auto-register if new (Default role USER)
            if not user:
                user = TelegramUser(telegram_id=user_id, username=username, role=UserRole.USER)
                session.add(user)
                await session.commit()
                logger.info(f"✅ New user registered: {username} ({user_id}) with role {user.role.value}")
            else:
                # Update username if changed (but PRESERVE existing role)
                if user.username != username:
                    user.username = username
                    await session.commit()
                    logger.debug(f"📝 Updated username for {user_id}: {user.username} → {username}")
                
                # Refresh from DB to ensure we have latest role (critical!)
                await session.refresh(user)
                logger.debug(f"🔍 Role fetched from DB: {user.role.value} for {username} ({user_id})")

            # Get required role from handler flags
            required_role = data.get("handler", {}).flags.get("role")
            
            # If handler requires specific role, check it
            if required_role:
                if user.role >= required_role:
                    # Inject user into handler
                    data["user"] = user
                    logger.debug(f"✅ Access granted: {username} ({user.role.value}) >= {required_role.value}")
                    return await handler(event, data)
                else:
                    logger.warning(f"⛔ Access denied: {username} ({user.role.value}) < {required_role.value}")
                    await event.reply(
                        f"⛔ Access Denied.\n"
                        f"Required: {required_role.value}\n"
                        f"Your Role: {user.role.value}"
                    )
                    return
            
            # No role requirement - inject user anyway for convenience
            data["user"] = user
            return await handler(event, data)

