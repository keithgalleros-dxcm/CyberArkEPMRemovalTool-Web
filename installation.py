"""Private installer inventory and vendor adapters; secrets never enter status responses."""
import hashlib, os, platform, shutil, subprocess, sys, tempfile, zipfile
import windows_verification
from pathlib import Path
ROOT=Path(os.environ.get('EPM_AGENT_ROOT',str(Path(__file__).resolve().parent.parent/'Cyberark Agents'))).resolve()
KEY_NAME='agent installation key.txt'
CONFIGS={'windows':'CyberArkEPMAgentSetupWindows.config','macos':'CyberArkEPMAgentSetupMacos.config','linux':'CyberArkEPMAgentSetupLinux.config'}
LINUX={
'epm-rhel7.x86_64.rpm':{'rhel':['7'],'amzn':['2'],'sles':['12'],'ol':['7']},
'epm-rhel8.x86_64.rpm':{'rhel':['8'],'sles':['15'],'ol':['8'],'cloudlinux':['8'],'rocky':['8']},
'epm-rhel9.x86_64.rpm':{'rhel':['9','10'],'ol':['9'],'amzn':['2023'],'rocky':['9','10']},
'epm-ubuntu.x86_64.deb':{'ubuntu':['18.04','20.04']},
'epm-ubuntu22.x86_64.deb':{'ubuntu':['22.04','24.04']}}
MAC_BIN=Path('/Applications/CyberArk EPM.app/Contents/MacOS/CyberArkEPM')
LINUX_BIN=Path('/opt/cyberark/epm/bin/epmcli')

def discover():
    records=[]
    if not ROOT.is_dir():return records
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or path.is_symlink():continue
        name=path.name.lower()
        family='windows' if name=='vfagentsetupx64.msi' else 'macos' if name=='cyberarkepm.pkg' else 'linux' if name in LINUX else None
        if not family or not path.resolve().is_relative_to(ROOT):continue
        config=path.parent/CONFIGS[family];key=path.parent/KEY_NAME
        ready=all(f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(ROOT) and f.stat().st_size>0 for f in [path,config,key])
        records.append({'id':hashlib.sha256(path.relative_to(ROOT).as_posix().encode()).hexdigest()[:20],'title':path.parent.name,'filename':path.name,'family':family,'bytes':path.stat().st_size,'ready':ready,'path':path,'config':config,'key':key,'rules':LINUX.get(name,{})})
    return records

def host():
    system=platform.system();arch=platform.machine().lower()
    if system=='Windows':arch=os.environ.get('PROCESSOR_ARCHITEW6432',arch).lower()
    arch={'amd64':'x86_64','x64':'x86_64','aarch64':'arm64'}.get(arch,arch)
    result={'system':system,'architecture':arch,'version':platform.release(),'distro_id':'','distro_version':''}
    if system=='Windows':
        v=sys.getwindowsversion();result.update(version=f'{v.major}.{v.minor}.{v.build}',build=v.build,server=v.product_type!=1)
    elif system=='Darwin':result['version']=platform.mac_ver()[0]
    elif system=='Linux':
        info=platform.freedesktop_os_release();result.update(distro_id=info.get('ID',''),distro_version=info.get('VERSION_ID',''),version=info.get('PRETTY_NAME','Linux'))
    return result

def compatible(rec,h):
    if not rec['ready']:return False
    if rec['family']=='windows':return h['system']=='Windows' and h['architecture']=='x86_64' and h.get('build',0)>=(14393 if h.get('server') else 19045)
    if rec['family']=='macos':
        try:return h['system']=='Darwin' and h['architecture'] in ('x86_64','arm64') and tuple(map(int,h['version'].split('.')[:2]))>=(14,5)
        except ValueError:return False
    return h['system']=='Linux' and h['architecture']=='x86_64' and (h['distro_version'] if h['distro_id']=='ubuntu' else h['distro_version'].split('.')[0]) in rec['rules'].get(h['distro_id'],[])

