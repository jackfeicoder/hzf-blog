"""Application-wide access gate; only homepage bootstrap data stays public."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from auth import bearer_scheme, get_current_user
from database import get_db

PUBLIC_GET = frozenset({
    '/api/health', '/api/appearance', '/api/categories', '/api/posts',
    '/api/rankings/posts', '/api/rankings/authors',
    '/api/auth/registration-settings', '/api/auth/welcome-author',
})
PUBLIC_POST = frozenset({'/api/auth/login', '/api/auth/register'})


def require_site_access(request: Request,
                        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
                        db: Session = Depends(get_db)):
    path = request.url.path.rstrip('/')
    if request.method == 'GET' and path in PUBLIC_GET:
        return
    if request.method == 'POST' and path in PUBLIC_POST:
        return
    # Audio elements cannot attach bearer headers. These routes retain their
    # own opaque/signed playback-capability validation; no anonymous discovery.
    # Cover art is an image resource, like public homepage avatars/backgrounds.
    if request.method in ('GET', 'HEAD') and (path.startswith('/api/music/stream/') or path == '/api/music/cover'):
        return
    try:
        return get_current_user(credentials=credentials, db=db)
    except HTTPException as error:
        error.headers = {**(error.headers or {}), 'Cache-Control': 'private, no-store', 'Vary': 'Authorization'}
        raise
