"""Public platform catalog. Linux entries are guidance only."""
DOWNLOAD_URL = 'https://github.com/keithgalleros-dxcm/CyberArkEPMRemovalTool-Web/releases/download/windows-v1.1.0/CyberArkEPMRemovalTool-1.1.0-portable-win-x64.zip'
DISTROS = {'ubuntu': 'Ubuntu', 'debian': 'Debian', 'rhel': 'Red Hat Enterprise Linux', 'rocky': 'Rocky Linux', 'almalinux': 'AlmaLinux', 'fedora': 'Fedora', 'suse': 'SUSE / openSUSE', 'arch': 'Arch Linux', 'other': 'Other Linux distributions'}
PAGES = {
 '/': {'title': 'Endpoint management workspace', 'file': 'index.html', 'kind': 'overview'},
 '/windows-server': {'title': 'Windows Server removal', 'file': 'windows-server.html', 'kind': 'removal', 'target': 'windows-server', 'description': 'Plan a maintenance window, review workload dependencies and select the installed EPM agent. Restart planning stays under your control.'},
 '/windows-desktop': {'title': 'Windows Desktop removal', 'file': 'windows-desktop.html', 'kind': 'removal', 'target': 'windows-desktop', 'description': 'Review the workstation agent and use Windows Installer for a full uninstall. Save your work and plan a restart before reinstalling.'},
 '/macos': {'title': 'macOS removal', 'file': 'macos.html', 'kind': 'removal', 'target': 'macos', 'description': 'Use the installed CyberArk EPM uninstall helper with full removal. Start the console as root and follow any vendor dialogs on this Mac.'},
 '/linux': {'title': 'Linux distributions', 'file': 'linux.html', 'kind': 'linux', 'description': 'Choose a distribution for identification and removal readiness guidance. Use matched private kits for installation. Linux removal remains a manual support workflow.'},
 '/integrations': {'title': 'API & AI integrations', 'file': 'integrations.html', 'kind': 'docs'},
}
for slug, title in DISTROS.items():
 PAGES['/linux/' + slug] = {'title': title + ' removal readiness', 'file': 'linux-' + slug + '.html', 'kind': 'distro', 'target': 'linux', 'distro': slug, 'description': 'Identify the installed CyberArk product and version before selecting a vendor-supported removal procedure. Automated Linux removal is not enabled.'}

PAGES['/installation']={'title':'CyberArk agent installation','file':'installation.html','kind':'installation'}
PAGES['/download-center']={'title':'Agent download center','file':'download-center.html','kind':'downloads'}
