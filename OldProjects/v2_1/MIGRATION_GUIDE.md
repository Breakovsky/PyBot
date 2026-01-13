# Руководство по миграции с v2_0 на v2_1

## Обзор изменений

v2_1 - это полностью переработанная версия с production-ready архитектурой:

### Основные изменения:

1. **База данных**: SQLite → PostgreSQL
2. **Архитектура БД**: Нормализованная структура с логическим разделением по схемам
3. **Excel данные**: Перенесены в БД с возможностью редактирования через веб
4. **Веб-интерфейс**: Flask → FastAPI
5. **Кластеризация**: Поддержка нескольких серверов
6. **Безопасность**: Секреты в Windows Credential Manager
7. **Конфигурация**: Настройки в БД вместо .env

## Шаги миграции

### 1. Подготовка окружения

#### Установка PostgreSQL

1. Скачайте PostgreSQL 14+ с [postgresql.org](https://www.postgresql.org/download/windows/)
2. Установите как Windows Service
3. Создайте базу данных:
```sql
CREATE DATABASE tbot;
CREATE USER tbot WITH PASSWORD 'P@SSWORD';
GRANT ALL PRIVILEGES ON DATABASE tbot TO tbot;
```

#### Установка Redis/Memurai (для кластеризации)

1. Скачайте Memurai с [memurai.com](https://www.memurai.com/)
2. Или используйте Redis для Windows
3. Установите как Windows Service

### 2. Установка зависимостей

```powershell
cd v2_1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Настройка секретов

#### Windows Credential Manager

Используйте скрипт для сохранения секретов:

```powershell
python scripts/setup_secrets.py
```

Или вручную через PowerShell:

```powershell
# Установить keyring
pip install keyring

# Сохранить секреты
python -c "import keyring; keyring.set_password('TBot', 'DB_PASSWORD', 'your_db_password')"
python -c "import keyring; keyring.set_password('TBot', 'TOKEN', 'your_telegram_token')"
python -c "import keyring; keyring.set_password('TBot', 'SUPERCHAT_TOKEN', 'your_chat_id')"
# ... и т.д.
```

### 4. Применение миграций БД

```powershell
# Настроить .env с параметрами БД
# Затем применить миграции
alembic upgrade head
```

### 5. Импорт данных из SQLite (если нужно)

```powershell
python scripts/migrate_from_sqlite.py
```

### 6. Импорт данных из Excel

```powershell
python scripts/import_excel_to_db.py
```

Этот скрипт:
- Читает Excel файл
- Создает подразделения
- Создает рабочие станции
- Создает сотрудников
- Связывает все данные

### 7. Настройка конфигурации

Настройки теперь хранятся в БД. Используйте веб-интерфейс или скрипт:

```powershell
python scripts/setup_settings.py
```

### 8. Запуск

```powershell
python main/main.py
```

## Структура данных

### Схемы PostgreSQL

1. **core** - основные таблицы (settings, users, audit_log)
2. **telegram** - Telegram данные
3. **employees** - данные сотрудников (бывший Excel)
4. **monitoring** - мониторинг серверов
5. **otrs** - OTRS интеграция
6. **cluster** - координация кластера

### Маппинг Excel → БД

| Excel колонка | БД таблица | Поле |
|---------------|-----------|------|
| ФИО | employees.employees | full_name |
| Подразделение | employees.departments | name |
| WorkStation | employees.workstations | name |
| Телефон | employees.employees | phone |
| AD | employees.employees | ad_account |
| Примечание | employees.employees | notes |

## Кластеризация

### Настройка для 2 серверов

**Сервер 1:**
```env
CLUSTER_NODE_ID=node1
CLUSTER_NODE_TYPE=bot
CLUSTER_ENABLED=true
```

**Сервер 2:**
```env
CLUSTER_NODE_ID=node2
CLUSTER_NODE_TYPE=bot
CLUSTER_ENABLED=true
```

Оба сервера подключаются к одной БД и Redis.

### Leader Election

- Только один узел выполняет scheduled задачи (мониторинг, OTRS)
- Автоматический failover при падении лидера
- Heartbeat каждые 30 секунд

## Веб-интерфейс

Доступен по адресу: `http://localhost:8000/admin`

### Новые возможности:

1. **Управление сотрудниками** - CRUD операции вместо Excel
2. **Управление серверами** - через веб-интерфейс
3. **Настройки системы** - редактирование в реальном времени
4. **Метрики и аналитика** - расширенные дашборды
5. **Audit log** - просмотр всех действий

## Обратная совместимость

- API методов сохранена где возможно
- Постепенная миграция возможна
- Старые данные можно импортировать

## Troubleshooting

### Проблемы с подключением к БД

1. Проверьте, что PostgreSQL запущен
2. Проверьте права доступа пользователя
3. Проверьте пароль в Windows Credential Manager

### Проблемы с Redis

1. Проверьте, что Redis/Memurai запущен
2. Проверьте подключение: `redis-cli ping`
3. Кластеризация будет отключена, если Redis недоступен

### Проблемы с миграциями

1. Проверьте подключение к БД в `alembic.ini`
2. Проверьте, что все схемы созданы
3. Проверьте логи миграций

## Поддержка

При возникновении проблем:
1. Проверьте логи: `logs/tbot.log`
2. Проверьте статус сервисов
3. Проверьте подключение к БД и Redis



