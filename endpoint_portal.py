"""Portal-side endpoints and private connector enrollment/downloads."""
import io,json,tempfile,zipfile
from pathlib import Path
import installation,lan_access,connector_installer
from endpoint_broker import BROKER
MANAGED={'/api/status','/api/packages','/api/installation-health','/api/install','/api/uninstall','/api/elevate'}
def direct(handler):
    import ipaddress
    return ipaddress.ip_address(handler.client_address[0]).is_loopback and handler.headers.get('Host')=='127.0.0.1:8765'
def data(handler):
    result=json.loads(handler.request_body)
    if not isinstance(result,dict):raise ValueError('Invalid request')
    return result
def browser_key(handler):
    return handler.headers.get('X-Endpoint-Key','')
def get(handler,api=False):
    path=handler.path.replace("/api/v1/endpoint/","/endpoint/",1) if api else handler.path
    try:
        if path=='/portal/context':
            handler.reply(200,{'direct_endpoint':direct(handler),'session':handler.portal_session(),'portal_url':'http://'+handler.headers['Host']});return True
        if path=='/portal/packages':
            host={'system':'Not connected','architecture':'unknown','version':'','distro_id':'','distro_version':''}
            handler.reply(200,{'host':host,'packages':installation.catalog(host),'existing_agents':[],'blockers':['Connect this PC to detect its installed agent.'],'can_install':False,'elevated':False,'job':{'status':'idle'}});return True
        if path=='/endpoint/info':
            handler.reply(200,BROKER.info(browser_key(handler)));return True
        if path.startswith('/endpoint/result/'):
            result=BROKER.response(browser_key(handler),path.rsplit('/',1)[1])
            handler.reply(200,{'done':result is not None,'result':result});return True
    except PermissionError as error:handler.reply(403,{'error':str(error)});return True
    return False
def bootstrap(handler):
    if not lan_access.ADDRESS:raise ValueError('Enable a LAN address on the portal before creating endpoint connector kits')
    platform=data(handler).get('platform','archive')
    if platform not in ('windows','macos','linux','archive'):raise ValueError('Unsupported connector installer platform')
    ticket,key=BROKER.ticket()
    config={'portal_url':'http://'+lan_access.ADDRESS+':8765','ticket':ticket,'browser_key':key}
    root=Path(__file__).resolve().parent
    names=['app.py','catalog.py','installation.py','lan_access.py','windows_verification.py','endpoint_broker.py','endpoint_portal.py','endpoint_connector.py','connector_installer.py']
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in names:archive.write(root/name,name)
        archive.writestr('connector.private.json',json.dumps(config))
    if platform=='archive':
        content,filename,kind=output.getvalue(),'endpoint-connector.zip','application/zip'
    else:
        content,filename,kind=connector_installer.render(output.getvalue(),platform)
    handler.reply(200,content,kind,{'Content-Disposition':'attachment; filename="'+filename+'"','X-Endpoint-Browser-Key':key})

def post(handler,api=False):
    path=handler.path.replace("/api/v1/endpoint/","/endpoint/",1) if api else handler.path
    try:
        if not api and path=='/endpoint/bootstrap':
            bootstrap(handler);return True
        if path=='/endpoint/rpc':
            payload=data(handler);method=payload.get('method');path=payload.get('path');body=payload.get('body')
            if body is not None and not isinstance(body,dict):raise ValueError('Invalid operation body')
            request=BROKER.submit(browser_key(handler),method,path,body)
            handler.reply(202,{'request_id':request});return True
    except (ValueError,TypeError,OSError) as error:handler.reply(409,{'error':'Unable to prepare connector enrollment or dispatch. Check connection and portal files.' if isinstance(error,OSError) else str(error)});return True
    return False
def connector(handler):
    if not handler.path.startswith('/connector/'):return False
    try:
        payload=data(handler)
        if handler.path=='/connector/enroll':
            result=BROKER.enroll(payload.get('ticket'),payload.get('hostname'))
            with BROKER.condition:BROKER.endpoints[result['endpoint_id']].update(host=payload.get('host',{}),instance=payload.get('instance'),busy=False)
            handler.reply(200,result);return True
        identity=handler.headers.get('X-Connector-ID','')
        authorization=handler.headers.get('Authorization','')
        secret=authorization[len('Connector '):] if authorization.startswith('Connector ') else ''
        with BROKER.condition:record=BROKER.endpoint(identity,secret)
        if handler.path=='/connector/resume':
            if payload.get('hostname')!=record['hostname']:raise PermissionError('Connector hostname changed; enroll again')
            if record.get('busy') and not payload.get('uac_handoff'):raise ValueError('An endpoint operation is active; wait for it to finish before replacing its connector')
            with BROKER.condition:
                import time
                record['seen']=time.time();record['host']=payload.get('host',record.get('host',{}));record['instance']=payload.get('instance')
            handler.reply(200,{'endpoint_id':identity,'secret':secret,'browser_key':record['browser']})
        elif handler.path=='/connector/poll':
            if handler.headers.get('X-Connector-Instance')!=record.get('instance'):raise PermissionError('A newer connector instance replaced this one')
            with BROKER.condition:record['busy']=bool(payload.get('busy'))
            handler.reply(200,{'command':BROKER.poll(identity,secret)})
        elif handler.path=='/connector/result':
            BROKER.result(identity,secret,payload.get('request_id'),payload.get('result'))
            with BROKER.condition:record['busy']=bool(payload.get('busy'))
            handler.reply(200,{'status':'received'})
        elif handler.path=='/connector/catalog':
            items=[]
            for kit in installation.discover():
                items.append({k:kit[k] for k in ('id','title','filename','family','bytes','ready','rules')})
            handler.reply(200,{'packages':items})
        elif handler.path=='/connector/kit':
            kit=installation.get_record(payload.get('package_id'))
            if not installation.compatible(kit,record.get('host',{})):raise ValueError('Kit does not match this endpoint')
            with tempfile.TemporaryFile() as output:
                if payload.get('purpose')=='verification':
                    with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as archive:archive.write(kit['path'],kit['filename'])
                else:installation.bundle(kit,output)
                output.seek(0,2);length=output.tell();output.seek(0)
                handler.send_response(200);handler.send_header('Content-Type','application/zip');handler.send_header('Content-Length',str(length));handler.send_header('Cache-Control','no-store');handler.end_headers()
                import shutil
                shutil.copyfileobj(output,handler.wfile)
        else:handler.reply(404,{'error':'Connector route not found'})
    except PermissionError as error:handler.reply(401,{'error':str(error)})
    except (ValueError,TypeError,KeyError,OSError) as error:handler.reply(400,{'error':'Invalid connector request or unavailable compatible kit'})
    return True
