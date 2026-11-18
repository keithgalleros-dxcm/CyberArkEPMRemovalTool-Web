# EPM Removal Web Console

Python 3.11+ endpoint-local web app, with no third-party dependencies.

## Pages

| Page | Function |
| --- | --- |
| `/` | Platform overview and local endpoint identity |
| `/windows-server` | Server maintenance guidance and Windows MSI removal |
| `/windows-desktop` | Workstation MSI removal |
| `/macos` | Installed CyberArk EPM helper with full removal |
| `/linux` | Linux distro chooser and OS identification |
| `/linux/{distro}` | Ubuntu, Debian, RHEL, Rocky, AlmaLinux, Fedora, SUSE, Arch, or other distro readiness |
| `/integrations` | API setup and AI integration guide |

Linux pages provide guidance only. The Linux CyberArk product and version have not been identified;
no Linux removal adapter or arbitrary package removal command is enabled.
Windows Server and Desktop share Windows Installer commands; the page must match the Windows product type.

## Run

Run on the endpoint you intend to manage. A browser cannot remove software from other computers.
Windows: open PowerShell as administrator in this folder and run `python app.py`.
macOS: use `sudo /absolute/path/to/trusted/python3 app.py`.
Linux: `python3 app.py` for distro identification and guidance; root is unnecessary for those features.
Open http://127.0.0.1:8765. Non-elevated Windows/macOS sessions support scanning only.
Keep the process running until removal finishes. Do not expose the console through a tunnel or proxy.

Review the agent, provide the vendor secure token if self-defense requires it, and type UNINSTALL.
Windows requests full MSI removal with no automatic restart. macOS invokes the vendor helper with `-full`.
The console never forcibly deletes services, drivers, registry keys or files.
Verification checks the selected MSI registration or macOS helper, not every artifact on the endpoint.
Plan a restart before reinstalling. Server removal requires maintenance planning; macOS may show vendor dialogs.

## AI and API integrations

