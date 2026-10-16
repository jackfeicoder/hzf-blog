"""Disposable loopback UI fixture for welcome, share links and public bio.
Run from backend with --app-dir tests, host 127.0.0.1, port 18766.
No production database, password entry, or live account access is involved.
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
from routers.visitors import router as visitors_router

app.include_router(router)
app.include_router(visitors_router)
dist = Path(__file__).resolve().parents[2] / 'frontend/dist'
app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='fixture-assets')
with sessions() as db:
    author = db.query(User).filter_by(username='jackfei').one()
    author.bio = '我是一名计算机专业在读研究生，热爱编程Github:https://github.com/jackfeicoder;Gitee:https://gitee.com/jackfei2545;CSDN:https://blog.csdn.net/qq_62480054'
    db.commit()


@app.get('/{path:path}')
def frontend(path: str, fixture: str = ''):
    if path.startswith('api/'):
        raise HTTPException(404)
    if fixture == 'mobile':
        return HTMLResponse('<html><head><title>390px welcome fixture</title></head>'
                            '<body style="margin:0;background:#eef2f7">'
                            '<iframe title="手机欢迎页验收" src="/?fixture=first" '
                            'style="display:block;width:390px;height:844px;border:0"></iframe></body></html>')
    statements = []
    if fixture in ('first', 'guest', 'member', 'admin'):
        if fixture in ('first', 'guest'):
            statements.append("localStorage.removeItem('blog_token');sessionStorage.removeItem('blog_token');")
        else:
            with sessions() as db:
                name = 'jackfei' if fixture == 'admin' else 'study-demo'
                account = db.query(User).filter_by(username=name).one()
                token = create_access_token(name, account)
            statements.append("localStorage.setItem('blog_token'," + json.dumps(token) + ");")
        if fixture == 'first':
            statements.append("localStorage.removeItem('blog_welcome_seen_v1');")
        statements.append("history.replaceState(null,''," + json.dumps('/'+path) + ");")
    script = '<script>'+''.join(statements)+'</script>' if statements else ''
    return HTMLResponse((dist / 'index.html').read_text(encoding='utf-8').replace('<head>', '<head>'+script))
