import json,threading,unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import app,lan_access

class LanAccessTests(unittest.TestCase):
    def test_cookie_validity_and_expiry(self):
        cookie=lan_access.session_cookie().split(';',1)[0]
        self.assertTrue(lan_access.authenticated(cookie))
        self.assertFalse(lan_access.authenticated(cookie+'tampered'))
        with patch('lan_access.time.time',return_value=99999999999):self.assertFalse(lan_access.authenticated(cookie))
    def test_restart_rotates_sessions(self):
        cookie=lan_access.session_cookie().split(';',1)[0]
        with patch('lan_access.ACCESS_CODE','changed'):self.assertFalse(lan_access.authenticated(cookie))
    def test_server_and_loopback_are_local(self):
        with patch('lan_access.ADDRESS','192.168.1.100'):
            self.assertTrue(lan_access.local_client('127.0.0.1'))
            self.assertTrue(lan_access.local_client('192.168.1.100'))
            self.assertFalse(lan_access.local_client('192.168.1.101'))

class LanHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        data={'hostname':'test-server','elevation':{'can_request':True,'manual_command':'private path'},'job':{'status':'idle'}}
        self.patches=[patch('lan_access.ADDRESS','192.168.1.100'),patch('lan_access.ACCESS_CODE','synthetic-lan-access-code-12345678'),patch.object(app.Handler,'local_client',return_value=False),patch('app.snapshot',return_value=data)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def request(self,path,body=None,authenticated=False,headers=None):
        h={'Host':'192.168.1.100:8765'}
        if body is not None:h.update({'Origin':'http://192.168.1.100:8765','Content-Type':'application/json','X-Session':app.SESSION})
        if authenticated:h['Cookie']=lan_access.session_cookie().split(';',1)[0]
        h.update(headers or {})
        req=Request(self.base+path,headers=h,data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req,timeout=5) as response:return response.status,response.read(),response.headers
        except HTTPError as error:
            with error:return error.code,error.read(),error.headers
    def test_remote_status_requires_login(self):self.assertEqual(self.request('/api/status')[0],401)
    def test_login_page_public(self):self.assertEqual(self.request('/login')[0],200)
    def test_wrong_code_rejected(self):self.assertEqual(self.request('/auth/login',{'code':'wrong'})[0],401)
    def test_login_rejects_cross_origin(self):self.assertEqual(self.request('/auth/login',{'code':lan_access.ACCESS_CODE},headers={'Origin':'https://example.com'})[0],403)
    def test_login_sets_signed_cookie(self):
        code,_,headers=self.request('/auth/login',{'code':lan_access.ACCESS_CODE})
        self.assertEqual(code,200);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
    def test_authenticated_remote_status_requires_visiting_pc_connector(self):
        code,raw,_=self.request('/api/status',authenticated=True);data=json.loads(raw)
        self.assertEqual(code,428);self.assertTrue(data['connector_required']);self.assertNotIn('hostname',data)
    def test_local_status_provides_pairing_code(self):
        with patch.object(app.Handler,'local_client',return_value=True):
            _,raw,_=self.request('/api/status',headers={'Host':'127.0.0.1:8765'});self.assertEqual(json.loads(raw)['network']['access_code'],lan_access.ACCESS_CODE)
    def test_unknown_host_rejected(self):self.assertEqual(self.request('/api/status',authenticated=True,headers={'Host':'evil.example:8765'})[0],403)
    def test_lan_host_rejected_when_disabled(self):
        with patch('lan_access.ADDRESS',''):self.assertEqual(self.request('/api/status',authenticated=True)[0],403)
    def test_remote_uac_cannot_be_triggered(self):
        with patch('app.request_windows_elevation') as launch:
            self.assertEqual(self.request('/api/elevate',{'confirmation':'REQUEST_ADMIN','hostname':'test-server'},authenticated=True)[0],403);launch.assert_not_called()
    def test_cookie_does_not_replace_csrf_session(self):self.assertEqual(self.request('/api/uninstall',{'confirmation':''},authenticated=True,headers={'X-Session':''})[0],403)
    def test_lan_browser_cannot_modify_host_without_connector(self):self.assertEqual(self.request('/api/uninstall',{'confirmation':''},authenticated=True)[0],428)
    def test_remote_post_without_cookie_denied(self):self.assertEqual(self.request('/api/uninstall',{'confirmation':''})[0],401)
    def test_api_bearer_stays_independent(self):
        with patch('app.API_KEY','synthetic-api-key-1234567890123456789'):
            self.assertEqual(self.request('/api/v1/status',headers={'Authorization':'Bearer synthetic-api-key-1234567890123456789'})[0],200)
if __name__=='__main__':unittest.main()
