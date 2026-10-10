# Read-only status logic. Dot-source after local_runtime.ps1.
Set-StrictMode -Version Latest

function Get-ResearchStatusField {
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    if ($Object -is [Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
    } elseif ($null -ne $Object.PSObject.Properties[$Name]) { return $Object.$Name }
    return $Default
}

function Compare-ResearchStatusIdentity {
    param($Expected, $Actual)
    if ($null -eq $Actual) { return 'MISSING' }
    try {
        if ([int]$Expected.pid -ne [int]$Actual.pid -or
            (Get-ResearchUtcTicks $Expected) -ne (Get-ResearchUtcTicks $Actual) -or
            $Expected.executable -ine $Actual.executable) { return 'MISMATCH' }
        if ($Expected.commandLine -and $Actual.commandLine -and
            $Expected.commandLine -cne $Actual.commandLine) { return 'MISMATCH' }
        return 'VERIFIED'
    } catch { return 'UNKNOWN' }
}

function Get-ResearchStatusIdentityProbe {
    param($Expected)
    if ($null -eq $Expected) { return 'MISSING' }
    try {
        $process = Get-Process -Id ([int]$Expected.pid) -ErrorAction SilentlyContinue
        if ($null -eq $process) { return 'MISSING' }
        $actual = Get-ResearchProcessIdentity ([int]$Expected.pid)
        if ($null -eq $actual) { return 'UNKNOWN' }
        return Compare-ResearchStatusIdentity $Expected $actual
    } catch { return 'UNKNOWN' }
}

function Convert-ResearchStatusPath {
    param([string]$Path, [hashtable]$DriveMappings = @{})
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'Path is unavailable.' }
    $normalized = $Path.Replace('/','\')
    foreach ($drive in $DriveMappings.Keys) {
        if ($normalized.StartsWith($drive + '\',[StringComparison]::OrdinalIgnoreCase)) {
            $normalized = $DriveMappings[$drive].TrimEnd('\') + $normalized.Substring($drive.Length)
            break
        }
    }
    return [IO.Path]::GetFullPath($normalized).TrimEnd('\')
}

function Test-ResearchExternalPostgresIdentity {
    param([string]$Root, [string]$DataPath, [string]$ExecutablePath,
        [string[]]$PidLines, $Actual, [int]$Port, [hashtable]$DriveMappings = @{})
    # A retained server is observable but is not adopted by the new host.
    try {
        $rootPath = Convert-ResearchStatusPath $Root
        $data = Convert-ResearchStatusPath $DataPath $DriveMappings
        $executable = Convert-ResearchStatusPath $ExecutablePath $DriveMappings
        if (-not $data.StartsWith($rootPath + '\',[StringComparison]::OrdinalIgnoreCase) -or
            -not $executable.StartsWith($rootPath + '\',[StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($executable) -ine 'postgres.exe' -or
            $PidLines.Count -lt 4 -or $null -eq $Actual) { return 'EXTERNAL_UNVERIFIED' }
        if ([int]$PidLines[0] -ne [int]$Actual.pid -or [int]$PidLines[3] -ne $Port -or
            (Convert-ResearchStatusPath $PidLines[1] $DriveMappings) -ine $data -or
            (Convert-ResearchStatusPath $Actual.executable $DriveMappings) -ine $executable) { return 'EXTERNAL_UNVERIFIED' }
        $started = [datetimeoffset]::new([datetime]::new((Get-ResearchUtcTicks $Actual),[DateTimeKind]::Utc))
        if ([math]::Abs($started.ToUnixTimeSeconds() - [long]$PidLines[2]) -gt 3) { return 'EXTERNAL_UNVERIFIED' }
        $argument = [regex]::Match([string]$Actual.commandLine,'(?:^|\s)-D\s+(?:"([^"]+)"|(\S+))')
        if (-not $argument.Success) { return 'EXTERNAL_UNVERIFIED' }
        $commandData = if ($argument.Groups[1].Success) { $argument.Groups[1].Value } else { $argument.Groups[2].Value }
        if ((Convert-ResearchStatusPath $commandData $DriveMappings) -ine $data) { return 'EXTERNAL_UNVERIFIED' }
        return 'EXTERNAL_VERIFIED'
    } catch { return 'EXTERNAL_UNVERIFIED' }
}

function Get-ResearchExternalPostgresProbe {
    param([string]$Root, $Runtime, [int]$Port)
    $out = [pscustomobject]@{identity='EXTERNAL_UNVERIFIED';pid=$null;verifiedPids=@();management='NOT_MANAGED'}
    try {
        $data = Get-ResearchStatusField $Runtime 'postgresData'
        if ([string]::IsNullOrWhiteSpace($data)) { $data = Join-Path $Root 'data/postgresql17' }
        $bin = Get-ResearchStatusField $Runtime 'postgresBin'
        if ([string]::IsNullOrWhiteSpace($bin)) { $bin = Join-Path $Root 'data/runtime/postgresql/pgsql/bin' }
        $mappings = @{}
        foreach ($drive in @(([IO.Path]::GetPathRoot($data)).TrimEnd('\'),([IO.Path]::GetPathRoot($bin)).TrimEnd('\'))) {
            $target = Get-ResearchSubstTarget $drive
            if ($null -ne $target) { $mappings[$drive] = $target }
        }
        # The pidfile may use a retained drive alias although new runtime fields are null.
        $data = Convert-ResearchStatusPath $data $mappings
        $executable = Convert-ResearchStatusPath (Join-Path $bin 'postgres.exe') $mappings
        foreach ($path in @($data,$executable)) {
            $cursor = $path
            while ($cursor -ine $Root) {
                if (-not $cursor.StartsWith($Root.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) { return $out }
                $item = Get-Item -LiteralPath $cursor -ErrorAction Stop
                if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $out }
                $cursor = Split-Path $cursor -Parent
            }
        }
        $pidFile = Join-Path $data 'postmaster.pid'
        if (((Get-Item -LiteralPath $pidFile -ErrorAction Stop).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $out }
        $lines = @(Get-Content -LiteralPath $pidFile -TotalCount 8)
        if ($lines.Count -lt 4) { return $out }
        $alias = ([IO.Path]::GetPathRoot($lines[1])).TrimEnd('\')
        $aliasTarget = Get-ResearchSubstTarget $alias
        if ($null -ne $aliasTarget) { $mappings[$alias] = $aliasTarget }
        $actual = Get-ResearchProcessIdentity ([int]$lines[0])
        $state = Test-ResearchExternalPostgresIdentity $Root $data $executable $lines $actual $Port $mappings
        $second = @(Get-Content -LiteralPath $pidFile -TotalCount 4)
        if ($second.Count -lt 4 -or $second[0] -cne $lines[0] -or $second[2] -cne $lines[2]) { return $out }
        $out.pid = [int]$lines[0]
        $out.identity = $state
        if ($state -eq 'EXTERNAL_VERIFIED') {
            $out.verifiedPids = @([int]$actual.pid)
            foreach ($child in @(Get-ResearchDescendantIdentities $actual)) {
                if ((Convert-ResearchStatusPath $child.executable $mappings) -ieq $executable -and
                    (Get-ResearchUtcTicks $child) -ge (Get-ResearchUtcTicks $actual) -and
                    (Test-ResearchProcessIdentity $child)) { $out.verifiedPids += [int]$child.pid }
            }
        }
    } catch { return $out }
    return $out
}

function Resolve-ResearchLocalStatus {
    param([string]$Root, $Runtime, $HostRecord, [object[]]$Services,
        [string]$HostIdentity, [object[]]$Listeners, [bool]$ListenersAvailable,
        $Scheduler, [string[]]$RecordErrors = @(),
        [datetimeoffset]$Now = [datetimeoffset]::UtcNow, [int]$HeartbeatSeconds = 30)
    $issues = @($RecordErrors)
    $runtimeWorkspaceValid = $null -ne $Runtime -and
        (Get-ResearchStatusField $Runtime 'workspace') -ieq $Root
    $hostWorkspaceValid = $null -ne $HostRecord -and
        (Get-ResearchStatusField $HostRecord 'workspace') -ieq $Root
    if ($null -ne $Runtime -and -not $runtimeWorkspaceValid) { $issues += 'RUNTIME_WORKSPACE_MISMATCH' }
    if ($null -ne $HostRecord -and -not $hostWorkspaceValid) { $issues += 'HOST_WORKSPACE_MISMATCH' }
    $age = $null
    $heartbeat = 'MISSING'
    if ($hostWorkspaceValid) {
        try {
            # PS7 ConvertFrom-Json can return DateTime; casting it to string
            # drops the UTC offset and incorrectly ages a +08 host by 8 hours.
            $heartbeatValue = $HostRecord.updatedUtc
            if ($heartbeatValue -is [datetime] -and $heartbeatValue.Kind -eq [DateTimeKind]::Unspecified) {
                throw 'Heartbeat timestamp has no timezone.'
            }
            $heartbeatTicks = Get-ResearchUtcTicks ([pscustomobject]@{createdUtc=$heartbeatValue})
            $heartbeatTime = [datetimeoffset]::new([datetime]::new($heartbeatTicks,[DateTimeKind]::Utc))
            $age = ($Now - $heartbeatTime).TotalSeconds
            $heartbeat = if ($age -lt -5) { 'INVALID' } elseif ($age -gt $HeartbeatSeconds) { 'STALE' } else { 'FRESH' }
        } catch { $heartbeat = 'INVALID' }
    }
    $checks = @()
    foreach ($service in $Services) {
        $listenerStatus = 'NOT_APPLICABLE'
        if ($null -ne $service.port) {
            if (-not $ListenersAvailable) { $listenerStatus = 'UNKNOWN' }
            else {
                $found = @($Listeners | Where-Object { [int]$_.LocalPort -eq [int]$service.port })
                if ($found.Count -eq 0) { $listenerStatus = 'MISSING' }
                elseif ($service.identity -notin @('VERIFIED','EXTERNAL_VERIFIED')) { $listenerStatus = 'UNKNOWN' }
                elseif (@($found | Where-Object {
                    $_.OwningProcess -notin $service.verifiedPids -or
                    $_.LocalAddress -notin @('127.0.0.1', '::1')
                }).Count -gt 0) { $listenerStatus = 'WRONG_OWNER_OR_BINDING' }
                else { $listenerStatus = 'VERIFIED' }
            }
        }
        if ($service.identity -notin @('VERIFIED','EXTERNAL_VERIFIED')) { $issues += ($service.name.ToUpperInvariant() + '_IDENTITY_' + $service.identity) }
        if ($listenerStatus -notin @('VERIFIED', 'NOT_APPLICABLE')) { $issues += ($service.name.ToUpperInvariant() + '_LISTENER_' + $listenerStatus) }
        $checks += [pscustomobject]@{name=$service.name;pid=$service.pid;identity=$service.identity;port=$service.port;listener=$listenerStatus;management=(Get-ResearchStatusField $service 'management' 'MANAGED')}
    }
    if ($HostIdentity -ne 'VERIFIED') { $issues += ('HOST_IDENTITY_' + $HostIdentity) }
    if ($heartbeat -ne 'FRESH') { $issues += ('HOST_HEARTBEAT_' + $heartbeat) }
    $schedulerAvailability = Get-ResearchStatusField $Scheduler 'availability' 'UNKNOWN'
    $schedulerState = Get-ResearchStatusField $Scheduler 'state'
    if ($schedulerAvailability -eq 'UNKNOWN') { $issues += 'SCHEDULER_UNKNOWN' }
    elseif ($schedulerAvailability -eq 'AVAILABLE' -and $schedulerState -ne 4) { $issues += 'SCHEDULER_NOT_RUNNING' }
    elseif ($schedulerAvailability -eq 'NOT_FOUND') { $issues += 'SCHEDULER_NOT_FOUND' }
    $phase = Get-ResearchStatusField $HostRecord 'phase'
    if ($phase -ne 'ready') { $issues += 'HOST_NOT_READY' }
    $state = 'DEGRADED'
    if ($null -eq $Runtime -and $null -eq $HostRecord -and $RecordErrors.Count -eq 0 -and
        $ListenersAvailable -and $Listeners.Count -eq 0 -and
        ($schedulerAvailability -eq 'NOT_FOUND' -or ($schedulerAvailability -eq 'AVAILABLE' -and $schedulerState -ne 4))) {
        $state = 'NOT_STARTED'
    } elseif (-not $runtimeWorkspaceValid -or -not $hostWorkspaceValid -or
        $HostIdentity -in @('MISSING','MISMATCH') -or $RecordErrors.Count -gt 0) {
        $state = 'UNAVAILABLE'
    } elseif ($issues.Count -eq 0 -and $checks.Count -ge 4) { $state = 'READY' }
    return [pscustomobject]@{
        schemaVersion=1;state=$state;observedUtc=$Now.ToString('o');issues=@($issues | Select-Object -Unique)
        host=[pscustomobject]@{pid=(Get-ResearchStatusField (Get-ResearchStatusField $HostRecord 'host') 'pid');identity=$HostIdentity;recordedPhase=$phase;heartbeat=$heartbeat;heartbeatAgeSeconds=$age}
        services=$checks;scheduler=$Scheduler
    }
}
