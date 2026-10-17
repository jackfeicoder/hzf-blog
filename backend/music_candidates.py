"""Finite playback routes: all advertised qualities and known aggregate branches."""
import json
import re

LEVELS = ('128k', '320k', 'flac', 'flac24bit')
AGGREGATE = {
    'xinghai': ('wy','tx','kw','kg','mg'), 'xinghaiBackup': ('wy','tx','kw'),
    'huibq': ('wy','tx','kw','kg','mg'), 'lingchuan': ('wy','tx','kw','kg','mg'),
    'suyinQQ': ('tx',), 'suyin163': ('wy',), 'suyinSearch': ('kw',), 'suyinMigu': ('mg',),
    'changqingVip': ('wy','tx','kw','kg','mg'), 'nianxinVip': ('wy','tx','kw','kg','mg'),
}


def branches(script, platform):
    # Only the reviewed registry protocol, never arbitrary script introspection.
    if not all(marker in script for marker in ('const SOURCE_HANDLERS =', 'function getUrlWithFallback(', 'function getPlatformSongId(')):
        return []
    return [key for key, platforms in AGGREGATE.items()
            if platform in platforms and re.search(r'\b' + key + r'\s*:', script)]


def branch_script(script, branch):
    if not branch:
        return script
    if branch not in AGGREGATE:
        raise ValueError('Unknown aggregate branch')
    # Register a single declared branch in the disposable LX sandbox. The stored
    # user script is never changed. IDs always belong to this candidate platform.
    return script + '\nlx.on(lx.EVENT_NAMES.request, ({source,info}) => SOURCE_HANDLERS[' + json.dumps(branch) + '].fn(source,info.musicInfo.id,info.type,info.musicInfo));\n'


def candidates(rows, platform, requested):
    groups = []
    for row in rows:
        cap = json.loads(row.capabilities)[platform]
        supported = [q for q in LEVELS if q in cap.get('qualitys', [])] or [requested]
        quality = requested if requested in supported else next((q for q in reversed(supported) if LEVELS.index(q) <= LEVELS.index(requested)), supported[0])
        groups.append((row, [quality] + [q for q in supported if q != quality], [''] + branches(row.script, platform)))
    # First pass is one ordinary request per source. Additional qualities and
    # inner branches follow; every supported tuple appears exactly once.
    for quality_index in range(max((len(g[1]) for g in groups), default=0)):
        for branch_index in range(max((len(g[2]) for g in groups), default=0)):
            for row, qualities, routes in groups:
                if quality_index < len(qualities) and branch_index < len(routes):
                    yield row, qualities[quality_index], routes[branch_index]
