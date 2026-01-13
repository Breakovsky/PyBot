# Руководство по настройке .env файла

## Минимальный .env файл

Создайте файл `.env` в корне проекта `v2_1` со следующим содержимым:

```env
# ============================================
# ОБЯЗАТЕЛЬНЫЕ НАСТРОЙКИ
# ============================================

# Токен Telegram бота (получить у @BotFather)
TOKEN=your_telegram_bot_token_here

# Пароль базы данных PostgreSQL
DB_PASSWORD=your_db_password_here

# ============================================
# НАСТРОЙКИ БАЗЫ ДАННЫХ (для первоначального подключения)
# ============================================

DB_HOST=localhost
DB_PORT=5432
DB_NAME=tbot
DB_USER=tbot

# ============================================
# СЕКРЕТНЫЕ ДАННЫЕ (опционально)
# ============================================

# Пароль для OTRS API (если используется OTRS)
# OTRS_PASSWORD=your_otrs_password

# Email и пароль для отправки писем (SMTP)
# SMTP_USER=bot@yourcompany.com
# SMTP_PASSWORD=your_smtp_password

# Пароль для Excel файла (если файл защищён паролем)
# EXCEL_PASSWORD=your_excel_password

# Пароль для подключения к Active Directory (если используется)
# DOMAIN_BIND_PASSWORD=your_ad_password
```

## Загрузка несекретных настроек в БД

Для загрузки несекретных настроек из старого .env файла в БД, временно добавьте их в .env перед запуском `.\bot.ps1 init-settings`:

```env
# Временные настройки для загрузки в БД (можно удалить после init-settings)
OTRS_URL=http://192.168.0.42/otrs
OTRS_USERNAME=telegram_bot
SMTP_HOST=mail.meb52.com
SMTP_PORT=465
SMTP_FROM_NAME=OTRS Bot
EXCEL_FILE_PATH=\\fs\it$\6. Наша\1. Общая\3. Общая документация ИТ\ВсеПК.xlsx
```

**Важно:** После выполнения `init-settings` эти настройки будут в БД, и их можно удалить из .env.

## Что НЕ должно быть в .env

- `IP_ADDRESSES_PATH` - настраивается только через БД/веб-интерфейс
- `TELEGRAM_CHAT_ID`, `EXCEL_TOPIC_ID`, `PING_TOPIC_ID` и другие ID топиков - настраиваются через БД
- `ALLOWED_THREADS` - настраивается через БД
- `BOT_STARTUP_MESSAGE` - настраивается через БД
- Настройки мониторинга - настраиваются через БД

## Безопасность

Рекомендуется хранить секретные данные в Windows Credential Manager:

```powershell
# Токен бота
cmdkey /generic:TOKEN /user:TBot /pass:your_token

# Пароль БД
cmdkey /generic:DB_PASSWORD /user:TBot /pass:your_password

# Пароль OTRS
cmdkey /generic:OTRS_PASSWORD /user:TBot /pass:your_password

# Пароль SMTP
cmdkey /generic:SMTP_PASSWORD /user:TBot /pass:your_password

# Пароль Excel
cmdkey /generic:EXCEL_PASSWORD /user:TBot /pass:your_password
```

После этого можно удалить соответствующие строки из .env файла.

