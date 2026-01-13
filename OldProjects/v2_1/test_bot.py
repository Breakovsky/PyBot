"""
Тестовый скрипт для проверки работоспособности бота v2.1
"""

import asyncio
import sys
import os
import logging
import io
from pathlib import Path

# Настройка кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, ValueError):
        pass

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent / "main"))

from utils.logger import setup_logger
from database.connection import init_db_pool, close_db_pool
from config.settings import init_settings
from config.security import get_security_manager
from handlers.auth_handler import AuthHandler
from handlers.employee_search import EmployeeSearchHandler
from handlers.otrs_handler import OTRSHandler
from database.repositories.employee_repository import EmployeeRepository


async def test_database_connection():
    """Тест подключения к БД."""
    print("=" * 60)
    print("Тест 1: Подключение к базе данных")
    print("=" * 60)
    
    try:
        import os
        from urllib.parse import quote_plus
        
        security = get_security_manager()
        db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
        
        if not db_password:
            print("❌ DB_PASSWORD не найден в Credential Manager или переменных окружения")
            return False
        
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "tbot")
        db_user = os.getenv("DB_USER", "tbot")
        
        db_user_escaped = quote_plus(db_user)
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
        
        db_pool = init_db_pool(dsn, min_size=2, max_size=5)
        await db_pool.initialize()
        
        # Тестовый запрос
        async with db_pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            if result == 1:
                print("✅ Подключение к БД успешно")
                # Закрываем пул с таймаутом
                try:
                    await asyncio.wait_for(db_pool.close(), timeout=5.0)
                except asyncio.TimeoutError:
                    print("⚠️ Таймаут при закрытии пула (это нормально для тестов)")
                return True
            else:
                print("❌ Неожиданный результат запроса")
                try:
                    await asyncio.wait_for(db_pool.close(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return False
                
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False


async def test_settings():
    """Тест инициализации настроек."""
    print("\n" + "=" * 60)
    print("Тест 2: Инициализация настроек")
    print("=" * 60)
    
    try:
        import os
        from urllib.parse import quote_plus
        
        security = get_security_manager()
        db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
        
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "tbot")
        db_user = os.getenv("DB_USER", "tbot")
        
        db_user_escaped = quote_plus(db_user)
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
        
        db_pool = init_db_pool(dsn, min_size=2, max_size=5)
        await db_pool.initialize()
        
        init_settings(db_pool)
        print("✅ Настройки инициализированы")
        
        # Закрываем пул с таймаутом
        try:
            await asyncio.wait_for(db_pool.close(), timeout=5.0)
        except asyncio.TimeoutError:
            print("⚠️ Таймаут при закрытии пула (это нормально для тестов)")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка инициализации настроек: {e}")
        return False


async def test_employee_repository():
    """Тест репозитория сотрудников."""
    print("\n" + "=" * 60)
    print("Тест 3: Репозиторий сотрудников")
    print("=" * 60)
    
    try:
        import os
        from urllib.parse import quote_plus
        
        security = get_security_manager()
        db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
        
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "tbot")
        db_user = os.getenv("DB_USER", "tbot")
        
        db_user_escaped = quote_plus(db_user)
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
        
        db_pool = init_db_pool(dsn, min_size=2, max_size=5)
        await db_pool.initialize()
        
        repo = EmployeeRepository(db_pool)
        
        # Тест поиска (даже если нет данных)
        results = await repo.search_by_name("test")
        print(f"✅ Поиск сотрудников работает (найдено: {len(results)})")
        
        # Закрываем пул с таймаутом
        try:
            await asyncio.wait_for(db_pool.close(), timeout=5.0)
        except asyncio.TimeoutError:
            print("⚠️ Таймаут при закрытии пула (это нормально для тестов)")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка работы с репозиторием: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_security_manager():
    """Тест Security Manager."""
    print("\n" + "=" * 60)
    print("Тест 4: Security Manager (Windows Credential Manager)")
    print("=" * 60)
    
    try:
        security = get_security_manager()
        
        # Проверяем наличие токена
        token = security.get_secret("TOKEN")
        if token:
            print(f"✅ TOKEN найден (длина: {len(token)} символов)")
        else:
            print("⚠️ TOKEN не найден в Credential Manager")
        
        # Проверяем наличие SUPERCHAT_TOKEN
        chat_id = security.get_secret("SUPERCHAT_TOKEN")
        if chat_id:
            print(f"✅ SUPERCHAT_TOKEN найден: {chat_id}")
        else:
            print("⚠️ SUPERCHAT_TOKEN не найден в Credential Manager")
        
        # Проверяем наличие DB_PASSWORD
        db_password = security.get_secret("DB_PASSWORD")
        if db_password:
            print(f"✅ DB_PASSWORD найден (длина: {len(db_password)} символов)")
        else:
            print("⚠️ DB_PASSWORD не найден в Credential Manager")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка работы с Security Manager: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_handlers():
    """Тест инициализации обработчиков."""
    print("\n" + "=" * 60)
    print("Тест 5: Инициализация обработчиков")
    print("=" * 60)
    
    try:
        import os
        from urllib.parse import quote_plus
        
        security = get_security_manager()
        db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
        
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "tbot")
        db_user = os.getenv("DB_USER", "tbot")
        
        db_user_escaped = quote_plus(db_user)
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
        
        db_pool = init_db_pool(dsn, min_size=2, max_size=5)
        await db_pool.initialize()
        
        # Создаём фиктивный бот для тестов
        from aiogram import Bot
        from aiogram.client.bot import DefaultBotProperties
        from aiogram.enums import ParseMode
        
        # Используем фиктивный токен для инициализации
        bot = Bot("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        
        # Тестируем создание обработчиков
        auth_handler = AuthHandler(db_pool, bot)
        print("✅ AuthHandler создан")
        
        employee_handler = EmployeeSearchHandler(db_pool)
        print("✅ EmployeeSearchHandler создан")
        
        otrs_handler = OTRSHandler(db_pool, bot)
        print("✅ OTRSHandler создан")
        
        await bot.session.close()
        # Закрываем пул с таймаутом
        try:
            await asyncio.wait_for(db_pool.close(), timeout=5.0)
        except asyncio.TimeoutError:
            print("⚠️ Таймаут при закрытии пула (это нормально для тестов)")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания обработчиков: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Главная функция тестирования."""
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ TBot v2.1")
    print("=" * 60 + "\n")
    
    # Настраиваем логирование (минимальное для тестов)
    logging.basicConfig(level=logging.WARNING)  # Только ошибки
    
    results = []
    
    # Запускаем тесты
    results.append(("Подключение к БД", await test_database_connection()))
    results.append(("Инициализация настроек", await test_settings()))
    results.append(("Репозиторий сотрудников", await test_employee_repository()))
    results.append(("Security Manager", await test_security_manager()))
    results.append(("Обработчики", await test_handlers()))
    
    # Выводим итоги
    print("\n" + "=" * 60)
    print("ИТОГИ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nПройдено: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 Все тесты пройдены! Бот готов к запуску.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} тест(ов) не пройдено. Проверьте конфигурацию.")
        return 1


if __name__ == "__main__":
    import logging
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nТестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

