# Explicitly start ResearchOS through a user Task Scheduler host.
# The task has no triggers. Registration alone never starts services.
param([switch]$SkipBuild, [switch]$Rebuild, [switch]$OpenBrowser,
    [switch]$Plan, [switch]$RegisterOnly, [int]$TimeoutSeconds = 600)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
. (Join-Path $PSScriptRoot 'durable_runtime.ps1')
. (Join-Path $PSScriptRoot 'startup_checks.ps1')
$root = Get-ResearchRoot
$definition = Get-ResearchDurablePlan $root
$xml = New-ResearchDurableXml $definition
Assert-ResearchDurableXml $xml $definition
if ($Plan) {
    $definition | Format-List
    Write-Output $xml
    return
}
if ($TimeoutSeconds -lt 5 -or $TimeoutSeconds -gt 1800) { throw 'TimeoutSeconds must be 5 to 1800.' }
if ($Rebuild -and $SkipBuild) { throw 'Choose Rebuild or SkipBuild, not both.' }
if (-not (Test-Path -LiteralPath (Join-Path $root '.env') -PathType Leaf)) { throw 'Create the root .env before starting.' }
$runDir = Join-Path $root 'data/run'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$lock = $null
$lockDeadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
while ($null -eq $lock) {
    try { $lock = [IO.File]::Open((Join-Path $runDir 'durable-client.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch [IO.IOException] {
        if ([datetime]::UtcNow -ge $lockDeadline) { throw 'Another startup is still being observed; inspect scripts/status_local.ps1.' }
        Start-Sleep -Milliseconds 500
    }
}
try {
    $folder = Get-ResearchTaskFolder
    $task = Get-ResearchTaskOrNull $folder $definition.taskName
    if ($null -eq $task) {
        # TASK_CREATE (2), never CREATE_OR_UPDATE; no OS password is supplied.
        $task = $folder.RegisterTask($definition.taskName, $xml, 2, $definition.ownerSid, $null, 3, $null)
        Write-Host "Created demand-only task: $($definition.taskName). Verifying its registered definition before starting."
    }
    Assert-ResearchDurableXml $task.Xml $definition
    if ($RegisterOnly) {
        Write-Host "Verified demand-only task: $($definition.taskName). Services were not started."
        return
    }
    $envPath = Join-Path $root '.env'
    $apiPort = Get-ResearchPort (Get-ResearchConfigValue API_PORT $envPath) 8000 'API_PORT'
    $webPort = Get-ResearchPort (Get-ResearchConfigValue WEB_PORT $envPath) 3000 'WEB_PORT'
    $statusPath = Join-Path $runDir 'durable-host.json'
    $running = $null
    $reuse = [int]$task.State -in @(2, 4)
    if ($reuse) {
        if ($Rebuild) { throw 'Stop the running platform before rebuilding; no live build was changed.' }
        $existing = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        if ($existing.workspace -ine $root -or $existing.ownerSid -cne $definition.ownerSid -or
            $existing.taskName -cne $definition.taskName) { throw 'Existing host record belongs to a different runtime.' }
        $requestId = [string]$existing.requestId
        Write-Host 'ResearchOS is already starting or running; checking the existing instance.'
    } else {
    $requestId = [guid]::NewGuid().ToString('D')
    $request = [ordered]@{
        schemaVersion = 1
        requestId = $requestId
        workspace = $root
        ownerSid = $definition.ownerSid
        createdUtc = [datetime]::UtcNow.ToString('o')
        skipBuild = -not [bool]$Rebuild
    }
    Save-ResearchRuntimeState $request (Join-Path $runDir 'durable-request.json')
    $running = $task.Run($null)
    Write-Host "Starting ResearchOS in your Windows session ($($definition.taskName))."
    }
    $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([datetime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if ($status.requestId -eq $requestId) {
                if ($status.phase -eq 'ready') {
                    if (-not (Test-ResearchProcessIdentity $status.host)) { throw 'The runtime host exited after reporting readiness.' }
                    $snapshot = (& (Join-Path $PSScriptRoot 'status_local.ps1') -Json) | ConvertFrom-Json
                    if (-not (Test-ResearchStartupReady $snapshot $apiPort $webPort)) {
                        throw 'Recorded runtime is not healthy. Run restart_researchos.cmd; see data/run logs and scripts/status_local.ps1.'
                    }
                    Write-Host "ResearchOS ready: http://127.0.0.1:$($status.webPort). Close this window; services stay in your Windows session."
                    if ($OpenBrowser) { Open-ResearchStartupBrowser $webPort }
                    return
                }
                if ($status.phase -in @('failed', 'degraded', 'stopped')) { throw "ResearchOS host is $($status.phase); run restart_researchos.cmd. Inspect data/run/durable-startup.log and durable-host.json." }
            }
        }
        if ($null -ne $running) {
            try { $running.Refresh() }
            catch {
                $cause = $_.Exception
                while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
                if ($cause -isnot [Runtime.InteropServices.COMException]) { throw }
                # Completed instances can invalidate their COM handle. Keep
                # observing the actual task and matching host rather than
                # leaking a bare HRESULT or assuming a live host has stopped.
                $running = $null
            }
        }
        if ($null -ne $running) {
            # Run is asynchronous: a fresh instance can be queued before it starts.
            if ([int]$running.State -notin @(2, 4)) { throw 'The runtime host exited before readiness; inspect data/run/durable-startup.log.' }
        } else {
            try {
                $taskState = [int]$task.State
                $taskResult = $task.LastTaskResult
            } catch {
                throw 'Runtime task observation is unavailable. Inspect the registered task and data/run/durable-host.json before retrying; no restart was attempted.'
            }
            $matchingHostAlive = $false
            if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
                $observed = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
                if ($observed.requestId -eq $requestId -and $null -ne $observed.host) {
                    $matchingHostAlive = Test-ResearchProcessIdentity $observed.host
                }
            }
            if ($taskState -notin @(2, 4) -and -not $matchingHostAlive) {
                throw "Runtime task ended (state $taskState, result $taskResult) and no matching host remains alive. Inspect data/run/durable-startup.log before retrying."
            }
        }
        Start-Sleep -Seconds 1
    }
    throw 'Startup observation timed out. The task was not stopped; inspect its actual state and data/run/durable-host.json before retrying.'
} finally { $lock.Dispose() }
