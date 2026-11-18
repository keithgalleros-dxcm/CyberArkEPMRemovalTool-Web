import io,json,os,tempfile,threading,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import app,installation

HOST={'system':'Windows','architecture':'x86_64','version':'10.0.26100','build':26100,'server':False,'distro_id':'','distro_version':''}

class KitFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        folder=self.root/'Windows 64-bit';folder.mkdir()
        (folder/'VFAgentSetupX64.msi').write_bytes(b'fake-installer-for-tests')
        (folder/installation.CONFIGS['windows']).write_text('synthetic-configuration')
        (folder/installation.KEY_NAME).write_text('synthetic-private-key')
        self.root_patch=patch('installation.ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.record=installation.discover()[0]
    def test_catalog_redacts_paths_and_secret_values(self):
        data=installation.catalog(HOST);raw=json.dumps(data)
        self.assertNotIn('synthetic-private-key',raw);self.assertNotIn(str(self.root),raw)
        self.assertNotIn('config',data[0]);self.assertTrue(data[0]['matched'])
    def test_missing_key_blocks_package(self):
        self.record['key'].unlink()
        self.assertFalse(installation.discover()[0]['ready'])
        with self.assertRaises(ValueError):installation.get_record(self.record['id'])
    def test_unknown_id_and_traversal_rejected(self):
        for value in ['../../file','invalid',None]:
            with self.assertRaises(ValueError):installation.get_record(value)
    def test_private_bundle_contains_paired_files(self):
        output=io.BytesIO();installation.bundle(self.record,output)
        with zipfile.ZipFile(output) as z:
            self.assertEqual(z.read(installation.KEY_NAME),b'synthetic-private-key')
            self.assertIn('INSTALL-README.txt',z.namelist())
            self.assertNotIn('synthetic-private-key',z.read('INSTALL-README.txt').decode())
    def test_windows_compatibility(self):
        self.assertTrue(installation.compatible(self.record,HOST))
        for changes in [{'architecture':'arm64'},{'build':19044},{'system':'Linux'}]:
            self.assertFalse(installation.compatible(self.record,{**HOST,**changes}))
        self.assertTrue(installation.compatible(self.record,{**HOST,'server':True,'build':14393}))
    def test_mac_compatibility(self):
        rec={**self.record,'family':'macos'}
        for arch in ['x86_64','arm64']:
            self.assertTrue(installation.compatible(rec,{**HOST,'system':'Darwin','architecture':arch,'version':'14.5'}))
        self.assertFalse(installation.compatible(rec,{**HOST,'system':'Darwin','version':'14.4'}))
    def test_linux_version_matching(self):
        for name,distro,version in [('epm-ubuntu.x86_64.deb','ubuntu','20.04'),('epm-ubuntu22.x86_64.deb','ubuntu','24.04'),('epm-rhel9.x86_64.rpm','rocky','10'),('epm-rhel7.x86_64.rpm','amzn','2'),('epm-rhel8.x86_64.rpm','sles','15.6')]:
            rec={**self.record,'family':'linux','rules':installation.LINUX[name]}
            h={**HOST,'system':'Linux','distro_id':distro,'distro_version':version}
            self.assertTrue(installation.compatible(rec,h),(name,distro,version))
            self.assertFalse(installation.compatible(rec,{**h,'architecture':'arm64'}))
        rec={**self.record,'family':'linux','rules':installation.LINUX['epm-ubuntu22.x86_64.deb']}
        for distro,version in [('ubuntu','26.04'),('ubuntu','24.10'),('debian','12'),('fedora','43')]:
            self.assertFalse(installation.compatible(rec,{**HOST,'system':'Linux','distro_id':distro,'distro_version':version}))
    def test_staging_rechecks_existing_agent(self):
        with patch('installation.run') as run:
            with self.assertRaises(ValueError):installation.install(self.record,HOST,lambda:False)
            run.assert_not_called()
    def test_windows_adapter_is_noninteractive_and_cleans_staging(self):
        seen=[]
        def execute(args):seen.append(list(args));self.assertTrue(Path(args[2]).exists());return 3010
        with patch('installation.run',side_effect=execute),patch.dict(os.environ,{'SystemRoot':r'C:\Windows'}):
            result=installation.install(self.record,HOST,lambda:True)
        self.assertTrue(result['restart_required']);self.assertIn('/norestart',seen[0])
        self.assertIn('INSTALLATIONKEY=synthetic-private-key',seen[0]);self.assertFalse(Path(seen[0][2]).exists())
    def test_worker_marks_failed_verification(self):
        old=app.JOB
        try:
            with patch('app.installation.install',return_value={'accepted':True,'exit_code':0}),patch('app.installation.existing',return_value=[]),patch('app.scan',return_value=[]):
                app.run_install_job(self.record,HOST)
                self.assertEqual(app.JOB['status'],'failed')
        finally:app.JOB=old
    def test_mac_install_failure_does_not_activate(self):
        rec={**self.record,'family':'macos'};calls=[]
        with patch('installation.run',side_effect=lambda args:calls.append(list(args)) or 1):
            result=installation.install(rec,{**HOST,'system':'Darwin'},lambda:True)
        self.assertFalse(result['accepted']);self.assertEqual(len(calls),1)
    def test_linux_activation_uses_key_file(self):
        rec={**self.record,'family':'linux','path':self.record['path'].with_suffix('.deb')}
        rec['path'].write_bytes(b'fake-deb');calls=[]
        with patch('installation.shutil.which',return_value='/usr/bin/apt-get'),patch('installation.run',side_effect=lambda args:calls.append(list(args)) or 0):
            result=installation.install(rec,{**HOST,'system':'Linux','distro_id':'ubuntu'},lambda:True)
        self.assertTrue(result['activation_verified']);self.assertIn('-f',calls[1]);self.assertNotIn('synthetic-private-key',str(calls))

class InstallHttpTests(KitFixture):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        super().setUp()
        self.patches=[patch('app.platform.node',return_value='endpoint'),patch('app.host_platform',return_value='windows-desktop'),patch('app.elevated',return_value=True),patch('installation.host',return_value=HOST),patch('installation.existing',return_value=[]),patch('installation.pending_restart',return_value=False),patch('app.JOB',{'status':'idle'}),patch('app.ELEVATING',False),patch('app.start_install')]
        self.mocks=[p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)
        self.start=self.mocks[-1]
    def request(self,path='/api/install',changes=None,headers=None,get=False):
        body={'package_id':self.record['id'],'hostname':'endpoint','target_platform':'windows-desktop','confirmation':'INSTALL'}
        body.update(changes or {})
        h={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765','X-Session':app.SESSION,'Content-Type':'application/json'};h.update(headers or {})
        req=Request(self.base+path,headers=h,data=None if get else json.dumps(body).encode())
        try:
            with urlopen(req,timeout=5) as response:return response.status,response.read()
        except HTTPError as error:
            with error:return error.code,error.read()
    def test_install_requires_session(self):self.assertEqual(self.request(headers={'X-Session':''})[0],403)
    def test_install_requires_admin(self):
        with patch('app.elevated',return_value=False):self.assertEqual(self.request()[0],403)
        self.start.assert_not_called()
    def test_install_requires_confirmation(self):self.assertEqual(self.request(changes={'confirmation':''})[0],400)
    def test_install_requires_endpoint_match(self):self.assertEqual(self.request(changes={'hostname':'other'})[0],409)
    def test_existing_agent_blocks(self):
        with patch('installation.existing',return_value=[{'id':'existing'}]):self.assertEqual(self.request()[0],409)
        self.start.assert_not_called()
    def test_restart_blocks(self):
        with patch('installation.pending_restart',return_value=True):self.assertEqual(self.request()[0],409)
    def test_running_job_blocks(self):
        with patch('app.JOB',{'status':'running'}):self.assertEqual(self.request()[0],409)
    def test_wrong_os_blocks(self):
        with patch('installation.compatible',return_value=False):self.assertEqual(self.request()[0],409)
    def test_accepted_without_running_installer(self):
        self.assertEqual(self.request()[0],202);self.start.assert_called_once()
    def test_preflight_does_not_disclose_keys(self):
        code,raw=self.request('/api/packages',get=True);self.assertEqual(code,200);self.assertNotIn(b'synthetic-private-key',raw)
    def test_private_download_requires_session(self):
        self.assertEqual(self.request('/api/packages/download',{'confirmation':'DOWNLOAD_KIT'},headers={'X-Session':''})[0],403)
    def test_private_download_bundle(self):
        code,raw=self.request('/api/packages/download',{'confirmation':'DOWNLOAD_KIT'});self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertIn(installation.KEY_NAME,z.namelist())
    def test_raw_key_url_unavailable(self):
        self.assertEqual(self.request('/Cyberark%20Agents/agent%20installation%20key.txt',get=True)[0],404)
    def test_api_install_explicit_confirmation(self):
        with patch('app.API_KEY','mock-api-key-for-unit-tests-only-12345'):
            self.assertEqual(self.request('/api/v1/install',headers={'Origin':'','Authorization':'Bearer mock-api-key-for-unit-tests-only-12345'})[0],202)
if __name__=='__main__':unittest.main()
