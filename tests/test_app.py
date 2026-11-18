import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import app

class AdapterTests(unittest.TestCase):
    def test_windows_command(self):
        with patch('app.platform.system', return_value='Windows'), patch.dict('os.environ', {'SystemRoot': r'C:\Windows'}):
            args=app.command('{11111111-1111-1111-1111-111111111111}', 'secret')
            self.assertIn('FULL_UNINSTALL=YES', args)
            self.assertIn('/norestart', args)
            self.assertIn('SECURE_TOKEN=secret', args)
            with self.assertRaises(ValueError): app.command('arbitrary', '')
    def test_mac_command(self):
        with patch('app.platform.system', return_value='Darwin'):
            self.assertEqual(app.command('mac-epm', 'abc'), [str(app.MAC), '-full', '-token', 'abc'])
    def test_invalid_tokens(self):
        for token in ['a\nb', 'a"b', '\x00', None]:
            with self.assertRaises(ValueError): app.command('mac-epm', token)
    def test_failed_verification(self):
        with patch('app.subprocess.Popen') as proc, patch('app.scan', return_value=[{'id':'selected'}]):
            proc.return_value.wait.return_value=0
            app.run_job(['dummy'], 'selected')
            self.assertEqual(app.JOB['status'], 'failed')
    def test_restart_result(self):
        with patch('app.subprocess.Popen') as proc, patch('app.scan', return_value=[]):
            proc.return_value.wait.return_value=3010
            app.run_job(['dummy'], 'selected')
            self.assertTrue(app.JOB['restart_required'])
            self.assertEqual(app.JOB['status'], 'completed')

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def test_host_rejected(self):
        with self.assertRaises(HTTPError) as e: urlopen(self.url)
        self.assertEqual(e.exception.code,403)
    def test_origin_rejected(self):
        req=Request(self.url+'/api/uninstall',data=b'{}',headers={'Host':'127.0.0.1:8765'})
        with self.assertRaises(HTTPError) as e: urlopen(req)
        self.assertEqual(e.exception.code,403)
    def test_assets(self):
        for path in ['/', '/ui.js', '/style.css']:
            with urlopen(Request(self.url+path,headers={'Host':'127.0.0.1:8765'})) as r:
                self.assertEqual(r.status,200)
                self.assertEqual(r.headers['Cache-Control'],'no-store')
    def test_status(self):
        with patch('app.scan',return_value=[]),patch('app.elevated',return_value=False):
            with urlopen(Request(self.url+'/api/status',headers={'Host':'127.0.0.1:8765'})) as r:
                self.assertEqual(json.load(r)['agents'],[])
if __name__ == '__main__': unittest.main()
