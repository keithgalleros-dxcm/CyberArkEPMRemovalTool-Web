# Dexcom CyberArk EPM portal

Python 3.11+ portal and endpoint connector, using the standard library only.

## How endpoint detection works

The LAN portal displays the **PC/VM paired with that browser**, not the computer hosting the portal.
A normal browser cannot inspect installed software, services or UAC state. Each visiting PC therefore
needs its own connector. Browser OS hints and source IPs are not used as a substitute for endpoint inventory.

1. Start the central portal and sign in from the target PC's browser.
2. Click **Install connector**. The OS selector defaults from browser hints; correct it if necessary.
   Browser hints select an installer only. Actual inventory comes from the installed connector.
3. **Windows desktop/server:** open the downloaded **Install-connector.cmd**. It detects a working
   Python 3.11+, or downloads a SHA-256 verified official private Python runtime for the actual CPU.
   Setup extracts and installs the connector under `%LOCALAPPDATA%\Dexcom\EPMConnector`, starts it
   in the background, and adds a **Dexcom Endpoint Connector** Start menu reconnect shortcut.
   No manual ZIP extraction, Python installation, PATH changes or copying into Python's folder.
4. **macOS/Linux:** open Terminal in Downloads and run `sh Install-connector.sh`. Setup finds Python
   3.11+, installs it when missing, extracts into a private per-user application folder and starts
   the connector. macOS uses the official checksum-verified Python PKG (sudo approval); Linux uses
   apt/dnf/zypper/pacman/apk repositories. Unsupported/older repositories stop with instructions.
5. The connector opens the paired portal and reports its own hostname, OS, CPU, agents and privileges.
   Confirm **Connected to this endpoint** and compare the hostname before any agent operation.
6. Approve Windows UAC **on that endpoint** when needed. macOS/Linux show local sudo instructions.
   Installing/removing CyberArk still requires explicit confirmation and the endpoint hostname.

A browser cannot silently run a downloaded program or detect Python on an unconnected PC. The first
installer launch is required; runtime detection and the remaining setup then run automatically.
Keep the installer private and open it within 10 minutes. A slow prerequisite installation can exhaust
enrollment; use **Install connector** again afterward (Python will already be present on macOS/Linux).
Windows private runtimes belong to their specific installation and may be downloaded again on re-enrollment.

Connector logs and `setup-info.json` (runtime mode/path) are stored in its installation folder. Windows:
`%LOCALAPPDATA%\Dexcom\EPMConnector\<installation-id>`. macOS:
`~/Library/Application Support/Dexcom/EPMConnector/installation.*`. Linux:
`${XDG_DATA_HOME:-~/.local/share}/dexcom/epm-connector/installation.*`.
Windows reconnects via Start menu; macOS/Linux via the generated `Reconnect.command`.
No connector service or automatic login startup is registered. After reboot, reconnect explicitly.
A portal restart requires a fresh installer on each endpoint. Stop only the connector process identified
in that installation's `connector.pid`, after its agent jobs finish. Closing the browser does not stop it.

No connector/offline connector means **Not connected**. The portal never silently falls back to the
web server's agent details or execution context. Connector requests are outbound HTTP(S) to the portal;
no inbound endpoint firewall port, browser localhost fetch, CORS exception or browser security flag is needed.
This also works with a bridged VM: launch the connector inside the guest, not in the VMware host terminal.

The intentional standalone mode at `http://127.0.0.1:8765` manages that same PC directly. LAN URLs always
use endpoint pairing, including when the browser source IP happens to equal the portal's LAN address.

## Requirements

| Component | Requirements |
| --- | --- |
| Portal | Python 3.11+, readable private deployment library, free TCP 8765 |
| Each endpoint | Run its own connector installer; Python detected/provisioned; outbound access to portal and prerequisite sources when needed |
| Browser | JavaScript, cookies and local storage enabled |
| Windows privilege changes | Local UAC approval / administrator credentials |
| macOS/Linux installation | Root/sudo on that endpoint; vendor prerequisites and macOS extension approvals |
| Dependencies | No pip, Node.js, Docker, .NET SDK or database required for the Python components |
| Private kit storage | Supplied library about 409 MiB; allow extra temporary staging and vendor installation space |