def catalog(endpoint=None):
    endpoint=endpoint or host();result=[]
    for rec in discover():
        supported='Windows x64: Windows 10 build 19045+, Windows 11, Server 2016+' if rec['family']=='windows' else 'macOS 14.5+ Intel / Apple silicon' if rec['family']=='macos' else '; '.join(k+' '+', '.join(v) for k,v in rec['rules'].items())
        result.append({**{k:rec[k] for k in ('id','title','filename','family','bytes','ready')},'matched':compatible(rec,endpoint),'supported':supported})
    return result

def get_record(ident):
    for rec in discover():
        if rec['id']==ident and rec['ready']:return rec
    raise ValueError('Package unavailable or required configuration/key missing')

def existing_linux():
    if LINUX_BIN.exists():return [{'id':'linux-epm','name':'CyberArk EPM','version':'Installed','location':str(LINUX_BIN)}]
    tool=shutil.which('rpm') or shutil.which('dpkg-query')
    if not tool:raise OSError('Unable to inspect Linux package inventory')
    args=[tool,'-q','epm'] if Path(tool).name=='rpm' else [tool,'-W','-f=$'+'{Status}','epm']
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    if result.returncode not in (0,1):raise OSError('Package query failed')
    present=result.returncode==0 and (Path(tool).name=='rpm' or 'install ok installed' in result.stdout)
    return [{'id':'linux-epm','name':'CyberArk EPM package','version':'Installed','location':'Package inventory'}] if present else []

def existing(scan):
    found=scan()
    if found:return found
    if platform.system()=='Darwin' and MAC_BIN.parent.parent.parent.exists():return [{'id':'mac-files','name':'CyberArk EPM application remains','version':'Unknown','location':str(MAC_BIN.parent.parent.parent)}]
    if platform.system()=='Windows':
        for name in ('ProgramFiles','ProgramFiles(x86)'):
            base=os.environ.get(name)
            if base and (Path(base)/'CyberArk'/'Endpoint Privilege Manager'/'Agent'/'vf_agent.exe').exists():return [{'id':'windows-files','name':'CyberArk agent files remain','version':'Unknown','location':'Program Files'}]
    return []

def pending_restart():
    if platform.system()!='Windows':return False
    import winreg
    for key in [r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',r'SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired']:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key):return True
        except FileNotFoundError:pass
    return False

def manual_guide(rec):
    package=rec['filename'];config=rec['config'].name
    lines=['PRIVATE DEPLOYMENT KIT','Contains tenant installation key and configuration. Authorized support only.','Remove existing EPM agents and complete restarts. Keep files together.','Run from extracted folder as administrator/root.','']
    if rec['family']=='windows':
        lines += ['PowerShell (administrator):',"$key = (Get-Content -LiteralPath '.\\"+KEY_NAME+"' -Raw).Trim()",f"$arguments = '/i \"{package}\" INSTALLATIONKEY=\"' + $key + '\" CONFIGURATION=\"' + (Join-Path $PWD '{config}') + '\" /qn /norestart'",'$p = Start-Process -FilePath "$env:SystemRoot\\System32\\msiexec.exe" -ArgumentList $arguments -Wait -PassThru','"MSI exit code: $($p.ExitCode)"','$key = $null; $arguments = $null','Verify agent registration and EPM console enrollment.']
    elif rec['family']=='macos':
        lines += [f'sudo /usr/sbin/installer -pkg "./{package}" -target /','# Continue only if installation succeeds.',f"EPM_KEY=$(cat './{KEY_NAME}')",f"""sudo '{MAC_BIN}' -activate -c "$PWD/{config}" -installationKey "$EPM_KEY" """.strip(),'unset EPM_KEY',f"sudo '{MAC_BIN}' -activationStatus",'Approve system/network extensions and Full Disk Access through macOS/MDM policy.']
    else:
        manager='sudo apt-get install -y' if package.endswith('.deb') else 'sudo yum install -y'
        lines += [f"{manager} './{package}'"]
        if package.endswith('.rpm'):lines += ['# Import the supplied vendor GPG key first when required: sudo rpm --import GPG-KEY-CyberArk','# On supported SUSE use this instead:',f"sudo zypper --non-interactive install './{package}'"]
        lines += ['# Continue only if installation succeeds.',f"""sudo {LINUX_BIN} --activate -c "$PWD/{config}" -f "$PWD/{KEY_NAME}" """.strip(),f'sudo {LINUX_BIN} --status']
    return '\n'.join(lines)+'\n\nPrivileged process inspection and vendor logs may expose credentials. Treat the whole kit as confidential.\n'

def bundle(rec,output):
    with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as z:
        for path in [rec['path'],rec['config'],rec['key']]:z.write(path,path.name)
        z.writestr('INSTALL-README.txt',manual_guide(rec))
        public=ROOT/'Linux'/'GPG-KEY-CyberArk'
        if rec['family']=='linux' and public.is_file():z.write(public,public.name)
    output.seek(0)

def run(args):
    return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,shell=False).returncode

