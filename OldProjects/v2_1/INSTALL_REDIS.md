# Установка Redis для Windows (опционально)

Redis нужен только если вы хотите использовать функции кластеризации (запуск на нескольких серверах).

## Вариант 1: Memurai (рекомендуется для Windows)

1. Скачайте Memurai с [memurai.com](https://www.memurai.com/)
2. Установите как Windows Service
3. После установки Redis будет доступен на `localhost:6379`

## Вариант 2: Redis для Windows (неофициальная сборка)

1. Скачайте последнюю версию с [github.com/microsoftarchive/redis/releases](https://github.com/microsoftarchive/redis/releases)
2. Распакуйте архив
3. Запустите `redis-server.exe`

## Вариант 3: WSL (Windows Subsystem for Linux)

Если у вас установлен WSL, можете использовать Redis из Linux:

```bash
# В WSL
sudo apt-get update
sudo apt-get install redis-server
sudo service redis-server start
```

## Настройка в приложении

После установки Redis, в файле `.env` установите:

```env
CLUSTER_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

Или через переменные окружения PowerShell:

```powershell
$env:CLUSTER_ENABLED="true"
$env:REDIS_HOST="localhost"
$env:REDIS_PORT="6379"
```

## Работа без Redis

Если Redis не установлен, просто оставьте:

```env
CLUSTER_ENABLED=false
```

Приложение будет работать в режиме одной инстанции без кластеризации.