Python setup: [Windows downloads](https://www.python.org/downloads/windows/) and
[official setup guidance](https://docs.python.org/3/using/windows.html).
Read **[execute commands.txt](execute%20commands.txt)** for host paths, exact commands and troubleshooting.
The public repository does not include tenant installers, installation keys, configurations or enrolled-device credentials.

## Start the portal on 192.168.1.101

On that laptop, change to the native source folder:

```powershell
Set-Location 'C:\Users\Keith\source\repos\CyberArkEPMRemovalTool\webapp'
py -3 --version
```

One-time firewall setup in an **Administrator PowerShell** session:

```powershell
$pythonPath = py -3 -c "import sys; print(sys.executable)"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Enable-LanFirewall.ps1 -LocalAddress 192.168.1.101 -RemoteSubnet 192.168.1.0/24 -PythonPath $pythonPath
```

Then start the portal (server elevation is not needed for remote endpoint operations):

```powershell
py -3 app.py --lan-address 192.168.1.101
```

Keep its terminal open. On the portal laptop, open [loopback](http://127.0.0.1:8765) and expand
**LAN access and managed endpoint** to obtain the LAN sign-in code. Other PCs visit
[the portal](http://192.168.1.101:8765), sign in and connect their own endpoint connector.
The firewall helper supports the specified matching /24 and leaves an existing named rule unchanged.

For the 192.168.1.100 workstation, use `C:\Users\iy52648\source\repos\CyberArkEPMRemovalTool\webapp`
and change `-LocalAddress` / `--lan-address` to `192.168.1.100`.
Do not assign the server's IP to a VM or another PC.

## Private deployment library and installation

Keep the approved **Cyberark Agents** folder beside **webapp**, preserving the paired installer,
`.config` and `agent installation key.txt` files. A custom library uses `EPM_AGENT_ROOT` on the portal.
Endpoint connectors do not need a copy of the entire library. Only the selected compatible kit is
downloaded privately when an installation is explicitly requested. Staged files are removed afterward.
Windows read-only health verification downloads only the MSI, not the installation key/config.

The installation workspace detects the connector endpoint's OS/version/CPU and existing agents.
Existing installations, known required restarts and missing elevation block installation. It supports
fresh installation after approved removal, not an in-place upgrade. Restart the endpoint when required;
restarting only the portal/connector is not an OS restart. No uninstall/install chaining happens automatically.

Current matching: Windows x64 desktop build 19045+ / Server build 14393+; supplied universal macOS PKG
requires macOS 14.5+; Linux x64 uses the exact provided distro families and Ubuntu LTS versions.
Unmatched Debian/Fedora/Arch/AlmaLinux or ARM Windows/Linux systems are not assigned an installer by analogy.
Native installer prerequisites, key validity and vendor support requirements still apply.
Linux automatic removal is not enabled; inventory and approved manual removal guidance remain available.

Windows completion requires the selected MSI ProductCode/version, its vf_agent.exe component file, and
a running vf_agent service. An accepted but unhealthy/unverified installation returns `attention_required`
with the actual endpoint hostname. Use **Verify Windows agent (read-only)** without rerunning installation.
Windows enrollment/policy health must still be confirmed in EPM. macOS/Linux activation status is checked;
macOS extensions and Full Disk Access may need local interaction or MDM.

## Download center and standalone utility

The download center provides confidential manual kits to authorized portal users, including installer,
paired config/key and `INSTALL-README.txt`. Downloading is separate from installation and does not grant admin rights.
[Windows standalone removal utility](https://github.com/keithgalleros-dxcm/CyberArkEPMRemovalTool-Web/releases/tag/windows-v1.1.0)
is also available. It is the existing unsigned portable desktop tool, with release checksums, not a packaged connector.

## API and AI integrations

Import [openapi.json](openapi.json). A paired-endpoint API call needs both:

- `Authorization: Bearer <EPM_API_KEY>` configured on the portal.
- `X-Endpoint-Key: <authorized endpoint capability>` provisioned privately from its connector setup.

Never paste either credential into chat, URLs or logs. Connector credentials are not EPM installation/uninstall tokens.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/endpoint/info` | Whether the paired endpoint is connected; its hostname |
| POST | `/api/v1/endpoint/rpc` | Queue an allowlisted operation for that endpoint |
| GET | `/api/v1/endpoint/result/{request_id}` | Poll the response for that endpoint request |

RPC body: `method` (`GET` or `POST`), `path` (an allowlisted endpoint API path), and optional object `body`.
Supported paths: `/api/status`, `/api/packages`, `/api/installation-health`, `/api/elevate`, `/api/install`, `/api/uninstall`.
Read operations must use GET; install/uninstall/elevation use POST. Obtain operator approval before mutations.
Installer selection and hostname/confirmation validation happen again on the endpoint. UAC occurs there.
A queued RPC is not proof of installation success. Read the native operation result and poll `/api/status` for its job.
Never blindly retry a timed-out mutation; rescan first because the operation may have started.

The legacy `/api/v1/status`, `/api/v1/packages`, `/api/v1/install`, `/api/v1/uninstall` routes remain
**explicit host-mode APIs** for existing integrations. They do not infer the browser PC. Use the paired-endpoint
API above for visiting PCs. The LAN GUI cannot use legacy browser routes to fall back to the portal host.

## Pairing, security and operational limits

- Enrollment tickets are one-use and expire after 10 minutes. Connector installers contain no CyberArk installers,
  tenant config or installation key, but their enrollment/device config is private. Never share/reuse kits across PCs.
- Each endpoint gets a separate credential and browser capability. Commands are allowlisted, consumed once,
  and are not arbitrary shell commands. Requests/results are isolated by endpoint and browser capability.
- Keep `connector.private.json` private. Run one connector instance per endpoint. A replacement instance
  invalidates the older polling instance; active operations block ordinary replacement.
- Portal registry, jobs and relay results are in memory. After a portal restart, reload/sign in and download
  a fresh connector installer to re-enroll. Do not restart the portal or close connectors during active operations.
- Paired browsers may remember their endpoint capability. Clear pairing on shared browsers. Only the PC
  where the connector actually runs supplies inventory; moving a private kit to another PC is not supported.
- LAN sign-in remains separate. LAN codes rotate on portal restart and cookies expire after eight hours.
  HTTP is unencrypted; use only a trusted LAN. HTTPS can be used with appropriately deployed transport.
- No agent installation/removal happens merely by starting the connector. Administrative approval is local.
  Organizational CyberArk JIT entitlement requests still go through IT, not automatic account-rights changes.
- Vendor command lines/logs can expose installation tokens to privileged inspection. Temporary MSI logging
  hides specified properties; raw staging logs are deleted and only numeric diagnostics are returned.
- The stdlib server and relay have not been load-tested for enterprise-scale deployment.

## Validation

```text
python -m unittest discover -s tests -q
node tests/check_endpoint_bridge.mjs
node --check static/endpoint-bridge.js
node --check static/ui.js
node --check static/install-ui.js
```

Node is optional for syntax checks, not required to run portal/connector. CI runs mocked checks on Windows,
macOS and Linux. Tests simulate VM identity routing and verify no host fallback. No live install/removal or
UAC approval was performed during development. Real multi-PC/VM and browser interaction still needs validation.

Vendor references: [Windows](https://docs.cyberark.com/epm/latest/en/content/installation/windows-installagents.htm),
[macOS](https://docs.cyberark.com/epm/latest/en/content/installation/macos-installagents.htm),
[Linux](https://docs.cyberark.com/epm/latest/en/content/installation/linux-installagents.htm).
Brand sources and ownership are recorded in `static/brand/SOURCES.md`.

## Connector runtime sources

Windows private runtime and missing macOS Python use the official [Python 3.15.2 release](https://www.python.org/downloads/release/python-3152/),
with SHA-256 digests pinned in `connector_setup`. Windows downloads the x64/x86/ARM64 embeddable ZIP
matching the actual machine; macOS downloads the universal PKG. The Windows embedded distribution
is supported for [private application runtimes](https://docs.python.org/3/using/windows.html#the-embeddable-package).
Existing compatible Python is reused. Linux prerequisite packages come from the endpoint's configured
OS repositories. Network/proxy policies, application control and local sudo/UAC policies still apply.
Setup reports failures and does not claim successful portal enrollment merely because files were copied.
