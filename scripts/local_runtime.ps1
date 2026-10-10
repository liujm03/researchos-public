# Shared helpers for the Windows local runtime scripts. Dot-source this file only.
Set-StrictMode -Version Latest

function Get-ResearchRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
}

function Get-ResearchConfigValue {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$EnvPath
    )

    $fromProcess = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($null -ne $fromProcess) { return $fromProcess }

    foreach ($line in [IO.File]::ReadLines($EnvPath)) {
        if ($line -match '^\s*' + [regex]::Escape($Name) + '=(.*)$') {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2 -and
                (($value[0] -eq '"' -and $value[-1] -eq '"') -or
                 ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
                return $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return $null
}

function Get-ResearchPort {
    param([string]$Value, [int]$Default, [string]$Name)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $Default }
    $port = 0
    if (-not [int]::TryParse($Value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "$Name must be a TCP port from 1 to 65535."
    }
    return $port
}

function Test-ResearchCodexWorkerEnabled {
    param([Parameter(Mandatory)][string]$EnvPath)
    return (Get-ResearchConfigValue CODEX_PROVIDER $EnvPath) -ceq 'openai_codex_sdk'
}

function Invoke-ResearchNativeLauncher {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$StdoutPath,
        [Parameter(Mandatory)][string]$StderrPath,
        [int]$TimeoutMilliseconds = 35000
    )
    # A native invocation through PowerShell's output pipeline can wait for EOF
    # from inherited pipes held by a long-lived server child. Give the launcher
    # real log handles and wait only for its own process, not its process tree.
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
    try {
        # Retain the native process handle before the short-lived launcher exits;
        # otherwise PowerShell 5 can lose its exit code between start and wait.
        $null = $process.Handle
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            throw 'Native command observation timed out; inspect its logs and process identity before retrying. The command was not killed.'
        }
        return $process.ExitCode
    } finally { $process.Dispose() }
}

function Get-ResearchProcessIdentity {
    param([Parameter(Mandatory)][int]$Id)
    $process = Get-Process -Id $Id -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        $executable = $process.Path
        # Read StartTime once while the process handle can still provide it.
        # A short-lived process may exit during CIM lookup; rereading this
        # property outside the guard previously allowed a null-method error.
        $startedAt = $process.StartTime
        if ($null -eq $startedAt -or $process.HasExited) { return $null }
        $startedUtc = $startedAt.ToUniversalTime()
        $createdUtc = $startedUtc.ToString('o')
        $createdUtcTicks = $startedUtc.Ticks
    } catch { return $null }
    if ([string]::IsNullOrEmpty($executable)) { return $null }
    $item = Get-CimInstance Win32_Process -Filter "ProcessId = $Id" -ErrorAction SilentlyContinue
    try {
        if ($process.HasExited) { return $null }
    } catch { return $null }
    return [pscustomobject]@{
        pid = $Id
        createdUtc = $createdUtc
        createdUtcTicks = $createdUtcTicks
        executable = $executable
        commandLine = if ($null -ne $item) { $item.CommandLine } else { $null }
    }
}

function Get-ResearchUtcTicks {
    param([Parameter(Mandatory)]$Identity)
    if ($null -ne $Identity.PSObject.Properties['createdUtcTicks']) {
        return [long]$Identity.createdUtcTicks
    }
    $value = $Identity.createdUtc
    if ($value -is [datetime]) { return $value.ToUniversalTime().Ticks }
    if ($value -is [datetimeoffset]) { return $value.UtcDateTime.Ticks }
    $parsed = [datetimeoffset]::Parse(
        [string]$value,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    )
    return $parsed.UtcDateTime.Ticks
}

function Test-ResearchProcessIdentity {
    param([Parameter(Mandatory)]$Expected)
    $actual = Get-ResearchProcessIdentity -Id ([int]$Expected.pid)
    if ($null -eq $actual) { return $false }
    if ((Get-ResearchUtcTicks $actual) -ne (Get-ResearchUtcTicks $Expected) -or
        $actual.executable -ine $Expected.executable) { return $false }
    # WMI command lines can be unavailable under a restricted Windows token.
    # PID + creation time + exact executable path still identifies the process
    # originally launched and recorded by start_local.ps1.
    if ($Expected.commandLine -and $actual.commandLine) {
        return $actual.commandLine -ceq $Expected.commandLine
    }
    return $true
}

function Stop-ResearchIdentifiedProcess {
    param([Parameter(Mandatory)]$Expected)
    $process = Get-Process -Id ([int]$Expected.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return 'gone' }
    try {
        # Keep the OS process handle open through validation and Kill(), so a
        # recycled PID cannot redirect the stop request to another process.
        $null = $process.Handle
        if ($process.HasExited) { return 'gone' }
        if ($process.StartTime.ToUniversalTime().Ticks -ne (Get-ResearchUtcTicks $Expected) -or
            $process.Path -ine $Expected.executable) {
            # Python launchers can exit their children between our process
            # lookup and path read. An exited handle is not a reused live PID.
            if ($process.HasExited) { return 'gone' }
            return 'mismatched'
        }
        if ($Expected.commandLine) {
            $item = Get-CimInstance Win32_Process -Filter "ProcessId = $($Expected.pid)" -ErrorAction SilentlyContinue
            if ($null -ne $item -and $item.CommandLine -cne $Expected.commandLine) {
                if ($process.HasExited) { return 'gone' }
                return 'mismatched'
            }
        }
        $process.Kill()
        if (-not $process.WaitForExit(5000)) { throw 'Verified process has not exited; runtime record must be retained.' }
        return 'stopped'
    } catch {
        if ($process.HasExited) { return 'gone' }
        throw
    } finally {
        $process.Dispose()
    }
}

