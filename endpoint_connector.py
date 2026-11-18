"""Run on the visiting endpoint. Outbound-only portal connector; no arbitrary shell RPC."""
import argparse,contextlib,ctypes,io,json,os,secrets,shlex,subprocess,sys,tempfile,threading,time,webbrowser,zipfile
from pathlib import Path
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler,ProxyHandler
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit,quote
import app,installation
from endpoint_broker import ALLOWED

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
class Client:
    def __init__(self,config):
        self.config=config;self.instance=secrets.token_urlsafe(24)
        parsed=urlsplit(config['portal_url'])
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):raise ValueError('Invalid portal URL')
        self.base=config['portal_url'].rstrip('/');self.opener=build_opener(ProxyHandler({}),NoRedirect)
    def post(self,path,body=None,binary=False):
        if not path.startswith('/connector/'):raise ValueError('Invalid connector route')
        headers={'Content-Type':'application/json','X-Connector-ID':self.config.get('endpoint_id',''),'X-Connector-Instance':self.instance}
        if self.config.get('secret'):headers['Authorization']='Connector '+self.config['secret']
        request=Request(self.base+path,headers=headers,data=json.dumps(body or {}).encode())
        try:
            with self.opener.open(request,timeout=180 if binary else 40) as response:
                raw=response.read(100*1024*1024+1 if binary else 2*1024*1024)
                if binary and len(raw)>100*1024*1024:raise ValueError('Deployment kit too large')
                return raw if binary else json.loads(raw)
        except HTTPError as error:
            with error:
                try:message=json.load(error).get('error','Portal rejected request')
                except (ValueError,AttributeError):message='Portal rejected request'
            if error.code==401:raise PermissionError(message) from None
            raise ValueError(message) from None

def save_config(path,config):
    previous=path.stat() if path.exists() else None
    descriptor,filename=tempfile.mkstemp(prefix='epm-connector-',suffix='.private.tmp',dir=path.parent)
    temporary=Path(filename)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:json.dump(config,output)
        os.chmod(temporary,0o600)
        if previous and os.name!='nt' and os.geteuid()==0:os.chown(temporary,previous.st_uid,previous.st_gid)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)

