"""Loopback-only AI UI fixture; synthetic account and upstream, no live key."""
import json
import time
from pathlib import Path
import httpx
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from preview_study import app, sessions
from auth import create_access_token
from models import User
from routers import chat, appearance
import sensenova_catalog

app.include_router(chat.router)
app.include_router(appearance.router)
chat.DEFAULT_FREE_KEY = 'fixture-no-live-provider-key'
sensenova_catalog._state.update(models=list(sensenova_catalog.FALLBACK_MODELS),
                                source='official', next_refresh=time.monotonic()+86400)
real_client = httpx.AsyncClient


def upstream(request):
    payload = json.loads(request.content)
    if '额度' in payload['messages'][-1]['content']:
        return httpx.Response(429, json={'error': {'message': 'fixture quota exhausted'}})
    if payload['stream']:
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"连接成功。这是本地模拟回复，模型选择和流式交互正常。"}}]}\n\ndata: [DONE]\n\n')
    return httpx.Response(200, json={'choices': [{'message': {'content': '连接成功'}}]})


chat.httpx.AsyncClient = lambda **kw: real_client(transport=httpx.MockTransport(upstream), **kw)
dist = Path(__file__).resolve().parents[2] / 'frontend/dist'
app.mount('/assets', StaticFiles(directory=dist/'assets'))


@app.get('/{path:path}')
def frontend(path: str, fixture: str=''):
    if path.startswith('api/'):
        raise HTTPException(404)
    if fixture == 'mobile':
        return HTMLResponse('<title>AI mobile fixture</title><body style="margin:0"><iframe title="手机AI验收" src="/ai?fixture=legacy" style="width:390px;height:844px;border:0"></iframe></body>')
    script = ''
    if fixture in ('legacy', 'guest'):
        statements = ["localStorage.setItem('blog_ai_provider','sensenova');localStorage.setItem('blog_ai_model','sensenova-6.7-flash-lite');localStorage.removeItem('blog_ai_apikey');"]
        if fixture == 'legacy':
            with sessions() as db:
                user = db.query(User).filter_by(username='study-demo').one()
                token = create_access_token(user.username, user)
            statements.append('localStorage.setItem("blog_token",'+json.dumps(token)+');')
        else:
            statements.append("localStorage.removeItem('blog_token');sessionStorage.removeItem('blog_token');")
        statements.append('history.replaceState(null,"","/'+path+'");')
        script = '<script>'+''.join(statements)+'</script>'
    return HTMLResponse((dist/'index.html').read_text(encoding='utf-8').replace('<head>', '<head>'+script))
