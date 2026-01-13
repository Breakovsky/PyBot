<#
.SYNOPSIS
    TBot v2.1 Manager - Production-ready Telegram Bot
.DESCRIPTION
    Управление Telegram ботом v2.1 с поддержкой PostgreSQL, кластеризации и веб-интерфейса
.EXAMPLE
    .\bot.ps1 start    - Start bot
    .\bot.ps1 stop     - Stop bot
    .\bot.ps1 restart  - Restart bot
    .\bot.ps1 status   - Check status
    .\bot.ps1 logs     - Show logs
    .\bot.ps1 install  - Install dependencies
    .\bot.ps1 test     - Run tests
    .\bot.ps1 migrate  - Run database migrations
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "restart", "status", "logs", "install", "run", "test", "migrate", "init-settings", "settings", "update-chat", "check-employees", "check-duplicates", "clear-employees", "create-user", "add-secret", "help")]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MainScript = Join-Path $ProjectRoot "main\main.py"
$TestScript = Join-Path $ProjectRoot "test_bot.py"
$LogFile = Join-Path $ProjectRoot "logs\tbot.log"
$PidFile = Join-Path $ProjectRoot "bot.pid"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"

function Get-BotProcess {
    # Сначала проверяем PID файл
    if (Test-Path $PidFile) {
        $procId = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($procId) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -eq "python") {
                # Проверяем, что это действительно наш бот
                try {
                    $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue).CommandLine
                    if ($cmdLine -and ($cmdLine -like "*main\main.py*" -or $cmdLine -like "*main/main.py*")) {
                        return $proc
                    }
                } catch {
                    # Если не можем проверить командную строку, считаем что это наш процесс
                    return $proc
                }
            }
        }
    }
    
    # Если PID файл не помог, ищем по командной строке
    try {
        $processes = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*main\main.py*" -or $_.CommandLine -like "*main/main.py*"
        }
        
        if ($processes) {
            foreach ($procInfo in $processes) {
                $proc = Get-Process -Id $procInfo.ProcessId -ErrorAction SilentlyContinue
                if ($proc -and $proc.ProcessName -eq "python") {
                    return $proc
                }
            }
        }
    } catch {
        # Игнорируем ошибки при поиске
    }
    
    return $null
}