class Engine:
    def __init__(self,client,config_path):
        self.client=client;self.config_path=config_path;self.relaunch=False;self.local_opener=build_opener(ProxyHandler({}),NoRedirect)
        self.catalog=[];self.cache=tempfile.TemporaryDirectory(prefix='epm-connector-')
        self.original_install=installation.install
        self.original_hooks={'discover':installation.discover,'install':installation.install,'api_key':app.API_KEY,'elevation':app.request_windows_elevation,'restart':app.restart_after_elevation,'info':app.elevation_info}
        installation.discover=lambda:self.catalog
        installation.install=self.install
        app.API_KEY=''
        app.request_windows_elevation=self.elevate
        app.restart_after_elevation=lambda server:setattr(self,'relaunch',True)
        app.elevation_info=self.elevation_info
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def refresh_catalog(self):
        records=self.client.post('/connector/catalog')['packages'];catalog=[]
        for rec in records:
            if rec.get('family') not in installation.CONFIGS:raise ValueError('Invalid package family')
            if not isinstance(rec.get('id'),str) or not rec['id'].isalnum():raise ValueError('Invalid package identifier')
            name=rec['filename']
            if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Invalid package filename')
            folder=Path(self.cache.name)/rec['id']
            catalog.append({**rec,'path':folder/name,'config':folder/installation.CONFIGS[rec['family']],'key':folder/installation.KEY_NAME})
        self.catalog=catalog
    @contextlib.contextmanager
    def kit(self,record,verification=False):
        raw=self.client.post('/connector/kit',{'package_id':record['id'],'purpose':'verification' if verification else 'install'},binary=True)
        with tempfile.TemporaryDirectory(prefix='epm-endpoint-kit-') as folder:
            root=Path(folder);os.chmod(root,0o700)
            required={record['filename']} if verification else {record['filename'],installation.CONFIGS[record['family']],installation.KEY_NAME}
            allowed=required|{'INSTALL-README.txt','GPG-KEY-CyberArk'}
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos=archive.infolist();names=[item.filename for item in infos]
                if len(names)!=len(set(names)) or not required.issubset(names) or any(name not in allowed for name in names) or sum(i.file_size for i in infos)>120*1024*1024:raise ValueError('Invalid deployment kit')
                for name in required:
                    target=root/name;target.write_bytes(archive.read(name));os.chmod(target,0o600)
            yield {**record,'path':root/record['filename'],'config':root/installation.CONFIGS[record['family']],'key':root/installation.KEY_NAME}
    def install(self,record,host,still_absent):
        with self.kit(record) as staged:return self.original_install(staged,host,still_absent)
    def elevation_info(self):
        arguments=[str(Path(__file__).resolve()),'--config',str(self.config_path),'--resume','--no-open-browser']
        if app.platform.system()=='Windows':
            ps=lambda text:"'"+text.replace("'","''")+"'"
            manual='Start-Process -Verb RunAs -FilePath '+ps(sys.executable)+' -ArgumentList '+ps(subprocess.list2cmdline(arguments))
        else:manual='sudo '+shlex.join([sys.executable]+arguments)
        return {'method':'windows-uac' if app.platform.system()=='Windows' else 'manual','can_request':app.platform.system()=='Windows','pending':app.ELEVATING,'manual_command':manual}
    def elevate(self):
        from ctypes import wintypes as W
        execute=ctypes.WinDLL('shell32',use_last_error=True).ShellExecuteW
        execute.argtypes=[W.HWND,W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,ctypes.c_int];execute.restype=ctypes.c_void_p
        arguments=subprocess.list2cmdline([str(Path(__file__).resolve()),'--config',str(self.config_path),'--resume','--uac-handoff','--no-open-browser'])
        code=execute(None,'runas',sys.executable,arguments,str(self.config_path.parent),1) or 0
        if code<=32:raise OSError('Endpoint UAC was cancelled or denied')
    def dispatch(self,command):
        method=command.get('method');path=command.get('path')
        if (method,path) not in ALLOWED:return {'status':400,'body':{'error':'Unsupported endpoint operation'}}
        try:
            if path in ('/api/packages','/api/install','/api/installation-health'):self.refresh_catalog()
            if path=='/api/installation-health' and app.platform.system()=='Windows':
                records=[r for r in self.catalog if installation.compatible(r,installation.host()) and r['family']=='windows']
                if len(records)!=1:raise ValueError('No unique Windows kit for verification')
                with self.kit(records[0],verification=True) as record:
                    verification=installation.windows_verification.evidence(installation.windows_verification.msi_identity(record['path']))
                return {'status':200,'body':{'hostname':app.platform.node(),'supported':True,'verification':verification}}
            headers={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765','Content-Type':'application/json','X-Session':app.SESSION}
            body=json.dumps(command.get('body') or {}).encode() if method=='POST' else None
            request=Request('http://127.0.0.1:'+str(self.server.server_port)+path,headers=headers,data=body,method=method)
            try:
                with self.local_opener.open(request,timeout=180) as response:status=response.status;data=json.load(response)
            except HTTPError as error:
                with error:status=error.code;data=json.load(error)
            if path=='/api/status' and status==200:
                data['session']='endpoint-relay'
                data['connector']={'endpoint_id':self.client.config['endpoint_id'],'portal_url':self.client.base}
                data['network']={'remote':False,'url':self.client.base}
            return {'status':status,'body':data}
        except (OSError,ValueError,KeyError,zipfile.BadZipFile,URLError):return {'status':409,'body':{'error':'The endpoint could not complete the request. Check its connector console and rescan before retrying.'}}
    def close(self):
        self.server.shutdown();self.server.server_close();self.cache.cleanup()
        installation.discover=self.original_hooks['discover'];installation.install=self.original_hooks['install'];app.API_KEY=self.original_hooks['api_key'];app.request_windows_elevation=self.original_hooks['elevation'];app.restart_after_elevation=self.original_hooks['restart'];app.elevation_info=self.original_hooks['info']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='connector.private.json')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--uac-handoff',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--no-open-browser',action='store_true')
    options=parser.parse_args();path=Path(options.config).resolve()
    config=json.loads(path.read_text(encoding='utf-8-sig'));client=Client(config)
    payload={'hostname':app.platform.node(),'host':installation.host(),'instance':client.instance,'uac_handoff':options.uac_handoff}
    if config.get('endpoint_id'):credentials=client.post('/connector/resume',payload)
    else:
        if options.resume:raise ValueError('Connector has not been enrolled')
        credentials=client.post('/connector/enroll',{**payload,'ticket':config.get('ticket')})
    config.update(credentials);config.pop('ticket',None);save_config(path,config)
    engine=Engine(client,path)
    print('Endpoint connector running on '+app.platform.node()+'. Keep this console open.')
    print('Portal: '+client.base+'. Installation/removal requires explicit confirmation.')
    if not options.no_open_browser:webbrowser.open(client.base+'/#endpoint='+quote(config['browser_key']))
    try:
        while True:
            try:
                command=client.post('/connector/poll',{'busy':app.JOB.get('status')=='running'})['command']
                if command:
                    result=engine.dispatch(command)
                    client.post('/connector/result',{'request_id':command['id'],'result':result,'busy':app.JOB.get('status')=='running'})
                    if engine.relaunch:break
            except PermissionError:
                print('Connector session replaced or portal restarted. Reconnect using a new connector kit if necessary.')
                while app.JOB.get('status')=='running':time.sleep(1)
                break
            except (ValueError,URLError,OSError):
                print('Portal connection interrupted. Commands are not retried automatically. Reconnecting…')
                time.sleep(3)
    except KeyboardInterrupt:
        while app.JOB.get('status')=='running':
            print('Waiting for the active endpoint operation to finish before closing…');time.sleep(2)
    finally:engine.close()
if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,PermissionError) as error:raise SystemExit('Connector setup failed. Confirm Python 3.11+, the portal URL and a fresh private connector kit. '+str(error))
