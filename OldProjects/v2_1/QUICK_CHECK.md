# Быстрая проверка настроек TOPIC_ID

## ✅ Текущие настройки в БД

```
EXCEL_TOPIC_ID    = 9   (поиск сотрудников)
PING_TOPIC_ID    = 7   (мониторинг серверов)
BOT_TOPIC_ID     = 5   (сообщения бота)
METRICS_TOPIC_ID = 69  (метрики)
TASKS_TOPIC_ID   = 145 (заявки OTRS)
```

## Проверка работы

### 1. Проверьте, что настройки загружены

```powershell
.\bot.ps1 settings
```

### 2. Перезапустите бота (если изменили настройки)

```powershell
.\bot.ps1 restart
```

### 3. Проверьте логи

```powershell
.\bot.ps1 logs
```

Должны увидеть:
```
[INFO] Database pool initialized
[INFO] Settings initialized
[INFO] Telegram Bot Service started
```

### 4. Тест в Telegram

1. Откройте групповой чат
2. Перейдите в топик с ID `9` (EXCEL_TOPIC_ID)
3. Отправьте имя сотрудника или IP
4. Бот должен ответить результатами поиска

## Если не работает

1. **Проверьте ID топика** - используйте @userinfobot для проверки
2. **Проверьте настройки**: `.\bot.ps1 settings`
3. **Проверьте логи**: `.\bot.ps1 logs`
4. **Перезапустите бота**: `.\bot.ps1 restart`

## Изменение TOPIC_ID

```powershell
# 1. Отредактируйте .env файл
# 2. Запустите инициализацию
.\bot.ps1 init-settings

# 3. Перезапустите бота
.\bot.ps1 restart
```

