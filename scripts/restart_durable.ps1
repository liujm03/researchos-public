# Explicit owner recovery only. Stop verified platform processes, preserve PG.
param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
. (Join-Path $PSScriptRoot 'durable_runtime.ps1')
$root = Get-ResearchRoot
$definition = Get-ResearchDurablePlan $root
$runDir = Join-Path $root 'data/run'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
# Exclude a simultaneous startup during stop; subsequent start can safely reuse.
try { $lock = [IO.File]::Open((Join-Path $runDir 'durable-client.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
catch [IO.IOException] { throw 'Another startup or recovery is active; wait before retrying.' }
try {
$task = Get-ResearchTaskOrNull (Get-ResearchTaskFolder) $definition.taskName
if ($null -ne $task) { Assert-ResearchDurableXml $task.Xml $definition }
$hostPath = Join-Path $root 'data/run/durable-host.json'
$record = $null
if (Test-Path -LiteralPath $hostPath -PathType Leaf) {
    $record = Get-Content -LiteralPath $hostPath -Raw | ConvertFrom-Json
    if ($record.workspace -ine $root -or $record.ownerSid -cne $definition.ownerSid -or
        $record.taskName -cne $definition.taskName) { throw 'Host identity mismatch; recovery refused.' }
    if ($record.phase -eq 'starting' -and (Test-ResearchProcessIdentity $record.host)) {
        throw 'Startup is still active; wait for it to finish before recovery.'
    }
}
& (Join-Path $PSScriptRoot 'stop_local.ps1') -KeepPostgres
if (Test-Path -LiteralPath (Join-Path $root 'data/run/local-runtime.json')) {
    throw 'Some processes could not be verified; runtime record retained. Recovery did not start another instance.'
}
if ($null -ne $record -and (Test-ResearchProcessIdentity $record.host)) {
    # Allow the host to observe the explicit stop; bounded fallback uses exact identity.
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        if (-not (Test-ResearchProcessIdentity $record.host)) { break }
        Start-Sleep -Seconds 1
    }
    if (Test-ResearchProcessIdentity $record.host) {
        $result = Stop-ResearchIdentifiedProcess $record.host
        if ($result -ne 'stopped') { throw 'Host identity changed; recovery refused.' }
    }
}
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    $task = Get-ResearchTaskOrNull (Get-ResearchTaskFolder) $definition.taskName
    if ($null -eq $task -or [int]$task.State -notin @(2, 4)) { break }
    Start-Sleep -Seconds 1
}
if ($null -ne $task -and [int]$task.State -in @(2, 4)) { throw 'Previous scheduled host is still active; no duplicate instance started.' }
} finally { $lock.Dispose() }
& (Join-Path $PSScriptRoot 'start_durable.ps1') -OpenBrowser:$OpenBrowser
