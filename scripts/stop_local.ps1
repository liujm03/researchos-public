# Stop only processes recorded by start_local.ps1 with matching process identity.
param([switch]$KeepPostgres)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')

$root = Get-ResearchRoot
$statePath = Join-Path $root 'data/run/local-runtime.json'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    Write-Host 'No ResearchOS local runtime record was found.'
    return
}
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.workspace -ine $root) { throw 'Runtime record belongs to another workspace; refusing to stop processes.' }
$skipped = $false

foreach ($name in @('web', 'codexWorker', 'worker', 'api')) {
    $serviceProperty = $state.PSObject.Properties[$name]
    if ($null -eq $serviceProperty) { continue } # Optional Codex worker was not recorded by older versions.
    $expected = $serviceProperty.Value
    if ($null -eq $expected) { continue }
    $childProperty = $state.PSObject.Properties["${name}Children"]
    $recorded = if ($null -ne $childProperty) { @($childProperty.Value) } else { @() }
    $result = Stop-ResearchTrackedTree $expected $recorded
    if ($result.stopped.Count -gt 0) {
        Write-Host "Stopped $name process tree: $($result.stopped -join ', ')."
    }
    if ($result.mismatched.Count -gt 0) {
        Write-Host "Skipped ${name}: process identity changed for PID $($result.mismatched -join ', ')."
        $skipped = $true
    }
}

if (-not $KeepPostgres -and $null -ne $state.postgres) {
    $expected = $state.postgres
    $pgCtl = Join-Path $state.postgresBin 'pg_ctl.exe'
    $pidFile = Join-Path $state.postgresData 'postmaster.pid'
    if ((Test-ResearchProcessIdentity $expected) -and
        (Test-Path -LiteralPath $pgCtl -PathType Leaf) -and
        (Test-Path -LiteralPath $pidFile -PathType Leaf) -and
        ([int](Get-Content -LiteralPath $pidFile -TotalCount 1) -eq [int]$expected.pid)) {
        & $pgCtl -D $state.postgresData -m fast -w stop
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not stop; runtime record retained.' }
        Write-Host "Stopped PostgreSQL (PID $($expected.pid))."
        if ($state.postgresDriveCreated -and
            (Get-ResearchSubstTarget $state.postgresDrive) -ieq $root.TrimEnd('\')) {
            & subst $state.postgresDrive /D
            if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL stopped, but its drive mapping could not be released.' }
            Write-Host "Released temporary drive mapping $($state.postgresDrive)."
        }
    } elseif ($null -eq (Get-Process -Id $expected.pid -ErrorAction SilentlyContinue)) {
        # A previous crash can leave the record after PostgreSQL has exited.
        # Only release our subst mapping when pg_ctl also reports no server.
        $serverRunning = $false
        if (Test-Path -LiteralPath $pgCtl -PathType Leaf) {
            & $pgCtl -D $state.postgresData status *> $null
            $serverRunning = $LASTEXITCODE -eq 0
        }
        if ($serverRunning) {
            Write-Host 'Skipped PostgreSQL: another server now uses the recorded data directory.'
            $skipped = $true
        } else {
            Write-Host 'PostgreSQL was already stopped.'
            if ($state.postgresDriveCreated -and
                (Get-ResearchSubstTarget $state.postgresDrive) -ieq $root.TrimEnd('\')) {
                & subst $state.postgresDrive /D
                if ($LASTEXITCODE -ne 0) { throw 'Could not release stale PostgreSQL drive mapping.' }
            }
        }
    } else {
        Write-Host 'Skipped PostgreSQL: process identity or data directory no longer matches.'
        $skipped = $true
    }
}

if ($skipped) {
    Write-Host 'Some recorded processes could not be verified; runtime record retained for inspection.'
} else {
    Remove-Item -LiteralPath $statePath
    Write-Host 'ResearchOS local runtime stopped.'
}
