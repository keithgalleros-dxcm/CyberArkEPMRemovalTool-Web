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
import lan_access
import ipaddress
import installation
import tempfile
import shutil
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
ACTIVE_SERVERS = []
SESSION = secrets.token_urlsafe(32)
API_KEY = os.environ.get('EPM_API_KEY', '')
if API_KEY and (len(API_KEY) < 32 or not API_KEY.isascii() or any(c.isspace() for c in API_KEY)):
    raise ValueError('EPM_API_KEY must contain at least 32 ASCII characters without whitespace')


def elevated():
    return bool(ctypes.windll.shell32.IsUserAnAdmin()) if platform.system() == 'Windows' else os.geteuid() == 0

def scan():
    if platform.system() == 'Darwin':
        return [{'id': 'mac-epm', 'name': 'CyberArk EPM', 'version': 'See installed application', 'location': str(MAC)}] if MAC.is_file() else []
    if platform.system() == 'Linux': return installation.existing_linux()
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
                        if 'endpoint privilege manager agent' not in display.lower() and not ('epm agent' in display.lower() and any(brand in value('Publisher').lower() for brand in ('cyberark','idira'))): continue
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
    result['operation'] = 'uninstall'
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
        arguments = subprocess.list2cmdline([str(Path(__file__).resolve())]+(['--lan-address',lan_access.ADDRESS] if lan_access.ADDRESS else []))
        manual = 'Start-Process -Verb RunAs -FilePath ' + ps(sys.executable) + ' -ArgumentList ' + ps(arguments)
    elif system in ('Darwin','Linux'):
        manual = 'sudo ' + shlex.join([sys.executable, str(Path(__file__).resolve())]+(['--lan-address',lan_access.ADDRESS] if lan_access.ADDRESS else []))
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
    parameters = subprocess.list2cmdline([str(Path(__file__).resolve()), '--wait-for-port'] + (['--lan-address',lan_access.ADDRESS] if lan_access.ADDRESS else []))
    code = execute(None, 'runas', sys.executable, parameters, str(Path(__file__).resolve().parent), 1) or 0
    if code <= 32:
        raise OSError('Administrator request was cancelled, denied, or could not start.')

def restart_after_elevation(server):
    def stop_original():
        time.sleep(0.4)
        for active in (ACTIVE_SERVERS or [server]):active.shutdown()
    threading.Thread(target=stop_original, daemon=True).start()

def snapshot(browser=False):
    with LOCK: job = dict(JOB)
    result = {'platform': platform.system(), 'target_platform': host_platform(), 'hostname': platform.node(), 'distribution': distribution(), 'elevated': elevated(), 'agents': scan(), 'job': job, 'removal_supported': host_platform() in ('windows-desktop', 'windows-server', 'macos'), 'api_enabled': bool(API_KEY), 'elevation': elevation_info()}
    if browser: result['session'] = SESSION
    return result

def start_removal(args, agent_id):
    threading.Thread(target=run_job, args=(args, agent_id), daemon=True).start()


def install_preflight():
    endpoint=installation.host()
    packages=installation.catalog(endpoint)
    found=installation.existing(scan)
    with LOCK: job=dict(JOB)
    restart=installation.pending_restart() or (job.get('operation')=='uninstall' and job.get('restart_required',False))
    blockers=[]
    if found:blockers.append('An existing EPM agent or installation files were detected. Remove the agent first.')
    if restart:blockers.append('A restart is required. Restart the endpoint before installing.')
    if job.get('status')=='running' or ELEVATING:blockers.append('Another operation is in progress.')
    matched=[p for p in packages if p['matched']]
    if len(matched)!=1:blockers.append('No unique compatible installer is available for this OS version and architecture.')
    return {'hostname':platform.node(),'host':endpoint,'packages':packages,'existing_agents':found,'blockers':blockers,'recommended_id':matched[0]['id'] if len(matched)==1 else None,'can_install':not blockers,'elevated':elevated(),'job':job}

