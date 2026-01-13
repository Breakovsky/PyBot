# Настройка секретов в Windows Credential Manager

## Что нужно добавить в Windows Credential Manager

Выполните эти команды в PowerShell (от имени администратора, если нужно):

```powershell
# Обязательные секреты
cmdkey /generic:TOKEN /user:TBot /pass:ВАШ_ТОКЕН_БОТА
cmdkey /generic:DB_PASSWORD /user:TBot /pass:ВАШ_ПАРОЛЬ_БД
cmdkey /generic:JWT_SECRET /user:TBot /pass:ВАШ_JWT_СЕКРЕТ_32_СИМВОЛА

# Опциональные секреты (если используете)
cmdkey /generic:OTRS_PASSWORD /user:TBot /pass:ВАШ_ПАРОЛЬ_OTRS
cmdkey /generic:SMTP_USER /user:TBot /pass:ВАШ_EMAIL
cmdkey /generic:SMTP_PASSWORD /user:TBot /pass:ВАШ_ПАРОЛЬ_SMTP
cmdkey /generic:EXCEL_PASSWORD /user:TBot /pass:ВАШ_ПАРОЛЬ_EXCEL
cmdkey /generic:DOMAIN_BIND_PASSWORD /user:TBot /pass:ВАШ_ПАРОЛЬ_AD
```

## Генерация JWT_SECRET

```powershell
# PowerShell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | % {[char]$_})

# Или Python
python -c "import secrets; print(secrets.token_hex(32))"
```

## Проверка секретов

```powershell
python .\show_secrets.py
```

## Что уже есть у вас

Судя по выводу `show_secrets.py`, у вас уже есть:
- ✅ `TOKEN` 
- ✅ `DB_PASSWORD`
- ✅ `SUPERCHAT_TOKEN` (не используется в v2.1, можно удалить)

## Что нужно добавить

- ⚠️ `JWT_SECRET` - обязательно для веб-интерфейса

## Удаление старых секретов

```powershell
cmdkey /delete:TELEGRAM_BOT_TOKEN
cmdkey /delete:SUPERCHAT_TOKEN
cmdkey /delete:WEB_SECRET_KEY
cmdkey /delete:JWT_SECRET_KEY
```

