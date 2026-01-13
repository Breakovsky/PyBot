"""
Скрипт для инициализации настроек в БД.
Заполняет таблицу core.settings значениями из .env или значениями по умолчанию.
"""

import asyncio
import sys
import os
import io
from pathlib import Path
from urllib.parse import quote_plus

# Настройка кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, ValueError):
        pass

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent / "main"))

from dotenv import load_dotenv
from database.connection import init_db_pool, close_db_pool
from config.settings import init_settings
from config.security import get_security_manager


async def init_default_settings():
    """Инициализирует настройки по умолчанию в БД."""
    
    # Загружаем .env если есть
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env from: {env_path}")
    else:
        print("⚠️  .env file not found, using environment variables and defaults")
    
    # Подключаемся к БД
    security = get_security_manager()
    db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    db_user_escaped = quote_plus(db_user)
    if db_password:
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user_escaped}@{db_host}:{db_port}/{db_name}"
    
    db_pool = init_db_pool(dsn, min_size=2, max_size=5)
    await db_pool.initialize()
    
    settings = init_settings(db_pool)
    
    print("\n" + "=" * 60)
    print("Инициализация настроек TBot v2.1")
    print("=" * 60 + "\n")
    
    # Настройки Telegram
    # Используем TELEGRAM_CHAT_ID вместо SUPERCHAT_TOKEN для совместимости
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("SUPERCHAT_TOKEN", "-1")
    telegram_settings = [
        ("TELEGRAM_CHAT_ID", telegram_chat_id, "telegram", "ID группового чата (отрицательное число)"),
        ("EXCEL_TOPIC_ID", os.getenv("EXCEL_TOPIC_ID", "9"), "telegram", "ID топика для поиска сотрудников (Excel)"),
        ("PING_TOPIC_ID", os.getenv("PING_TOPIC_ID", "7"), "telegram", "ID топика для мониторинга серверов"),
        ("BOT_TOPIC_ID", os.getenv("BOT_TOPIC_ID", "5"), "telegram", "ID топика для сообщений бота"),
        ("METRICS_TOPIC_ID", os.getenv("METRICS_TOPIC_ID", "0"), "telegram", "ID топика для метрик мониторинга"),
        ("TASKS_TOPIC_ID", os.getenv("TASKS_TOPIC_ID", "145"), "telegram", "ID топика для заявок OTRS"),
    ]
    
    # Настройки удаления сообщений
    deletion_settings = [
        ("USER_MESSAGE_DELETE_DELAY", os.getenv("USER_MESSAGE_DELETE_DELAY", "30"), "telegram", "Задержка удаления сообщений пользователей (секунды)"),
        ("EXCEL_MESSAGE_DELETE_DELAY", os.getenv("EXCEL_MESSAGE_DELETE_DELAY", "300"), "telegram", "Задержка удаления сообщений в Excel топике (секунды, 5 минут)"),
        ("BOT_MESSAGE_DELETE_DELAY", os.getenv("BOT_MESSAGE_DELETE_DELAY", "600"), "telegram", "Задержка удаления сообщений бота (секунды, 10 минут)"),
        ("ALLOWED_THREADS", os.getenv("ALLOWED_THREADS", "9,7,5,164"), "telegram", "Разрешенные топики для удаления сообщений (через запятую)"),
    ]
    
    # Другие настройки
    other_settings = [
        ("BOT_STARTUP_MESSAGE", os.getenv("BOT_STARTUP_MESSAGE", "🤖 Бот включился и готов к работе!"), "telegram", "Сообщение при запуске бота"),
        ("MONITOR_CHECK_INTERVAL", os.getenv("MONITOR_CHECK_INTERVAL", "30"), "monitoring", "Интервал проверки серверов (секунды)"),
        ("OTRS_CHECK_INTERVAL", os.getenv("OTRS_CHECK_INTERVAL", "60"), "otrs", "Интервал проверки новых тикетов (секунды)"),
    ]
    
    # Настройки OTRS (не секретные)
    # Всегда создаём в БД, чтобы можно было настроить через веб-интерфейс
    # Значения из .env используются только при первом создании
    otrs_url = os.getenv("OTRS_URL", "")
    otrs_username = os.getenv("OTRS_USERNAME", "")
    otrs_webservice = os.getenv("OTRS_WEBSERVICE", "TelegramBot")
    
    otrs_settings = [
        ("OTRS_URL", otrs_url, "otrs", "URL OTRS сервера (например: http://192.168.0.42/otrs). Настраивается через веб-интерфейс."),
        ("OTRS_USERNAME", otrs_username, "otrs", "Логин для OTRS API. Настраивается через веб-интерфейс."),
        ("OTRS_WEBSERVICE", otrs_webservice, "otrs", "Имя Web Service в OTRS. Настраивается через веб-интерфейс."),
    ]
    
    # Настройки SMTP (не секретные)
    # Всегда создаём в БД, чтобы можно было настроить через веб-интерфейс
    # Значения из .env используются только при первом создании
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port_str = os.getenv("SMTP_PORT", "587")
    try:
        smtp_port = int(smtp_port_str) if smtp_port_str else 587
    except ValueError:
        smtp_port = 587
    
    # Для порта 465 используется SSL (не TLS), для 587 - STARTTLS (TLS)
    # Если порт 465, то SMTP_USE_TLS должен быть false
    default_use_tls = "true" if smtp_port != 465 else "false"
    smtp_use_tls = os.getenv("SMTP_USE_TLS", default_use_tls)
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "TBot")
    
    smtp_user = os.getenv("SMTP_USER", "")
    
    smtp_settings = [
        ("SMTP_HOST", smtp_host, "smtp", "SMTP сервер (например: mail.company.ru). Настраивается через веб-интерфейс."),
        ("SMTP_PORT", str(smtp_port), "smtp", "SMTP порт (587 для STARTTLS/TLS, 465 для SSL). Настраивается через веб-интерфейс."),
        ("SMTP_USER", smtp_user, "smtp", "Email для отправки писем (например: bot@company.com). Настраивается через веб-интерфейс."),
        ("SMTP_FROM_NAME", smtp_from_name, "smtp", "Имя отправителя в письмах. Настраивается через веб-интерфейс."),
        ("SMTP_USE_TLS", smtp_use_tls, "smtp", "Использовать STARTTLS/TLS (true для порта 587, false для порта 465/SSL). Настраивается через веб-интерфейс."),
    ]
    
    # Настройки Active Directory (опционально, создаём только если указаны)
    ad_settings = []
    if os.getenv("DOMAIN_SERVER"):
        ad_settings = [
            ("DOMAIN_SERVER", os.getenv("DOMAIN_SERVER", ""), "ad", "IP или FQDN контроллера домена"),
            ("DOMAIN_PORT", os.getenv("DOMAIN_PORT", "389"), "ad", "Порт LDAP (389 для LDAP, 636 для LDAPS)"),
            ("DOMAIN_BASE_DN", os.getenv("DOMAIN_BASE_DN", ""), "ad", "Base DN (например: dc=meb52,dc=local)"),
            ("DOMAIN_BIND_DN", os.getenv("DOMAIN_BIND_DN", ""), "ad", "Bind DN для подключения (может быть пустым)"),
        ]
    
    # Пути к файлам
    # IP_ADDRESSES_PATH не должен быть в .env, только в БД (настраивается через веб-интерфейс)
    file_paths_settings = [
        ("EXCEL_FILE_PATH", os.getenv("EXCEL_FILE_PATH", r"\\fs\it$\6. Наша\1. Общая\3. Общая документация ИТ\ВсеПК.xlsx"), "files", "Путь к Excel файлу с данными сотрудников"),
    ]
    
    # IP_ADDRESSES_PATH создаём только если указан в .env (для миграции со старой версии)
    # В будущем это должно настраиваться только через БД/веб-интерфейс
    if os.getenv("IP_ADDRESSES_PATH"):
        file_paths_settings.append(
            ("IP_ADDRESSES_PATH", os.getenv("IP_ADDRESSES_PATH", r"main\assets\ip_addresses.xml"), "files", "Путь к XML файлу с IP адресами серверов (настраивается через веб-интерфейс)")
        )
    
    # Настройки базы данных (не секретные)
    db_settings = [
        ("DB_HOST", os.getenv("DB_HOST", "localhost"), "database", "Хост PostgreSQL"),
        ("DB_PORT", os.getenv("DB_PORT", "5432"), "database", "Порт PostgreSQL"),
        ("DB_NAME", os.getenv("DB_NAME", "tbot"), "database", "Имя базы данных"),
        ("DB_USER", os.getenv("DB_USER", "tbot"), "database", "Пользователь базы данных"),
        ("DB_POOL_MIN_SIZE", os.getenv("DB_POOL_MIN_SIZE", "5"), "database", "Минимальный размер пула соединений"),
        ("DB_POOL_MAX_SIZE", os.getenv("DB_POOL_MAX_SIZE", "20"), "database", "Максимальный размер пула соединений"),
    ]
    
    all_settings = telegram_settings + deletion_settings + other_settings + otrs_settings + smtp_settings + ad_settings + file_paths_settings + db_settings
    
    updated_count = 0
    created_count = 0
    
    for key, default_value, category, description in all_settings:
        # Проверяем, существует ли уже настройка в БД
        existing = await settings.get(key)
        
        # Получаем значение из .env (если есть), иначе используем default_value
        env_value = os.getenv(key)
        value_to_use = env_value if env_value is not None else default_value
        
        if existing is not None:
            # Настройка уже существует в БД
            if str(existing) != str(value_to_use):
                # Обновляем только если значение из .env отличается от БД
                # ИЛИ если это значение по умолчанию и в .env ничего нет
                if env_value is not None:
                    # Есть значение в .env - обновляем БД
                    await settings.set(key, value_to_use, category=category, description=description, updated_by="init_script")
                    print(f"🔄 Обновлено из .env: {key} = {value_to_use}")
                    updated_count += 1
                else:
                    # Нет значения в .env - оставляем существующее значение в БД
                    print(f"✓  Оставлено без изменений: {key} = {existing} (в .env не указано, используется значение из БД)")
            else:
                print(f"✓  Уже установлено: {key} = {existing}")
        else:
            # Создаём новую настройку (используем значение из .env или default)
            await settings.set(key, value_to_use, category=category, description=description, updated_by="init_script")
            if env_value is not None:
                source = "из .env"
                print(f"➕ Создано ({source}): {key} = {value_to_use}")
            else:
                source = "по умолчанию"
                if value_to_use:
                    print(f"➕ Создано ({source}): {key} = {value_to_use}")
                else:
                    print(f"➕ Создано ({source}): {key} = (пусто - можно настроить через веб-интерфейс)")
            created_count += 1
    
    print("\n" + "=" * 60)
    print(f"Итоги: создано {created_count}, обновлено {updated_count}, всего {len(all_settings)}")
    print("=" * 60)
    
    # Показываем текущие настройки по категориям
    print("\n📋 Текущие настройки:")
    
    print("\n   Telegram:")
    for key, _, _, _ in telegram_settings:
        value = await settings.get(key)
        print(f"      {key}: {value}")
    
    print("\n   OTRS:")
    for key, _, _, _ in otrs_settings:
        value = await settings.get(key)
        if value:
            print(f"      {key}: {value}")
        else:
            print(f"      {key}: (не настроено - можно настроить через веб-интерфейс)")
    
    print("\n   SMTP:")
    for key, _, _, _ in smtp_settings:
        value = await settings.get(key)
        if value:
            print(f"      {key}: {value}")
        else:
            print(f"      {key}: (не настроено - можно настроить через веб-интерфейс)")
    
    if ad_settings:
        print("\n   Active Directory:")
        for key, _, _, _ in ad_settings:
            value = await settings.get(key)
            print(f"      {key}: {value}")
    
    if file_paths_settings:
        print("\n   Файлы:")
        for key, _, _, _ in file_paths_settings:
            value = await settings.get(key)
            print(f"      {key}: {value}")
    
    print("\n   База данных:")
    for key, _, _, _ in db_settings:
        value = await settings.get(key)
        print(f"      {key}: {value}")
    
    await db_pool.close()
    print("\n✅ Настройки инициализированы!")
    print("\n💡 Секретные данные (TOKEN, пароли) остаются в .env или Windows Credential Manager")


if __name__ == "__main__":
    try:
        asyncio.run(init_default_settings())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

