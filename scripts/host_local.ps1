# Fixed Task Scheduler action. It starts only the existing local platform and
# remains alive so service children belong to the user runtime host.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
. (Join-Path $PSScriptRoot 'durable_runtime.ps1')
$root = Get-ResearchRoot
$definition = Get-ResearchDurablePlan $root
$runDir = Join-Path $root 'data/run'
$requestPath = Join-Path $runDir 'durable-request.json'
$statusPath = Join-Path $runDir 'durable-host.json'
$runtimePath = Join-Path $runDir 'local-runtime.json'
$logPath = Join-Path $runDir 'durable-startup.log'
$lock = [IO.File]::Open((Join-Path $runDir 'durable-host.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$status = $null
try {
    $request = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
    if ($request.schemaVersion -ne 1 -or $request.workspace -ine $root -or
        $request.ownerSid -cne $definition.ownerSid -or $request.skipBuild -isnot [bool]) {
        throw 'Runtime request identity or format is invalid.'
    }
    $requestGuid = [guid]::Empty
    if (-not [guid]::TryParse([string]$request.requestId, [ref]$requestGuid)) { throw 'Runtime request ID is invalid.' }
    $created = [datetimeoffset]::Parse([string]$request.createdUtc)
    $age = [datetimeoffset]::UtcNow - $created
    if ($age.TotalMinutes -gt 10 -or $age.TotalSeconds -lt -30) { throw 'Runtime request expired. Start through start_durable.ps1.' }
    $status = [ordered]@{
        schemaVersion = 1
        requestId = $request.requestId
        workspace = $root
        ownerSid = $definition.ownerSid
        taskName = $definition.taskName
        host = Get-ResearchProcessIdentity $PID
        startedUtc = [datetime]::UtcNow.ToString('o')
        updatedUtc = [datetime]::UtcNow.ToString('o')
        phase = 'starting'
        apiPort = $null
        webPort = $null
        stoppedServices = @()
    }
    if ($null -eq $status.host) { throw 'Runtime host process identity cannot be verified.' }
    Save-ResearchRuntimeState $status $statusPath
    & (Join-Path $PSScriptRoot 'start_local.ps1') -SkipBuild:$request.skipBuild *> $logPath
    $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
    if ($runtime.workspace -ine $root) { throw 'Runtime record belongs to another workspace.' }
    $envPath = Join-Path $root '.env'
    $status.apiPort = Get-ResearchPort (Get-ResearchConfigValue API_PORT $envPath) 8000 'API_PORT'
    $status.webPort = Get-ResearchPort (Get-ResearchConfigValue WEB_PORT $envPath) 3000 'WEB_PORT'
    $status.phase = 'ready'
    while (Test-Path -LiteralPath $runtimePath -PathType Leaf) {
        $unavailable = @()
        foreach ($name in @('api', 'worker', 'codexWorker', 'web', 'postgres')) {
            $serviceProperty = $runtime.PSObject.Properties[$name]
            if ($null -eq $serviceProperty) { continue }
            if ($null -ne $serviceProperty.Value -and -not (Test-ResearchProcessIdentity $serviceProperty.Value)) { $unavailable += $name }
        }
        $status.stoppedServices = $unavailable
        $status.phase = if ($unavailable.Count -gt 0) { 'degraded' } else { 'ready' }
        $status.updatedUtc = [datetime]::UtcNow.ToString('o')
        Save-ResearchRuntimeState $status $statusPath
        # No restart: retain the host and report failure for owner inspection.
        Start-Sleep -Seconds 3
    }
    $status.phase = 'stopped'
    $status.updatedUtc = [datetime]::UtcNow.ToString('o')
    Save-ResearchRuntimeState $status $statusPath
} catch {
    if ($null -ne $status) {
        $status.phase = 'failed'
        $status.updatedUtc = [datetime]::UtcNow.ToString('o')
        Save-ResearchRuntimeState $status $statusPath
    }
    # Logs are private, ignored runtime files; status does not expose env values.
    $_ | Out-String | Add-Content -LiteralPath $logPath -Encoding utf8
    exit 1
} finally { $lock.Dispose() }