Import [openapi.json](openapi.json) into a tool that can reach the endpoint-local service.
Cloud AI tools cannot reach a colleague's loopback address; use a connector running on that endpoint.

Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Set `EPM_API_KEY` in the server environment before starting. Use 32+ ASCII characters without whitespace.
Configure the same key in the local client. This key is separate from the vendor EPM secure token.
Do not commit keys, place them in URLs, or include vendor tokens in prompts or logs.
API access is disabled when the variable is unset. Restart the server to rotate the key.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/status` | Endpoint, distro, agents, privileges, operation status |
| GET | `/api/v1/platforms` | Platform and distro page catalog |
| POST | `/api/v1/uninstall` | Explicitly confirmed removal |

Send `Authorization: Bearer <key>` on integration requests. POST also requires `Content-Type: application/json`.
Browser Origin headers are rejected on integration routes; the UI uses a separate origin/session check.
Removal body: `id`, `hostname`, `target_platform`, `confirmation: "UNINSTALL"`, optional `token`.
Read status and obtain explicit operator approval for the exact hostname and agent first.
HTTP 202 means accepted; poll `/api/v1/status` until `job.status` is `completed` or `failed`.
Operation state is in memory; there is no durable history, queue, or cross-process coordination.
Only one removal runs at a time. Do not blindly retry POST after an uncertain response: check status first.

Use `python examples/client.py` for read-only status. For removal use:
`python examples/client.py --uninstall "<exact-agent-id>" --hostname "<exact-hostname>" --with-token`.
The client requires confirmation and privately prompts for the vendor token.

## Windows standalone download

[Portable Windows x64 v1.1.0](https://github.com/keithgalleros-dxcm/CyberArkEPMRemovalTool-Web/releases/tag/windows-v1.1.0).
The Windows pages provide the same download link. The release contains the existing desktop utility,
not a packaged Python server. Extract and run the EXE as administrator. The binary is unsigned.
Compare the ZIP and EXE SHA-256 hashes against the release checksum file before running.
Original source: [CyberArkEPMRemovalTool](https://github.com/keithgalleros-dxcm/CyberArkEPMRemovalTool).
No end-to-end removal has been tested for this web version or on Windows Server.

## Validation

`python -m unittest discover -s tests -v`
`node --check static/ui.js` (optional; Node is not needed to run the app).
CI runs mocked tests on Windows, macOS and Linux. Tests never uninstall software.
Validate actual removal on disposable approved endpoints. Tokens are not persisted or logged by this app,
but privileged process inspection and vendor logs may expose tokens passed on vendor command lines.

## Vendor references

- [Windows uninstall](https://docs.cyberark.com/epm/latest/en/content/installation/windows-uninstallagents.htm)
- [macOS uninstall](https://docs.cyberark.com/epm/latest/en/content/installation/macos-uninstallagents.htm)

This is an endpoint-local tool, not a central fleet-management server.

## Manual terminal commands

Windows Server/Desktop pages include a process-scoped PowerShell invocation using
`powershell.exe -NoProfile -ExecutionPolicy Bypass`, a removal script with a masked
vendor-token prompt, and CMD examples with and without a token. Replace the MSI GUID
placeholder before running. Policy bypass does not grant elevation or disable EPM protection.
macOS includes vendor full-uninstall commands with no token or a token file.
Linux distro pages include read-only OS and package-inventory commands only; the product
and vendor uninstall procedure must be identified before supplying a Linux removal command.
Commands are displayed and copied only. Terminal removals are outside the console’s job tracking.
Regenerate command sections after editing `manual_commands.py` with `python manual_commands.py`.

## Dexcom visual theme

The console uses the existing Dexcom logo, Gilroy Medium/Bold typography, public-site green (#137D00), charcoal (#161A1D), and white surfaces. Brand assets are served locally, including offline use. Font fallback is Arial/sans-serif. See `static/brand/SOURCES.md` for provenance and ownership. All platform, API, download and CLI workflows are preserved.

## Requesting administrator access

The UI provides a **Request administrator access (UAC)** action on Windows. It calls a
browser-session-protected local route and asks Windows to relaunch only this app with the
`runas` verb. An administrator must approve or enter credentials. Cancellation leaves the
original console available. The browser reconnects after approval and must confirm removal
separately. Vendor tokens are cleared and never forwarded during relaunch. Account membership
is unchanged. No UAC prompt is triggered automatically or through the integration API.

The relaunch uses the same trusted Python executable and absolute app path. Use the local
checkout: an approving administrator may not have access to a network share or user-scoped
Python installation. If relaunch cannot reconnect, stop any remaining console and use the
displayed manual launch command. An elevated console runs on the local endpoint until its
terminal is closed; closing the browser alone does not stop it.

API-enabled instances must be restarted manually by an administrator with their intended
configuration. macOS shows a sudo launch command to run after stopping the current server;
password entry happens in Terminal. Linux inventory needs no root access. Organizational
CyberArk EPM/JIT entitlement requests still go through your established IT workflow; this
app does not submit approval tickets or automatically grant rights.

## Installation workspace and private download center

Open `/installation` to detect OS version/architecture, inspect existing agents, and select the matching kit.
Open `/download-center` for confidential support bundles with installer, paired config/key file, and manual instructions.
Downloading does not need admin privileges. Installing requires Windows UAC-approved console elevation or root on macOS/Linux.
After uninstall, use the reinstall link and complete required restarts. Existing registrations/files and known pending
Windows restarts block installation. Reboot state is partly in memory; do not bypass vendor restart instructions by
restarting only the web server. No automatic uninstall/install chaining occurs.

Keep `Cyberark Agents` beside `webapp`, preserving the supplied directory structure; alternatively set `EPM_AGENT_ROOT`
to a private local folder before launch. UAC relaunch uses the default relative folder; custom environment configuration
should be preserved through a manual administrator launch. Never place kits under `static` or commit them. Git exclusions
cover deployment directories, keys, configs and native package files. The public repository includes source only;
colleagues must provision their approved private kit library separately. Original files remain unchanged.

Automatic matching is conservative: Windows x64 desktop build 19045+ and Server build 14393+; macOS 14.5+ Intel/Apple silicon
(as declared in the supplied PKG); exact Linux distro/version mappings from the vendor kit families. Debian, Fedora, Arch,
AlmaLinux, ARM Linux/Windows and other unmatched versions are not assigned an installer by analogy. Verify vendor
prerequisites and support status separately. The native installer validates actual prerequisites and config/key validity.

Linux package inventory checks `epm` and the vendor CLI path. macOS checks the vendor app/helper. Windows checks MSI
registrations and known remaining agent files. Detection errors block installation; these checks do not prove complete
removal of every driver or file. Reinstall through this workspace means a new install after removing the old agent,
not an in-place upgrade. Failed activation may leave installed files and blocks a blind retry.

The operation stages only required files in a local temporary directory and removes that staging area afterward.
Keys/configs are never returned by catalog/status endpoints or logged by the app. Windows/macOS vendor commands still
pass the installation key to a privileged child process; vendor logs/process inspection can expose it. Downloaded
ZIPs intentionally contain secrets and must be handled through approved internal channels. macOS extension/Full Disk
Access approval may still require user interaction or MDM. Windows verification checks registration; confirm enrollment
and policy health in the EPM console separately. Linux/macOS activation status is checked after installation.

API additions (same bearer authentication and explicit local endpoint confirmation):
- `GET /api/v1/packages`: redacted catalog, compatibility and preflight blockers.
- `POST /api/v1/install`: `package_id`, `hostname`, `target_platform`, `confirmation: "INSTALL"`; poll status afterward.
- Private kit downloads are browser-session-only POST requests, not public download URLs or integration API routes.

Vendor installation references:
- https://docs.cyberark.com/epm/latest/en/content/installation/windows-installagents.htm
- https://docs.cyberark.com/epm/latest/en/content/installation/macos-installagents.htm
- https://docs.cyberark.com/epm/latest/en/content/installation/linux-installagents.htm

Development tests use synthetic kits and mocked installers. No live installation or removal was performed.
