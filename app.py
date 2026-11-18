"""Loopback-only EPM removal console. Python 3.11+, no dependencies."""
import ctypes
import json
import os
import platform
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAC = Path('/Applications/CyberArk EPM.app/Contents/Helpers/CyberArkEPMUninstall')
GUID = re.compile(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}')
LOCK = threading.Lock()
JOB = {'status': 'idle'}
SESSION = secrets.token_urlsafe(32)

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

    def do_GET(self):
        if not self.trusted(): return self.reply(403, {'error': 'Invalid host'})
        if self.path == '/api/status':
            try:
                with LOCK: job = dict(JOB)
                return self.reply(200, {'platform': platform.system(), 'hostname': platform.node(), 'elevated': elevated(), 'agents': scan(), 'job': job, 'session': SESSION})
            except OSError: return self.reply(500, {'error': 'Scan failed; check registry access.'})
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/style.css': ('style.css', 'text/css'), '/ui.js': ('ui.js', 'text/javascript')}
        if self.path not in assets: return self.reply(404, {'error': 'Not found'})
        name, kind = assets[self.path]
        self.reply(200, (Path(__file__).parent/'static'/name).read_bytes(), kind)

    def do_POST(self):
        global JOB
        if not self.trusted() or self.headers.get('Origin') != 'http://127.0.0.1:8765' or self.headers.get('X-Session') != SESSION:
            return self.reply(403, {'error': 'Invalid session or origin'})
        if self.path != '/api/uninstall': return self.reply(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192: raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict): raise ValueError('Invalid request')
            if data.get('confirmation') != 'UNINSTALL': raise ValueError('Type UNINSTALL to confirm')
            if not elevated(): return self.reply(403, {'error': 'Restart Python as administrator/root'})
            with LOCK:
                if JOB['status'] == 'running': return self.reply(409, {'error': 'Removal already running'})
                ident = data.get('id')
                if ident not in [a['id'] for a in scan()]: raise ValueError('Agent no longer detected; rescan')
                args = command(ident, data.get('token', ''))
                JOB = {'status': 'running', 'message': 'Vendor uninstall is running. Keep this application open.'}
                threading.Thread(target=run_job, args=(args, ident), daemon=True).start()
            self.reply(202, {'status': 'running'})
        except (ValueError, TypeError): self.reply(400, {'error': 'Invalid request, token, or selection; rescan and confirm.'})
        except OSError: self.reply(500, {'error': 'Unable to access installation information'})

if __name__ == '__main__':
    print('EPM Removal Console: http://127.0.0.1:8765 (Ctrl+C to stop)')
    print('Run on the endpoint to manage. Removal requires administrator/root privileges.')
    with ThreadingHTTPServer(('127.0.0.1', 8765), Handler) as server:
        try: server.serve_forever()
        except KeyboardInterrupt: pass
