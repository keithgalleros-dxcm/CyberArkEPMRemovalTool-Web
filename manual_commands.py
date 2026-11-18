"""Build display-only manual CLI guides. This module never executes shell commands."""
from html import escape
from pathlib import Path
import re
from catalog import PAGES

WINDOWS_LAUNCH = 'powershell.exe -NoProfile -ExecutionPolicy Bypass'
WINDOWS_PS = r'''
$productCode = '{PRODUCT-GUID}'
if ($productCode -notmatch '^\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}$') {
    throw 'Replace {PRODUCT-GUID} with the exact selected MSI product GUID first.'
}
$secureToken = Read-Host 'Vendor EPM secure token (leave blank if not required)' -AsSecureString
$token = [Net.NetworkCredential]::new('', $secureToken).Password
try {
    if ($token -match '["\r\n]') { throw 'Invalid token character.' }
    $arguments = "/x $productCode FULL_UNINSTALL=YES /qn /norestart"
    if ($token) { $arguments += ' SECURE_TOKEN="' + $token + '"' }
    $result = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $arguments -Wait -PassThru
    "MSI exit code: $($result.ExitCode)"
} finally {
    $token = $null
    $arguments = $null
    $secureToken.Dispose()
}
'''.strip()
WINDOWS_CMD = 'msiexec.exe /x "{PRODUCT-GUID}" FULL_UNINSTALL="YES" /qn /norestart'
WINDOWS_CMD_TOKEN = 'msiexec.exe /x "{PRODUCT-GUID}" FULL_UNINSTALL="YES" SECURE_TOKEN="REPLACE_WITH_VENDOR_TOKEN" /qn /norestart'
MAC_FULL = 'sudo "/Applications/CyberArk EPM.app/Contents/Helpers/CyberArkEPMUninstall" -full'
MAC_TOKEN = 'sudo "/Applications/CyberArk EPM.app/Contents/Helpers/CyberArkEPMUninstall" -full -token "/absolute/path/to/epm-secure-token.txt"'
OS_INFO = 'cat /etc/os-release'
FILTER = "grep -Ei 'cyberark|idira|viewfinity|epm'"
DEB = r"dpkg-query -W -f='${binary:Package}\t${Version}\n' | " + FILTER
RPM = r"rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\n' | " + FILTER
ARCH = 'pacman -Q | ' + FILTER

def block(ident, title, command):
    return ('<div class="cli-block"><div class="row"><h3>' + escape(title) +
            '</h3><button type="button" class="copy-command" data-copy="' + ident +
            '" aria-label="Copy ' + escape(title, quote=True) + '">Copy command</button></div>' +
            '<pre><code id="' + ident + '">' + escape(command) + '</code></pre></div>')

