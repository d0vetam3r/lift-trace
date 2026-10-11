param(
    [string]$PythonPath = '',
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [ValidateRange(-1, 15)][int]$DeviceId = 0,
    [ValidateRange(1, 2147483647)][int]$ObsProcessId,
    [string]$DataDir = ''
)

$ErrorActionPreference = 'Stop'
$bridgeRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DataDir)) { $DataDir = Join-Path $bridgeRoot 'data' }
$DataDir = [IO.Path]::GetFullPath($DataDir)
[IO.Directory]::CreateDirectory($DataDir) | Out-Null
$statusFile = Join-Path $DataDir "obs-bridge-$ObsProcessId-$Port.status"
$baseUrl = "http://127.0.0.1:$Port"
$ownedServer = $null
$mutex = $null
$haveMutex = $false

function Set-BridgeStatus([string]$Message) {
    [IO.File]::WriteAllText($statusFile, $Message, [Text.UTF8Encoding]::new($false))
}

function Get-BridgeStatus {
    try {
        $value = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 1
        if ($value.app -ne 'lift-trace' -or $value.apiVersion -ne 1) { return $null }
        if ($null -eq $value.PSObject.Properties['nativeSupported'] -or
            $null -eq $value.PSObject.Properties['selectedDevice'] -or
            $null -eq $value.PSObject.Properties['devices']) { return $null }
        return $value
    } catch { return $null }
}

function Quote-Argument([string]$Value) {
    # Process argv quoting only: these strings are not executed as shell code.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Find-Python {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        $candidates += @{ File = $PythonPath; Prefix = @() }
    } else {
        foreach ($name in @('py.exe', 'python.exe', 'python3.exe')) {
            $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($command -and $command.Source -notmatch '\\WindowsApps\\') {
                $prefix = @()
                if ($name -eq 'py.exe') { $prefix = @('-3') }
                $candidates += @{ File = $command.Source; Prefix = $prefix }
            }
        }
    }
    foreach ($candidate in $candidates) {
        try {
            $probeArgs = @($candidate.Prefix) + @('-c', 'import sys; print(sys.executable) if sys.version_info >= (3,10) else sys.exit(2)')
            $resolved = & $candidate.File @probeArgs 2>$null | Select-Object -Last 1
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) {
                return [string]$resolved
            }
        } catch { }
    }
    throw 'Python 3.10+ was not found. Set the Python executable in the OBS script properties.'
}

try {
    Set-BridgeStatus 'starting'
    $obsProcess = Get-Process -Id $ObsProcessId -ErrorAction Stop
    $obsStart = $obsProcess.StartTime
    $mutex = [Threading.Mutex]::new($false, "Local\LiftInput-Bridge-$Port")
    try { $haveMutex = $mutex.WaitOne(15000) }
    catch [Threading.AbandonedMutexException] { $haveMutex = $true }
    if (-not $haveMutex) { throw 'Timed out waiting for another bridge startup.' }
    $bridge = Get-BridgeStatus
    if ($null -eq $bridge) {
        $bundledApp = Join-Path $bridgeRoot 'LiftTrace.exe'
        if (Test-Path -LiteralPath $bundledApp -PathType Leaf) {
            $serverProgram = $bundledApp
            $serverArgs = @('--serve', '--port', $Port, '--data-dir', (Quote-Argument $DataDir)) -join ' '
        } else {
            $serverProgram = Find-Python
            $serverFile = Join-Path $bridgeRoot 'server.py'
            if (-not (Test-Path -LiteralPath $serverFile -PathType Leaf)) { throw 'LiftTrace.exe or server.py is required beside the OBS script.' }
            $serverArgs = @((Quote-Argument $serverFile), '--port', $Port, '--data-dir', (Quote-Argument $DataDir)) -join ' '
        }
        $ownedServer = Start-Process -FilePath $serverProgram -ArgumentList $serverArgs -WorkingDirectory $bridgeRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $DataDir "obs-bridge-$Port.stdout.log") `
            -RedirectStandardError (Join-Path $DataDir "obs-bridge-$Port.stderr.log")
        for ($attempt = 0; $attempt -lt 100; $attempt++) {
            Start-Sleep -Milliseconds 200
            $ownedServer.Refresh()
            if ($ownedServer.HasExited) { throw 'The bridge exited during startup. Check data/obs-bridge-*.stderr.log.' }
            $bridge = Get-BridgeStatus
            if ($null -ne $bridge) { break }
        }
        if ($null -eq $bridge) { throw 'The bridge did not become ready. Check the port and Python executable.' }
    }
    if ($DeviceId -ge 0) {
        # Missing/unplugged controllers do not prevent the overlay server from starting.
        try {
            Invoke-RestMethod -Method Post -Uri "$baseUrl/api/rescan" -ContentType 'application/json' -Body '{}' -TimeoutSec 2 | Out-Null
            Invoke-RestMethod -Method Post -Uri "$baseUrl/api/device" -ContentType 'application/json' -Body (@{ id = $DeviceId } | ConvertTo-Json -Compress) -TimeoutSec 2 | Out-Null
            $config = Invoke-RestMethod -Uri "$baseUrl/api/settings" -TimeoutSec 2
            $config | Add-Member -MemberType NoteProperty -Name inputMode -Value 'native' -Force
            Invoke-RestMethod -Method Post -Uri "$baseUrl/api/settings" -ContentType 'application/json; charset=utf-8' `
                -Body ([Text.Encoding]::UTF8.GetBytes(($config | ConvertTo-Json -Depth 30 -Compress))) -TimeoutSec 2 | Out-Null
        } catch {
            [IO.File]::AppendAllText((Join-Path $DataDir "obs-controller-$Port.log"), "Controller selection: $($_.Exception.Message)`r`n")
        }
    }
    Set-BridgeStatus 'ready'
    $mutex.ReleaseMutex()
    $haveMutex = $false
    if ($null -ne $ownedServer) {
        # Watch the original OBS process; do not terminate a server started elsewhere.
        while (-not $ownedServer.HasExited) {
            Start-Sleep -Seconds 2
            $currentObs = Get-Process -Id $ObsProcessId -ErrorAction SilentlyContinue
            if ($null -eq $currentObs -or $currentObs.StartTime -ne $obsStart) { break }
            $ownedServer.Refresh()
        }
    }
} catch {
    Set-BridgeStatus ("error: " + $_.Exception.Message)
} finally {
    if ($haveMutex) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
    if ($null -ne $ownedServer) {
        $ownedServer.Refresh()
        if (-not $ownedServer.HasExited) { $ownedServer.Kill(); $ownedServer.WaitForExit() }
        $ownedServer.Dispose()
    }
}
