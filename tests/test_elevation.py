import json
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import app

class ElevationHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        self.patches=[patch('app.platform.system',return_value='Windows'),patch('app.platform.node',return_value='endpoint'),patch('app.elevated',return_value=False),patch('app.API_KEY',''),patch('app.ELEVATING',False),patch('app.JOB',{'status':'idle'}),patch('app.request_windows_elevation'),patch('app.restart_after_elevation')]
        self.mocks=[p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)
        self.launch=self.mocks[-2];self.restart=self.mocks[-1]
    def request(self,body=None,headers=None,path='/api/elevate'):
        h={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765','X-Session':app.SESSION,'Content-Type':'application/json'}
        h.update(headers or {})
        data={'hostname':'endpoint','confirmation':'REQUEST_ADMIN'} if body is None else body
        req=Request(self.base+path,headers=h,data=json.dumps(data).encode())
        try:
            with urlopen(req,timeout=5) as response:return response.status,json.load(response)
        except HTTPError as e:
            with e:return e.code,json.load(e)
    def test_missing_session_denied(self):
        self.assertEqual(self.request(headers={'X-Session':''})[0],403);self.launch.assert_not_called()
    def test_wrong_origin_denied(self):
        self.assertEqual(self.request(headers={'Origin':'https://example.com'})[0],403);self.launch.assert_not_called()
    def test_bad_confirmation(self):
        self.assertEqual(self.request({'hostname':'endpoint','confirmation':'yes'})[0],400);self.launch.assert_not_called()
    def test_identity_mismatch(self):
        self.assertEqual(self.request({'hostname':'other','confirmation':'REQUEST_ADMIN'})[0],409);self.launch.assert_not_called()
    def test_other_os_manual_only(self):
        with patch('app.platform.system',return_value='Darwin'):self.assertEqual(self.request()[0],422)
        self.launch.assert_not_called()
    def test_job_running_blocks_elevation(self):
        with patch('app.JOB',{'status':'running'}):self.assertEqual(self.request()[0],409)
        self.launch.assert_not_called()
    def test_duplicate_request_blocked(self):
        with patch('app.ELEVATING',True):self.assertEqual(self.request()[0],409)
        self.launch.assert_not_called()
    def test_already_admin(self):
        with patch('app.elevated',return_value=True):
            code,body=self.request();self.assertEqual(code,200);self.assertEqual(body['status'],'already_elevated')
        self.launch.assert_not_called();self.restart.assert_not_called()
    def test_configured_api_requires_manual_restart(self):
        with patch('app.API_KEY','test-configuration-key-012345678901234567'):
            self.assertEqual(self.request()[0],409)
        self.launch.assert_not_called()
    def test_uac_cancel_keeps_server(self):
        self.launch.side_effect=OSError('cancelled')
        self.assertEqual(self.request()[0],409);self.assertFalse(app.ELEVATING);self.restart.assert_not_called()
    def test_uac_approval_restarts_console_only(self):
        with patch('app.start_removal') as remove:
            code,body=self.request();self.assertEqual(code,202);self.assertEqual(body['status'],'restarting')
            self.assertTrue(app.ELEVATING);self.launch.assert_called_once_with();self.restart.assert_called_once_with(self.server);remove.assert_not_called()
    def test_integration_route_cannot_prompt_uac(self):
        with patch('app.API_KEY','test-key-012345678901234567890123456789'):
            self.assertEqual(self.request(path='/api/v1/elevate',headers={'Origin':'','Authorization':'Bearer test-key-012345678901234567890123456789'})[0],404)
        self.launch.assert_not_called()

class NativeLaunchTests(unittest.TestCase):
    def test_fixed_paths_and_runas_without_credentials(self):
        native=MagicMock();native.ShellExecuteW.return_value=42
        with patch('app.ctypes.WinDLL',create=True,return_value=native):app.request_windows_elevation()
        args=native.ShellExecuteW.call_args.args
        self.assertEqual(args[1],'runas');self.assertEqual(args[2],app.sys.executable)
        self.assertIn('--wait-for-port',args[3]);self.assertIn('app.py',args[3])
    def test_os_rejection(self):
        native=MagicMock();native.ShellExecuteW.return_value=5
        with patch('app.ctypes.WinDLL',create=True,return_value=native):
            with self.assertRaises(OSError):app.request_windows_elevation()
if __name__=='__main__':unittest.main()
