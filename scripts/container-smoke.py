#!/usr/bin/env python3
"""Run against the isolated compose.test stack; includes restart persistence mode."""
import argparse
from pathlib import Path
import json
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--verify', action='store_true')
parser.add_argument('--state', default='/tmp/fleet-smoke.json')
args = parser.parse_args()
base = 'https://localhost:18443'
# Caddy uses its disposable internal CA for localhost in this isolated stack.
headers = {'Origin': 'https://localhost:18443'}
assert 'max-age=' in httpx.get(base+'/health/live', verify=False).headers['strict-transport-security']
assert httpx.get(base+'/health/live', verify=False).status_code == 200
assert httpx.get(base+'/health/ready', verify=False).status_code == 200
assert httpx.get(base+'/login', verify=False).status_code == 200
if args.verify:
    state = json.loads(Path(args.state).read_text())
    with httpx.Client(base_url=base, headers=headers, verify=False) as client:
        r = client.post('/api/v1/auth/login',json={'email':state['email'],'password':state['password']})
        r.raise_for_status()
        r = client.get('/api/v1/admin/company-settings/logo')
        r.raise_for_status()
        assert r.content == bytes.fromhex(state['logo'])
else:
    import uuid
    suffix = uuid.uuid4().hex[:10]
    state = {'email':f'admin-{suffix}@fleet.test','password':'isolated smoke test password',
             'logo':b'\x89PNG\r\n\x1a\nsmoke-test'.hex()}
    with httpx.Client(base_url=base, headers=headers, verify=False) as client:
        r=client.post('/api/v1/auth/register',json={'company_name':f'CI {suffix}', 'full_name':'CI Administrator','email':state['email'],'password':state['password']})
        r.raise_for_status()
        r=client.post('/api/v1/admin/company-settings/logo',files={'file':('logo.png',bytes.fromhex(state['logo']),'image/png')})
        r.raise_for_status()
        r=client.get('/api/v1/admin/company-settings/logo')
        r.raise_for_status()
        assert r.content == bytes.fromhex(state['logo'])
        assert r.headers['cache-control'] == 'private, no-store'
    assert httpx.get(base+'/api/v1/admin/company-settings/logo',verify=False).status_code == 401
    with httpx.Client(base_url=base,headers=headers,verify=False) as other:
        r=other.post('/api/v1/auth/register',json={'company_name':f'Other CI {suffix}','full_name':'Other Administrator','email':f'other-{suffix}@fleet.test','password':state['password']})
        r.raise_for_status()
        assert other.get('/api/v1/admin/company-settings/logo').status_code == 404
    Path(args.state).write_text(json.dumps(state))
    Path(args.state).chmod(0o600)
print('Container startup, tenant access and storage persistence checks passed.')
