# EPM Removal Web Console

Python 3.11+ endpoint-local web app, with no third-party dependencies.


## Setup prerequisites and launch guide

Read **[execute commands.txt](execute%20commands.txt)** for complete prerequisites, exact commands for the
192.168.1.101 laptop and 192.168.1.100 workstation, LAN sign-in, private kits, and troubleshooting.
The file is a reference guide; it does not execute commands automatically.

| Requirement | Details |
| --- | --- |
| Python | Python 3.11+ supported by the host OS; standard installation, preferably x64 on Windows x64 |
| Windows shell | PowerShell 5.1+; administrator approval for firewall changes and agent operations |
| Browser | Current browser with JavaScript and cookies enabled |
| Dependencies | No pip packages, Node.js, Docker, .NET SDK or database setup needed for this Python app |
| Deployment data | Approved private `Cyberark Agents` folder beside `webapp`, or configure `EPM_AGENT_ROOT` |
| Disk space | Supplied private kits occupy about 409 MiB, plus staging space and vendor agent requirements |
| Network | Free TCP 8765; assigned private IPv4 and scoped firewall rule for LAN; EPM service connectivity for agents |
| Privileges | Administrator/UAC on Windows; root for macOS/Linux installation; no elevation needed for read-only inventory |

Python setup: [official Windows downloads](https://www.python.org/downloads/windows/)
and [Windows setup documentation](https://docs.python.org/3/using/windows.html).
After installing an approved Python release, reopen PowerShell and verify `py -3 --version`.
If only `python` is available, replace `py -3` with `python` in the examples.
Web-app runtime requirements and vendor agent compatibility are separate; see the installation section below.

### Start on the 192.168.1.101 laptop

Run these commands **on that laptop**, in **PowerShell as Administrator**:

```powershell
Set-Location 'C:\Users\Keith\source\repos\CyberArkEPMRemovalTool\webapp'
py -3 --version
$pythonPath = py -3 -c "import sys; print(sys.executable)"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Enable-LanFirewall.ps1 -LocalAddress 192.168.1.101 -RemoteSubnet 192.168.1.0/24 -PythonPath $pythonPath
py -3 app.py --lan-address 192.168.1.101
```

Keep the terminal open. Browse to [loopback](http://127.0.0.1:8765) on the host or
[192.168.1.101](http://192.168.1.101:8765) from the LAN. Other devices enter the code shown in the host's
**LAN access and managed endpoint** panel. The firewall helper expects a matching /24 subnet and leaves
an existing named rule unchanged; review its IP and executable scope when reusing it.

### Start on the 192.168.1.100 workstation

Use the same steps **on that workstation**, changing the project path to
`C:\Users\iy52648\source\repos\CyberArkEPMRemovalTool\webapp` and both `-LocalAddress` and
`--lan-address` to `192.168.1.100`. The subnet remains `192.168.1.0/24` for this network.
Each instance manages its hosting machine; a browser on another device does not change that target.

### Fresh public checkout

Clone or download this repository into a new folder, then run commands from the folder containing `app.py`.
For a fresh Windows checkout with Git installed (use a new destination folder):

```powershell
git clone https://github.com/keithgalleros-dxcm/CyberArkEPMRemovalTool-Web.git CyberArkEPMRemovalTool-Web
Set-Location .\CyberArkEPMRemovalTool-Web
py -3 --version
py -3 app.py
```

This starts local-only mode. Use the LAN steps above with this checkout’s actual path when needed.
The public source does **not** include tenant installers, installation keys or configurations.
Provision the approved private kit library separately and set `EPM_AGENT_ROOT` if it is not in the default sibling folder.
Do not copy deployment secrets into `static` or commit them. Starting Python does not start an agent installation.

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
| `/installation` | Existing-agent checks, OS matching and private-kit installation |
| `/download-center` | Confidential manual deployment bundles |

Linux removal pages provide manual guidance; no automatic Linux removal adapter is enabled.
The installation workspace supports the supplied Linux kits only when distro/version and architecture match.
Windows Server and Desktop share Windows Installer commands; the page must match the Windows product type.

## Run

Run Python on the endpoint you intend to manage. LAN browsers control that hosting endpoint;
opening a page from another device does not retarget installation/removal to the browser device.
Windows: open PowerShell as administrator in this folder and run `python app.py`.
macOS: use `sudo /absolute/path/to/trusted/python3 app.py`.
Linux: `python3 app.py` for read-only inventory; approved agent installation requires a root launch.
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
to a private local folder before launch. UAC relaunch preserves the LAN address and uses the default relative private-kit folder; custom environment configuration
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

## Optional LAN access

Run `python app.py --lan-address 192.168.1.100` when that private IPv4 address is assigned to the host.
The app listens separately on loopback and the specified address, port 8765; it does not bind all interfaces.
Open http://192.168.1.100:8765. On another device, enter the LAN access code shown under **LAN access and
managed endpoint** in the server’s loopback UI. Codes rotate on process restart; signed HttpOnly/SameSite
cookies expire after eight hours. Codes are not logged, put in URLs, or saved in the repository. Bearer
API integration still requires its separately configured key. Host and Origin allowlists remain enforced.

Authenticated LAN operators can view/manage the hosting endpoint and download its private kits.
They are not managing their browser device. UAC must be requested/approved on the server locally.
Administrator relaunch preserves the LAN address but rotates browser sign-in sessions.
HTTP is unencrypted: use a trusted LAN and approved channels for access codes and downloaded kits.
The default launch remains loopback-only. Windows Firewall must permit TCP 8765 for the configured local
address from the intended LAN subnet; do not use unrestricted inbound or internet port-forwarding rules.

Windows firewall setup: review and run `Enable-LanFirewall.ps1` from an administrator PowerShell session. The helper scopes access to the configured local address, Python executable and matching /24 subnet; it does not change the network profile.
LAN bearer clients may use the configured LAN address as their API base URL. Browser cookies do not replace API bearer keys.

## VM targets and Windows installation verification

VMware bridged networking does not make the browser VM the installation target. A browser at
`http://192.168.1.101:8765` manages the Python process on the machine owning that address. To install
inside a VM, run Python inside that VM and open its loopback URL, or download a private kit inside
the VM and follow its INSTALL-README.txt as administrator. Confirm the VM computer name matches
Managed endpoint before installing. The installation form now requires typing that hostname.

Windows completion requires the selected MSI's exact ProductCode and version, its vf_agent.exe
component file, and a running vf_agent service. MSI acceptance alone or an unrelated EPM registration
does not count as complete. An accepted but unverified install returns attention_required with the
actual execution hostname and Windows verification fields. Restart when required and confirm
console enrollment separately. Tray visibility is not used as the health test.

Windows installation temporarily enables a verbose MSI log with confidential properties marked
hidden. The log stays in the private staging directory and is deleted with staging. Only numeric
MSI error/engine codes and failure flags are returned; raw log lines are not served or retained by
the app. Installer/debug policy may still put sensitive values in temporary vendor logs.

Use **Verify Windows agent (read-only)** in the installation workspace to inspect the expected product, version, component file and vf_agent service on the host without reinstalling. Compare the returned hostname with the VM computer name.
