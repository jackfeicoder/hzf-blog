"""Read-only production verification; never prints IPs or creates visit logs."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path('/www/wwwroot/blog.120115.xyz')
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request
import models
from routers import visitors

backup = Path(sys.argv[1]).resolve(strict=True)
assert backup.parent == ROOT / '.deploy-backups'
engine = create_engine('sqlite://', creator=lambda: sqlite3.connect('file:' + str(ROOT / 'backend/blog.db') + '?mode=ro', uri=True))
with Session(engine, autoflush=False) as db:
    owner = db.query(models.User).filter_by(username='jackfei').one()
    request = Request({'type': 'http', 'method': 'GET', 'path': '/api/visitors', 'headers': []})
    with patch.object(visitors, 'record_visit'):
        result = visitors.get_visitors(request, Response(), db, owner)
    assert len(result.items) <= 10
    assert len({item.ip for item in result.items}) == len(result.items)
    assert [item.created_at for item in result.items] == sorted((item.created_at for item in result.items), reverse=True)
    account_ips = {}
    for item in result.items:
        if item.user:
            account_ips.setdefault(item.user.id, set()).add(item.ip)
    print(json.dumps({'displayed_rows': len(result.items), 'distinct_displayed_ips': len(result.items),
                      'accounts_with_multiple_displayed_ips': sum(len(ips) > 1 for ips in account_ips.values())}))
engine.dispose()
with sqlite3.connect('file:' + str(ROOT / 'backend/blog.db') + '?mode=ro', uri=True) as live:
    with sqlite3.connect('file:' + str(backup / 'blog.db') + '?mode=ro', uri=True) as old:
        for table in ('users', 'music_sources', 'music_lists', 'music_entries', 'site_appearance', 'registration_invites', 'registration_settings'):
            assert live.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall() == old.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall(), 'Inspect concurrent changes: ' + table
        cutoff = str(datetime.utcnow() - timedelta(days=7))
        old_ids = {r[0] for r in old.execute('SELECT id FROM visit_logs WHERE created_at>=?', (cutoff,))}
        live_ids = {r[0] for r in live.execute('SELECT id FROM visit_logs')}
        assert old_ids.issubset(live_ids), 'Visit history unexpectedly removed'
for path, expected in (('/api/health', 200), ('/api/visitors', 401)):
    try:
        response = urlopen('https://ithzf.xyz' + path, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected
print('VISITORS_IP_PRODUCTION_CHECKS_OK; EXISTING_DATA_PRESERVED')
