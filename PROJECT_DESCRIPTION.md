# NetAdmin Bot v3.0 — Полное описание проекта

## 📋 Оглавление
1. [Обзор проекта](#обзор-проекта)
2. [Архитектура системы](#архитектура-системы)
3. [Компоненты и технологии](#компоненты-и-технологии)
4. [Структура проекта](#структура-проекта)
5. [Функциональность](#функциональность)
6. [База данных](#база-данных)
7. [Интеграции](#интеграции)
8. [Безопасность и RBAC](#безопасность-и-rbac)
9. [DevOps и развертывание](#devops-и-развертывание)
10. [Текущий статус](#текущий-статус)

---

## 🎯 Обзор проекта

**NetAdmin Bot v3.0** — комплексная система управления IT-инфраструктурой, объединяющая:
- **Telegram-бот** с интеллектуальной маршрутизацией и RBAC
- **Redmine** для управления задачами и тикетами
- **Java Agent** для мониторинга и интеграции с MDaemon
- **Web Admin Panel** для управления инфраструктурой
- **Динамическое планирование** задач мониторинга

### Ключевые особенности
- ✅ **Role-Based Access Control (RBAC)** — 7 уровней доступа
- ✅ **Telegram Topics Integration** — разделение рабочих потоков по темам
- ✅ **Dynamic Scheduling** — переконфигурация мониторинга без перезапуска
- ✅ **Event-Driven Architecture** — Redis pub/sub для межсервисной коммуникации
- ✅ **Docker Compose** — полная контейнеризация всех сервисов
- ✅ **Production-Ready** — healthchecks, backups, logging, error handling

---

## 🏗️ Архитектура системы

### Диаграмма компонентов

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Supergroup                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Topic:  │  │  Topic:  │  │  Topic:  │  │  Topic:  │   │
│  │ Alerts   │  │ Tickets  │  │ Assets   │  │  Admin   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │   Python Bot (Aiogram)│
            │   - RBAC Middleware   │
            │   - Topic Router      │
            │   - Redis Listener    │
            └──────────┬────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│   Redis      │ │PostgreSQL│ │  Java Agent  │
│  (Pub/Sub)   │ │  (DB)    │ │  (Spring)    │
└──────┬───────┘ └────┬─────┘ └──────┬───────┘
       │              │              │
       │              │              │
       ▼              ▼              ▼
┌─────────────────────────────────────────────┐
│         Admin Panel (FastAPI)               │
│  - Docker Management                         │
│  - Target CRUD                               │
│  - Backup Management                         │
└─────────────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │   Redmine (Rails)    │
            │   - Issue Tracking   │
            │   - Plugins:         │
            │     • email_reports  │
            │     • issue_guard    │
            │     • recurring_tasks│
            └──────────────────────┘
```

### Потоки данных

1. **Telegram → Bot → Database**: Пользователь отправляет команду → Middleware проверяет роль → Handler обрабатывает → Сохранение в БД
2. **Java Agent → Redis → Bot → Telegram**: Мониторинг обнаруживает проблему → Публикация в Redis → Bot получает → Отправка в нужный Topic
3. **Admin Panel → Database → Redis → Java Agent**: Создание нового target → Сохранение в БД → Событие в Redis → Java Agent переконфигурирует schedule
4. **Redmine → Webhooks → Java Agent**: Обновление тикета → Webhook → Java Agent обрабатывает

---

## 🧩 Компоненты и технологии

### 1. Python Bot (`python-bot/`)

**Технологии:**
- **Aiogram 3.3.0+** — асинхронный фреймворк для Telegram Bot API
- **SQLAlchemy 2.0.25+** — ORM для работы с PostgreSQL
- **asyncpg** — асинхронный драйвер PostgreSQL
- **Redis 5.0.1+** — клиент для pub/sub

**Основные модули:**
- `src/main.py` — точка входа, регистрация handlers, Redis listener
- `src/core/database.py` — SQLAlchemy модели (`TelegramUser`, `TelegramTopic`, `UserRole` Enum)
- `src/core/middlewares.py` — `RoleMiddleware` для RBAC проверок

**Функциональность:**
- Автоматическая регистрация новых пользователей (роль `USER` по умолчанию)
- Проверка прав доступа через `flags={"role": UserRole.REQUIRED_ROLE}`
- Маршрутизация сообщений в Telegram Topics по `thread_id`
- Обработка команд: `/start`, `/admin`, `/set_topic`, `/cookie`, `WS\d+` (asset queries)
- Фоновый worker для прослушивания Redis каналов (`bot_alerts`, `netadmin_tasks`)

**Примеры команд:**
```python
@dp.message(Command("admin"), flags={"role": UserRole.SENIOR_ADMIN})
@dp.message(Command("set_topic"), flags={"role": UserRole.CTO})
```

---

### 2. Java Agent (`java-agent/`)

**Технологии:**
- **Spring Boot 3.4.1** — основной фреймворк
- **Spring Data JPA** — работа с БД
- **Spring Data Redis** — интеграция с Redis
- **PostgreSQL Driver** — подключение к БД
- **Java 21** — LTS версия

**Основные сервисы:**
- `DynamicSchedulerService` — динамическое планирование задач мониторинга
  - Загружает `MonitoredTarget` из БД
  - Создает/обновляет scheduled tasks при изменении конфигурации
  - Выполняет ping-проверки с настраиваемым интервалом
  - Отслеживает изменения состояния (UP → DOWN, DOWN → UP)
  
- `AlertDispatcher` — отправка алертов в Redis
  - Формат: `"TOPIC_NAME|MESSAGE"`
  - Python Bot получает и маршрутизирует в нужный Telegram Topic
  
- `RedisEventListener` — подписка на события конфигурации
  - Слушает канал `netadmin_events`
  - При событии `CONFIG_UPDATE:MONITORING` вызывает `refreshSchedule()`

**Модели данных:**
- `MonitoredTarget` — хост для мониторинга (name, hostname, interval_seconds, is_active, last_status, last_check)
- `TelegramTopic` — маппинг логических топиков на thread_id

---

### 3. Admin Panel (`admin-panel/`)

**Технологии:**
- **FastAPI** — современный Python веб-фреймворк
- **Jinja2** — шаблонизатор для HTML
- **Docker SDK** — управление контейнерами (через `/var/run/docker.sock`)
- **SQLAlchemy** — синхронная работа с БД
- **Redis** — публикация событий конфигурации

**Функциональность:**
- **Dashboard** — обзор контейнеров, targets, backups
- **Container Management** — перезапуск, просмотр логов
- **Target CRUD** — создание/удаление monitored targets
- **Backup Management** — просмотр и скачивание backups
- **Simple Auth** — cookie-based аутентификация (MVP)

**Endpoints:**
- `GET /` — dashboard
- `POST /login` — аутентификация
- `POST /api/containers/{id}/restart` — перезапуск контейнера
- `GET /api/containers/{id}/logs` — логи контейнера
- `POST /api/targets` — создание target
- `POST /api/targets/{id}/delete` — удаление target
- `GET /api/backups/download/{filename}` — скачивание backup

---

### 4. Redmine Service (`redmine-service/`)

**Технологии:**
- **Redmine 6.0** (Rails-based)
- **PostgreSQL** — основная БД
- **Supervisor** — управление процессами (Rails server + background jobs)
- **Ruby Gems:**
  - `whenever` — cron-like задачи
  - `chronic` — парсинг времени
  - `mail` — работа с email
  - `pg` — драйвер PostgreSQL

**Кастомные плагины:**

1. **`email_reports`** — автоматическая генерация и отправка отчетов
   - Периодические отчеты по проектам
   - Настраиваемые фильтры (дата, проект, трекер)
   - Email-рассылка группам пользователей
   - Rake tasks для запуска: `rake email_reports:send_pending`

2. **`redmine_issue_guard`** — валидация обязательных полей при создании/обновлении issues
   - Принудительное заполнение времени (spent time)
   - Валидация категории
   - JavaScript блокировка UI до заполнения

3. **`redmine_recurring_tasks`** (external) — создание повторяющихся задач
   - GitHub: `southbridgeio/redmine_recurring_tasks`

**Supervisor конфигурация:**
- Rails server (Puma) на порту 3000
- Background jobs (если используются)

**Init Script (`init.sh`):**
- Исправление прав доступа для mounted volumes
- Запуск миграций БД и плагинов
- Запуск Supervisor

---

### 5. Infrastructure Services

#### Nginx (`nginx/`)
- **Порт:** 8081
- **Роль:** Reverse proxy для Redmine
- **Конфигурация:** `config/nginx.conf`

#### PostgreSQL (`db/`)
- **Версия:** PostgreSQL 17 (Alpine)
- **База данных:** `netadmin_db`
- **Инициализация:** `config/init_rbac.sql` (создание RBAC таблиц)
- **Volumes:** `storage/postgresql-data`

#### Redis (`redis/`)
- **Версия:** Redis 7.4 (Alpine)
- **Роль:** Message broker, cache
- **Каналы:**
  - `bot_alerts` — алерты от Java Agent к Python Bot
  - `netadmin_tasks` — задачи для бота
  - `netadmin_events` — события конфигурации (для Java Agent)
- **Volumes:** `storage/redis-data`

#### Backup Service (`backup/`)
- **Роль:** Автоматические бэкапы БД и файлов Redmine
- **Скрипт:** `config/backup.sh`
- **Volumes:** `backups/`

---

## 📁 Структура проекта

```
PyBot/
├── admin-panel/              # Web Control Plane (FastAPI)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── main.py
│       └── templates/
│           ├── dashboard.html
│           └── login.html
│
├── python-bot/               # Telegram Bot (Aiogram)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── main.py
│       └── core/
│           ├── database.py   # SQLAlchemy models
│           └── middlewares.py # RBAC middleware
│
├── java-agent/               # Java Backend (Spring Boot)
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/main/java/com/netadmin/agent/
│       ├── NetAdminAgentApplication.java
│       ├── config/
│       │   └── RedisConfig.java
│       ├── model/
│       │   ├── MonitoredTarget.java
│       │   └── TelegramTopic.java
│       ├── repository/
│       │   ├── MonitoredTargetRepository.java
│       │   └── TelegramTopicRepository.java
│       └── service/
│           ├── DynamicSchedulerService.java
│           ├── AlertDispatcher.java
│           ├── RedisEventListener.java
│           └── TaskListener.java
│
├── redmine-service/          # Redmine Customization
│   ├── Dockerfile
│   ├── init.sh               # Entrypoint script
│   ├── config/
│   │   └── supervisord.conf
│   └── plugins/
│       ├── email_reports/    # Custom plugin
│       └── redmine_issue_guard/ # Custom plugin
│
├── config/                   # Configuration files
│   ├── nginx.conf
│   ├── database.yml          # Redmine DB config
│   ├── configuration.yml     # Redmine app config
│   ├── backup.sh
│   └── init_rbac.sql         # RBAC schema
│
├── docker-compose.yml        # Orchestration
├── Makefile                  # CLI shortcuts
├── env.example               # Environment template
├── .gitignore
└── README.md
```

---

## 🎨 Функциональность

### Phase 1: Core Infrastructure ✅
- [x] Docker Compose orchestration
- [x] Redmine с кастомными плагинами
- [x] PostgreSQL + Redis
- [x] Nginx reverse proxy
- [x] Backup service
- [x] Supervisor для Redmine процессов

### Phase 2: Web Control Plane & Dynamic Orchestration ✅
- [x] Admin Panel (FastAPI) для управления инфраструктурой
- [x] Docker container management через API
- [x] CRUD для monitored targets
- [x] Dynamic scheduling в Java Agent
- [x] Redis event-driven конфигурация

### Phase 3: Telegram Supergroup Integration (Topics & RBAC) ✅
- [x] RBAC система (7 уровней: CREATOR, CTO, IT_HEAD, SENIOR_ADMIN, ADMIN, JUNIOR_ADMIN, USER)
- [x] Telegram Topics интеграция
- [x] RoleMiddleware для автоматической проверки прав
- [x] Topic-based маршрутизация сообщений
- [x] Автоматическая регистрация пользователей
- [x] Gamification (karma points через `/cookie`)

### Планируемые функции (Future Phases)
- [ ] Интеграция с инвентарем активов (asset queries)
- [ ] Weekly metrics и leaderboard
- [ ] Redmine webhooks → Java Agent
- [ ] Расширенная аналитика и отчетность
- [ ] Multi-language support

---

## 🗄️ База данных

### Схема RBAC

**Таблица `telegram_users`:**
```sql
CREATE TABLE telegram_users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    role user_role DEFAULT 'USER',
    karma_points INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**ENUM `user_role`:**
```sql
CREATE TYPE user_role AS ENUM (
    'CREATOR',      -- Высший уровень
    'CTO',
    'IT_HEAD',
    'SENIOR_ADMIN',
    'ADMIN',
    'JUNIOR_ADMIN',
    'USER'          -- По умолчанию
);
```

**Таблица `telegram_topics`:**
```sql
CREATE TABLE telegram_topics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,  -- 'tickets', 'monitoring', etc.
    thread_id INT NOT NULL,            -- Telegram thread ID
    description VARCHAR(255)
);
```

**Предустановленные топики:**
- `tickets` — Redmine Ticket Stream
- `assets` — Asset Inventory Queries
- `metrics` — Weekly Metrics & Leaderboard
- `monitoring` — Infrastructure Alerts
- `admin` — Bot Command Center

**Таблица `monitored_targets` (Admin Panel):**
```sql
CREATE TABLE monitored_targets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    hostname VARCHAR(255),
    interval_seconds INT DEFAULT 60,
    is_active BOOLEAN DEFAULT TRUE,
    last_status VARCHAR(50),
    last_check TIMESTAMP WITH TIME ZONE
);
```

---

## 🔗 Интеграции

### 1. Telegram Bot API
- **Протокол:** HTTPS Webhook/Polling
- **Библиотека:** Aiogram 3.3.0
- **Функции:** Команды, inline keyboards, topic routing

### 2. Redis Pub/Sub
- **Каналы:**
  - `bot_alerts` — формат: `"TOPIC_NAME|MESSAGE"`
  - `netadmin_tasks` — задачи для бота
  - `netadmin_events` — события конфигурации (`CONFIG_UPDATE:MONITORING`)

### 3. PostgreSQL
- **Драйверы:**
  - Python: `asyncpg` (async) для бота, `psycopg2` (sync) для admin panel
  - Java: `postgresql` JDBC driver
  - Ruby: `pg` gem для Redmine

### 4. Docker API
- **Доступ:** `/var/run/docker.sock` (mounted в admin-panel)
- **Функции:** Управление контейнерами, логи, статусы

### 5. Redmine Plugins
- **Интеграция:** Через стандартный Redmine plugin API
- **Миграции:** `rake redmine:plugins:migrate`

---

## 🔐 Безопасность и RBAC

### Иерархия ролей

Роли упорядочены по приоритету (ниже = выше привилегии):
1. **CREATOR** — полный доступ, может назначать роли
2. **CTO** — управление топиками (`/set_topic`)
3. **IT_HEAD** — расширенные права
4. **SENIOR_ADMIN** — доступ к `/admin`, управление конфигурацией
5. **ADMIN** — базовое администрирование
6. **JUNIOR_ADMIN** — ограниченные права
7. **USER** — базовый доступ (по умолчанию)

### Проверка прав

**В Python Bot:**
```python
@dp.message(Command("admin"), flags={"role": UserRole.SENIOR_ADMIN})
async def cmd_admin(message: Message, user: TelegramUser):
    # Handler выполнится только если user.role >= SENIOR_ADMIN
    pass
```

**В Middleware:**
```python
if user.role >= required_role:
    data["user"] = user
    return await handler(event, data)
else:
    await event.reply("⛔ Access Denied.")
```

### Безопасность Admin Panel

- **MVP Auth:** Cookie-based token (`admin_token=valid_token`)
- **⚠️ Production:** Требуется замена на JWT/OAuth2
- **Docker Socket:** Монтируется с предупреждением о рисках

---

## 🚀 DevOps и развертывание

### Docker Compose

**Сервисы:**
- `nginx` — порт 8081
- `admin-panel` — порт 8000
- `redmine` — внутренний порт 3000
- `db` — PostgreSQL 17
- `redis` — Redis 7.4
- `backup` — периодические бэкапы
- `python-bot` — Telegram bot
- `java-agent` — Spring Boot на порту 8080

**Networks:**
- `bot_net` — bridge network для всех сервисов

**Volumes:**
- `storage/postgresql-data` — данные БД
- `storage/redis-data` — данные Redis
- `storage/redmine/files` — файлы Redmine
- `storage/redmine/plugins` — плагины
- `storage/redmine/themes` — темы
- `backups/` — бэкапы
- `logs/` — логи сервисов

### Makefile команды

**Docker Compose:**
```bash
make up          # Запуск всех сервисов
make down        # Остановка
make build       # Сборка образов
make rebuild     # Пересборка и перезапуск
make restart     # Перезапуск
make logs        # Логи всех сервисов
make logs-bot    # Логи бота
make logs-redmine # Логи Redmine
make ps          # Статус контейнеров
make health      # Healthcheck статус
```

**Git:**
```bash
make commit MSG="message"  # Коммит
make push                  # Push
make save MSG="message"    # Commit + Push
```

**Utilities:**
```bash
make shell-bot      # Shell в контейнер бота
make shell-db       # PostgreSQL shell
make backup         # Создать бэкап
make redmine-migrate # Запустить миграции Redmine
```

### Healthchecks

Все сервисы имеют healthchecks:
- **Nginx:** `curl -f http://localhost:8081`
- **Redmine:** `curl -f http://localhost:3000`
- **PostgreSQL:** `pg_isready -U $POSTGRES_USER`
- **Redis:** `redis-cli ping`
- **Java Agent:** `curl -f http://localhost:8080/actuator/health`
- **Admin Panel:** `curl -f http://localhost:8000/`

### Environment Variables

**Основные:**
- `BOT_TOKEN` — токен Telegram бота
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `REDIS_HOST`, `REDIS_PORT`
- `REDMINE_SECRET_KEY` — секретный ключ для Rails
- `TELEGRAM_SUPERGROUP_ID` — ID супергруппы
- `ADMIN_PASSWORD` — пароль для Admin Panel

**Redmine Email:**
- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`
- `SMTP_ADDRESS`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`

---

## 📊 Текущий статус

### ✅ Реализовано

1. **Infrastructure:**
   - [x] Docker Compose orchestration
   - [x] Все сервисы контейнеризированы
   - [x] Healthchecks настроены
   - [x] Volumes для персистентности
   - [x] Backup service

2. **Redmine:**
   - [x] Кастомный Dockerfile с плагинами
   - [x] Supervisor для процессов
   - [x] Плагины: `email_reports`, `redmine_issue_guard`, `recurring_tasks`
   - [x] Миграции и инициализация

3. **Python Bot:**
   - [x] RBAC middleware
   - [x] Topic routing
   - [x] Redis listener
   - [x] Автоматическая регистрация пользователей
   - [x] Команды: `/start`, `/admin`, `/set_topic`, `/cookie`

4. **Java Agent:**
   - [x] Dynamic scheduling
   - [x] Alert dispatching
   - [x] Redis event listener
   - [x] Мониторинг хостов (ping)

5. **Admin Panel:**
   - [x] Dashboard
   - [x] Container management
   - [x] Target CRUD
   - [x] Backup management
   - [x] Simple auth

6. **Database:**
   - [x] RBAC schema
   - [x] Telegram topics mapping
   - [x] Monitored targets

### 🔧 Исправленные проблемы

1. **Python Bot:**
   - ✅ `ModuleNotFoundError: No module named 'src'` → добавлен `PYTHONPATH=/app`
   - ✅ `ProgrammingError: type "userrole" does not exist` → исправлен Enum mapping (`name="user_role"`)
   - ✅ Redis connection errors → добавлены явные `REDIS_HOST` и `REDIS_PORT`

2. **Redmine:**
   - ✅ Permission denied errors → `chown` в `init.sh` после монтирования volumes
   - ✅ Missing secret key → исправлено имя переменной (`SECRET_KEY_BASE`)
   - ✅ Plugin loading → правильная структура директорий

3. **Admin Panel:**
   - ✅ `psycopg2-binary` build failure → добавлены `build-essential`, `libpq-dev`
   - ✅ SQLAlchemy compatibility → обновлена версия до 2.0.36+

### 📝 Известные ограничения

1. **Admin Panel Auth:** MVP реализация, требуется замена на production-ready решение
2. **Docker Socket:** Монтирование `/var/run/docker.sock` — security risk
3. **Error Handling:** Базовая обработка ошибок, требуется расширение
4. **Testing:** Отсутствуют unit/integration тесты
5. **Documentation:** Частичная документация кода

### 🎯 Следующие шаги

1. Настройка Telegram Topics в супергруппе
2. Тестирование RBAC системы
3. Интеграция с инвентарем активов
4. Реализация weekly metrics
5. Улучшение безопасности Admin Panel

---

## 📈 Метрики проекта

- **Языки:** Python, Java, Ruby, SQL, Shell
- **Фреймворки:** Aiogram, Spring Boot, FastAPI, Rails
- **Базы данных:** PostgreSQL 17, Redis 7.4
- **Контейнеры:** 8 сервисов
- **Плагины Redmine:** 3 (2 кастомных, 1 external)
- **Строк кода:** ~3000+ (оценка)
- **Коммитов:** Активная разработка

---

## 🔄 Workflow примеры

### Добавление нового monitored target

1. Администратор открывает Admin Panel (`http://localhost:8000`)
2. Вводит данные: name, hostname, interval
3. Нажимает "Create Target"
4. Admin Panel сохраняет в `monitored_targets` таблицу
5. Публикует событие `CONFIG_UPDATE:MONITORING` в Redis
6. Java Agent получает событие через `RedisEventListener`
7. `DynamicSchedulerService.refreshSchedule()` перезагружает targets из БД
8. Создается новый scheduled task для ping-проверок

### Отправка алерта в Telegram

1. Java Agent обнаруживает, что хост недоступен (ping failed)
2. `AlertDispatcher.sendAlert("monitoring", "🚨 ALERT: Host X is DOWN!")`
3. Публикация в Redis канал `bot_alerts`: `"monitoring|🚨 ALERT: Host X is DOWN!"`
4. Python Bot получает сообщение в `redis_listener()`
5. Парсит формат: `topic_name, text = data.split("|", 1)`
6. Запрашивает `thread_id` для топика `monitoring` из БД
7. Отправляет сообщение в Telegram Supergroup в нужный Topic

### Проверка прав доступа

1. Пользователь отправляет `/admin`
2. `RoleMiddleware` перехватывает сообщение
3. Проверяет `flags={"role": UserRole.SENIOR_ADMIN}`
4. Запрашивает пользователя из БД по `telegram_id`
5. Если пользователь не найден — создает с ролью `USER`
6. Сравнивает: `user.role >= SENIOR_ADMIN`
7. Если да — передает в handler, иначе — отправляет "Access Denied"

---

## 📚 Дополнительная информация

### Версии зависимостей

**Python Bot:**
- `aiogram>=3.3.0`
- `sqlalchemy>=2.0.25`
- `asyncpg>=0.29.0`
- `redis>=5.0.1`

**Java Agent:**
- Spring Boot 3.4.1
- Java 21
- PostgreSQL Driver (runtime)

**Admin Panel:**
- `fastapi` (latest)
- `sqlalchemy>=2.0.36`
- `psycopg2-binary`
- `docker` (Python SDK)

**Redmine:**
- Redmine 6.0 (Alpine)
- Ruby gems: `whenever`, `chronic`, `mail`, `pg`

### Конфигурационные файлы

- `docker-compose.yml` — оркестрация
- `config/nginx.conf` — Nginx proxy
- `config/database.yml` — Redmine DB
- `config/configuration.yml` — Redmine app config
- `config/init_rbac.sql` — RBAC schema
- `env.example` — шаблон переменных окружения

---

**Дата создания документа:** 2025-01-XX  
**Версия проекта:** 3.0  
**Статус:** Production-Ready (MVP)

