import io,tempfile,unittest,zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch,MagicMock
import app,installation
from endpoint_connector import Engine
HOST={'system':'Windows','architecture':'x86_64','version':'10.0.26100','build':26100,'server':False,'distro_id':'','distro_version':''}
class FakeClient:
    base='http://192.168.1.101:8765'
    config={'endpoint_id':'visiting-device','secret':'synthetic-private-device-secret'}
    def __init__(self):self.calls=[];self.blob=None
    def post(self,path,body=None,binary=False):
        self.calls.append((path,body))
        if binary:return self.blob
        return {'packages':[{'id':'a'*20,'title':'Windows x64','filename':'VFAgentSetupX64.msi','family':'windows','bytes':20,'ready':True,'rules':{}}]}
class ConnectorEngineTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.client=FakeClient()
        self.engine=Engine(self.client,Path(self.tmp.name)/'connector.private.json');self.addCleanup(self.engine.close)
        for item in [patch('app.platform.node',return_value='VISITING-VM'),patch('app.host_platform',return_value='windows-desktop'),patch('app.elevated',return_value=False),patch('app.JOB',{'status':'idle'}),patch('app.ELEVATING',False)]:
            self.stack.enter_context(item)
    def test_status_reads_endpoint_not_portal(self):
        with patch('app.scan',return_value=[{'id':'visitor-agent','name':'VM agent'}]):
            result=self.engine.dispatch({'method':'GET','path':'/api/status'})
        self.assertEqual(result['status'],200);self.assertEqual(result['body']['hostname'],'VISITING-VM')
        self.assertEqual(result['body']['agents'][0]['id'],'visitor-agent');self.assertEqual(result['body']['connector']['endpoint_id'],'visiting-device')
        self.assertEqual(result['body']['session'],'endpoint-relay')
    def test_preflight_matches_endpoint_os_to_central_catalog(self):
        with patch('installation.host',return_value=HOST),patch('installation.existing',return_value=[]),patch('installation.pending_restart',return_value=False):
            result=self.engine.dispatch({'method':'GET','path':'/api/packages'})
        self.assertEqual(result['status'],200);self.assertEqual(result['body']['hostname'],'VISITING-VM')
        self.assertEqual(result['body']['recommended_id'],'a'*20);self.assertFalse(result['body']['elevated'])
    def test_wrong_hostname_cannot_uninstall(self):
        with patch('app.command') as command:
            result=self.engine.dispatch({'method':'POST','path':'/api/uninstall','body':{'confirmation':'UNINSTALL','hostname':'PORTAL-HOST','target_platform':'windows-desktop','id':'unknown'}})
        self.assertEqual(result['status'],409);command.assert_not_called()
    def test_arbitrary_commands_are_rejected(self):
        self.assertEqual(self.engine.dispatch({'method':'POST','path':'/run-shell','body':{'command':'anything'}})['status'],400)
    def test_private_kit_is_temporary_and_paired(self):
        self.engine.refresh_catalog();record=self.engine.catalog[0];out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:
            archive.writestr(record['filename'],b'fake-msi');archive.writestr(installation.CONFIGS['windows'],'synthetic-config');archive.writestr(installation.KEY_NAME,'synthetic-key')
        self.client.blob=out.getvalue()
        with self.engine.kit(record) as staged:
            self.assertEqual(staged['key'].read_text(),'synthetic-key');path=staged['path'];self.assertTrue(path.exists())
        self.assertFalse(path.exists())
    def test_verification_download_does_not_require_or_extract_vendor_keys(self):
        self.engine.refresh_catalog();record=self.engine.catalog[0];out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:archive.writestr(record['filename'],b'fake-msi')
        self.client.blob=out.getvalue()
        with self.engine.kit(record,verification=True) as staged:self.assertFalse(staged['key'].exists());self.assertTrue(staged['path'].exists())
    def test_zip_traversal_is_rejected(self):
        self.engine.refresh_catalog();record=self.engine.catalog[0];out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:archive.writestr('../outside.txt','bad')
        self.client.blob=out.getvalue()
        with self.assertRaises(ValueError):
            with self.engine.kit(record):self.fail('Unsafe kit accepted')
    def test_endpoint_uac_launches_connector_not_portal(self):
        shell=MagicMock();shell.ShellExecuteW.return_value=42
        with patch('endpoint_connector.ctypes.WinDLL',create=True,return_value=shell):
            self.engine.elevate()
        args=shell.ShellExecuteW.call_args.args
        self.assertEqual(args[1],'runas');self.assertIn('endpoint_connector.py',args[3]);self.assertIn('--uac-handoff',args[3]);self.assertNotIn('--lan-address',args[3])
if __name__=='__main__':unittest.main()
