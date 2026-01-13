<#
.SYNOPSIS
    Telegram Bot Manager
.EXAMPLE
    .\bot.ps1 start    - Start bot
    .\bot.ps1 stop     - Stop bot
    .\bot.ps1 restart  - Restart bot
    .\bot.ps1 status   - Check status
    .\bot.ps1 logs     - Show logs
    .\bot.ps1 install  - Install dependencies
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "restart", "status", "logs", "install", "run", "help")]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MainDir = Join-Path $ProjectRoot "main"
$MainScript = Join-Path $MainDir "main.py"
$LogFile = Join-Path $MainDir "bot_log.log"
$PidFile = Join-Path $ProjectRoot "bot.pid"

function Get-BotProcess {
    if (Test-Path $PidFile) {
        $procId = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($procId) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -eq "python") {
                return $proc
            }
        }
    }
    return $null
}

function Start-Bot {
    $existing = Get-BotProcess
    if ($existing) {
        Write-Host "[!] Bot already running (PID: $($existing.Id))" -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Host "[X] Virtual environment not found. Run: .\bot.ps1 install" -ForegroundColor Red
        return
    }

    Write-Host "[*] Starting bot..." -ForegroundColor Cyan
    
    Push-Location $MainDir
    try {
        $process = Start-Process -FilePath $VenvPython -ArgumentList "main.py" `
            -WindowStyle Hidden -PassThru
        
        $process.Id | Out-File $PidFile -Force
        Start-Sleep -Seconds 3
        
        $check = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
        if ($check) {
            Write-Host "[OK] Bot started (PID: $($check.Id))" -ForegroundColor Green
        } else {
            Write-Host "[X] Failed to start bot. Check logs: .\bot.ps1 logs" -ForegroundColor Red
        }
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
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    
    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force
    }
    
    Start-Sleep -Seconds 1
    Write-Host "[OK] Bot stopped" -ForegroundColor Green
}

function Restart-Bot {
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
        Write-Host "   Uptime: $($uptime.Hours)h $($uptime.Minutes)m $($uptime.Seconds)s"
    } else {
        Write-Host "[X] Bot is not running" -ForegroundColor Red
    }
}

function Show-Logs {
    if (Test-Path $LogFile) {
        Write-Host "[*] Last 50 lines of logs:" -ForegroundColor Cyan
        Write-Host ""
        Get-Content $LogFile -Tail 50
    } else {
        Write-Host "[X] Log file not found: $LogFile" -ForegroundColor Red
    }
}

function Install-Dependencies {
    Write-Host "[*] Installing dependencies..." -ForegroundColor Cyan
    
    $reqFile = Join-Path $ProjectRoot "requirements.txt"
    $venvDir = Join-Path $ProjectRoot ".venv"
    
    if (-not (Test-Path $venvDir)) {
        Write-Host "[*] Creating virtual environment..." -ForegroundColor Yellow
        python -m venv $venvDir
    }
    
    if (Test-Path $reqFile) {
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -r $reqFile
        & $VenvPython -m pip install tabulate
        Write-Host "[OK] Dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "[X] requirements.txt not found" -ForegroundColor Red
    }
}

function Run-Bot {
    Write-Host "[*] Starting bot in foreground mode..." -ForegroundColor Cyan
    Push-Location $MainDir
    try {
        & $VenvPython main.py
    } finally {
        Pop-Location
    }
}

function Show-Help {
    Write-Host ""
    Write-Host "=== Telegram Bot Manager ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage: .\bot.ps1 [command]"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  start    - Start bot in background"
    Write-Host "  stop     - Stop bot"
    Write-Host "  restart  - Restart bot"
    Write-Host "  status   - Show bot status"
    Write-Host "  logs     - Show last 50 log lines"
    Write-Host "  run      - Run bot in foreground (debug)"
    Write-Host "  install  - Install/update dependencies"
    Write-Host "  help     - Show this help"
    Write-Host ""
}

switch ($Command) {
    "start"   { Start-Bot }
    "stop"    { Stop-Bot }
    "restart" { Restart-Bot }
    "status"  { Get-Status }
    "logs"    { Show-Logs }
    "run"     { Run-Bot }
    "install" { Install-Dependencies }
    "help"    { Show-Help }
    default   { Show-Help }
}