function Start-Bot {
    # Проверяем и останавливаем все старые процессы
    $existing = Get-BotProcess
    if ($existing) {
        Write-Host "[!] Found existing bot process (PID: $($existing.Id))" -ForegroundColor Yellow
        Write-Host "[*] Stopping old process..." -ForegroundColor Cyan
        Stop-Process -Id $existing.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        
        # Проверяем еще раз
        $stillRunning = Get-Process -Id $existing.Id -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Write-Host "[X] Failed to stop old process. Please stop it manually." -ForegroundColor Red
            return
        }
        
        # Очищаем PID файл
        if (Test-Path $PidFile) {
            Remove-Item $PidFile -Force
        }
        
        Write-Host "[OK] Old process stopped" -ForegroundColor Green
        Start-Sleep -Seconds 1
    }
    
    # Ищем все процессы Python, которые могут быть нашим ботом
    try {
        $allPythonProcs = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*main\main.py*" -or $_.CommandLine -like "*main/main.py*"
        }
        
        if ($allPythonProcs) {
            Write-Host "[!] Found additional bot processes, stopping them..." -ForegroundColor Yellow
            foreach ($procInfo in $allPythonProcs) {
                $proc = Get-Process -Id $procInfo.ProcessId -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "    Stopping PID: $($proc.Id)" -ForegroundColor Gray
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                }
            }
            Start-Sleep -Seconds 2
        }
    } catch {
        # Игнорируем ошибки
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }

    if (-not (Test-Path $MainScript)) {
        Write-Host "[X] Main script not found: $MainScript" -ForegroundColor Red
        return
    }

    Write-Host "[*] Starting TBot v2.1..." -ForegroundColor Cyan
    
    # Проверяем наличие .env или переменных окружения
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) {
        Write-Host "[!] Warning: .env file not found. Using environment variables and defaults." -ForegroundColor Yellow
    }
    
    Push-Location $ProjectRoot
    try {
        $process = Start-Process -FilePath $VenvPython -ArgumentList "main\main.py" `
            -WindowStyle Hidden -PassThru -WorkingDirectory $ProjectRoot
        
        $process.Id | Out-File $PidFile -Force -Encoding ASCII
        Start-Sleep -Seconds 3
        
        $check = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
        if ($check) {
            Write-Host "[OK] Bot started (PID: $($check.Id))" -ForegroundColor Green
            Write-Host "     Check logs: .\bot.ps1 logs" -ForegroundColor Gray
        } else {
            Write-Host "[X] Failed to start bot. Check logs: .\bot.ps1 logs" -ForegroundColor Red
            if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        }
    } catch {
        Write-Host "[X] Error starting bot: $_" -ForegroundColor Red
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    } finally {
        Pop-Location
    }
}

function Stop-Bot {
    $proc = Get-BotProcess
    if (-not $proc) {
        Write-Host "[i] Bot is not running" -ForegroundColor Yellow
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        return
    }

    Write-Host "[*] Stopping bot (PID: $($proc.Id))..." -ForegroundColor Cyan
    
    # Пытаемся graceful shutdown через сигнал
    try {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "[!] Warning: Could not stop gracefully, forcing..." -ForegroundColor Yellow
    }
    
    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force
    }
    
    Start-Sleep -Seconds 2
    
    # Проверяем, что процесс действительно остановлен
    $check = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $check) {
        Write-Host "[OK] Bot stopped" -ForegroundColor Green
    } else {
        Write-Host "[!] Warning: Process may still be running" -ForegroundColor Yellow
    }
}

function Restart-Bot {
    Write-Host "[*] Restarting bot..." -ForegroundColor Cyan
    Stop-Bot
    Start-Sleep -Seconds 2
    Start-Bot
}

function Get-Status {
    $proc = Get-BotProcess
    if ($proc) {
        Write-Host "[OK] Bot is running" -ForegroundColor Green
        Write-Host "   PID: $($proc.Id)"
        Write-Host "   Memory: $([math]::Round($proc.WorkingSet64 / 1MB, 2)) MB"
        Write-Host "   Started: $($proc.StartTime)"
        
        $uptime = (Get-Date) - $proc.StartTime
        Write-Host "   Uptime: $($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m $($uptime.Seconds)s"
        
        # Проверяем последние логи
        if (Test-Path $LogFile) {
            $lastLog = Get-Content $LogFile -Tail 1 -ErrorAction SilentlyContinue
            if ($lastLog) {
                Write-Host "   Last log: $($lastLog.Substring(0, [Math]::Min(60, $lastLog.Length)))..."
            }
        }
    } else {
        Write-Host "[X] Bot is not running" -ForegroundColor Red
        
        # Проверяем, есть ли PID файл
        if (Test-Path $PidFile) {
            Write-Host "[!] PID file exists but process not found. Cleaning up..." -ForegroundColor Yellow
            Remove-Item $PidFile -Force
        }
    }
}

function Show-Logs {
    if (Test-Path $LogFile) {
        Write-Host "[*] Last 50 lines of logs:" -ForegroundColor Cyan
        Write-Host ""
        Get-Content $LogFile -Tail 50 -Encoding UTF8
    } else {
        Write-Host "[X] Log file not found: $LogFile" -ForegroundColor Red
        Write-Host "[i] Logs will be created when bot starts" -ForegroundColor Gray
    }
}

function Install-Dependencies {
    Write-Host "[*] Installing dependencies for TBot v2.1..." -ForegroundColor Cyan
    
    $venvDir = Join-Path $ProjectRoot ".venv"
    
    if (-not (Test-Path $venvDir)) {
        Write-Host "[*] Creating virtual environment..." -ForegroundColor Yellow
        python -m venv $venvDir
        if (-not $?) {
            Write-Host "[X] Failed to create virtual environment" -ForegroundColor Red
            return
        }
    }
    
    if (Test-Path $RequirementsFile) {
        Write-Host "[*] Upgrading pip..." -ForegroundColor Yellow
        & $VenvPython -m pip install --upgrade pip --quiet
        
        Write-Host "[*] Installing packages from requirements.txt..." -ForegroundColor Yellow
        & $VenvPython -m pip install -r $RequirementsFile
        
        if ($?) {
            Write-Host "[OK] Dependencies installed successfully" -ForegroundColor Green
            Write-Host "[i] Next steps:" -ForegroundColor Cyan
            Write-Host "    1. Configure .env file (see QUICK_START.md)" -ForegroundColor Gray
            Write-Host "    2. Save secrets in Windows Credential Manager" -ForegroundColor Gray
            Write-Host "    3. Run migrations: .\bot.ps1 migrate" -ForegroundColor Gray
            Write-Host "    4. Run tests: .\bot.ps1 test" -ForegroundColor Gray
        } else {
            Write-Host "[X] Failed to install dependencies" -ForegroundColor Red
        }
    } else {
        Write-Host "[X] requirements.txt not found: $RequirementsFile" -ForegroundColor Red
    }
}

function Run-Bot {
    Write-Host "[*] Starting bot in foreground mode (Ctrl+C to stop)..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython main\main.py
    } catch {
        Write-Host "[X] Error: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Run-Tests {
    Write-Host "[*] Running tests..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    if (-not (Test-Path $TestScript)) {
        Write-Host "[X] Test script not found: $TestScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython test_bot.py
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Host ""
            Write-Host "[OK] All tests passed!" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "[X] Some tests failed (exit code: $exitCode)" -ForegroundColor Red
        }
    } catch {
        Write-Host "[X] Error running tests: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Run-Migrations {
    Write-Host "[*] Running database migrations..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    $oldErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    
    try {
        Write-Host "[*] Checking current migration status..." -ForegroundColor Yellow
        $currentOutput = & $VenvPython -m alembic current 2>&1
        $currentExitCode = $LASTEXITCODE
        
        # Display output but filter out INFO messages from error stream
        $currentOutput | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                # This is stderr output (including INFO messages)
                $message = $_.ToString()
                if ($message -match "^INFO\s+\[alembic") {
                    # This is just an INFO log, not an error
                    Write-Host $message -ForegroundColor Gray
                } else {
                    # This might be a real error
                    Write-Host $message -ForegroundColor Yellow
                }
            } else {
                # This is stdout output
                Write-Host $_
            }
        }
        
        if ($currentExitCode -ne 0) {
            Write-Host ""
            Write-Host "[X] Failed to check migration status (exit code: $currentExitCode)" -ForegroundColor Red
            return
        }
        
        Write-Host ""
        Write-Host "[*] Applying migrations..." -ForegroundColor Yellow
        $upgradeOutput = & $VenvPython -m alembic upgrade head 2>&1
        $upgradeExitCode = $LASTEXITCODE
        
        # Display output but filter out INFO messages from error stream
        $upgradeOutput | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                # This is stderr output (including INFO messages)
                $message = $_.ToString()
                if ($message -match "^INFO\s+\[alembic") {
                    # This is just an INFO log, not an error
                    Write-Host $message -ForegroundColor Gray
                } else {
                    # This might be a real error
                    Write-Host $message -ForegroundColor Yellow
                }
            } else {
                # This is stdout output
                Write-Host $_
            }
        }
        
        if ($upgradeExitCode -eq 0) {
            Write-Host ""
            Write-Host "[OK] Migrations applied successfully" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "[X] Migration failed (exit code: $upgradeExitCode). Check the output above." -ForegroundColor Red
        }
    } catch {
        Write-Host "[X] Error running migrations: $_" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
    } finally {
        $ErrorActionPreference = $oldErrorAction
        Pop-Location
    }
}

function Init-Settings {
    Write-Host "[*] Initializing settings in database..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $InitScript = Join-Path $ProjectRoot "scripts\init_settings.py"
    if (-not (Test-Path $InitScript)) {
        Write-Host "[X] Init settings script not found: $InitScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $InitScript
        if ($?) {
            Write-Host ""
            Write-Host "[OK] Settings initialized successfully" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "[X] Settings initialization failed" -ForegroundColor Red
        }
    } catch {
        Write-Host "[X] Error initializing settings: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Show-Settings {
    Write-Host "[*] Showing current settings..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $ShowScript = Join-Path $ProjectRoot "scripts\show_settings.py"
    if (-not (Test-Path $ShowScript)) {
        Write-Host "[X] Show settings script not found: $ShowScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $ShowScript
    } catch {
        Write-Host "[X] Error showing settings: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Update-ChatSettings {
    Write-Host "[*] Updating chat and topic IDs..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $UpdateScript = Join-Path $ProjectRoot "scripts\update_chat_id.py"
    if (-not (Test-Path $UpdateScript)) {
        Write-Host "[X] Update script not found: $UpdateScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $UpdateScript
        if ($?) {
            Write-Host ""
            Write-Host "[OK] Settings updated successfully" -ForegroundColor Green
            Write-Host "[!] Don't forget to restart the bot: .\bot.ps1 restart" -ForegroundColor Yellow
        } else {
            Write-Host ""
            Write-Host "[X] Settings update failed" -ForegroundColor Red
        }
    } catch {
        Write-Host "[X] Error updating settings: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Check-Employees {
    Write-Host "[*] Checking employees in database..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $CheckScript = Join-Path $ProjectRoot "scripts\check_employees.py"
    if (-not (Test-Path $CheckScript)) {
        Write-Host "[X] Check script not found: $CheckScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $CheckScript
    } catch {
        Write-Host "[X] Error checking employees: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Check-Duplicates {
    Write-Host "[*] Checking for duplicate employees..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $CheckScript = Join-Path $ProjectRoot "scripts\check_duplicates.py"
    if (-not (Test-Path $CheckScript)) {
        Write-Host "[X] Check duplicates script not found: $CheckScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $CheckScript
    } catch {
        Write-Host "[X] Error checking duplicates: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Clear-Employees {
    Write-Host "[*] Clearing employees table..." -ForegroundColor Yellow
    Write-Host "[!] WARNING: This will delete all employees!" -ForegroundColor Red
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $ClearScript = Join-Path $ProjectRoot "scripts\clear_employees.py"
    if (-not (Test-Path $ClearScript)) {
        Write-Host "[X] Clear script not found: $ClearScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $ClearScript
    } catch {
        Write-Host "[X] Error clearing employees: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Create-WebUser {
    Write-Host "[*] Creating web interface user..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $CreateUserScript = Join-Path $ProjectRoot "scripts\create_user.py"
    if (-not (Test-Path $CreateUserScript)) {
        Write-Host "[X] Create user script not found: $CreateUserScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $CreateUserScript
        if ($?) {
            Write-Host ""
            Write-Host "[OK] User created successfully" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "[X] User creation failed" -ForegroundColor Red
        }
    } catch {
        Write-Host "[X] Error creating user: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Add-Secret {
    Write-Host "[*] Adding secret to Windows Credential Manager..." -ForegroundColor Cyan
    Write-Host ""
    
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }
    
    $AddSecretScript = Join-Path $ProjectRoot "scripts\add_secret.py"
    if (-not (Test-Path $AddSecretScript)) {
        Write-Host "[X] Add secret script not found: $AddSecretScript" -ForegroundColor Red
        return
    }
    
    Push-Location $ProjectRoot
    try {
        & $VenvPython $AddSecretScript
        if ($?) {
            Write-Host ""
            Write-Host "[OK] Secret added successfully" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "[X] Secret addition failed" -ForegroundColor Red
        }
    } catch {
        Write-Host "[X] Error adding secret: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Show-Help {
    Write-Host ""
    Write-Host "=== TBot v2.1 Manager ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Production-ready Telegram Bot with PostgreSQL, clustering, and web interface"
    Write-Host ""
    Write-Host "Usage: .\bot.ps1 [command]"
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  start    - Start bot in background"
    Write-Host "  stop     - Stop bot"
    Write-Host "  restart  - Restart bot"
    Write-Host "  status   - Show bot status and uptime"
    Write-Host "  logs     - Show last 50 log lines"
    Write-Host "  run      - Run bot in foreground (debug mode)"
    Write-Host "  test         - Run test suite"
    Write-Host "  migrate      - Run database migrations"
    Write-Host "  init-settings   - Initialize settings in database (TOPIC_ID, etc.)"
    Write-Host "  settings        - Show current settings from database"
    Write-Host "  update-chat       - Update chat ID and topic IDs interactively"
    Write-Host "  check-employees   - Check employees data in database"
    Write-Host "  check-duplicates  - Check and remove duplicate employees"
    Write-Host "  clear-employees   - Clear employees table (WARNING: deletes all data!)"
    Write-Host "  create-user       - Create user for web interface"
    Write-Host "  add-secret        - Add secret to Windows Credential Manager"
    Write-Host "  install           - Install/update dependencies"
    Write-Host "  help            - Show this help"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Yellow
    Write-Host "  .\bot.ps1 install        # First time setup"
    Write-Host "  .\bot.ps1 migrate        # Apply database migrations"
    Write-Host "  .\bot.ps1 init-settings  # Initialize TOPIC_ID and other settings"
    Write-Host "  .\bot.ps1 settings       # View current settings"
    Write-Host "  .\bot.ps1 test           # Verify configuration"
    Write-Host "  .\bot.ps1 start          # Start bot"
    Write-Host "  .\bot.ps1 status         # Check if running"
    Write-Host "  .\bot.ps1 logs           # View logs"
    Write-Host ""
}

switch ($Command) {
    "start"           { Start-Bot }
    "stop"            { Stop-Bot }
    "restart"         { Restart-Bot }
    "status"          { Get-Status }
    "logs"            { Show-Logs }
    "run"             { Run-Bot }
    "test"            { Run-Tests }
    "migrate"         { Run-Migrations }
    "init-settings"   { Init-Settings }
    "settings"        { Show-Settings }
    "update-chat"       { Update-ChatSettings }
    "check-employees"   { Check-Employees }
    "check-duplicates"  { Check-Duplicates }
    "clear-employees"   { Clear-Employees }
    "create-user"       { Create-WebUser }
    "add-secret"        { Add-Secret }
    "install"           { Install-Dependencies }
    "help"            { Show-Help }
    default           { Show-Help }
}
