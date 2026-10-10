# Owner-invoked diagnosis. No service changes, vendor calls or credentials export.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
. (Join-Path $PSScriptRoot 'startup_checks.ps1')
$root = Get-ResearchRoot
$envPath = Join-Path $root '.env'
$configurationPresent = Test-Path -LiteralPath $envPath -PathType Leaf
$configurationReadable = $configurationPresent
$apiPort = 8000
$webPort = 3000
if ($configurationPresent) {
    try {
        $apiPort = Get-ResearchPort (Get-ResearchConfigValue API_PORT $envPath) 8000 'API_PORT'
        $webPort = Get-ResearchPort (Get-ResearchConfigValue WEB_PORT $envPath) 3000 'WEB_PORT'
    } catch { $configurationReadable = $false }
}
$snapshot = (& (Join-Path $PSScriptRoot 'status_local.ps1') -Json) | ConvertFrom-Json
$healthy = $configurationReadable -and (Test-ResearchStartupReady $snapshot $apiPort $webPort)
$report = [ordered]@{
    schemaVersion = 1
    observedUtc = [datetime]::UtcNow.ToString('o')
    ready = $healthy
    runtime = $snapshot
    files = [ordered]@{
        configurationPresent = $configurationPresent
        configurationReadable = $configurationReadable
        pythonPresent = Test-Path -LiteralPath (Join-Path $root '.venv/Scripts/python.exe') -PathType Leaf
        independentPythonPresent = Test-Path -LiteralPath (Join-Path $root 'data/runtime/python/python.exe') -PathType Leaf
        productionBuildPresent = Test-Path -LiteralPath (Join-Path $root 'apps/web/.next/BUILD_ID') -PathType Leaf
        databasePresent = Test-Path -LiteralPath (Join-Path $root 'data/postgresql17/PG_VERSION') -PathType Leaf
    }
    webUrl = "http://127.0.0.1:$webPort"
    nextAction = if ($healthy) { 'OPEN_SYSTEM' } else { 'START_OR_EXPLICIT_RECOVERY' }
}
$runDir = Join-Path $root 'data/run'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$reportPath = Join-Path $runDir 'system-check.json'
Save-ResearchRuntimeState $report $reportPath
Write-Host "ResearchOS runtime: $($snapshot.state)"
Write-Host "Identity + listener + HTTP readiness: $healthy"
Write-Host "Current report: $reportPath"
if ($healthy) { Write-Host "Open: $($report.webUrl)" }
else {
    Write-Host ('Issues: ' + ($snapshot.issues -join ', '))
    Write-Host 'Run start_researchos.cmd; for a degraded runtime use restart_researchos.cmd.'
    exit 1
}
