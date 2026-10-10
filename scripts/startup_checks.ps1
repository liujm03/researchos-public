# Startup checks share the owner/process/listener validation of status_local.ps1.
# HTTP probes are loopback-only, bypass proxies and never follow redirects.
Set-StrictMode -Version Latest

function Test-ResearchStartupHttp {
    param([Parameter(Mandatory)][string]$Url)
    $uri = [uri]$Url
    if ($uri.Scheme -cne 'http' -or $uri.Host -cne '127.0.0.1') {
        throw 'Startup health probes must use local IPv4 HTTP.'
    }
    $response = $null
    try {
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.Proxy = $null
        $request.AllowAutoRedirect = $false
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $response = $request.GetResponse()
        return [int]$response.StatusCode -eq 200
    } catch { return $false }
    finally { if ($null -ne $response) { $response.Close() } }
}

function Test-ResearchStartupReady {
    param([Parameter(Mandatory)]$Snapshot,
        [Parameter(Mandatory)][int]$ApiPort, [Parameter(Mandatory)][int]$WebPort,
        [scriptblock]$HttpProbe = { param($Url) Test-ResearchStartupHttp $Url })
    if ($Snapshot.state -cne 'READY') { return $false }
    foreach ($entry in @(@('api', $ApiPort), @('web', $WebPort))) {
        $service = @($Snapshot.services | Where-Object { $_.name -ceq $entry[0] })
        if ($service.Count -ne 1 -or [int]$service[0].port -ne $entry[1] -or
            $service[0].identity -cne 'VERIFIED' -or $service[0].listener -cne 'VERIFIED') {
            return $false
        }
    }
    if (-not (& $HttpProbe "http://127.0.0.1:$ApiPort/health/ready")) { return $false }
    return [bool](& $HttpProbe "http://127.0.0.1:$WebPort/login")
}

function Open-ResearchStartupBrowser {
    param([Parameter(Mandatory)][int]$WebPort)
    # Fixed local URL; prefer the owner's Chrome without collecting credentials.
    $url = "http://127.0.0.1:$WebPort"
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $chrome = Join-Path $base 'Google/Chrome/Application/chrome.exe'
        if (Test-Path -LiteralPath $chrome -PathType Leaf) {
            Start-Process -FilePath $chrome -ArgumentList $url
            return
        }
    }
    Start-Process $url
}
