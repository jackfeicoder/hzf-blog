"""Disposable, loopback-only UI fixture. No production accounts or DB access.

Run from backend: ../.venv-study/Scripts/python -m uvicorn
  preview_appearance:app --app-dir tests --host 127.0.0.1 --port 18765
Use 127.0.0.1:18765/?fixture=admin and localhost:18765/?fixture=guest
for independent browser origins; synthetic sessions require no login dialog.
"""
import json
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from preview_study import app, sessions
from auth import create_access_token
from models import User
from routers.appearance import router

app.include_router(router)
dist = Path(__file__).resolve().parents[2] / 'frontend/dist'
app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='fixture-assets')


@app.get('/{path:path}')
def frontend(path: str, fixture: str = ''):
    if path.startswith('api/'):
        raise HTTPException(404)
    if fixture == 'mobile':
        return HTMLResponse('<html><head><title>390px responsive fixture</title></head>'
                            '<body style="margin:0;background:#eef2f7">'
                            '<iframe title="手机外观验收" src="/?fixture=admin" '
                            'style="display:block;width:390px;height:844px;border:0"></iframe></body></html>')
    script = ''
    if fixture in ('admin', 'guest', 'member'):
        with sessions() as db:
            name = 'jackfei' if fixture == 'admin' else 'study-demo'
            account = db.query(User).filter_by(username=name).one()
            token = create_access_token(name, account)
        script = '<script>' + ("localStorage.removeItem('blog_token');" if fixture == 'guest' else
                  "localStorage.setItem('blog_token'," + json.dumps(token) + ");") + '</script>'
    return HTMLResponse((dist / 'index.html').read_text(encoding='utf-8').replace('<head>', '<head>' + script))
