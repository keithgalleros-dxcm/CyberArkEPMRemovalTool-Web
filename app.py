"""Loopback-only EPM removal console. Python 3.11+, no dependencies."""
import ctypes
import json
import os
import platform
import re
import secrets
import subprocess
import threading
import sys
import argparse
import errno
import shlex
import time
from catalog import PAGES, DOWNLOAD_URL
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAC = Path('/Applications/CyberArk EPM.app/Contents/Helpers/CyberArkEPMUninstall')
GUID = re.compile(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}')
LOCK = threading.Lock()
JOB = {'status': 'idle'}
ELEVATING = False
SESSION = secrets.token_urlsafe(32)
API_KEY = os.environ.get('EPM_API_KEY', '')
if API_KEY and (len(API_KEY) < 32 or not API_KEY.isascii() or any(c.isspace() for c in API_KEY)):
    raise ValueError('EPM_API_KEY must contain at least 32 ASCII characters without whitespace')


def elevated():
    return bool(ctypes.windll.shell32.IsUserAnAdmin()) if platform.system() == 'Windows' else os.geteuid() == 0

def scan():
    if platform.system() == 'Darwin':
        return [{'id': 'mac-epm', 'name': 'CyberArk EPM', 'version': 'See installed application', 'location': str(MAC)}] if MAC.is_file() else []
    if platform.system() != 'Windows':
        return []
    import winreg
    found = {}
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            base = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 0, winreg.KEY_READ | view)
        except FileNotFoundError:
            continue
        with base:
            for i in range(winreg.QueryInfoKey(base)[0]):
                try:
                    name = winreg.EnumKey(base, i)
                    with winreg.OpenKey(base, name) as key:
                        def value(k):
                            try: return str(winreg.QueryValueEx(key, k)[0])
                            except FileNotFoundError: return ''
                        display = value('DisplayName')
                        if 'endpoint privilege manager agent' not in display.lower(): continue
                        code = GUID.search(name) or GUID.search(value('UninstallString'))
                        if code:
                            ident = code.group().upper()
                            found[ident] = {'id': ident, 'name': display, 'version': value('DisplayVersion'), 'location': value('InstallLocation')}
                except FileNotFoundError:
                    continue
    return list(found.values())

def command(agent_id, token):
    if not isinstance(token, str) or len(token) > 4096 or any(c in token for c in '\r\n\x00"'):
        raise ValueError('Invalid secure token')
    if platform.system() == 'Windows':
        if not GUID.fullmatch(agent_id): raise ValueError('Invalid MSI identifier')
        args = [str(Path(os.environ['SystemRoot'])/'System32'/'msiexec.exe'), '/x', agent_id, 'FULL_UNINSTALL=YES', '/qn', '/norestart']
        if token: args.append('SECURE_TOKEN=' + token)
        return args
    if platform.system() == 'Darwin' and agent_id == 'mac-epm':
        return [str(MAC), '-full'] + (['-token', token] if token else [])
    raise ValueError('Unsupported platform or agent')

def run_job(args, agent_id):
    global JOB
    try:
        # Never capture vendor output: it may contain the secure token.
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
        args.clear()
        code = process.wait()
        remaining = any(a['id'] == agent_id for a in scan())
        success = code in (0, 1641, 3010) and not remaining
        result = {'status': 'completed' if success else 'failed', 'exit_code': code, 'registration_present': remaining, 'restart_required': code in (1641, 3010), 'message': 'Selected installation is no longer detected. Restart before reinstalling.' if success else 'Removal was not verified. Review vendor guidance and rescan.'}
    except Exception:
        result = {'status': 'failed', 'message': 'Unable to complete removal or verification. Rescan and review vendor support guidance.'}
    with LOCK: JOB = result


def host_platform():
    system = platform.system()
    if system == 'Windows':
        return 'windows-desktop' if sys.getwindowsversion().product_type == 1 else 'windows-server'
    return {'Darwin': 'macos', 'Linux': 'linux'}.get(system, 'unsupported')

def distribution():
    if platform.system() != 'Linux': return None
    try:
        info = platform.freedesktop_os_release()
        return {'id': info.get('ID', 'unknown'), 'name': info.get('PRETTY_NAME', 'Linux'), 'version': info.get('VERSION_ID', ''), 'like': info.get('ID_LIKE', '')}
    except OSError:
        return {'id': 'unknown', 'name': 'Linux', 'version': '', 'like': ''}


