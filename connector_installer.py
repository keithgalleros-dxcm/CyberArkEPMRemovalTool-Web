"""Render private single-file endpoint installers with one-use enrollment credentials."""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'connector_setup'
BATCH_HEADER = """@echo off
setlocal
set "EPM_SETUP_FILE=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:EPM_SETUP_FILE); & ([ScriptBlock]::Create($s.Substring($s.LastIndexOf('# BEGIN POWERSHELL'))))"
exit /b %errorlevel%
"""


def render(payload, platform):
    encoded = base64.b64encode(payload).decode('ascii')
    if platform == 'windows':
        script = (ROOT / 'install-windows.ps1').read_text(encoding='utf-8').replace('__PAYLOAD__', encoded)
        # Read the PowerShell section from this file, keeping credentials off the command line.
        header = BATCH_HEADER.replace('\n', '\r\n')
        return (header + '# BEGIN POWERSHELL\n' + script).encode('utf-8'), 'Install-connector.cmd', 'application/octet-stream'
    if platform in ('macos', 'linux'):
        script = (ROOT / 'install-unix.sh').read_text(encoding='utf-8').replace('__PAYLOAD__', encoded)
        return script.encode('utf-8'), 'Install-connector.sh', 'application/octet-stream'
    raise ValueError('Unsupported connector installer platform')
