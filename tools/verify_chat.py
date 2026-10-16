"""Public-only smoke checks, without credentials or production user tokens."""
import hashlib
import json
from pathlib import Path
import httpx

root=Path('/www/wwwroot/blog.120115.xyz')
base='https://blog.120115.xyz:8443'
with httpx.Client(trust_env=False,timeout=30) as client:
    health=client.get(base+'/api/health')
    assert health.status_code==200
    info=client.get(base+'/api/chat/providers')
    assert info.status_code==200
    provider=info.json()['providers'][0]
    assert provider['site_key_configured'] and provider['requires_login']
    assert provider['default_model']=='sensenova-6.8-flash-lite'
    assert 'sensenova-6.7-flash-lite' not in provider['models']
    assert 'deepseek-v4.1-flash' not in provider['models']
    assert set(provider['models']) <= {'sensenova-6.8-flash-lite','deepseek-v4-flash','kimi-k3'}
    assert 'sk-' not in info.text
    body={'provider':'sensenova','messages':[{'role':'user','content':'连接测试'}]}
    for path in ('/api/chat','/api/chat/stream'):
        denied=client.post(base+path,json=body)
        assert denied.status_code==401,(path,denied.status_code)
    page=client.get(base+'/ai')
    assert page.status_code==200 and page.content==(root/'frontend/dist/index.html').read_bytes()
print(json.dumps({'health':200,'ai_page':200,'shared_key_anonymous_access':401,
                  'default_model':provider['default_model'],'models':provider['models'],
                  'catalog_source':provider['catalog_source'],
                  'index_sha256':hashlib.sha256(page.content).hexdigest()}))
