# Task Scheduler helpers for an explicitly started local ResearchOS runtime.
# Dot-source this file. It never registers or runs a task on its own.
Set-StrictMode -Version Latest

function Get-ResearchDurablePlan {
    param([Parameter(Mandatory)][string]$Root, [string]$OwnerSid = '')
    $workspace = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ([string]::IsNullOrWhiteSpace($OwnerSid)) {
        $OwnerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    }
    $digest = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($workspace.ToLowerInvariant() + "`n" + $OwnerSid)
        $hash = ([BitConverter]::ToString($digest.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    } finally { $digest.Dispose() }
    $powershell = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell/v1.0/powershell.exe'
    $hostScript = Join-Path $workspace 'scripts/host_local.ps1'
    return [pscustomobject]@{
        workspace = $workspace
        ownerSid = $OwnerSid
        taskName = 'ResearchOS-OnDemand-' + $hash.Substring(0, 20)
        taskUri = '\ResearchOS-OnDemand-' + $hash.Substring(0, 20)
        executable = $powershell
        arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $hostScript + '"'
        description = 'ResearchOS explicit local runtime; definition v1; workspace=' + $workspace
    }
}

function New-ResearchDurableXml {
    param([Parameter(Mandatory)]$Plan)
    $escape = { param([string]$Text) [Security.SecurityElement]::Escape($Text) }
    $author = & $escape $Plan.ownerSid
    $uri = & $escape $Plan.taskUri
    $description = & $escape $Plan.description
    $executable = & $escape $Plan.executable
    $arguments = & $escape $Plan.arguments
    $workspace = & $escape $Plan.workspace
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>$description</Description><Author>$author</Author><URI>$uri</URI></RegistrationInfo>
  <Triggers />
  <Principals><Principal id="Owner"><UserId>$author</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>4</Priority>
  </Settings>
  <Actions Context="Owner"><Exec><Command>$executable</Command><Arguments>$arguments</Arguments><WorkingDirectory>$workspace</WorkingDirectory></Exec></Actions>
</Task>
"@
}

function Assert-ResearchDurableXml {
    param([Parameter(Mandatory)][string]$Xml, [Parameter(Mandatory)]$Plan,
        [ValidateSet(4, 7)][int]$ExpectedPriority = 4)
    $document = [xml]$Xml
    $namespaces = [Xml.XmlNamespaceManager]::new($document.NameTable)
    $namespaces.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    $requirements = [ordered]@{
        '/t:Task/t:RegistrationInfo/t:Author' = $Plan.ownerSid
        '/t:Task/t:RegistrationInfo/t:URI' = $Plan.taskUri
        '/t:Task/t:RegistrationInfo/t:Description' = $Plan.description
        '/t:Task/t:Principals/t:Principal/t:UserId' = $Plan.ownerSid
        '/t:Task/t:Principals/t:Principal/t:LogonType' = 'InteractiveToken'
        '/t:Task/t:Principals/t:Principal/t:RunLevel' = 'LeastPrivilege'
        '/t:Task/t:Actions/t:Exec/t:Command' = $Plan.executable
        '/t:Task/t:Actions/t:Exec/t:Arguments' = $Plan.arguments
        '/t:Task/t:Actions/t:Exec/t:WorkingDirectory' = $Plan.workspace
        '/t:Task/t:Settings/t:MultipleInstancesPolicy' = 'IgnoreNew'
        '/t:Task/t:Settings/t:DisallowStartIfOnBatteries' = 'false'
        '/t:Task/t:Settings/t:StopIfGoingOnBatteries' = 'false'
        '/t:Task/t:Settings/t:AllowHardTerminate' = 'false'
        '/t:Task/t:Settings/t:StartWhenAvailable' = 'false'
        '/t:Task/t:Settings/t:RunOnlyIfNetworkAvailable' = 'false'
        '/t:Task/t:Settings/t:IdleSettings/t:StopOnIdleEnd' = 'false'
        '/t:Task/t:Settings/t:IdleSettings/t:RestartOnIdle' = 'false'
        '/t:Task/t:Settings/t:AllowStartOnDemand' = 'true'
        '/t:Task/t:Settings/t:Enabled' = 'true'
        '/t:Task/t:Settings/t:Hidden' = 'false'
        '/t:Task/t:Settings/t:RunOnlyIfIdle' = 'false'
        '/t:Task/t:Settings/t:WakeToRun' = 'false'
        '/t:Task/t:Settings/t:ExecutionTimeLimit' = 'PT0S'
        '/t:Task/t:Settings/t:Priority' = [string]$ExpectedPriority
    }
    # Windows removes default-valued nodes when serializing a registered task.
    # Accept only documented defaults that are exactly our expected behavior.
    # In particular PT72H, battery restrictions and AllowHardTerminate=true are
    # NOT our behavior, so their nodes cannot be omitted.
    # https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema
    # https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks
    $omittedDefaults = @{
        '/t:Task/t:Principals/t:Principal/t:RunLevel' = 'LeastPrivilege'
        '/t:Task/t:Settings/t:MultipleInstancesPolicy' = 'IgnoreNew'
        '/t:Task/t:Settings/t:StartWhenAvailable' = 'false'
        '/t:Task/t:Settings/t:RunOnlyIfNetworkAvailable' = 'false'
        '/t:Task/t:Settings/t:IdleSettings/t:RestartOnIdle' = 'false'
        '/t:Task/t:Settings/t:AllowStartOnDemand' = 'true'
        '/t:Task/t:Settings/t:Enabled' = 'true'
        '/t:Task/t:Settings/t:Hidden' = 'false'
        '/t:Task/t:Settings/t:RunOnlyIfIdle' = 'false'
        '/t:Task/t:Settings/t:WakeToRun' = 'false'
        '/t:Task/t:Settings/t:Priority' = '7'
    }
    foreach ($pair in $requirements.GetEnumerator()) {
        $nodes = $document.SelectNodes($pair.Key, $namespaces)
        if ($nodes.Count -eq 0 -and $omittedDefaults.ContainsKey($pair.Key) -and
            $omittedDefaults[$pair.Key] -ceq $pair.Value) { continue }
        if ($nodes.Count -ne 1 -or $nodes[0].InnerText -cne $pair.Value) {
            throw "Task definition does not match ResearchOS: $($pair.Key). Review the registered definition before proceeding."
        }
    }
    foreach ($path in @('/t:Task/t:Triggers/*', '/t:Task/t:Settings/t:RestartOnFailure', '/t:Task/t:Settings/t:MaintenanceSettings')) {
        if ($document.SelectNodes($path, $namespaces).Count -ne 0) {
            throw 'Task has an automatic trigger or restart policy. Refusing this operation.'
        }
    }
    if ($document.SelectNodes('/t:Task/t:Principals/*', $namespaces).Count -ne 1 -or
        $document.SelectNodes('/t:Task/t:Actions/*', $namespaces).Count -ne 1 -or
        $document.SelectNodes('/t:Task/t:Actions/t:Exec/*', $namespaces).Count -ne 3 -or
        $document.SelectNodes('/t:Task/t:Principals/t:Principal/*', $namespaces).Count -notin @(2, 3) -or
        $document.SelectNodes('/t:Task/t:Principals/t:Principal/t:GroupId', $namespaces).Count -ne 0) {
        throw 'Task has unexpected actions or principals. Refusing this operation.'
    }
    $principal = $document.SelectSingleNode('/t:Task/t:Principals/t:Principal', $namespaces)
    $actions = $document.SelectSingleNode('/t:Task/t:Actions', $namespaces)
    if ($principal.GetAttribute('id') -cne 'Owner' -or $actions.GetAttribute('Context') -cne 'Owner') {
        throw 'Task action context does not match its owner. Refusing this operation.'
    }
    foreach ($field in $principal.ChildNodes) {
        if ($field.NodeType -ne [Xml.XmlNodeType]::Element) { continue }
        if ($field.LocalName -notin @('UserId', 'LogonType', 'RunLevel') -or
            $field.NamespaceURI -cne $namespaces.LookupNamespace('t')) {
            throw 'Task has an unexpected principal field. Refusing this operation.'
        }
    }
    # Task Scheduler can insert these harmless default settings on registration.
    # All other settings must come from our explicit definition.
    $optionalDefaults = @{
        UseUnifiedSchedulingEngine = 'false'
        DisallowStartOnRemoteAppSession = 'false'
        Volatile = 'false'
    }
    $allowedSettings = @('MultipleInstancesPolicy', 'DisallowStartIfOnBatteries',
        'StopIfGoingOnBatteries', 'AllowHardTerminate', 'StartWhenAvailable',
        'RunOnlyIfNetworkAvailable', 'IdleSettings', 'AllowStartOnDemand', 'Enabled',
        'Hidden', 'RunOnlyIfIdle', 'WakeToRun', 'ExecutionTimeLimit', 'Priority')
    foreach ($setting in $document.SelectNodes('/t:Task/t:Settings/*', $namespaces)) {
        if ($document.SelectNodes('/t:Task/t:Settings/t:' + $setting.LocalName, $namespaces).Count -ne 1 -or
            $setting.NamespaceURI -cne $namespaces.LookupNamespace('t')) {
            throw 'Task has duplicate or foreign scheduler settings. Refusing this operation.'
        }
        if ($allowedSettings -contains $setting.LocalName) { continue }
        if (-not $optionalDefaults.ContainsKey($setting.LocalName) -or
            $setting.InnerText -cne $optionalDefaults[$setting.LocalName]) {
            throw 'Task has an unexpected scheduler setting. Refusing this operation.'
        }
    }
}

function Convert-ResearchDurableNormalPriorityXml {
    param([Parameter(Mandatory)][string]$Xml, [Parameter(Mandatory)]$Plan)
    # The only accepted legacy is the complete, same-owner/task definition with
    # default priority 7. Unknown tasks or altered fields are rejected first.
    Assert-ResearchDurableXml $Xml $Plan -ExpectedPriority 7
    $document = [xml]$Xml
    $namespaces = [Xml.XmlNamespaceManager]::new($document.NameTable)
    $namespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
    $namespaces.AddNamespace('t', $namespace)
    $priority = $document.SelectSingleNode('/t:Task/t:Settings/t:Priority', $namespaces)
    if ($null -eq $priority) {
        $priority = $document.CreateElement('Priority', $namespace)
        $settings = $document.SelectSingleNode('/t:Task/t:Settings', $namespaces)
        $null = $settings.AppendChild($priority)
    }
    $priority.InnerText = '4'
    Assert-ResearchDurableXml $document.OuterXml $Plan
    return $document.OuterXml
}

function Get-ResearchTaskFolder {
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    return $scheduler.GetFolder('\')
}

function Get-ResearchTaskOrNull {
    param([Parameter(Mandatory)]$Folder, [Parameter(Mandatory)][string]$Name)
    try { return $Folder.GetTask($Name) }
    catch {
        $exception = $_.Exception
        while ($null -ne $exception.InnerException) { $exception = $exception.InnerException }
        if ($exception.HResult -eq -2147024894) { return $null } # ERROR_FILE_NOT_FOUND only
        throw
    }
}
