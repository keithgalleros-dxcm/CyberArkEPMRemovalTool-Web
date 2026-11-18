# CyberArk EPM Removal Web Console

Python 3.11+ local web application for Windows and macOS. No third-party dependencies.
Run **on the endpoint being managed**; the browser cannot remove software from other computers.

## Start

Windows: open PowerShell as Administrator, change to this folder, then run `python app.py`.
macOS: change to this folder, then run `sudo /absolute/path/to/python3 app.py` using a trusted Python installation.
Open http://127.0.0.1:8765 in a browser on that same endpoint. Stop with Ctrl+C only after removal completes.
Without elevation the console supports scanning only. Do not expose this service through a proxy or tunnel.

Review the selected installation, supply the vendor secure token if required, type UNINSTALL, then select Uninstall.
Windows uses both machine registry views, MSI full uninstall and no automatic restart.
macOS uses `/Applications/CyberArk EPM.app/Contents/Helpers/CyberArkEPMUninstall -full`.
No forced service, driver, registry or file cleanup is performed.

Tokens are not persisted or logged by this app. Vendor command lines necessarily pass tokens to the child process;
privileged process inspection and vendor logging may expose them. Vendor output is discarded by the app.
Verification checks the selected MSI registration or macOS helper, not every file, service or driver.
Restart before reinstalling. macOS may require interaction with vendor dialogs.

## Workspaces

Primary: `\\192.168.1.101\Users\Keith\source\repos\CyberArkEPMRemovalTool\webapp`
Secondary: `C:\Users\iy52648\source\repos\CyberArkEPMRemovalTool\webapp`
Edit primary first. Keep `.git`, caches and runtime state separate.

## Checks

`python -m unittest discover -s tests -v`
CI runs mocked adapter and HTTP security tests on Windows, macOS and Linux. No tests uninstall software.
Actual removal requires validation on disposable Windows/macOS endpoints with vendor-approved tokens.

## Vendor references

- https://docs.cyberark.com/epm/latest/en/content/installation/macos-uninstallagents.htm
- https://docs.cyberark.com/epm/latest/en/content/installation/windows-uninstallagents.htm

This is a local administrative utility, not a central fleet-management server.
