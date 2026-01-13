# Текущий минимальный .env файл для TBot v2.1

## Обязательные переменные

```env
# Токен Telegram бота
TOKEN=your_telegram_bot_token_here

# Пароль базы данных
DB_PASSWORD=your_db_password_here

# Секретный ключ для JWT (веб-интерфейс)
JWT_SECRET=your-random-secret-key-minimum-32-characters-long
```

## Настройки БД (для первоначального подключения)

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tbot
DB_USER=tbot
```

## Опциональные настройки веб-интерфейса

```env
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8000
```

## Опциональные секреты (если используются)

```env
# OTRS
OTRS_PASSWORD=your_otrs_password

# SMTP
SMTP_USER=bot@yourcompany.com
SMTP_PASSWORD=your_smtp_password

# Excel
EXCEL_PASSWORD=your_excel_password

# Active Directory
DOMAIN_BIND_PASSWORD=your_ad_password
```

## Что НЕ нужно в .env

Все эти настройки теперь хранятся в БД и настраиваются через веб-интерфейс или `init-settings`:

- ❌ `TELEGRAM_CHAT_ID` - в БД
- ❌ `EXCEL_TOPIC_ID`, `PING_TOPIC_ID`, `BOT_TOPIC_ID` - в БД
- ❌ `OTRS_URL`, `OTRS_USERNAME` - в БД
- ❌ `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_NAME` - в БД
- ❌ `EXCEL_FILE_PATH` - в БД
- ❌ `IP_ADDRESSES_PATH` - в БД
- ❌ Все остальные несекретные настройки - в БД

## Пример минимального .env

```env
# Обязательные
TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
DB_PASSWORD=your_secure_password
JWT_SECRET=your-random-secret-key-minimum-32-characters-long

# БД
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tbot
DB_USER=tbot

# Веб-интерфейс (опционально)
WEB_ENABLED=true
WEB_PORT=8000
```

## Генерация JWT_SECRET

```powershell
# PowerShell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | % {[char]$_})

# Python
python -c "import secrets; print(secrets.token_hex(32))"

# OpenSSL
openssl rand -hex 32
```

## Безопасность

Рекомендуется хранить секреты в Windows Credential Manager:

```powershell
cmdkey /generic:TOKEN /user:TBot /pass:your_token
cmdkey /generic:DB_PASSWORD /user:TBot /pass:your_password
cmdkey /generic:JWT_SECRET /user:TBot /pass:your_jwt_secret
```

После этого можно удалить соответствующие строки из .env.