if (-not ('ResearchOSRuntime.ProcessTree' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
namespace ResearchOSRuntime {
    public static class ProcessTree {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct Entry {
            public uint size;
            public uint usage;
            public uint pid;
            public IntPtr defaultHeap;
            public uint moduleId;
            public uint threadCount;
            public uint parentPid;
            public int basePriority;
            public uint flags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string exeFile;
        }
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool Process32FirstW(IntPtr snapshot, ref Entry entry);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool Process32NextW(IntPtr snapshot, ref Entry entry);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        public static Dictionary<int, int> SnapshotParents() {
            var result = new Dictionary<int, int>();
            var snapshot = CreateToolhelp32Snapshot(0x00000002, 0);
            if (snapshot == new IntPtr(-1)) {
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            }
            try {
                var entry = new Entry();
                entry.size = (uint)Marshal.SizeOf(typeof(Entry));
                if (!Process32FirstW(snapshot, ref entry)) {
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                }
                do {
                    result[(int)entry.pid] = (int)entry.parentPid;
                    entry.size = (uint)Marshal.SizeOf(typeof(Entry));
                } while (Process32NextW(snapshot, ref entry));
            } finally {
                CloseHandle(snapshot);
            }
            return result;
        }
    }
}
'@
}

function Get-ResearchDescendantIdentities {
    param([Parameter(Mandatory)]$RootIdentity)
    if (-not (Test-ResearchProcessIdentity $RootIdentity)) { return @() }
    $parents = [ResearchOSRuntime.ProcessTree]::SnapshotParents()
    $pending = [Collections.Generic.Queue[int]]::new()
    $pending.Enqueue([int]$RootIdentity.pid)
    $seen = [Collections.Generic.HashSet[int]]::new()
    $result = [Collections.Generic.List[object]]::new()
    $minimumTicks = Get-ResearchUtcTicks $RootIdentity
    while ($pending.Count -gt 0) {
        $parent = $pending.Dequeue()
        foreach ($pair in $parents.GetEnumerator()) {
            if ($pair.Value -ne $parent -or -not $seen.Add($pair.Key)) { continue }
            $child = Get-ResearchProcessIdentity -Id $pair.Key
            if ($null -eq $child -or (Get-ResearchUtcTicks $child) -lt $minimumTicks) { continue }
            $result.Add($child)
            $pending.Enqueue($pair.Key)
        }
    }
    return @($result.ToArray())
}

function Stop-ResearchTrackedTree {
    param([Parameter(Mandatory)]$RootIdentity, [object[]]$RecordedChildren = @())
    $stopped = [Collections.Generic.List[int]]::new()
    $mismatched = [Collections.Generic.List[int]]::new()
    $activeRoot = Test-ResearchProcessIdentity $RootIdentity
    $children = [Collections.Generic.List[object]]::new()
    foreach ($child in $RecordedChildren) { if ($null -ne $child) { $children.Add($child) } }
    if ($activeRoot) {
        foreach ($child in (Get-ResearchDescendantIdentities $RootIdentity)) {
            if (-not ($children | Where-Object { $_.pid -eq $child.pid })) { $children.Add($child) }
        }
    }

    # Stop the verified root first so it cannot create new children. Then stop
    # descendants from leaves to trunk, including recorded children whose
    # launcher exited before the stop command.
    $rootStop = Stop-ResearchIdentifiedProcess $RootIdentity
    if ($rootStop -eq 'stopped') {
        $stopped.Add([int]$RootIdentity.pid)
    } elseif ($rootStop -eq 'mismatched') {
        $mismatched.Add([int]$RootIdentity.pid)
    }
    for ($index = $children.Count - 1; $index -ge 0; $index--) {
        $child = $children[$index]
        $childStop = Stop-ResearchIdentifiedProcess $child
        if ($childStop -eq 'stopped') {
            $stopped.Add([int]$child.pid)
        } elseif ($childStop -eq 'mismatched') {
            $mismatched.Add([int]$child.pid)
        }
    }
    return [pscustomobject]@{ stopped = @($stopped.ToArray()); mismatched = @($mismatched.ToArray()) }
}

function Save-ResearchRuntimeState {
    param([Parameter(Mandatory)]$State, [Parameter(Mandatory)][string]$Path)
    $temporary = "$Path.tmp"
    # PS7's utf8 is BOM-less; the fixed scheduler host is Windows PS5, whose
    # default Get-Content would decode Chinese paths as ANSI without a BOM.
    $json = $State | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($true))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

if (-not ('ResearchOSRuntime.DosDevice' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
namespace ResearchOSRuntime {
    public static class DosDevice {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern uint QueryDosDevice(string name, StringBuilder target, int length);
    }
}
'@
}

function Get-ResearchSubstTarget {
    param([Parameter(Mandatory)][string]$Drive)
    $buffer = [Text.StringBuilder]::new(2048)
    $length = [ResearchOSRuntime.DosDevice]::QueryDosDevice($Drive, $buffer, $buffer.Capacity)
    if ($length -eq 0) { return $null }
    $target = $buffer.ToString().Split([char]0)[0]
    if (-not $target.StartsWith('\??\', [StringComparison]::Ordinal)) { return $null }
    $path = $target.Substring(4)
    if (-not [IO.Path]::IsPathRooted($path)) { return $null }
    return [IO.Path]::GetFullPath($path).TrimEnd('\')
}

function Convert-ResearchPathToDrive {
    param([string]$Path, [string]$Root, [string]$Drive)
    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ($fullPath.Equals($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return "$Drive\"
    }
    if ($fullPath.StartsWith($fullRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        return $Drive + $fullPath.Substring($fullRoot.Length)
    }
    return $fullPath
}
