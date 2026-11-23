param(
    [Parameter(Position = 0)]
    [string]$Backup,
    [switch]$Force,
    [string]$EnvFile = $env:ENV_FILE,
    [string]$ComposeFile = $env:COMPOSE_FILE,
    [string]$DbService = $env:DB_SERVICE,
    [string]$PostgresUser = $env:POSTGRES_USER,
    [string]$PostgresDb = $env:POSTGRES_DB
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Backup)) {
    throw "Usage: .\scripts\restore_postgres.ps1 -Backup backups\file.dump [-Force]"
}
if (-not (Test-Path -LiteralPath $Backup)) {
    throw "Backup file not found: $Backup"
}

if ([string]::IsNullOrWhiteSpace($EnvFile)) { $EnvFile = ".env" }
if ([string]::IsNullOrWhiteSpace($ComposeFile)) { $ComposeFile = "docker-compose.yml" }
if ([string]::IsNullOrWhiteSpace($DbService)) { $DbService = "postgres" }

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

if (-not $Force) {
    Write-Host "This will overwrite objects in database '$PostgresDb' using '$Backup'."
    $confirmation = Read-Host "Type RESTORE to continue"
    if ($confirmation -ne "RESTORE") {
        Write-Host "Restore cancelled."
        exit 1
    }
}

$containerOutput = & docker compose -f $ComposeFile ps -q $DbService
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not inspect service '$DbService'." }
$containerId = ($containerOutput | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($containerId)) { throw "Could not find running container for service '$DbService'." }

$containerBackup = "/tmp/restore_$([System.IO.Path]::GetFileName($Backup))"
Write-Host "Copying backup into service '$DbService'..."
& docker cp $Backup "${containerId}:$containerBackup"
if ($LASTEXITCODE -ne 0) { throw "Failed to copy backup into container." }

Write-Host "Restoring PostgreSQL backup into database '$PostgresDb'..."
& docker compose -f $ComposeFile exec -T $DbService pg_restore --clean --if-exists --no-owner -U $PostgresUser -d $PostgresDb $containerBackup
$restoreCode = $LASTEXITCODE
& docker compose -f $ComposeFile exec -T $DbService rm -f $containerBackup | Out-Null
if ($restoreCode -ne 0) { throw "Restore failed." }

Write-Host "Restore completed."