def run_install_job(record, endpoint):
    global JOB
    hostname=platform.node()
    try:
        result=installation.install(record,endpoint,lambda:not installation.existing(scan) and not installation.pending_restart())
        accepted=result.pop('accepted')
        if record['family']=='windows':
            verification=result.get('windows_verification',{})
            present=bool(verification.get('registered'))
            healthy=bool(verification.get('runtime_verified'))
            status='completed' if accepted and healthy else 'attention_required' if accepted else 'failed'
            message=('Expected MSI product, version, agent executable and running vf_agent service verified on '+hostname+'. Confirm enrollment separately in the EPM console.' if status=='completed' else 'Installation is NOT fully verified on '+hostname+'. Check MSI product, agent file and service evidence below. Complete any required restart; do not retry blindly.')
        else:
            present=bool(scan())
            status='completed' if accepted and present else 'failed'
            message='Agent installation and activation verified on '+hostname+'. Confirm EPM console enrollment.' if status=='completed' else 'Installation or activation was not verified on '+hostname+'. Review vendor guidance and rescan.'
        result.update(status=status,operation='install',hostname=hostname,platform=endpoint.get('system'),registration_present=present,message=message)
    except Exception:
        result={'status':'failed','operation':'install','hostname':hostname,'platform':endpoint.get('system'),'message':'Installation or verification could not complete on '+hostname+'. Check prerequisites and deployment files. An incomplete installation may need support.'}
    with LOCK:JOB=result

