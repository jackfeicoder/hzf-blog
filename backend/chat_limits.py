"""Bounded shared-key quotas for the production single-worker process."""
from collections import deque
import threading
import time
from fastapi import HTTPException

_lock = threading.Lock()
_users = {}
_global = deque()
_active = {}


def reserve(user_id):
    now = time.monotonic()
    with _lock:
        for key in list(_users):
            queue = _users[key]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if not queue and key not in _active:
                del _users[key]
        while _global and _global[0] <= now - 60:
            _global.popleft()
        queue = _users.get(user_id, deque())
        if user_id in _active or len(_active) >= 4:
            raise HTTPException(429, '已有对话正在生成，或站点繁忙，请稍后重试', headers={'Retry-After': '5'})
        if len(queue) >= 10 or len(_global) >= 60 or len(_users) >= 4096:
            raise HTTPException(429, '站点调用频率已达限制，请稍后重试', headers={'Retry-After': '60'})
        queue.append(now)
        _users[user_id] = queue
        _global.append(now)
        lease = object()
        _active[user_id] = lease
        return lease


def release(user_id, lease):
    with _lock:
        if _active.get(user_id) is lease:
            _active.pop(user_id, None)
