"""In-memory endpoint relay. Enrollment is operator-authorized; commands are allowlisted."""
import secrets,time,threading
ALLOWED={('GET','/api/status'),('GET','/api/packages'),('GET','/api/installation-health'),('POST','/api/install'),('POST','/api/uninstall'),('POST','/api/elevate')}
class Broker:
    def __init__(self):
        self.condition=threading.Condition();self.tickets={};self.endpoints={};self.browsers={};self.requests={}
    def ticket(self):
        with self.condition:
            self.cleanup()
            if len(self.tickets)>=128:raise ValueError('Too many pending connector setups')
            ticket=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32)
            self.tickets[ticket]={'expires':time.time()+600,'browser':browser}
            return ticket,browser
    def cleanup(self):
        now=time.time()
        for key in list(self.tickets):
            if self.tickets[key]['expires']<now:del self.tickets[key]
        for key in list(self.requests):
            if now-self.requests[key]['created']>300:del self.requests[key]
    def enroll(self,ticket,hostname):
        if not isinstance(hostname,str) or not hostname or len(hostname)>255:raise ValueError('Invalid endpoint hostname')
        with self.condition:
            self.cleanup();pending=self.tickets.pop(ticket,None)
            if not pending:raise ValueError('Enrollment expired or already used; download a new connector kit')
            identity=secrets.token_urlsafe(24);secret=secrets.token_urlsafe(32)
            self.endpoints[identity]={'secret':secret,'hostname':hostname,'browser':pending['browser'],'seen':time.time(),'queue':[]}
            self.browsers[pending['browser']]=identity
            return {'endpoint_id':identity,'secret':secret,'browser_key':pending['browser']}
    def endpoint(self,identity,secret):
        rec=self.endpoints.get(identity)
        if not rec or not isinstance(secret,str) or not secrets.compare_digest(rec['secret'].encode(),secret.encode()):raise PermissionError('Connector credentials invalid; enroll again after portal restart')
        return rec
    def info(self,browser):
        with self.condition:
            identity=self.browsers.get(browser);rec=self.endpoints.get(identity)
            if not rec:return {'connected':False,'message':'Run the connector on this PC to connect it.'}
            online=time.time()-rec['seen']<45
            return {'connected':online,'hostname':rec['hostname'],'message':'Endpoint connected' if online else 'Endpoint connector is offline; start it on that PC.'}
    def submit(self,browser,method,path,body):
        if (method,path) not in ALLOWED:raise ValueError('Endpoint operation is not supported')
        with self.condition:
            self.cleanup()
            identity=self.browsers.get(browser);rec=self.endpoints.get(identity)
            if not rec or time.time()-rec['seen']>=45:raise ValueError('This PC connector is not connected; no server fallback is allowed')
            request=secrets.token_urlsafe(24)
            self.requests[request]={'browser':browser,'endpoint':identity,'created':time.time(),'delivered':False,'result':None,'command':{'id':request,'method':method,'path':path,'body':body}}
            rec['queue'].append(request);self.condition.notify_all()
            return request
    def poll(self,identity,secret,timeout=15):
        with self.condition:
            rec=self.endpoint(identity,secret);rec['seen']=time.time();deadline=time.monotonic()+timeout
            while True:
                while rec['queue']:
                    key=rec['queue'].pop(0);request=self.requests.get(key)
                    if request and time.time()-request['created']<120 and not request['delivered']:
                        request['delivered']=True;command=request['command'];request['command']=None
                        return command
                left=deadline-time.monotonic()
                if left<=0:return None
                self.condition.wait(left)
    def result(self,identity,secret,request_id,result):
        with self.condition:
            rec=self.endpoint(identity,secret);rec['seen']=time.time();request=self.requests.get(request_id)
            if not request or request['endpoint']!=identity or not request['delivered']:raise PermissionError('Invalid endpoint response')
            if not isinstance(result,dict) or not isinstance(result.get('status'),int) or not 100<=result['status']<=599:raise ValueError('Invalid response')
            request['result']=result;self.condition.notify_all()
    def response(self,browser,request_id):
        with self.condition:
            self.cleanup();request=self.requests.get(request_id)
            if not request or not secrets.compare_digest(request['browser'].encode(),str(browser).encode()):raise PermissionError('Response does not belong to this browser')
            return request['result']
BROKER=Broker()
