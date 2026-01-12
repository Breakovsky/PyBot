from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message
from sqlalchemy import select
from .database import async_session, TelegramUser, UserRole

class RoleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        # Get required role from handler flags
        # Usage: @dp.message(..., flags={"role": UserRole.ADMIN})
        required_role = data.get("handler", {}).flags.get("role")
        
        if not required_role:
            return await handler(event, data)

        user_id = event.from_user.id
        username = event.from_user.username

        async with async_session() as session:
            # Fetch user
            result = await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == user_id))
            user = result.scalar_one_or_none()

            # Auto-register if new (Default role USER)
            if not user:
                user = TelegramUser(telegram_id=user_id, username=username, role=UserRole.USER)
                session.add(user)
                await session.commit()
                # If Creator role is needed for bootstrap, can be done via SQL or secret command
            
            # Check Role
            if user.role >= required_role:
                # Inject user into handler
                data["user"] = user
                return await handler(event, data)
            else:
                await event.reply(f"⛔ Access Denied.\nRequired: {required_role.value}\nYour Role: {user.role.value}")
                return