def elevation_info():
    system = platform.system()
    if system == 'Windows':
        ps = lambda value: "'" + value.replace("'", "''") + "'"
        arguments = subprocess.list2cmdline([str(Path(__file__).resolve())])
        manual = 'Start-Process -Verb RunAs -FilePath ' + ps(sys.executable) + ' -ArgumentList ' + ps(arguments)
    elif system == 'Darwin':
        manual = 'sudo ' + shlex.join([sys.executable, str(Path(__file__).resolve())])
    else:
        manual = ''
    return {'method': 'windows-uac' if system == 'Windows' else 'manual', 'can_request': system == 'Windows' and not API_KEY, 'pending': ELEVATING, 'manual_command': manual}

def request_windows_elevation():
    """OS consent/credential prompt. Paths and arguments are fixed by this app."""
    from ctypes import wintypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    execute = shell.ShellExecuteW
    execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    execute.restype = ctypes.c_void_p
    parameters = subprocess.list2cmdline([str(Path(__file__).resolve()), '--wait-for-port'])
    code = execute(None, 'runas', sys.executable, parameters, str(Path(__file__).resolve().parent), 1) or 0
    if code <= 32:
        raise OSError('Administrator request was cancelled, denied, or could not start.')

def restart_after_elevation(server):
    def stop_original():
        time.sleep(0.4)
        server.shutdown()
    threading.Thread(target=stop_original, daemon=True).start()

def snapshot(browser=False):
    with LOCK: job = dict(JOB)
    result = {'platform': platform.system(), 'target_platform': host_platform(), 'hostname': platform.node(), 'distribution': distribution(), 'elevated': elevated(), 'agents': scan(), 'job': job, 'removal_supported': host_platform() in ('windows-desktop', 'windows-server', 'macos'), 'api_enabled': bool(API_KEY), 'elevation': elevation_info()}
    if browser: result['session'] = SESSION
    return result

