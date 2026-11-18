$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Find-ConnectorPython {
    # -I ignores user environment/site customizations while probing a real interpreter.
    $probe = 'import sys; print(sys.executable) if sys.version_info >= (3,11) else sys.exit(1)'
    foreach ($name in @('py','python3','python')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if (!$command -or $command.Source -like '*\WindowsApps\*') { continue }
        try {
            $arguments = @('-I','-c',$probe)
            if ($name -eq 'py') { $arguments = @('-3') + $arguments }
            $candidate = & $command.Source @arguments 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath ([string]$candidate))) { return [string]$candidate }
        } catch { }
    }
    return $null
}
function Install-EndpointConnector {
    param(
        [string]$InstallRoot = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Dexcom\EPMConnector'),
        [string]$ProgramsDirectory = [Environment]::GetFolderPath('Programs')
    )
    Write-Host 'Installing Dexcom endpoint connector for this Windows account...'
    $base = $InstallRoot
    $target = Join-Path $base ([Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    # Limit credential access to this account, SYSTEM and local administrators.
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $target /inheritance:r /grant:r "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to secure the connector folder.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $python = Find-ConnectorPython
    $runtimeMode = 'existing-python'
    if (!$python) {
        Write-Host 'Python 3.11+ was not found. Preparing a private Python runtime (no PATH changes)...'
        $architecture = [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432')
        if (!$architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
        switch ($architecture.ToUpperInvariant()) {
            'AMD64' { $asset = 'amd64'; $digest = 'd012f3aa29cf07436dae8aea1fec0fd195c2612a0b059b1f915ae0afb9ad1f62' }
            'ARM64' { $asset = 'arm64'; $digest = '089eae5e8aba8284c2ce59df008c1dc915af46fd9e8b1227e3a7f315211567c9' }
            'X86'   { $asset = 'win32'; $digest = '8d20269d378040117c9cec11d1ad6c6d17c6b77774424955ee180a0f49c6b41e' }
            default { throw 'Unsupported Windows processor architecture.' }
        }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $runtime = Join-Path $target 'python-runtime.zip'
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/3.15.2/python-3.15.2-embed-$asset.zip" -OutFile $runtime
        $hasher = [Security.Cryptography.SHA256]::Create()
        $stream = [IO.File]::OpenRead($runtime)
        try { $actual = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
        finally { $stream.Dispose(); $hasher.Dispose() }
        if ($actual -ne $digest) { throw 'Python runtime checksum failed. Setup stopped.' }
        [IO.Compression.ZipFile]::ExtractToDirectory($runtime,$target)
        Remove-Item -LiteralPath $runtime
        $python = Join-Path $target 'python.exe'
        $runtimeMode = 'private-python'
    } else { Write-Host 'Compatible Python detected.' }
    $archive = Join-Path $target 'connector.zip'
    [IO.File]::WriteAllBytes($archive,[Convert]::FromBase64String('__PAYLOAD__'))
    [IO.Compression.ZipFile]::ExtractToDirectory($archive,$target)
    Remove-Item -LiteralPath $archive
    # Validate imports before starting or creating a shortcut.
    & $python -c "import sys; sys.path.insert(0,sys.argv[1]); import endpoint_connector; assert sys.version_info >= (3,11)" $target
    if ($LASTEXITCODE -ne 0) { throw 'Connector Python validation failed; check OS support and Python installation.' }
    @{runtime=$runtimeMode; python=$python} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'setup-info.json') -Encoding UTF8
    $argumentLine = '-u "' + (Join-Path $target 'endpoint_connector.py') + '" --config "' + (Join-Path $target 'connector.private.json') + '"'
    $shell = New-Object -ComObject WScript.Shell
    $programs = $ProgramsDirectory
    $shortcut = $shell.CreateShortcut((Join-Path $programs 'Dexcom Endpoint Connector.lnk'))
    $shortcut.TargetPath = $python
    $shortcut.Arguments = $argumentLine
    $shortcut.WorkingDirectory = $target
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Reconnect this PC to the EPM portal'
    $shortcut.Save()
    $process = Start-Process -FilePath $python -ArgumentList $argumentLine -WorkingDirectory $target -WindowStyle Hidden -RedirectStandardOutput (Join-Path $target 'connector.log') -RedirectStandardError (Join-Path $target 'connector-error.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $target 'connector.pid')
    Start-Sleep -Seconds 3
    if ($process.HasExited) { throw ('Connector did not remain running. See ' + $target + '\connector-error.log. If enrollment expired, use Install connector again.') }
    Write-Host ('Installed and started. Return to the portal to confirm this PC is connected. Files and logs: ' + $target)
    Write-Host 'The Start menu shortcut reconnects this installation. A portal restart requires a fresh installer.'
}
try { Install-EndpointConnector; exit 0 }
catch { Write-Host ('Setup failed: ' + $_.Exception.Message) -ForegroundColor Red; Write-Host 'Check outbound HTTPS to python.org and access to your portal. No CyberArk agent operation ran.'; Read-Host 'Press Enter to close'; exit 1 }
