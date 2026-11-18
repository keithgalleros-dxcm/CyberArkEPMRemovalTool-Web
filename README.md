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
