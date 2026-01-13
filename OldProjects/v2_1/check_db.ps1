# Database status check script
# Sets UTF-8 encoding for proper output

# Set UTF-8 encoding for PowerShell console
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$PSQL_PATH = "C:\Program Files\PostgreSQL\18\bin\psql.exe"

if (-not (Test-Path $PSQL_PATH)) {
    Write-Host "Error: psql.exe not found at: $PSQL_PATH" -ForegroundColor Red
    Write-Host "Please specify the correct path to PostgreSQL in the script" -ForegroundColor Yellow
    exit 1
}

$DB_USER = if ($env:DB_USER) { $env:DB_USER } else { "tbot" }
$DB_NAME = if ($env:DB_NAME) { $env:DB_NAME } else { "tbot" }
$DB_HOST = if ($env:DB_HOST) { $env:DB_HOST } else { "localhost" }
$DB_PORT = if ($env:DB_PORT) { $env:DB_PORT } else { "5432" }

Write-Host ("=" * 60)
Write-Host "Database Status Check"
Write-Host ("=" * 60)
Write-Host "Connecting to: ${DB_HOST}:${DB_PORT}/${DB_NAME} as ${DB_USER}"
Write-Host ""

# Get password from environment variable or prompt
$DB_PASSWORD = if ($env:DB_PASSWORD) { $env:DB_PASSWORD } else { 
    $securePassword = Read-Host "Enter password for user $DB_USER" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

# Set environment variable for psql
$env:PGPASSWORD = $DB_PASSWORD

Write-Host "1. Database schemas:" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast') ORDER BY schema_name;"

Write-Host "`n2. Alembic migration version:" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "SELECT version_num FROM core.alembic_version;"

Write-Host "`n3. Tables in schema 'core':" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "\dt core.*"

Write-Host "`n4. Tables in schema 'telegram':" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "\dt telegram.*"

Write-Host "`n5. Tables in schema 'employees':" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "\dt employees.*"

Write-Host "`n6. Tables in schema 'monitoring':" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "\dt monitoring.*"

Write-Host "`n7. Tables in schema 'otrs':" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "\dt otrs.*"

Write-Host "`n8. Tables in schema 'cluster':" -ForegroundColor Cyan
& $PSQL_PATH -U $DB_USER -d $DB_NAME -h $DB_HOST -p $DB_PORT -c "\dt cluster.*"

Write-Host "`n" + ("=" * 60)
Write-Host "Check completed!" -ForegroundColor Green
Write-Host ("=" * 60)

# Clear environment variable
$env:PGPASSWORD = $null
