# Start the local PostgreSQL, API, worker and production Web on Windows.
param(
    [string]$PostgresBin = '',
    [string]$PostgresData = '',
    [string]$PostgresDrive = 'R:',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')

$root = Get-ResearchRoot
$envPath = Join-Path $root '.env'
$runDir = Join-Path $root 'data/run'
$statePath = Join-Path $runDir 'local-runtime.json'
$apiDir = Join-Path $root 'apps/api'
$webDir = Join-Path $root 'apps/web'
$python = Join-Path $root '.venv/Scripts/python.exe'
$nextCli = Join-Path $webDir 'node_modules/next/dist/bin/next'
$started = [ordered]@{}
$startedChildren = [ordered]@{}
$postgresStarted = $false
$driveCreated = $false
$pgCtl = $null
$previousApiInternalUrl = [Environment]::GetEnvironmentVariable('API_INTERNAL_URL', 'Process')
$previousNextTelemetry = [Environment]::GetEnvironmentVariable('NEXT_TELEMETRY_DISABLED', 'Process')
$previousMaxUploadMb = [Environment]::GetEnvironmentVariable('MAX_UPLOAD_MB', 'Process')

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) { throw 'Create the root .env from .env.example before starting.' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python .venv is missing; install apps/api dependencies first.' }
if (-not (Test-Path -LiteralPath $nextCli -PathType Leaf)) { throw 'Next.js dependencies are missing; run pnpm install first.' }

$node = Get-ResearchConfigValue WEB_NODE_EXE $envPath
if ([string]::IsNullOrWhiteSpace($node)) {
    $node = Join-Path $root 'data/runtime/node/node.exe'
    if (-not (Test-Path -LiteralPath $node -PathType Leaf)) {
        $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
        if ($null -eq $nodeCommand) { throw 'Node.js is missing; install it or set WEB_NODE_EXE in .env.' }
        $node = $nodeCommand.Source
    }
} elseif (-not [IO.Path]::IsPathRooted($node)) {
    $node = Join-Path $root $node
}
if (-not (Test-Path -LiteralPath $node -PathType Leaf)) { throw 'WEB_NODE_EXE does not point to an existing executable.' }
$node = (Resolve-Path -LiteralPath $node).Path
$apiPort = Get-ResearchPort (Get-ResearchConfigValue API_PORT $envPath) 8000 'API_PORT'
$webPort = Get-ResearchPort (Get-ResearchConfigValue WEB_PORT $envPath) 3000 'WEB_PORT'
if ($apiPort -eq $webPort) { throw 'API_PORT and WEB_PORT must differ.' }
$databaseUrl = Get-ResearchConfigValue DATABASE_URL $envPath
if ([string]::IsNullOrWhiteSpace($databaseUrl) -or $databaseUrl -notmatch '^postgresql(?:\+psycopg)?://') {
    throw 'DATABASE_URL must point to a local PostgreSQL database.'
}
$databaseUri = [uri]$databaseUrl
if ($databaseUri.Host -notin @('localhost', '127.0.0.1', '[::1]', '::1')) {
    throw 'start_local.ps1 only accepts loopback PostgreSQL; use Compose or a separate deployment for remote databases.'
}
$pgPort = if ($databaseUri.IsDefaultPort) { 5432 } else { $databaseUri.Port }

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
if (Test-Path -LiteralPath $statePath) {
    $old = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($old.workspace -ine $root) { throw 'Runtime record belongs to another workspace.' }
    foreach ($name in @('api', 'worker', 'codexWorker', 'web', 'postgres')) {
        $serviceProperty = $old.PSObject.Properties[$name]
        if ($null -eq $serviceProperty) { continue } # Optional service absent in legacy records.
        if ($null -ne $serviceProperty.Value -and (Test-ResearchProcessIdentity $serviceProperty.Value)) {
            throw "ResearchOS $name is already running; use scripts/stop_local.ps1 before restarting."
        }
        $childProperty = $old.PSObject.Properties["${name}Children"]
        if ($null -ne $childProperty) {
            foreach ($child in @($childProperty.Value)) {
                if ($null -ne $child -and (Test-ResearchProcessIdentity $child)) {
                    throw "ResearchOS $name child is still running; use scripts/stop_local.ps1 before restarting."
                }
            }
        }
    }
    Remove-Item -LiteralPath $statePath
}
foreach ($port in @($apiPort, $webPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "TCP port $port is already in use."
    }
}

if ([string]::IsNullOrWhiteSpace($PostgresBin)) { $PostgresBin = Join-Path $root 'data/runtime/postgresql/pgsql/bin' }
if ([string]::IsNullOrWhiteSpace($PostgresData)) { $PostgresData = Join-Path $root 'data/postgresql17' }
$PostgresBin = [IO.Path]::GetFullPath($PostgresBin)
$PostgresData = [IO.Path]::GetFullPath($PostgresData)
$pgCtl = Join-Path $PostgresBin 'pg_ctl.exe'
if ($PostgresDrive -notmatch '^[A-Za-z]:$') { throw 'PostgresDrive must be one drive letter, such as R:.' }
$PostgresDrive = $PostgresDrive.ToUpperInvariant()

function Start-TrackedProcess {
    param([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory)
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir "$Name.stdout.log") `
        -RedirectStandardError (Join-Path $runDir "$Name.stderr.log")
    $identity = $null
    for ($attempt = 0; $attempt -lt 15 -and $null -eq $identity; $attempt++) {
        Start-Sleep -Milliseconds 200
        $identity = Get-ResearchProcessIdentity -Id $process.Id
        if ($process.HasExited) { break }
    }
    if ($null -eq $identity -or $process.HasExited) {
        if (-not $process.HasExited) { $process.Kill() }
        throw "$Name exited immediately or could not be identified; inspect data/run/$Name.stderr.log."
    }
    $started[$Name] = $identity
}

function Wait-ResearchHttp {
    param([string]$Url, [string]$Name, [int]$Seconds = 45)
    for ($attempt = 0; $attempt -lt $Seconds; $attempt++) {
        if ($started.Contains($Name) -and -not (Test-ResearchProcessIdentity $started[$Name])) {
            throw "$Name exited; inspect data/run/$Name.stderr.log."
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "$Name did not become ready at $Url; inspect data/run/$Name.stderr.log."
}

function Confirm-ResearchPortOwner {
    param([string]$Name, [int]$Port)
    $children = @(Get-ResearchDescendantIdentities $started[$Name])
    $startedChildren[$Name] = $children
    $knownPids = @([int]$started[$Name].pid) + @($children | ForEach-Object { [int]$_.pid })
    $listening = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (-not ($listening | Where-Object { $knownPids -contains [int]$_.OwningProcess })) {
        throw "$Name health endpoint is not owned by its recorded process tree."
    }
}

try {
    $env:NEXT_TELEMETRY_DISABLED = '1'
    $configuredUploadMb = Get-ResearchConfigValue MAX_UPLOAD_MB $envPath
    $env:MAX_UPLOAD_MB = if ([string]::IsNullOrWhiteSpace($configuredUploadMb)) { '100' } else { $configuredUploadMb }
    if ((Test-Path -LiteralPath $pgCtl -PathType Leaf) -and (Test-Path -LiteralPath $PostgresData -PathType Container)) {
        # PostgreSQL's Windows initdb/pg_ctl may reject non-ASCII data paths.
        # A pre-existing subst mapping is reused and never removed by this script.
        if (($PostgresBin + $PostgresData) -match '[^\x00-\x7F]') {
            $mappedTo = Get-ResearchSubstTarget $PostgresDrive
            if ($null -ne $mappedTo -and $mappedTo -ine $root.TrimEnd('\')) {
                throw "$PostgresDrive is already mapped to a different directory."
            }
            if ($null -eq $mappedTo) {
                if (Test-Path -LiteralPath "$PostgresDrive\") {
                    throw "$PostgresDrive is already in use; choose another drive with -PostgresDrive."
                }
                & subst $PostgresDrive $root
                if ($LASTEXITCODE -ne 0) { throw "Could not create the $PostgresDrive workspace mapping." }
                $driveCreated = $true
            }
            $PostgresBin = Convert-ResearchPathToDrive $PostgresBin $root $PostgresDrive
            $PostgresData = Convert-ResearchPathToDrive $PostgresData $root $PostgresDrive
            $pgCtl = Join-Path $PostgresBin 'pg_ctl.exe'
        }
        & $pgCtl -D $PostgresData status *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Starting local PostgreSQL...'
            $pgLog = Join-Path $runDir 'postgres.log'
            if ($PostgresData.StartsWith("$PostgresDrive\", [StringComparison]::OrdinalIgnoreCase)) {
                $pgLog = Convert-ResearchPathToDrive $pgLog $root $PostgresDrive
            }
            $pgArguments = @('-D', ('"' + $PostgresData.TrimEnd('\') + '"'),
                '-l', ('"' + $pgLog + '"'), '-o', ('"-h 127.0.0.1 -p ' + $pgPort + '"'),
                '-w', '-t', '30', 'start')
            $pgExitCode = Invoke-ResearchNativeLauncher -FilePath $pgCtl -Arguments $pgArguments `
                -WorkingDirectory $PostgresBin -StdoutPath (Join-Path $runDir 'postgres-start.stdout.log') `
                -StderrPath (Join-Path $runDir 'postgres-start.stderr.log') -TimeoutMilliseconds 35000
            if ($pgExitCode -ne 0) { throw 'PostgreSQL failed to start; inspect data/run/postgres.log and postgres-start.stderr.log.' }
            $postgresStarted = $true
            $pgPidPath = Join-Path $PostgresData 'postmaster.pid'
            $pgPid = [int](Get-Content -LiteralPath $pgPidPath -TotalCount 1)
            $started['postgres'] = Get-ResearchProcessIdentity -Id $pgPid
            if ($null -eq $started['postgres']) { throw 'PostgreSQL process identity could not be verified.' }
        } else {
            Write-Host 'Using an already running PostgreSQL instance; it will remain running on stop.'
            if ($driveCreated) {
                & subst $PostgresDrive /D
                if ($LASTEXITCODE -ne 0) { throw "Could not release unused $PostgresDrive mapping." }
                $driveCreated = $false
            }
        }
    } else {
        Write-Host 'Using an externally managed PostgreSQL instance.'
    }

    Push-Location $apiDir
    try {
        Write-Host 'Applying database migrations; logs: data/run/migration.stdout.log and migration.stderr.log.'
        $migrationExitCode = Invoke-ResearchNativeLauncher -FilePath $python `
            -Arguments @('-m', 'alembic', 'upgrade', 'head') -WorkingDirectory $apiDir `
            -StdoutPath (Join-Path $runDir 'migration.stdout.log') `
            -StderrPath (Join-Path $runDir 'migration.stderr.log') -TimeoutMilliseconds 120000
        if ($migrationExitCode -ne 0) { throw 'Alembic migration failed; inspect data/run/migration.stderr.log.' }
        Write-Host 'Checking configuration; logs: data/run/doctor.stdout.log and doctor.stderr.log.'
        $doctorExitCode = Invoke-ResearchNativeLauncher -FilePath $python `
            -Arguments @('-m', 'app.doctor', '--connect') -WorkingDirectory $apiDir `
            -StdoutPath (Join-Path $runDir 'doctor.stdout.log') `
            -StderrPath (Join-Path $runDir 'doctor.stderr.log') -TimeoutMilliseconds 120000
        if ($doctorExitCode -ne 0) { throw 'Configuration doctor failed; inspect data/run/doctor.stdout.log and doctor.stderr.log.' }
    } finally { Pop-Location }

    $pdfAssetsScript = Join-Path $webDir 'scripts/sync-pdfjs-assets.mjs'
    if (Test-Path -LiteralPath $pdfAssetsScript -PathType Leaf) {
        $pdfAssetsExitCode = Invoke-ResearchNativeLauncher -FilePath $node `
            -Arguments @('scripts/sync-pdfjs-assets.mjs') -WorkingDirectory $webDir `
            -StdoutPath (Join-Path $runDir 'pdf-assets.stdout.log') `
            -StderrPath (Join-Path $runDir 'pdf-assets.stderr.log') -TimeoutMilliseconds 120000
        if ($pdfAssetsExitCode -ne 0) { throw 'Local PDF viewer assets could not be prepared; inspect data/run/pdf-assets.stderr.log.' }
    }

    if (-not $SkipBuild -or -not (Test-Path -LiteralPath (Join-Path $webDir '.next/BUILD_ID'))) {
        Write-Host 'Building Next.js; logs: data/run/build.stdout.log and build.stderr.log.'
        Push-Location $webDir
        try {
            $env:API_INTERNAL_URL = "http://127.0.0.1:$apiPort"
            $buildExitCode = Invoke-ResearchNativeLauncher -FilePath $node `
                -Arguments @('node_modules/next/dist/bin/next', 'build') -WorkingDirectory $webDir `
                -StdoutPath (Join-Path $runDir 'build.stdout.log') `
                -StderrPath (Join-Path $runDir 'build.stderr.log') -TimeoutMilliseconds 600000
            if ($buildExitCode -ne 0) { throw 'Next.js build failed; inspect data/run/build.stdout.log and build.stderr.log.' }
        } finally { Pop-Location }
    }

    Write-Host 'Starting FastAPI...'
    Start-TrackedProcess 'api' $python @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$apiPort") $apiDir
    Wait-ResearchHttp "http://127.0.0.1:$apiPort/health/ready" 'api'
    Confirm-ResearchPortOwner 'api' $apiPort

    Write-Host 'Starting research worker...'
    Start-TrackedProcess 'worker' $python @('-m', 'app.worker') $apiDir

    if (Test-ResearchCodexWorkerEnabled $envPath) {
        Write-Host 'Starting optional Codex worker...'
        Start-TrackedProcess 'codexWorker' $python @('-m', 'app.codex_worker') $apiDir
    }

    Write-Host 'Starting Next.js...'
    $env:API_INTERNAL_URL = "http://127.0.0.1:$apiPort"
    Start-TrackedProcess 'web' $node @('node_modules/next/dist/bin/next', 'start', '-H', '127.0.0.1', '-p', "$webPort") $webDir
    Wait-ResearchHttp "http://127.0.0.1:$webPort/login" 'web'
    Confirm-ResearchPortOwner 'web' $webPort
    if (-not (Test-ResearchProcessIdentity $started['worker'])) {
        throw 'Research worker exited; inspect data/run/worker.stderr.log.'
    }
    $startedChildren['worker'] = @(Get-ResearchDescendantIdentities $started['worker'])
    $startedChildren['api'] = @(Get-ResearchDescendantIdentities $started['api'])
    $startedChildren['web'] = @(Get-ResearchDescendantIdentities $started['web'])
    if ($started.Contains('codexWorker')) {
        if (-not (Test-ResearchProcessIdentity $started['codexWorker'])) {
            throw 'Codex worker exited; inspect data/run/codexWorker.stderr.log.'
        }
        $startedChildren['codexWorker'] = @(Get-ResearchDescendantIdentities $started['codexWorker'])
    }

    $state = [ordered]@{
        workspace = $root
        api = $started['api']
        apiChildren = $startedChildren['api']
        worker = $started['worker']
        workerChildren = $startedChildren['worker']
        codexWorker = if ($started.Contains('codexWorker')) { $started['codexWorker'] } else { $null }
        codexWorkerChildren = if ($startedChildren.Contains('codexWorker')) { $startedChildren['codexWorker'] } else { @() }
        web = $started['web']
        webChildren = $startedChildren['web']
        postgres = if ($postgresStarted) { $started['postgres'] } else { $null }
        postgresData = if ($postgresStarted) { $PostgresData } else { $null }
        postgresBin = if ($postgresStarted) { $PostgresBin } else { $null }
        postgresDrive = if ($postgresStarted) { $PostgresDrive } else { $null }
        postgresDriveCreated = $driveCreated
    }
    Save-ResearchRuntimeState $state $statePath
    Write-Host "ResearchOS ready: http://127.0.0.1:$webPort (API http://127.0.0.1:$apiPort)."
} catch {
    foreach ($name in @('web', 'codexWorker', 'worker', 'api')) {
        if ($started.Contains($name)) {
            $recorded = if ($startedChildren.Contains($name)) { @($startedChildren[$name]) } else { @() }
            Stop-ResearchTrackedTree $started[$name] $recorded | Out-Null
        }
    }
    if ($postgresStarted -and $started.Contains('postgres') -and
        $null -ne $started['postgres'] -and (Test-ResearchProcessIdentity $started['postgres'])) {
        & $pgCtl -D $PostgresData -m fast -w stop *> $null
    }
    if ($driveCreated -and (Get-ResearchSubstTarget $PostgresDrive) -ieq $root.TrimEnd('\')) {
        & $pgCtl -D $PostgresData status *> $null
        if ($LASTEXITCODE -ne 0) { & subst $PostgresDrive /D }
    }
    throw
} finally {
    [Environment]::SetEnvironmentVariable('API_INTERNAL_URL', $previousApiInternalUrl, 'Process')
    [Environment]::SetEnvironmentVariable('NEXT_TELEMETRY_DISABLED', $previousNextTelemetry, 'Process')
    [Environment]::SetEnvironmentVariable('MAX_UPLOAD_MB', $previousMaxUploadMb, 'Process')
}
