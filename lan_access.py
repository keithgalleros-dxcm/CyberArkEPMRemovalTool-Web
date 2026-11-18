"""Optional authenticated LAN browser access; all operations still manage the server."""
import hashlib,hmac,ipaddress,secrets,time
from http.cookies import SimpleCookie,CookieError
ADDRESS=''
ACCESS_CODE=secrets.token_urlsafe(24)
COOKIE='epm_lan_session'
def local_client(address):
    return ipaddress.ip_address(address).is_loopback or bool(ADDRESS and address==ADDRESS)
def valid_code(code):
    return isinstance(code,str) and secrets.compare_digest(code.encode(),ACCESS_CODE.encode())
def session_cookie():
    expiry=str(int(time.time())+8*3600)
    signature=hmac.new(ACCESS_CODE.encode(),expiry.encode(),hashlib.sha256).hexdigest()
    return COOKIE+'='+expiry+'.'+signature+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
def authenticated(raw):
    try:
        cookie=SimpleCookie();cookie.load(raw or '')
        value=cookie[COOKIE].value;expiry,signature=value.split('.',1)
        if not int(time.time())<int(expiry)<=int(time.time())+8*3600:return False
        expected=hmac.new(ACCESS_CODE.encode(),expiry.encode(),hashlib.sha256).hexdigest()
        return secrets.compare_digest(signature.encode(),expected.encode())
    except (KeyError,ValueError,CookieError):return False
