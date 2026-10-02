"""Platform metadata adapters; never substitute another platform's song IDs.

Only metadata is retrieved here; playback uses the existing source resolver.
"""
import json
from html import unescape
from urllib.parse import urlencode


def rows(payload, *path):
    for key in path:
        if not isinstance(payload, dict) or key not in payload:
            raise ValueError('搜索格式异常')
        payload = payload[key]
    if not isinstance(payload, list):
        raise ValueError('搜索格式异常')
    return payload


async def platform_search(upstream, source, query, page):
    if source == 'tx':
        request = {'comm': {'ct': 19, 'cv': 1845}, 'req': {
            'module': 'music.search.SearchCgiService', 'method': 'DoSearchForQQMusicDesktop',
            'param': {'query': query, 'num_per_page': 20, 'page_num': page}}}
        payload = await upstream('https://u.y.qq.com/cgi-bin/musicu.fcg?' + urlencode({'data': json.dumps(request)}))
        if not isinstance(payload, dict) or payload.get('code') != 0 or payload.get('req', {}).get('code') != 0:
            raise ValueError('搜索响应异常')
        raw = rows(payload, 'req', 'data', 'body', 'song', 'list')
        return [dict(id=r.get('mid', ''), name=r.get('name', ''),
                     artist=[s.get('name', '') for s in r.get('singer', []) if isinstance(s, dict)],
                     album=r.get('album', {}).get('name', ''), pic_id=r.get('album', {}).get('mid', ''),
                     lyric_id=r.get('mid', ''), duration=r.get('interval', 0))
                for r in raw if isinstance(r, dict)]
    if source == 'kw':
        payload = await upstream('http://search.kuwo.cn/r.s?' + urlencode(dict(
            client='kt', all=query, pn=page - 1, rn=20, ft='music', encoding='utf8',
            rformat='json', vermerge=1, mobi=1)))
        raw = rows(payload, 'abslist')
        return [dict(id=str(r.get('MUSICRID', '')).removeprefix('MUSIC_'),
                     name=unescape(r.get('SONGNAME') or r.get('NAME') or ''),
                     artist=unescape(r.get('ARTIST') or ''), album=unescape(r.get('ALBUM') or ''),
                     duration=r.get('DURATION', 0)) for r in raw if isinstance(r, dict)]
    if source == 'kg':
        payload = await upstream('http://songsearch.kugou.com/song_search_v2?' + urlencode(dict(
            platform='AndroidFilter', iscorrection=1, keyword=query, hifiquality=0,
            pagesize=20, PrivilegeFilter=0, page=page)))
        if not isinstance(payload, dict) or payload.get('error_code') != 0:
            raise ValueError('搜索响应异常')
        raw = rows(payload, 'data', 'lists')
        return [dict(id=r.get('FileHash', ''), name=unescape(r.get('OriSongName') or r.get('SongName') or ''),
                     artist=unescape(r.get('SingerName') or ''), album=unescape(r.get('AlbumName') or ''),
                     lyric_id=r.get('FileHash', ''), duration=r.get('Duration', 0))
                for r in raw if isinstance(r, dict)]
    if source == 'mg':
        payload = await upstream('https://app.c.nf.migu.cn/MIGUM2.0/v1.0/content/search_all.do?' + urlencode(dict(
            isCopyright=1, isCorrect=1, pageNo=page, pageSize=20, sort=0, text=query,
            searchSwitch=json.dumps(dict(song=1, album=0, singer=0, tagSong=0, mvSong=0, songlist=0, bestShow=0)))))
        if not isinstance(payload, dict) or payload.get('code') != '000000':
            raise ValueError('搜索响应异常')
        raw = rows(payload, 'songResultData', 'resultList')
        result = []
        for group in raw:
            for r in (group if isinstance(group, list) else [group]):
                if not isinstance(r, dict):
                    continue
                albums = r.get('albums') or []
                result.append(dict(id=r.get('copyrightId', ''), name=r.get('name', ''),
                    artist=[s.get('name', '') for s in r.get('singers', []) if isinstance(s, dict)],
                    album=albums[0].get('name', '') if albums and isinstance(albums[0], dict) else '',
                    lyric_id=r.get('copyrightId', ''), duration=r.get('duration') or 0))
        return result[:20]
    raise ValueError('未知搜索平台')
