param(
    [string]$Snapshot,
    [ValidateSet('custom', 'plain')][string]$SnapshotFormat = 'custom',
    [int]$LeadRows = 100000,
    [int]$MessagesPerLead = 3,
    [string]$PostgresContainer = 'manyosirischat-postgres-1',
    [string]$BackendContainer = 'manyosirischat-backend-1',
    [string]$PostgresUser = 'postgres',
    [string]$Report = "$PSScriptRoot/../docs/whatsapp-outreach-migration-rehearsal.json",
    [switch]$KeepDatabase
)
$ErrorActionPreference = 'Stop'
$database = 'wa_rehearsal_' + [guid]::NewGuid().ToString('N')
$runner = "/tmp/$database.py"
$dump = "/tmp/$database.dump"
$remoteReport = "/tmp/$database.json"
$rehearsalSucceeded = $false
function Invoke-DockerChecked {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
if ($Snapshot) {
    $resolvedSnapshot = (Resolve-Path -LiteralPath $Snapshot).Path
    if (-not (Test-Path -LiteralPath $resolvedSnapshot -PathType Leaf)) { throw 'Snapshot must be a pg_dump file.' }
}
Invoke-DockerChecked exec $PostgresContainer createdb -U $PostgresUser $database
try {
    Invoke-DockerChecked cp "$PSScriptRoot/rehearse_whatsapp_migrations.py" "${BackendContainer}:$runner"
    $runnerArgs = @('--database-name', $database, '--backend-dir', '/app', '--report', $remoteReport,
                    '--lead-rows', "$LeadRows", '--messages-per-lead', "$MessagesPerLead")
    if ($Snapshot) {
        Invoke-DockerChecked cp $resolvedSnapshot "${PostgresContainer}:$dump"
        if ($SnapshotFormat -eq 'custom') {
            Invoke-DockerChecked exec $PostgresContainer pg_restore -U $PostgresUser --no-owner --no-acl --exit-on-error -d $database $dump
        } else {
            # Plain dumps must be database-local (no --create / \connect directives).
            if (Select-String -LiteralPath $resolvedSnapshot -Pattern '^\\connect|^CREATE DATABASE' -Quiet) {
                throw 'Use a database-local pg_dump without --create.'
            }
            Invoke-DockerChecked exec $PostgresContainer psql -U $PostgresUser -v ON_ERROR_STOP=1 -d $database -f $dump
        }
        $runnerArgs += '--snapshot-restored'
    }
    Invoke-DockerChecked exec -e APP_ENV=test -e RATE_LIMIT_ENABLED=false $BackendContainer python $runner @runnerArgs
    Invoke-DockerChecked cp "${BackendContainer}:$remoteReport" $Report
    $rehearsalSucceeded = $true
    Write-Host "Rehearsal passed; report: $Report"
} finally {
    if (-not $rehearsalSucceeded) {
        & docker exec $BackendContainer test -f $remoteReport
        if ($LASTEXITCODE -eq 0) {
            & docker cp "${BackendContainer}:$remoteReport" $Report
            if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not export failed rehearsal report.' }
        }
    }
    & docker exec $BackendContainer rm -f $runner $remoteReport
    if ($Snapshot) { & docker exec $PostgresContainer rm -f $dump }
    if (-not $KeepDatabase) {
        & docker exec $PostgresContainer dropdb -U $PostgresUser --if-exists --force $database
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not remove disposable database $database" }
    } else { Write-Host "Retained disposable database: $database" }
}
