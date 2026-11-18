import json
from html import unescape
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
import app
from catalog import PAGES, DISTROS, DOWNLOAD_URL

KEY = 'test-only-not-a-real-key-01234567890123456789'
AGENT = '{11111111-1111-1111-1111-111111111111}'

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def setUp(self):
        self.previous = app.JOB
        app.JOB = {'status':'idle'}
        self.key = patch('app.API_KEY', KEY); self.key.start(); self.addCleanup(self.key.stop)
        self.target = patch('app.host_platform', return_value='windows-desktop'); self.target.start(); self.addCleanup(self.target.stop)
        self.host = patch('app.platform.node', return_value='test-host'); self.host.start(); self.addCleanup(self.host.stop)
        self.scan = patch('app.scan', return_value=[{'id':AGENT,'name':'Test EPM','version':'1','location':''}]); self.scan.start(); self.addCleanup(self.scan.stop)
    def tearDown(self): app.JOB = self.previous
    def request(self,path,body=None,headers=None):
        h={'Host':'127.0.0.1:8765','Authorization':'Bearer '+KEY,'Content-Type':'application/json'}
        h.update(headers or {})
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with urlopen(req,timeout=5) as r: return r.status,r.read(),r.headers
        except HTTPError as e:
            with e: return e.code,e.read(),e.headers
    def body(self,**changes):
        b={'id':AGENT,'hostname':'test-host','target_platform':'windows-desktop','confirmation':'UNINSTALL'}
        b.update(changes);return b
    def test_all_pages(self):
        for route,page in PAGES.items():
            with self.subTest(route=route):
                code,body,headers=self.request(route)
                self.assertEqual(code,200)
                self.assertIn(page['title'],unescape(body.decode()))
                self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
    def test_distro_pages(self):
        self.assertEqual(len(DISTROS),9)
        for slug in DISTROS:self.assertIn('/linux/'+slug,PAGES)
    def test_api_status_has_no_browser_session(self):
        code,raw,_=self.request('/api/v1/status');body=json.loads(raw)
        self.assertEqual(code,200);self.assertNotIn('session',body);self.assertEqual(body['hostname'],'test-host')
    def test_api_missing_key(self):
        self.assertEqual(self.request('/api/v1/status',headers={'Authorization':''})[0],401)
    def test_api_wrong_key(self):
        self.assertEqual(self.request('/api/v1/status',headers={'Authorization':'Bearer incorrect'})[0],401)
    def test_api_disabled(self):
        with patch('app.API_KEY',''):self.assertEqual(self.request('/api/v1/status')[0],401)
    def test_api_rejects_browser_even_with_key(self):
        self.assertEqual(self.request('/api/v1/status',headers={'Origin':'http://127.0.0.1:8765'})[0],401)
        self.assertEqual(self.request('/api/v1/uninstall',self.body(),{'Origin':'http://127.0.0.1:8765'})[0],401)
    def test_openapi(self):
        code,raw,_=self.request('/openapi.json');schema=json.loads(raw)
        self.assertEqual(code,200)
        self.assertEqual(schema['openapi'],'3.1.0')
        self.assertTrue(schema['paths']['/api/v1/uninstall']['post']['x-openai-isConsequential'])
    def test_missing_confirmation(self):
        self.assertEqual(self.request('/api/v1/uninstall',self.body(confirmation=''))[0],400)
    def test_target_mismatch(self):
        self.assertEqual(self.request('/api/v1/uninstall',self.body(target_platform='windows-server'))[0],409)
    def test_host_mismatch(self):
        self.assertEqual(self.request('/api/v1/uninstall',self.body(hostname='other-host'))[0],409)
    def test_linux_removal_disabled(self):
        with patch('app.host_platform',return_value='linux'):
            self.assertEqual(self.request('/api/v1/uninstall',self.body(target_platform='linux'))[0],422)
    def test_requires_elevation(self):
        with patch('app.elevated',return_value=False):
            self.assertEqual(self.request('/api/v1/uninstall',self.body())[0],403)
    def test_stale_agent(self):
        with patch('app.elevated',return_value=True):
            self.assertEqual(self.request('/api/v1/uninstall',self.body(id='missing'))[0],400)
    def test_running_job_rejected(self):
        with patch('app.elevated',return_value=True):
            app.JOB={'status':'running'}
            self.assertEqual(self.request('/api/v1/uninstall',self.body())[0],409)
    def test_wrong_content_type(self):
        self.assertEqual(self.request('/api/v1/uninstall',self.body(),{'Content-Type':'text/plain'})[0],415)
    def test_removal_accepted_without_executing(self):
        with patch('app.elevated',return_value=True),patch('app.command',return_value=['dummy']),patch('app.start_removal') as start:
            code,raw,_=self.request('/api/v1/uninstall',self.body())
            self.assertEqual(code,202);self.assertEqual(json.loads(raw)['status_url'],'/api/v1/status');start.assert_called_once()
    def test_browser_session_removal(self):
        headers={'Origin':'http://127.0.0.1:8765','X-Session':app.SESSION}
        with patch('app.elevated',return_value=True),patch('app.command',return_value=['dummy']),patch('app.start_removal'):
            self.assertEqual(self.request('/api/uninstall',self.body(),headers)[0],202)
    def test_api_platform_catalog(self):
        code,raw,_=self.request('/api/v1/platforms')
        self.assertEqual(code,200);self.assertIn('/windows-server',json.loads(raw))
    def test_download_redirect(self):
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        req=Request(self.base+'/downloads/windows',headers={'Host':'127.0.0.1:8765'})
        try:build_opener(NoRedirect).open(req)
        except HTTPError as e:
            with e:self.assertEqual(e.code,302);self.assertEqual(e.headers['Location'],DOWNLOAD_URL)
        else:self.fail('Expected redirect')

class PlatformTests(unittest.TestCase):
    def test_windows_types(self):
        from types import SimpleNamespace
        with patch('app.platform.system',return_value='Windows'),patch('app.sys.getwindowsversion',create=True,return_value=SimpleNamespace(product_type=1)):
            self.assertEqual(app.host_platform(),'windows-desktop')
        for value in (2,3):
            with patch('app.platform.system',return_value='Windows'),patch('app.sys.getwindowsversion',create=True,return_value=SimpleNamespace(product_type=value)):
                self.assertEqual(app.host_platform(),'windows-server')
    def test_linux_distribution(self):
        with patch('app.platform.system',return_value='Linux'),patch('app.platform.freedesktop_os_release',return_value={'ID':'ubuntu','PRETTY_NAME':'Ubuntu 24.04','VERSION_ID':'24.04','ID_LIKE':'debian'}):
            self.assertEqual(app.distribution()['id'],'ubuntu')
    def test_linux_unknown(self):
        with patch('app.platform.system',return_value='Linux'),patch('app.platform.freedesktop_os_release',side_effect=OSError):
            self.assertEqual(app.distribution()['id'],'unknown')
if __name__=='__main__':unittest.main()
