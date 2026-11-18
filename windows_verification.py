"""Read-only MSI identity and Windows agent health checks."""
import ctypes,re
from pathlib import Path
def msi_identity(path):
    from ctypes import wintypes as W
    lib=ctypes.WinDLL('msi');U=ctypes.c_uint
    lib.MsiOpenDatabaseW.argtypes=[W.LPCWSTR,W.LPCWSTR,ctypes.POINTER(U)]
    lib.MsiDatabaseOpenViewW.argtypes=[U,W.LPCWSTR,ctypes.POINTER(U)]
    lib.MsiViewExecute.argtypes=[U,U];lib.MsiViewFetch.argtypes=[U,ctypes.POINTER(U)]
    lib.MsiRecordGetStringW.argtypes=[U,U,W.LPWSTR,ctypes.POINTER(W.DWORD)];lib.MsiCloseHandle.argtypes=[U]
    db=U()
    if lib.MsiOpenDatabaseW(str(path),None,ctypes.byref(db)):raise OSError('Cannot read MSI identity')
    q=lambda value:chr(96)+value+chr(96)
    def rows(query):
        view=U()
        if lib.MsiDatabaseOpenViewW(db,query,ctypes.byref(view)):raise OSError('Cannot query MSI identity')
        result=[]
        try:
            if lib.MsiViewExecute(view,0):raise OSError('Cannot execute MSI query')
            while True:
                record=U();code=lib.MsiViewFetch(view,ctypes.byref(record))
                if code==259:break
                if code:raise OSError('Cannot read MSI record')
                try:
                    values=[]
                    for column in (1,2):
                        buffer=ctypes.create_unicode_buffer(2048);length=W.DWORD(2048)
                        if lib.MsiRecordGetStringW(record,column,buffer,ctypes.byref(length)):raise OSError('Cannot read MSI field')
                        values.append(buffer.value)
                    result.append(values)
                finally:lib.MsiCloseHandle(record)
        finally:lib.MsiCloseHandle(view)
        return result
    try:
        where=' OR '.join(q('Property')+"='"+key+"'" for key in ['ProductCode','ProductVersion','ProductName'])
        props=dict(rows('SELECT '+q('Property')+', '+q('Value')+' FROM '+q('Property')+' WHERE '+where))
        product=props.get('ProductCode','').upper()
        if not re.fullmatch(r'\{[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}\}',product):raise ValueError('Invalid MSI product code')
        component=''
        for key,name in rows('SELECT '+q('Component_')+', '+q('FileName')+' FROM '+q('File')):
            if name.split('|')[-1].lower()=='vf_agent.exe':
                values=rows('SELECT '+q('Component')+', '+q('ComponentId')+' FROM '+q('Component')+' WHERE '+q('Component')+"='"+key.replace("'","''")+"'")
                if values:component=values[0][1]
                break
        return {'product_code':product,'product_version':props.get('ProductVersion',''),'product_name':props.get('ProductName',''),'agent_component':component}
    finally:lib.MsiCloseHandle(db)

def service_state():
    from ctypes import wintypes as W
    class Status(ctypes.Structure):
        _fields_=[(name,W.DWORD) for name in ('kind','current','accepted','win32_exit','service_exit','checkpoint','wait_hint')]
    lib=ctypes.WinDLL('advapi32',use_last_error=True)
    lib.OpenSCManagerW.argtypes=[W.LPCWSTR,W.LPCWSTR,W.DWORD];lib.OpenSCManagerW.restype=W.HANDLE
    lib.OpenServiceW.argtypes=[W.HANDLE,W.LPCWSTR,W.DWORD];lib.OpenServiceW.restype=W.HANDLE
    lib.QueryServiceStatus.argtypes=[W.HANDLE,ctypes.POINTER(Status)];lib.QueryServiceStatus.restype=W.BOOL
    lib.CloseServiceHandle.argtypes=[W.HANDLE]
    manager=lib.OpenSCManagerW(None,None,1)
    if not manager:raise OSError('Cannot inspect service manager')
    try:
        service=lib.OpenServiceW(manager,'vf_agent',4)
        if not service:
            if ctypes.get_last_error()==1060:return 'missing'
            raise OSError('Cannot inspect EPM service')
        try:
            status=Status()
            if not lib.QueryServiceStatus(service,ctypes.byref(status)):raise OSError('Cannot query EPM service')
            return {1:'stopped',2:'start_pending',3:'stop_pending',4:'running',5:'continue_pending',6:'pause_pending',7:'paused'}.get(status.current,'unknown')
        finally:lib.CloseServiceHandle(service)
    finally:lib.CloseServiceHandle(manager)

def evidence(identity):
    from ctypes import wintypes as W
    lib=ctypes.WinDLL('msi')
    lib.MsiQueryProductStateW.argtypes=[W.LPCWSTR];lib.MsiQueryProductStateW.restype=ctypes.c_int
    lib.MsiGetProductInfoW.argtypes=[W.LPCWSTR,W.LPCWSTR,W.LPWSTR,ctypes.POINTER(W.DWORD)]
    lib.MsiGetComponentPathW.argtypes=[W.LPCWSTR,W.LPCWSTR,W.LPWSTR,ctypes.POINTER(W.DWORD)];lib.MsiGetComponentPathW.restype=ctypes.c_int
    code=identity['product_code'];state=lib.MsiQueryProductStateW(code)
    version=ctypes.create_unicode_buffer(2048);size=W.DWORD(2048)
    installed_version=version.value if lib.MsiGetProductInfoW(code,'VersionString',version,ctypes.byref(size))==0 else ''
    path=ctypes.create_unicode_buffer(32768);size=W.DWORD(32768)
    component_state=lib.MsiGetComponentPathW(code,identity['agent_component'],path,ctypes.byref(size)) if identity.get('agent_component') else -1
    file_present=component_state==3 and Path(path.value).name.lower()=='vf_agent.exe' and Path(path.value).is_file()
    service=service_state();matches=bool(installed_version) and installed_version==identity['product_version']
    return {'product_code':code,'expected_version':identity['product_version'],'installed_version':installed_version,'product_state':state,'registered':state==5,'version_matches':matches,'agent_file_present':file_present,'service_name':'vf_agent','service_state':service,'runtime_verified':state==5 and matches and file_present and service=='running'}

def log_summary(path):
    if not path.exists():return {'log_created':False}
    raw=path.read_bytes()[:32*1024*1024]
    text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
    return {'log_created':True,'return_value_3_detected':'Return value 3' in text,'msi_error_codes':sorted({int(x) for x in re.findall(r'(?:Error\s+|Note:\s+1:\s*)(\d{3,5})\b',text)})[:20],'engine_return_codes':sorted({int(x) for x in re.findall(r'MainEngineThread is returning (\d+)',text)})[:10]}