def guide(page):
    target = page.get('target')
    if target not in ('windows-server', 'windows-desktop', 'macos', 'linux') and page['kind'] != 'linux': return ''
    body = '<section class="panel manual-cli" id="manual-cli"><span class="eyebrow">MANUAL OPTION · DISPLAY ONLY</span><h2>Manual command-line instructions</h2><p>Copy these commands into a terminal on the endpoint you intend to manage. Copying a command does not execute it. The console does not track removals started in a terminal; rescan afterward.</p>'
    if target in ('windows-server', 'windows-desktop'):
        body += '<p>Open CMD or PowerShell as administrator. Replace <code>{PRODUCT-GUID}</code> with the exact MSI identifier shown under Review installation. Use a vendor-issued secure token when self-defense requires it.</p><h3>PowerShell</h3><p>Start the session below, then paste the removal script. The execution-policy option applies to this new process; it does not grant administrator privileges, override enforced Group Policy, or disable EPM self-defense.</p>'
        body += block('cli-ps-launch', '1. Start PowerShell with execution-policy bypass', WINDOWS_LAUNCH)
        body += block('cli-ps-remove', '2. Full uninstall with a masked token prompt', WINDOWS_PS)
        body += '<h3>Command Prompt (CMD)</h3><p>Use the first command when no secure token is required, or the second when self-defense requires one. Replace all placeholders before running. For tokens containing CMD expansion characters such as <code>%</code> or <code>!</code>, use the PowerShell prompt above.</p>'
        body += block('cli-cmd-remove', 'CMD: full uninstall without a token', WINDOWS_CMD)
        body += block('cli-cmd-token', 'CMD: full uninstall with a vendor token', WINDOWS_CMD_TOKEN)
        body += '<p>These commands request full removal and suppress automatic restart. MSI codes: <code>0</code> successful, <code>3010</code> restart required, <code>1641</code> restart initiated. Other codes need investigation; <code>1605</code> means the selected product is not installed. Check the selected registration again and plan a restart before reinstalling.</p><p>Inline CMD tokens may appear in command history. Even prompted tokens can be visible to privileged process inspection and vendor logs.</p><a href="https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1" target="_blank" rel="noopener">PowerShell invocation reference ↗</a>'
    elif target == 'macos':
        body += '<p>Open Terminal on the Mac. The full uninstall uses the installed vendor helper and requires an administrator account for <code>sudo</code>. Use the token-file variant if EPM self-defense requires a token.</p>'
        body += block('cli-mac-full', 'Terminal: full uninstall without a token', MAC_FULL)
        body += block('cli-mac-token', 'Terminal: full uninstall with a token file', MAC_TOKEN)
        body += '<p>Replace the absolute token-file path with your vendor-issued secure token file. Restrict its permissions to the owner (<code>chmod 600 /absolute/path/to/epm-secure-token.txt</code>) and handle it according to your organization’s secret-retention policy. Do not paste tokens into shell history. Follow any vendor dialogs, then rescan this endpoint.</p>'
    else:
        body += '<p>Read-only Linux identification commands are available below. The console has no automatic Linux removal adapter. Confirm the installed product/version and follow its approved vendor uninstall procedure; no generic removal command is supplied. Package matches are candidates for investigation and do not prove that a package is the EPM agent. No matches can also mean the software was installed outside the package manager.</p>'
        body += block('cli-linux-os', 'Identify the Linux distribution', OS_INFO)
        distro = page.get('distro')
        if distro in ('ubuntu', 'debian'): body += block('cli-linux-deb', 'Inspect DEB package inventory', DEB)
        elif distro in ('rhel', 'rocky', 'almalinux', 'fedora', 'suse'): body += block('cli-linux-rpm', 'Inspect RPM package inventory', RPM)
        elif distro == 'arch': body += block('cli-linux-arch', 'Inspect Arch package inventory', ARCH)
        else:
            body += block('cli-linux-tools', 'Check available package inventory tools', 'command -v dpkg-query rpm pacman')
            body += block('cli-linux-deb', 'DEB-based systems: inspect package inventory', DEB)
            body += block('cli-linux-rpm', 'RPM-based systems: inspect package inventory', RPM)
            body += block('cli-linux-arch', 'Arch-based systems: inspect package inventory', ARCH)
        body += '<p>Share the product name, installed version and distro version with your CyberArk administrator, obtain the exact vendor uninstall procedure, and validate it on an approved test endpoint. Avoid generic purge or file-deletion commands.</p>'
    return body + '<p class="muted" id="cli-copy-feedback" aria-live="polite"></p></section>'

def update_pages(root):
    for page in PAGES.values():
        fragment = guide(page)
        if not fragment: continue
        path = root / 'static' / page['file']
        content = path.read_text(encoding='utf-8')
        # Idempotent generated region; hand-authored content remains untouched.
        content = re.sub(r'<!-- manual-cli:start -->.*?<!-- manual-cli:end -->', '', content, flags=re.S)
        content = content.replace('<footer>', '<!-- manual-cli:start -->' + fragment + '<!-- manual-cli:end --><footer>', 1)
        path.write_text(content, encoding='utf-8')

if __name__ == '__main__': update_pages(Path(__file__).resolve().parent)
