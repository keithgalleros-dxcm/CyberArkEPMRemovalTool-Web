import io,json,threading,unittest,zipfile,time
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import app,lan_access,endpoint_portal
from endpoint_broker import Broker

class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker=Broker();ticket,self.browser=self.broker.ticket();self.agent=self.broker.enroll(ticket,'VM-CLIENT')
    def test_one_use_enrollment(self):
        ticket,_=self.broker.ticket();self.broker.enroll(ticket,'PC2')
        with self.assertRaises(ValueError):self.broker.enroll(ticket,'PC3')
    def test_expired_enrollment(self):
        ticket,_=self.broker.ticket();self.broker.tickets[ticket]['expires']=time.time()-1
        with self.assertRaises(ValueError):self.broker.enroll(ticket,'PC2')
    def test_offline_endpoint_never_falls_back(self):
        self.broker.endpoints[self.agent['endpoint_id']]['seen']-=60
        with self.assertRaises(ValueError):self.broker.submit(self.browser,'GET','/api/status',None)
    def test_unknown_browser_cannot_submit(self):
        with self.assertRaises(ValueError):self.broker.submit('other','GET','/api/status',None)
    def test_shell_and_arbitrary_paths_rejected(self):
        for method,path in [('POST','/run-shell'),('GET','/etc/passwd'),('GET','/api/status?path=anything')]:
            with self.assertRaises(ValueError):self.broker.submit(self.browser,method,path,{})
    def test_command_delivered_once(self):
        request=self.broker.submit(self.browser,'POST','/api/install',{'hostname':'VM-CLIENT','confirmation':'INSTALL'})
        command=self.broker.poll(self.agent['endpoint_id'],self.agent['secret'],timeout=0)
        self.assertEqual(command['id'],request)
        self.assertIsNone(self.broker.poll(self.agent['endpoint_id'],self.agent['secret'],timeout=0))
        self.assertIsNone(self.broker.requests[request]['command'])
    def test_result_isolated_by_browser_and_endpoint(self):
        request=self.broker.submit(self.browser,'GET','/api/status',None)
        self.broker.poll(self.agent['endpoint_id'],self.agent['secret'],timeout=0)
        ticket,other_browser=self.broker.ticket();other=self.broker.enroll(ticket,'PC2')
        with self.assertRaises(PermissionError):self.broker.result(other['endpoint_id'],other['secret'],request,{'status':200,'body':{}})
        self.broker.result(self.agent['endpoint_id'],self.agent['secret'],request,{'status':200,'body':{'hostname':'VM-CLIENT'}})
        self.assertEqual(self.broker.response(self.browser,request)['body']['hostname'],'VM-CLIENT')
        with self.assertRaises(PermissionError):self.broker.response(other_browser,request)
    def test_bad_connector_credential(self):
        with self.assertRaises(PermissionError):self.broker.poll(self.agent['endpoint_id'],'invalid',timeout=0)

class EndpointPortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        self.broker=Broker()
        self.patches=[patch('endpoint_portal.BROKER',self.broker),patch('lan_access.ADDRESS','192.168.1.101'),patch.object(app.Handler,'local_client',return_value=False)]
        for item in self.patches:item.start();self.addCleanup(item.stop)
    def request(self,path,body=None,headers=None,auth=True):
        h={'Host':'192.168.1.101:8765','Origin':'http://192.168.1.101:8765','Content-Type':'application/json','X-Portal-Session':app.SESSION}
        if auth:h['Cookie']=lan_access.session_cookie().split(';',1)[0]
        h.update(headers or {})
        req=Request(self.base+path,headers=h,data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req,timeout=5) as response:return response.status,response.read(),response.headers
        except HTTPError as error:
            with error:return error.code,error.read(),error.headers
    def test_unpaired_browser_cannot_scan_portal(self):
        with patch('app.snapshot',side_effect=AssertionError('portal host was scanned')),patch('app.install_preflight',side_effect=AssertionError('portal host was inspected')):
            for path in ['/api/status','/api/packages','/api/installation-health']:
                code,raw,_=self.request(path);self.assertEqual(code,428);self.assertTrue(json.loads(raw)['connector_required'])
    def test_portal_context_contains_no_endpoint_fingerprint(self):
        code,raw,_=self.request('/portal/context');body=json.loads(raw)
        self.assertEqual(code,200);self.assertFalse(body['direct_endpoint']);self.assertNotIn('hostname',body);self.assertNotIn('agents',body)
    def test_manual_catalog_has_no_host_match(self):
        _,raw,_=self.request('/portal/packages');body=json.loads(raw)
        self.assertFalse(body['can_install']);self.assertFalse(any(kit['matched'] for kit in body['packages']))
    def test_unpaired_post_cannot_install_portal(self):
        with patch('app.start_install') as install:
            code,_,_=self.request('/api/install',{'confirmation':'INSTALL'},headers={'X-Session':app.SESSION})
            self.assertEqual(code,428);install.assert_not_called()
    def test_connector_kit_has_no_vendor_credentials(self):
        code,raw,headers=self.request('/endpoint/bootstrap',{})
        self.assertEqual(code,200);self.assertTrue(headers['X-Endpoint-Browser-Key'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names=archive.namelist();self.assertIn('endpoint_connector.py',names);self.assertIn('connector.private.json',names)
            self.assertFalse(any(name.endswith(('.msi','.rpm','.deb','.pkg','.config')) for name in names))
            self.assertNotIn('agent installation key.txt',names)
    def test_endpoint_routes_require_portal_csrf(self):
        self.assertEqual(self.request('/endpoint/bootstrap',{},headers={'X-Portal-Session':''})[0],403)
    def test_endpoint_routes_require_lan_signin(self):
        self.assertEqual(self.request('/endpoint/bootstrap',{},auth=False)[0],401)
    def test_relay_returns_visiting_vm_identity_not_portal(self):
        ticket,browser=self.broker.ticket()
        code,raw,_=self.request('/connector/enroll',{'ticket':ticket,'hostname':'VM-CLIENT','host':{'system':'Windows','architecture':'x86_64'},'instance':'instance-1'},auth=False)
        self.assertEqual(code,200);agent=json.loads(raw)
        connector={'Authorization':'Connector '+agent['secret'],'X-Connector-ID':agent['endpoint_id'],'X-Connector-Instance':'instance-1'}
        with patch('app.scan',side_effect=AssertionError('Portal was scanned')),patch('app.snapshot',side_effect=AssertionError('Portal fingerprint leaked')):
            code,raw,_=self.request('/endpoint/rpc',{'method':'GET','path':'/api/status','body':None},headers={'X-Endpoint-Key':browser})
            self.assertEqual(code,202);request=json.loads(raw)['request_id']
            code,raw,_=self.request('/connector/poll',{},headers=connector,auth=False)
            command=json.loads(raw)['command'];self.assertEqual(command['path'],'/api/status')
            self.assertEqual(self.request('/connector/result',{'request_id':request,'result':{'status':200,'body':{'hostname':'VM-CLIENT','agents':[{'id':'vm-agent'}]}}},headers=connector,auth=False)[0],200)
            code,raw,_=self.request('/endpoint/result/'+request,headers={'X-Endpoint-Key':browser})
            body=json.loads(raw);self.assertEqual(body['result']['body']['hostname'],'VM-CLIENT');self.assertEqual(body['result']['body']['agents'][0]['id'],'vm-agent')
    def test_endpoint_api_requires_bearer(self):
        self.assertEqual(self.request('/api/v1/endpoint/info',headers={'Origin':''},auth=False)[0],401)
    def test_endpoint_api_requires_specific_endpoint_key(self):
        with patch('app.API_KEY','synthetic-api-key-for-endpoints-123456'):
            self.assertEqual(self.request('/api/v1/endpoint/rpc',{'method':'GET','path':'/api/status','body':None},headers={'Origin':'','Authorization':'Bearer synthetic-api-key-for-endpoints-123456'},auth=False)[0],409)
    def test_endpoint_api_dispatches_only_paired_device(self):
        ticket,browser=self.broker.ticket();agent=self.broker.enroll(ticket,'VM-CLIENT')
        with patch('app.API_KEY','synthetic-api-key-for-endpoints-123456'),patch('app.scan',side_effect=AssertionError('Portal scan forbidden')):
            code,raw,_=self.request('/api/v1/endpoint/rpc',{'method':'GET','path':'/api/status','body':None},headers={'Origin':'','Authorization':'Bearer synthetic-api-key-for-endpoints-123456','X-Endpoint-Key':browser},auth=False)
            self.assertEqual(code,202);request=json.loads(raw)['request_id'];self.assertEqual(self.broker.requests[request]['endpoint'],agent['endpoint_id'])
    def test_source_ip_not_used_as_endpoint_identity(self):
        with patch.object(app.Handler,'local_client',return_value=True):
            self.assertEqual(self.request('/api/status')[0],428)
if __name__=='__main__':unittest.main()