def start_install(record,endpoint):
    threading.Thread(target=run_install_job,args=(record,endpoint),daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def reply(self, status, data, kind='application/json', extra_headers=None):
        raw = json.dumps(data).encode() if kind == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        for name,value in (extra_headers or {}).items():self.send_header(name,value)
        self.end_headers()
        self.wfile.write(raw)

    def trusted(self):
        allowed={'127.0.0.1:8765'}
        if lan_access.ADDRESS:allowed.add(lan_access.ADDRESS+':8765')
        return self.headers.get('Host') in allowed

    def local_client(self):
        return lan_access.local_client(self.client_address[0])

    def origin_allowed(self):
        return self.headers.get('Origin')=='http://'+self.headers.get('Host','')

    def browser_authorized(self):
        return self.local_client() or lan_access.authenticated(self.headers.get('Cookie'))

    def browser_snapshot(self):
        data=snapshot(browser=True)
        data['network']={'url':'http://'+lan_access.ADDRESS+':8765' if lan_access.ADDRESS else '', 'remote':not self.local_client()}
        if self.local_client() and lan_access.ADDRESS:data['network']['access_code']=lan_access.ACCESS_CODE
        if not self.local_client():
            data['elevation']['can_request']=False
            data['elevation']['manual_command']='Request administrator approval locally on '+data['hostname']
        return data

    def api_authorized(self):
        # Browser sessions never confer integration access; integrations cannot use CORS.
        value = self.headers.get('Authorization', '')
        return bool(API_KEY) and not self.headers.get('Origin') and secrets.compare_digest(value.encode('utf-8'), ('Bearer ' + API_KEY).encode('utf-8'))

    def do_GET(self):
        if not self.trusted(): return self.reply(403, {'error': 'Invalid host'})
        public_assets={'/login','/lan-login.js','/style.css','/brand/dexcom-logo.png','/brand/Gilroy-Medium.woff2','/brand/Gilroy-Bold.woff2'}
        if not self.path.startswith('/api/v1/') and not self.browser_authorized() and self.path not in public_assets:
            if self.path.startswith('/api/'):return self.reply(401,{'error':'LAN sign-in required','login_url':'/login'})
            return self.reply(302,b'', 'text/plain',{'Location':'/login'})
        if self.path=='/login':return self.reply(200,(Path(__file__).parent/'static'/'lan-login.html').read_bytes(),'text/html; charset=utf-8')
        if self.path.startswith('/api/v1/'):
            if not self.api_authorized(): return self.reply(401, {'error': 'Configure EPM_API_KEY and supply a valid Bearer token; browser origins are not accepted.'})
            if self.path == '/api/v1/packages':
                try:return self.reply(200, install_preflight())
                except (OSError, subprocess.SubprocessError):return self.reply(500, {'error':'Unable to safely inspect package compatibility or existing agents.'})
            if self.path == '/api/v1/platforms': return self.reply(200, PAGES)
            if self.path != '/api/v1/status': return self.reply(404, {'error': 'Not found'})
            try: return self.reply(200, snapshot())
            except (OSError, subprocess.SubprocessError): return self.reply(500, {'error': 'Endpoint scan failed'})
        if self.path == '/api/installation-health':
            if platform.system()!='Windows':return self.reply(200,{'hostname':platform.node(),'supported':False,'message':'This verification action currently targets Windows agents.'})
            try:
                records=[record for record in installation.discover() if record['family']=='windows' and record['ready']]
                if len(records)!=1:return self.reply(409,{'error':'A unique complete Windows kit is required to verify the expected product.'})
                identity=installation.windows_verification.msi_identity(records[0]['path'])
                evidence=installation.windows_verification.evidence(identity)
                return self.reply(200,{'hostname':platform.node(),'supported':True,'verification':evidence,'message':'Expected agent runtime verified on this host.' if evidence['runtime_verified'] else 'Agent runtime is not fully verified on this host. Compare this hostname with the VM computer name.'})
            except (OSError,ValueError):return self.reply(500,{'error':'Unable to inspect the expected Windows agent safely.'})
        if self.path == '/api/packages':
            try:return self.reply(200, install_preflight())
            except (OSError, subprocess.SubprocessError):return self.reply(500, {'error':'Unable to safely inspect package compatibility or existing agents.'})
        if self.path == '/api/status':
            try: return self.reply(200, self.browser_snapshot())
            except (OSError, subprocess.SubprocessError): return self.reply(500, {'error': 'Endpoint scan failed'})
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
                '/lan-login.js': ('lan-login.js', 'text/javascript'),
                '/install-ui.js': ('install-ui.js', 'text/javascript'),
                '/brand/dexcom-logo.png': ('brand/dexcom-logo.png', 'image/png'),
                '/brand/Gilroy-Medium.woff2': ('brand/Gilroy-Medium.woff2', 'font/woff2'),
                '/brand/Gilroy-Bold.woff2': ('brand/Gilroy-Bold.woff2', 'font/woff2'),
            }
            if self.path not in assets: return self.reply(404, {'error': 'Not found'})
            name, kind = assets[self.path]
        self.reply(200, (Path(__file__).parent/'static'/name).read_bytes(), kind)

    def handle_elevation(self):
        global ELEVATING
        if not self.local_client():return self.reply(403,{'error':'UAC must be requested and approved locally on the server endpoint.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2048: raise ValueError()
            if self.headers.get_content_type() != 'application/json': raise ValueError()
            data = json.loads(self.request_body)
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


    def install_or_download(self, download=False):
        global JOB
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=2048 or self.headers.get_content_type()!='application/json':raise ValueError()
            data=json.loads(self.request_body)
            if not isinstance(data,dict) or data.get('confirmation')!=('DOWNLOAD_KIT' if download else 'INSTALL'):raise ValueError()
            record=installation.get_record(data.get('package_id'))
            if download:
                # Private kits are browser-session-only POST downloads, never public URLs.
                with tempfile.TemporaryFile() as output:
                    installation.bundle(record,output)
                    output.seek(0,2);length=output.tell();output.seek(0)
                    self.send_response(200)
                    self.send_header('Content-Type','application/zip')
                    self.send_header('Content-Length',str(length))
                    self.send_header('Content-Disposition','attachment; filename="epm-'+record['id']+'-private-kit.zip"')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers();shutil.copyfileobj(output,self.wfile)
                return
            if data.get('hostname')!=platform.node() or data.get('target_platform')!=host_platform():
                return self.reply(409,{'error':'Endpoint identity mismatch; refresh the workspace.'})
            if not elevated():return self.reply(403,{'error':'Administrator/root privileges required. Use Request administrator access or the platform launch instructions.'})
            # Serialize installation/removal preflight and reserve the operation atomically.
            endpoint=installation.host()
            if not installation.compatible(record,endpoint):return self.reply(409,{'error':'Selected installer is incompatible with this endpoint.'})
            with LOCK:
                if JOB['status']=='running' or ELEVATING:return self.reply(409,{'error':'Another operation is in progress.'})
                if installation.existing(scan):return self.reply(409,{'error':'Existing agent detected; installation is blocked.'})
                if installation.pending_restart() or (JOB.get('operation')=='uninstall' and JOB.get('restart_required')):
                    return self.reply(409,{'error':'Restart this endpoint before installing.'})
                JOB={'status':'running','operation':'install','hostname':platform.node(),'platform':endpoint['system'],'message':'Installing the matched agent and applying its paired configuration. Keep the console running.'}
                start_install(record,endpoint)
            return self.reply(202,{'status':'running','status_url':'/api/v1/status' if self.path.startswith('/api/v1/') else '/api/status'})
        except (ValueError,TypeError):return self.reply(400,{'error':'Invalid request or incomplete deployment kit.'})
        except (OSError,subprocess.SubprocessError):return self.reply(500,{'error':'Cannot safely access the kit or inspect this endpoint.'})

    def do_POST(self):
        global JOB
        # Consume bounded request bodies before early rejection. Closing a socket with
        # unread POST bytes can reset the connection and discard the error on Windows.
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192:return self.reply(400,{'error':'Invalid request size'})
            self.connection.settimeout(15)
            self.request_body=self.rfile.read(size)
            if len(self.request_body)!=size:return self.reply(400,{'error':'Incomplete request'})
        except (ValueError,OSError):return self.reply(400,{'error':'Unable to read request'})
        if not self.trusted(): return self.reply(403, {'error': 'Invalid host'})
        if self.path=='/auth/login':
            if not self.origin_allowed():return self.reply(403,{'error':'Invalid origin'})
            try:data=json.loads(self.request_body)
            except (ValueError,TypeError):return self.reply(400,{'error':'Invalid sign-in request'})
            if not isinstance(data,dict) or not lan_access.valid_code(data.get('code')):return self.reply(401,{'error':'Invalid LAN access code'})
            return self.reply(200,{'status':'signed_in'},extra_headers={'Set-Cookie':lan_access.session_cookie()})
        integration = self.path.startswith('/api/v1/')
        if not integration and not self.browser_authorized():return self.reply(401,{'error':'LAN sign-in required','login_url':'/login'})
        if integration:
            if not self.api_authorized(): return self.reply(401, {'error': 'Invalid API credentials or browser origin'})
        elif not self.origin_allowed() or self.headers.get('X-Session') != SESSION:
            return self.reply(403, {'error': 'Invalid session or origin'})
        if self.path in ('/api/install','/api/v1/install'):return self.install_or_download()
        if self.path == '/api/packages/download':return self.install_or_download(download=True)
        if self.path == '/api/elevate': return self.handle_elevation()
        if self.path not in ('/api/uninstall', '/api/v1/uninstall'): return self.reply(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192: raise ValueError('Invalid request size')
            if self.headers.get_content_type() != 'application/json':
                return self.reply(415, {'error': 'Content-Type must be application/json'})
            data = json.loads(self.request_body)
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
                JOB = {'status': 'running', 'operation': 'uninstall', 'message': 'Vendor uninstall is running. Keep this application open.'}
                start_removal(args, ident)
            self.reply(202, {'status': 'running', 'status_url': '/api/v1/status' if integration else '/api/status'})
        except (ValueError, TypeError): self.reply(400, {'error': 'Invalid request, token, or selection; rescan and confirm.'})
        except OSError: self.reply(500, {'error': 'Unable to access installation information'})

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-for-port', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--lan-address', help='Optional private IPv4 address to listen on alongside loopback')
    options = parser.parse_args()
    if options.lan_address:
        address=ipaddress.ip_address(options.lan_address)
        if address.version!=4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            parser.error('--lan-address must be a specific private IPv4 address assigned to this endpoint')
        lan_access.ADDRESS=str(address)
    if options.wait_for_port and not elevated():raise SystemExit('Administrator relaunch was not elevated. Restart manually as administrator.')
    deadline=time.monotonic()+(30 if options.wait_for_port else 0)
    while True:
        servers=[]
        try:
            for address in ['127.0.0.1']+([lan_access.ADDRESS] if lan_access.ADDRESS else []):
                servers.append(ThreadingHTTPServer((address,8765),Handler))
            break
        except OSError as error:
            for server in servers:server.server_close()
            if error.errno not in (errno.EADDRINUSE,10048) or time.monotonic()>=deadline:
                raise SystemExit('Unable to bind the configured address/port. Check the local IP and close the previous console.') from error
            time.sleep(0.25)
    ACTIVE_SERVERS[:]=servers
    print('EPM Console: http://127.0.0.1:8765 (Ctrl+C to stop)')
    if lan_access.ADDRESS:print('LAN URL: http://'+lan_access.ADDRESS+':8765 — obtain the sign-in code from the loopback UI.')
    for server in servers[1:]:threading.Thread(target=server.serve_forever,daemon=True).start()
    try:servers[0].serve_forever()
    except KeyboardInterrupt:pass
    finally:
        for server in servers[1:]:server.shutdown()
        for server in servers:server.server_close()
        ACTIVE_SERVERS.clear()

if __name__=='__main__':main()
