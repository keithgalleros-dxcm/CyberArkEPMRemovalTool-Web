import tempfile,unittest,os,json
from pathlib import Path
from unittest.mock import patch,MagicMock
import app,windows_verification as verify
IDENTITY={'product_code':'{11111111-1111-1111-1111-111111111111}','product_version':'26.10.1115','agent_component':'{22222222-2222-2222-2222-222222222222}'}
class WindowsVerificationTests(unittest.TestCase):
    def native_evidence(self,state=5,version='26.10.1115',service='running',file=True):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'vf_agent.exe'
            if file:path.write_bytes(b'synthetic-agent')
            lib=MagicMock();lib.MsiQueryProductStateW.return_value=state
            def info(code,name,buffer,size):buffer.value=version;return 0
            def component(code,identity,buffer,size):buffer.value=str(path);return 3
            lib.MsiGetProductInfoW.side_effect=info;lib.MsiGetComponentPathW.side_effect=component
            with patch('windows_verification.ctypes.WinDLL',create=True,return_value=lib),patch('windows_verification.service_state',return_value=service):
                return verify.evidence(IDENTITY)
    def test_verified_runtime_requires_all_evidence(self):self.assertTrue(self.native_evidence()['runtime_verified'])
    def test_advertised_product_is_not_installed(self):self.assertFalse(self.native_evidence(state=1)['runtime_verified'])
    def test_wrong_version_is_not_healthy(self):self.assertFalse(self.native_evidence(version='25.1')['runtime_verified'])
    def test_missing_agent_file_is_not_healthy(self):self.assertFalse(self.native_evidence(file=False)['runtime_verified'])
    def test_stopped_service_is_not_healthy(self):self.assertFalse(self.native_evidence(service='stopped')['runtime_verified'])
    def test_missing_service_is_not_healthy(self):self.assertFalse(self.native_evidence(service='missing')['runtime_verified'])
    def test_summary_never_returns_raw_log_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'installer.log'
            path.write_text('INSTALLATIONKEY=synthetic-private-value\nError 1603\nAction ended: InstallFinalize. Return value 3.\nMainEngineThread is returning 1603',encoding='utf-16')
            data=verify.log_summary(path);self.assertEqual(data['msi_error_codes'],[1603]);self.assertTrue(data['return_value_3_detected'])
            self.assertNotIn('synthetic-private-value',json.dumps(data))
    def test_worker_does_not_accept_unrelated_registration(self):
        previous=app.JOB
        try:
            result={'accepted':True,'exit_code':0,'windows_verification':{'registered':False,'runtime_verified':False}}
            with patch('app.installation.install',return_value=result),patch('app.scan',return_value=[{'id':'unrelated'}]),patch('app.platform.node',return_value='actual-host'):
                app.run_install_job({'family':'windows'},{'system':'Windows'})
                self.assertEqual(app.JOB['status'],'attention_required');self.assertFalse(app.JOB['registration_present']);self.assertEqual(app.JOB['hostname'],'actual-host')
        finally:app.JOB=previous
    def test_worker_healthy_runtime_is_complete(self):
        previous=app.JOB
        try:
            with patch('app.installation.install',return_value={'accepted':True,'windows_verification':{'registered':True,'runtime_verified':True}}):
                app.run_install_job({'family':'windows'},{'system':'Windows'});self.assertEqual(app.JOB['status'],'completed')
        finally:app.JOB=previous
    def test_worker_installer_error_cannot_be_complete(self):
        previous=app.JOB
        try:
            with patch('app.installation.install',return_value={'accepted':False,'exit_code':1603,'windows_verification':{'registered':True,'runtime_verified':True}}):
                app.run_install_job({'family':'windows'},{'system':'Windows'});self.assertEqual(app.JOB['status'],'failed')
        finally:app.JOB=previous
if __name__=='__main__':unittest.main()
