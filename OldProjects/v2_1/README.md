# TBot v2.1 - Production Ready Telegram Bot

## 🎯 Описание

Полностью переработанная версия Telegram бота с production-ready архитектурой:
- ✅ PostgreSQL с правильной нормализацией БД
- ✅ Поддержка кластеризации (2+ серверов)
- ✅ Полноценный веб-интерфейс для управления
- ✅ Excel данные в БД с редактированием через веб
- ✅ Асинхронная архитектура
- ✅ Безопасное хранение секретов
- ✅ Audit logging
- ✅ Rate limiting
- ✅ Мониторинг и метрики

## 🏗️ Архитектура

### Компоненты

1. **Telegram Bot Service** - обработка сообщений Telegram
2. **Web Admin Service** - веб-интерфейс управления (FastAPI)
3. **Background Workers** - фоновые задачи (мониторинг, OTRS)
4. **PostgreSQL** - основная БД
5. **Redis/Memurai** - кэширование и координация кластера

### Кластеризация

- **Leader Election** через Redis для scheduled задач
- **Shared State** через PostgreSQL и Redis
- **Load Balancing** для веб-интерфейса (опционально)
- **Health Checks** для мониторинга инстансов

## 📁 Структура проекта

```
v2_1/
├── main/
│   ├── main.py                    # Точка входа
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py            # Настройки из БД
│   │   └── security.py            # Безопасность (keyring)
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py          # Connection pooling
│   │   ├── models.py              # SQLAlchemy модели
│   │   └── repositories.py        # Репозитории для работы с БД
│   ├── migrations/                # Alembic миграции
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/
│   ├── services/
│   │   ├── __init__.py
│   │   ├── telegram_bot.py        # Telegram бот сервис
│   │   ├── web_admin.py           # Веб-админ сервис
│   │   ├── monitoring.py          # Мониторинг серверов
│   │   ├── otrs_integration.py   # OTRS интеграция
│   │   └── cluster_coordinator.py # Координация кластера
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── employees.py       # API для сотрудников (Excel)
│   │   │   ├── servers.py         # API для серверов
│   │   │   ├── metrics.py          # API для метрик
│   │   │   └── users.py           # API для пользователей
│   │   └── auth.py                # Аутентификация
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── excel_search.py        # Поиск в БД (вместо Excel)
│   │   ├── server_monitor.py      # Мониторинг серверов
│   │   └── otrs_handler.py        # OTRS обработчик
│   ├── web/
│   │   ├── static/                # CSS, JS
│   │   ├── templates/             # HTML шаблоны
│   │   └── routes.py              # Веб-роуты
│   ├── utils/
│   │   ├── logger.py              # Логирование
│   │   ├── cache.py               # Кэширование
│   │   └── validators.py          # Валидация
│   └── tests/
│       ├── unit/
│       └── integration/
├── requirements.txt
├── alembic.ini
├── .env.example
└── docker-compose.yml              # Для разработки (опционально)
```

## 🗄️ Структура базы данных

### Схемы PostgreSQL

1. **core** - основные таблицы
   - `settings` - настройки системы
   - `users` - пользователи
   - `audit_log` - аудит действий

2. **telegram** - Telegram данные
   - `telegram_users` - пользователи Telegram
   - `telegram_chats` - чаты и топики
   - `telegram_messages` - сообщения

3. **employees** - данные сотрудников (бывший Excel)
   - `employees` - сотрудники
   - `departments` - подразделения
   - `workstations` - рабочие станции

4. **monitoring** - мониторинг серверов
   - `server_groups` - группы серверов
   - `servers` - серверы
   - `server_events` - события
   - `server_metrics` - метрики

5. **otrs** - OTRS интеграция
   - `otrs_users` - авторизованные пользователи
   - `otrs_tickets` - тикеты
   - `otrs_metrics` - метрики действий

6. **cluster** - координация кластера
   - `cluster_nodes` - узлы кластера
   - `cluster_locks` - блокировки для задач

## 🚀 Установка

### Требования

- Python 3.9+
- PostgreSQL 14+
- Redis/Memurai (для кластеризации)
- Windows Server 2019

### Установка зависимостей

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Настройка БД

1. Создать базу данных:
```sql
CREATE DATABASE tbot;
```

2. Применить миграции:
```powershell
alembic upgrade head
```

3. Настроить секреты в Windows Credential Manager

### Запуск

```powershell
python main/main.py
```

## 🔧 Конфигурация

См. `.env.example` для примера конфигурации.

Основные настройки хранятся в БД (таблица `core.settings`).
Секреты хранятся в Windows Credential Manager.

## 📊 Мониторинг

- Health check: `http://localhost:8000/health`
- Metrics: `http://localhost:8000/metrics`
- Web Admin: `http://localhost:8000/admin`

## 🔒 Безопасность

- JWT токены для API
- Rate limiting
- Audit logging всех действий
- Секреты в Windows Credential Manager
- HTTPS (рекомендуется)

## 📝 Лицензия

Внутренний проект компании



