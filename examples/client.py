"""Endpoint-local API client. Removal requires explicit flags and human confirmation."""
import argparse
import getpass
import json
import os
import time
from urllib.request import Request, urlopen

BASE = os.environ.get('EPM_PORTAL_URL', 'http://127.0.0.1:8765').rstrip('/')
def direct_request(path, body=None):
    key = os.environ.get('EPM_API_KEY', '')
    if not key: raise SystemExit('Set EPM_API_KEY first (same key as the server).')
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    if os.environ.get('EPM_ENDPOINT_KEY'): headers['X-Endpoint-Key'] = os.environ['EPM_ENDPOINT_KEY']
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(BASE + path, headers=headers, data=data), timeout=30) as response:
        return json.load(response)

def request(path, body=None):
    if not os.environ.get('EPM_ENDPOINT_KEY'): return direct_request(path, body)
    queued=direct_request('/api/v1/endpoint/rpc',{'method':'POST' if body is not None else 'GET','path':path.replace('/api/v1/','/api/',1),'body':body})
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        time.sleep(0.5)
        result=direct_request('/api/v1/endpoint/result/'+queued['request_id'])
        if result['done']:
            response=result['result']
            if response['status']>=400:raise SystemExit(response['body'].get('error','Endpoint request failed'))
            return response['body']
    raise SystemExit('Endpoint response timed out; rescan before retrying any mutation.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', metavar='AGENT_ID', help='Exact id from status')
    parser.add_argument('--hostname', help='Expected hostname; required for removal')
    parser.add_argument('--with-token', action='store_true', help='Privately prompt for vendor token')
    args = parser.parse_args()
    if not os.environ.get('EPM_ENDPOINT_KEY'): print('HOST MODE: set EPM_ENDPOINT_KEY for a paired visiting PC.')
    status = request('/api/v1/status')
    print(json.dumps(status, indent=2))
    if not args.uninstall: return
    if args.hostname != status['hostname']: raise SystemExit('Expected hostname must match the endpoint.')
    if not status['removal_supported']: raise SystemExit('Removal is not configured for this platform.')
    if args.uninstall not in [a['id'] for a in status['agents']]: raise SystemExit('Agent not detected.')
    expected = 'UNINSTALL ' + status['hostname']
    if input('Full removal deletes agent data. Type '+expected+' to continue: ') != expected:
        raise SystemExit('Cancelled')
    token = getpass.getpass('Vendor secure token: ') if args.with_token else ''
    body = {'id':args.uninstall, 'hostname':args.hostname, 'target_platform':status['target_platform'], 'confirmation':'UNINSTALL', 'token':token}
    print(request('/api/v1/uninstall', body))
    body.clear(); token = ''
    while True:
        time.sleep(2)
        job = request('/api/v1/status')['job']
        if job['status'] != 'running':
            print(json.dumps(job, indent=2))
            raise SystemExit(0 if job['status'] == 'completed' else 1)
if __name__ == '__main__': main()