def start_removal(args, agent_id):
    threading.Thread(target=run_job, args=(args, agent_id), daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def reply(self, status, data, kind='application/json'):
        raw = json.dumps(data).encode() if kind == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def trusted(self):
        return self.headers.get('Host') == '127.0.0.1:8765'

    def api_authorized(self):
        # Browser sessions never confer integration access; integrations cannot use CORS.
        value = self.headers.get('Authorization', '')
        return bool(API_KEY) and not self.headers.get('Origin') and secrets.compare_digest(value.encode('utf-8'), ('Bearer ' + API_KEY).encode('utf-8'))

    def do_GET(self):
        if not self.trusted(): return self.reply(403, {'error': 'Invalid host'})
        if self.path.startswith('/api/v1/'):
            if not self.api_authorized(): return self.reply(401, {'error': 'Configure EPM_API_KEY and supply a valid Bearer token; browser origins are not accepted.'})
            if self.path == '/api/v1/platforms': return self.reply(200, PAGES)
            if self.path != '/api/v1/status': return self.reply(404, {'error': 'Not found'})
            try: return self.reply(200, snapshot())
            except OSError: return self.reply(500, {'error': 'Endpoint scan failed'})
        if self.path == '/api/status':
            try: return self.reply(200, snapshot(browser=True))
            except OSError: return self.reply(500, {'error': 'Endpoint scan failed'})
        if self.path == '/catalog.json': return self.reply(200, PAGES)
        if self.path == '/openapi.json':
            return self.reply(200, json.loads((Path(__file__).parent/'openapi.json').read_text(encoding='utf-8')))
        if self.path == '/downloads/windows':
            self.send_response(302)
            self.send_header('Location', DOWNLOAD_URL)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path in PAGES:
            name, kind = PAGES[self.path]['file'], 'text/html; charset=utf-8'
        else:
            assets = {
                '/style.css': ('style.css', 'text/css'),
                '/ui.js': ('ui.js', 'text/javascript'),
                '/brand/dexcom-logo.png': ('brand/dexcom-logo.png', 'image/png'),
                '/brand/Gilroy-Medium.woff2': ('brand/Gilroy-Medium.woff2', 'font/woff2'),
                '/brand/Gilroy-Bold.woff2': ('brand/Gilroy-Bold.woff2', 'font/woff2'),
            }
            if self.path not in assets: return self.reply(404, {'error': 'Not found'})
            name, kind = assets[self.path]
        self.reply(200, (Path(__file__).parent/'static'/name).read_bytes(), kind)

    def handle_elevation(self):
        global ELEVATING
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2048: raise ValueError()
            if self.headers.get_content_type() != 'application/json': raise ValueError()
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or data.get('confirmation') != 'REQUEST_ADMIN': raise ValueError()
        except (ValueError, TypeError): return self.reply(400, {'error': 'Invalid elevation request'})
        if data.get('hostname') != platform.node(): return self.reply(409, {'error': 'Endpoint changed; refresh and request again.'})
        if platform.system() != 'Windows': return self.reply(422, {'error': 'Use the manual elevation instructions for this platform.'})
        with LOCK:
            if JOB['status'] == 'running' or ELEVATING: return self.reply(409, {'error': 'Removal or elevation is already in progress.'})
            if elevated(): return self.reply(200, {'status': 'already_elevated'})
            if API_KEY: return self.reply(409, {'error': 'API-enabled consoles must be restarted manually with the same administrator-approved configuration.'})
            ELEVATING = True
        try:
            request_windows_elevation()
        except OSError:
            with LOCK: ELEVATING = False
            return self.reply(409, {'error': 'UAC was cancelled, denied, or could not launch Python. This console remains available. Ask IT for administrator approval or use the manual instructions.'})
        # Approval starts only the console; no uninstall is initiated or token forwarded.
        try: self.reply(202, {'status': 'restarting', 'message': 'UAC approved. Reconnecting to the administrator console.'})
        finally: restart_after_elevation(self.server)

    def do_POST(self):
        global JOB
        if not self.trusted(): return self.reply(403, {'error': 'Invalid host'})
        integration = self.path.startswith('/api/v1/')
        if integration:
            if not self.api_authorized(): return self.reply(401, {'error': 'Invalid API credentials or browser origin'})
        elif self.headers.get('Origin') != 'http://127.0.0.1:8765' or self.headers.get('X-Session') != SESSION:
            return self.reply(403, {'error': 'Invalid session or origin'})
        if self.path == '/api/elevate': return self.handle_elevation()
        if self.path not in ('/api/uninstall', '/api/v1/uninstall'): return self.reply(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192: raise ValueError('Invalid request size')
            if self.headers.get_content_type() != 'application/json':
                return self.reply(415, {'error': 'Content-Type must be application/json'})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict): raise ValueError('Invalid request')
            if data.get('confirmation') != 'UNINSTALL': raise ValueError('Type UNINSTALL to confirm')
            target = host_platform()
            if target not in ('windows-desktop', 'windows-server', 'macos'):
                return self.reply(422, {'error': 'Removal is not configured for this platform. Identify the Linux product and vendor-supported method first.'})
            if data.get('target_platform') != target or data.get('hostname') != platform.node():
                return self.reply(409, {'error': 'Endpoint identity mismatch. Refresh status and confirm the local hostname and platform.'})
            if not elevated(): return self.reply(403, {'error': 'Restart Python as administrator/root'})
            with LOCK:
                if JOB['status'] == 'running' or ELEVATING: return self.reply(409, {'error': 'Removal or elevation already running'})
                ident = data.get('id')
                if not isinstance(ident, str) or ident not in [a['id'] for a in scan()]: raise ValueError('Agent no longer detected; rescan')
                args = command(ident, data.get('token', ''))
                JOB = {'status': 'running', 'message': 'Vendor uninstall is running. Keep this application open.'}
                start_removal(args, ident)
            self.reply(202, {'status': 'running', 'status_url': '/api/v1/status' if integration else '/api/status'})
        except (ValueError, TypeError): self.reply(400, {'error': 'Invalid request, token, or selection; rescan and confirm.'})
        except OSError: self.reply(500, {'error': 'Unable to access installation information'})

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-for-port', action='store_true', help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.wait_for_port and not elevated():
        raise SystemExit('Administrator relaunch was not elevated. Restart manually as administrator.')
    deadline = time.monotonic() + (30 if options.wait_for_port else 0)
    while True:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
            break
        except OSError as error:
            if error.errno not in (errno.EADDRINUSE, 10048) or time.monotonic() >= deadline:
                raise SystemExit('Unable to bind port 8765. Close the previous console and restart manually.') from error
            time.sleep(0.25)
    print('EPM Removal Console: http://127.0.0.1:8765 (Ctrl+C to stop)')
    print('Run on the endpoint to manage. Removal requires administrator/root privileges.')
    with server:
        try: server.serve_forever()
        except KeyboardInterrupt: pass

if __name__ == '__main__': main()
