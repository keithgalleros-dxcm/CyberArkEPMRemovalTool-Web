import base64,io,json,os,re,shutil,signal,subprocess,sys,tempfile,time,unittest,zipfile
from pathlib import Path
import connector_installer

# Harmless test connector: no portal, agent operations, elevation or vendor files.
FAKE="""import time
from pathlib import Path
if __name__ == '__main__':
    Path(__file__).with_name('started.txt').write_text('started')
    time.sleep(90)
"""
def payload():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('endpoint_connector.py',FAKE)
        archive.writestr('connector.private.json',json.dumps({'ticket':'synthetic-one-use-ticket'}))
    return output.getvalue()

class InstallerTests(unittest.TestCase):
    def test_windows_single_file_payload_and_marker(self):
        raw,name,kind=connector_installer.render(payload(),'windows')
        self.assertEqual(name,'Install-connector.cmd');text=raw.decode()
        self.assertEqual(text.count('# BEGIN POWERSHELL'),2)
        self.assertIn("LastIndexOf('# BEGIN POWERSHELL')",text)
        encoded=re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)",text)[1]
        self.assertEqual(base64.b64decode(encoded),payload())
        self.assertIn('Find-ConnectorPython',text);self.assertIn('ComputeHash',text)
        self.assertIn('-WindowStyle Hidden',text)
    def test_unix_payload_and_reconnect_script_compile(self):
        for platform in ('linux','macos'):
            text,name,_=connector_installer.render(payload(),platform);text=text.decode()
            self.assertEqual(name,'Install-connector.sh')
            embedded=text.split("<<'CONNECTOR_PAYLOAD'\n",1)[1].split('\nCONNECTOR_PAYLOAD',1)[0]
            compile(embedded,'installer-python','exec')
            self.assertIn('sys.version_info < (3,11)',text)
            self.assertIn('shasum -a 256 -c',text)
    def test_unknown_platform_rejected(self):
        with self.assertRaises(ValueError):connector_installer.render(payload(),'unknown')
    @unittest.skipUnless(os.name=='nt','Windows batch bootstrap')
    def test_batch_header_executes_embedded_powershell_without_unpacking(self):
        with tempfile.TemporaryDirectory(prefix='connector setup ') as folder:
            text=connector_installer.render(payload(),'windows')[0].decode()
            text=text[:text.rindex('# BEGIN POWERSHELL')]+"# BEGIN POWERSHELL\nWrite-Output 'BOOTSTRAP_OK'\n"
            script=Path(folder)/'Install-connector.cmd';script.write_text(text,encoding='utf-8')
            result=subprocess.run(['cmd.exe','/d','/c',str(script)],cwd=folder,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('BOOTSTRAP_OK',result.stdout)
    @unittest.skipUnless(os.name=='nt','Windows PowerShell integration')
    def test_windows_installer_extracts_and_starts_harmless_connector(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);programs=root/'programs';programs.mkdir()
            text=connector_installer.render(payload(),'windows')[0].decode()
            script=text[text.rindex('# BEGIN POWERSHELL'):].split('try { Install-EndpointConnector;',1)[0]
            quote=lambda s:"'"+str(s).replace("'","''")+"'"
            # No runtime download; use the test interpreter. Shortcut goes into a temp folder.
            script+='\nfunction Find-ConnectorPython { return '+quote(sys.executable)+' }\n'
            script+='Install-EndpointConnector -InstallRoot '+quote(root/'install')+' -ProgramsDirectory '+quote(programs)+'\n'
            test=root/'test.ps1';test.write_text(script,encoding='utf-8-sig')
            pid=None
            try:
                # Files avoid waiting for handles inherited by the intentionally detached dummy process.
                with (root/'test-output.txt').open('w') as output:
                    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(test)],stdout=output,stderr=subprocess.STDOUT,text=True,timeout=30)
                result.stdout=(root/'test-output.txt').read_text(errors='replace');result.stderr=''
                dirs=list((root/'install').glob('*'));self.assertEqual(len(dirs),1)
                location=dirs[0]
                if (location/'connector.pid').exists():pid=int((location/'connector.pid').read_text(encoding='utf-8-sig').strip())
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertTrue((location/'started.txt').exists())
                self.assertEqual(json.loads((location/'setup-info.json').read_text(encoding='utf-8-sig'))['runtime'],'existing-python')
                self.assertTrue((programs/'Dexcom Endpoint Connector.lnk').exists())
                self.assertEqual(json.loads((location/'connector.private.json').read_text())['ticket'],'synthetic-one-use-ticket')
            finally:
                if not pid:
                    pid_files=list(root.rglob('connector.pid'))
                    if pid_files:pid=int(pid_files[0].read_text(encoding='utf-8-sig').strip())
                if pid:
                    try:os.kill(pid,signal.SIGTERM);time.sleep(.3)
                    except OSError:pass
    @unittest.skipUnless(os.name=='nt','Windows PowerShell integrity rejection')
    def test_windows_bad_runtime_hash_never_starts_connector(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            text=connector_installer.render(payload(),'windows')[0].decode()
            script=text[text.rindex('# BEGIN POWERSHELL'):].split('try { Install-EndpointConnector;',1)[0]
            quote=lambda s:"'"+str(s).replace("'","''")+"'"
            script+='\nfunction Find-ConnectorPython { return $null }\n'
            script+='function Invoke-WebRequest { param($UseBasicParsing,$Uri,$OutFile) [IO.File]::WriteAllText($OutFile,"invalid runtime") }\n'
            # Match the real switch parameter so the mock intercepts without network traffic.
            script=script.replace('param($UseBasicParsing,$Uri,$OutFile)','param([switch]$UseBasicParsing,$Uri,$OutFile)')
            script+='try { Install-EndpointConnector -InstallRoot '+quote(root/'install')+'; throw "Expected hash failure" } catch { if ($_.Exception.Message -notlike "*checksum failed*") { throw }; Write-Output "HASH_REJECTED" }'
            test=root/'test.ps1';test.write_text(script,encoding='utf-8-sig')
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(test)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('HASH_REJECTED',result.stdout)
            self.assertFalse(list(root.rglob('connector.pid')))
    @unittest.skipIf(os.name=='nt','POSIX shell integration')
    def test_unix_installer_extracts_starts_and_creates_working_reconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'home';home.mkdir();bin=root/'bin';bin.mkdir()
            (bin/'python3.15').symlink_to(sys.executable)
            installer=root/'Install-connector.sh';installer.write_bytes(connector_installer.render(payload(),'linux')[0])
            env={**os.environ,'HOME':str(home),'XDG_DATA_HOME':str(home/'data'),'PATH':str(bin)+os.pathsep+os.environ['PATH']}
            pid=None
            try:
                result=subprocess.run(['sh',str(installer)],env=env,capture_output=True,text=True,timeout=20)
                pids=list(home.rglob('connector.pid'))
                if pids:pid=int(pids[0].read_text())
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(len(pids),1);target=pids[0].parent
                self.assertTrue((target/'started.txt').exists())
                self.assertEqual(json.loads((target/'setup-info.json').read_text())['runtime'],'existing-python')
                reconnect=(target/'Reconnect.command').read_text();self.assertTrue(reconnect.startswith('#!/bin/sh\n'))
                subprocess.run(['sh','-n',str(target/'Reconnect.command')],check=True)
                self.assertEqual(target.stat().st_mode & 0o777,0o700)
                self.assertEqual((target/'connector.private.json').stat().st_mode & 0o777,0o600)
            finally:
                if pid:
                    try:os.kill(pid,signal.SIGTERM)
                    except ProcessLookupError:pass
if __name__=='__main__':unittest.main()