def install(rec,h,still_absent):
    with tempfile.TemporaryDirectory(prefix='epm-install-') as tmp:
        folder=Path(tmp);os.chmod(folder,0o700);paths={}
        for name in ('path','config','key'):
            target=folder/rec[name].name;shutil.copyfile(rec[name],target);os.chmod(target,0o600);paths[name]=target
        if not still_absent():raise ValueError('Existing agent detected after staging')
        family=rec['family'];key=None
        if family in ('windows','macos'):
            key=paths['key'].read_text(encoding='utf-8-sig').strip()
            if not key or len(key)>4096 or any(c in key for c in '\r\n\x00"'):raise ValueError('Invalid installation key')
        if family=='windows':
            identity=windows_verification.msi_identity(paths['path'])
            log=folder/'installer.log'
            args=[str(Path(os.environ['SystemRoot'])/'System32'/'msiexec.exe'),'/i',str(paths['path']),'INSTALLATIONKEY='+key,'CONFIGURATION='+str(paths['config']),'MsiHiddenProperties=INSTALLATIONKEY;CONFIGURATION;SECURE_TOKEN','/qn','/norestart','/L*V',str(log)]
            code=run(args);args.clear();key=None
            diagnostics=windows_verification.log_summary(log)
            try:verification=windows_verification.evidence(identity)
            except OSError:verification={'runtime_verified':False,'verification_error':'Unable to inspect Windows product/component/service state.'}
            return {'exit_code':code,'restart_required':code in (3010,1641),'activation_verified':False,'accepted':code in (0,3010,1641),'windows_verification':verification,'installer_diagnostics':diagnostics}
        if family=='macos':
            code=run(['/usr/sbin/installer','-pkg',str(paths['path']),'-target','/'])
            if code:return {'exit_code':code,'accepted':False,'activation_verified':False}
            args=[str(MAC_BIN),'-activate','-c',str(paths['config']),'-installationKey',key]
            code=run(args);args.clear();key=None
            activated=code==0 and run([str(MAC_BIN),'-activationStatus'])==0
        else:
            manager=shutil.which('apt-get' if rec['path'].suffix=='.deb' else 'zypper' if h['distro_id']=='sles' else 'yum')
            if not manager:raise ValueError('Required package manager unavailable')
            args=[manager,'--non-interactive','install',str(paths['path'])] if Path(manager).name=='zypper' else [manager,'install','-y',str(paths['path'])]
            code=run(args)
            if code:return {'exit_code':code,'accepted':False,'activation_verified':False}
            code=run([str(LINUX_BIN),'--activate','-c',str(paths['config']),'-f',str(paths['key'])])
            activated=code==0 and run([str(LINUX_BIN),'--status'])==0
        return {'exit_code':code,'accepted':activated,'activation_verified':activated,'restart_required':False}
