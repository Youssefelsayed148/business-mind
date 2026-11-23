param(
    [string]$EnvFile = $env:ENV_FILE,
    [string]$ComposeFile = $env:COMPOSE_FILE,
    [string]$DbService = $env:DB_SERVICE,
    [string]$PostgresUser = $env:POSTGRES_USER,
    [string]$PostgresDb = $env:POSTGRES_DB,
    [string]$BackupDir = $env:BACKUP_DIR
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($EnvFile)) { $EnvFile = ".env" }
if ([string]::IsNullOrWhiteSpace($ComposeFile)) { $ComposeFile = "docker-compose.yml" }
if ([string]::IsNullOrWhiteSpace($DbService)) { $DbService = "postgres" }
if ([string]::IsNullOrWhiteSpace($BackupDir)) { $BackupDir = "backups" }

function Get-EnvValue {
    param([string]$Key)
    if (-not (Test-Path -LiteralPath $EnvFile)) { return $null }
    $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match "^\s*$([regex]::Escape($Key))=" } | Select-Object -Last 1
    if (-not $line) { return $null }
    return (($line -replace "^\s*$([regex]::Escape($Key))=", "") -replace '^"|"$', "")
}

if ([string]::IsNullOrWhiteSpace($PostgresUser)) { $PostgresUser = Get-EnvValue "POSTGRES_USER" }
if ([string]::IsNullOrWhiteSpace($PostgresDb)) { $PostgresDb = Get-EnvValue "POSTGRES_DB" }
if ([string]::IsNullOrWhiteSpace($PostgresUser)) { $PostgresUser = "postgres" }
if ([string]::IsNullOrWhiteSpace($PostgresDb)) { $PostgresDb = "postgres" }

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$backupFile = Join-Path $BackupDir "postgres_${PostgresDb}_${timestamp}.dump"

Write-Host "Creating PostgreSQL backup from service '$DbService' database '$PostgresDb'..."
$containerOutput = & docker compose -f $ComposeFile ps -q $DbService
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not inspect service '$DbService'." }
$containerId = ($containerOutput | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($containerId)) { throw "Could not find running container for service '$DbService'." }
$containerBackup = "/tmp/postgres_${PostgresDb}_${timestamp}.dump"
& docker compose -f $ComposeFile exec -T $DbService pg_dump -U $PostgresUser -d $PostgresDb -Fc -f $containerBackup
if ($LASTEXITCODE -ne 0) {
    throw "Backup failed."
}
& docker cp "${containerId}:$containerBackup" $backupFile
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath $backupFile) { Remove-Item -LiteralPath $backupFile -Force }
    throw "Failed to copy backup from container."
}
& docker compose -f $ComposeFile exec -T $DbService rm -f $containerBackup | Out-Null
Write-Host "Backup created: $backupFile"
