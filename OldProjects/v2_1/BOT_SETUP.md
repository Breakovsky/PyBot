# Настройка Telegram бота v2.1

## Быстрый старт

### 1. Установка зависимостей

```powershell
cd v2_1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Настройка PostgreSQL

1. Установите PostgreSQL 14+
2. Создайте базу данных:
```sql
CREATE DATABASE tbot;
CREATE USER tbot WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE tbot TO tbot;
```

3. Сохраните пароль в Windows Credential Manager:
```powershell
python -c "import keyring; keyring.set_password('TBot', 'DB_PASSWORD', 'your_password')"
```

### 3. Настройка секретов

Сохраните все секреты в Windows Credential Manager:

```powershell
# Токен Telegram бота
python -c "import keyring; keyring.set_password('TBot', 'TOKEN', 'your_bot_token')"

# ID чата (отрицательное число)
python -c "import keyring; keyring.set_password('TBot', 'SUPERCHAT_TOKEN', '-1001234567890')"

# Пароль БД (если еще не сохранили)
python -c "import keyring; keyring.set_password('TBot', 'DB_PASSWORD', 'your_db_password')"
```

### 4. Настройка .env

Создайте файл `.env` в корне проекта:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tbot
DB_USER=tbot

EXCEL_TOPIC_ID=38
PING_TOPIC_ID=40
BOT_TOPIC_ID=42
METRICS_TOPIC_ID=0
TASKS_TOPIC_ID=145

CLUSTER_ENABLED=false
```

### 5. Применение миграций

```powershell
alembic upgrade head
```

### 6. Импорт данных сотрудников (опционально)

Если у вас есть Excel файл с данными сотрудников:

```powershell
python scripts/import_excel_to_db.py
```

### 7. Запуск бота

```powershell
python main/main.py
```

## Структура команд бота

### `/start`
- В личных сообщениях: авторизация или главное меню
- В группах: приветствие

### `/botexec`
- Показывает статус бота
- Кнопка "Показать время работы"

### `/status`
- Показывает статус авторизации (только в личных сообщениях)

### `/mystats`
- Показывает статистику по OTRS (только в личных сообщениях)

## Поиск сотрудников

В топике с ID `EXCEL_TOPIC_ID` бот автоматически обрабатывает сообщения как поисковые запросы:

- **По имени**: "Иванов", "Петр Сергеев"
- **По телефону**: "2583109"
- **По IP**: "192.168.1.1"
- **По рабочей станции**: "ws111", "WS222"

## Troubleshooting

### Бот не запускается

1. Проверьте, что PostgreSQL запущен
2. Проверьте, что все секреты сохранены в Windows Credential Manager
3. Проверьте логи: `logs/tbot.log`

### Ошибка подключения к БД

1. Проверьте, что PostgreSQL запущен
2. Проверьте пароль в Windows Credential Manager
3. Проверьте права доступа пользователя

### Бот не отвечает

1. Проверьте токен бота
2. Проверьте, что бот добавлен в чат
3. Проверьте ID чата (должен быть отрицательным)

## Следующие шаги

После настройки бота можно:
1. Импортировать данные сотрудников
2. Настроить мониторинг серверов
3. Настроить интеграцию с OTRS
4. Включить кластеризацию (если нужно)

