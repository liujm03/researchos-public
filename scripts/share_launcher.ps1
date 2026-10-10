# Blank-package dispatch only; existing personal installation keeps its launcher.
param([ValidateSet('start','stop','check','recover')][string]$Action='start')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
. (Join-Path $PSScriptRoot 'startup_checks.ps1')
$root=Get-ResearchRoot
$envPath=Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Run python scripts/initialize_blank.py and read INSTALL.md first.' }
$mode=Get-ResearchConfigValue RESEARCHOS_DEPLOYMENT $envPath
if ($mode -eq 'local') {
    switch ($Action) {
        'start' { & (Join-Path $PSScriptRoot 'start_durable.ps1') -OpenBrowser }
        'stop' { & (Join-Path $PSScriptRoot 'stop_local.ps1') }
        'check' { & (Join-Path $PSScriptRoot 'check_local.ps1') }
        'recover' { & (Join-Path $PSScriptRoot 'restart_durable.ps1') -OpenBrowser }
    }
    return
}
if ($mode -ne 'compose') { throw 'RESEARCHOS_DEPLOYMENT must be compose or local.' }
if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install/start your Docker Linux engine; see INSTALL.md.' }
Push-Location $root
try {
    if ($Action -eq 'stop') {
        & docker compose stop
        if ($LASTEXITCODE -ne 0) { throw 'Compose stop failed; data volumes were not removed.' }
        return
    }
    if ($Action -in @('start','recover')) {
        & docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed; inspect docker compose logs.' }
        if ($Action -eq 'recover') {
            & docker compose restart api web worker
            if ($LASTEXITCODE -ne 0) { throw 'Compose application restart failed; database volume was not removed.' }
        }
    }
    $apiIds=@(& docker compose ps --status running -q api)
    if ($LASTEXITCODE -ne 0 -or $apiIds.Count -ne 1) { throw 'This installation API container is not running.' }
    $webIds=@(& docker compose ps --status running -q web)
    if ($LASTEXITCODE -ne 0 -or $webIds.Count -ne 1) { throw 'This installation Web container is not running.' }
    $apiPort=Get-ResearchPort (Get-ResearchConfigValue API_PORT $envPath) 8100 'API_PORT'
    $webPort=Get-ResearchPort (Get-ResearchConfigValue WEB_PORT $envPath) 3100 'WEB_PORT'
    $attempts=if ($Action -in @('start','recover')) { 60 } else { 1 }
    for ($attempt=0; $attempt -lt $attempts; $attempt++) {
        if ((Test-ResearchStartupHttp "http://127.0.0.1:$apiPort/health/ready") -and
            (Test-ResearchStartupHttp "http://127.0.0.1:$webPort/login")) {
            Write-Host "ResearchOS ready: http://127.0.0.1:$webPort"
            if ($Action -in @('start','recover')) { Open-ResearchStartupBrowser $webPort }
            return
        }
        if ($Action -in @('start','recover')) { Start-Sleep -Seconds 2 }
    }
    throw 'Platform is not ready. Inspect docker compose ps/logs; do not delete the data volume.'
} finally { Pop-Location }
