"""Read-only public smoke test: recommendation -> direct file GET, no resolve."""
import json
import re
import subprocess
import sys
import time


def read(url, span=None):
    command = ['curl', '--fail', '--silent', '--show-error', '--max-time', '30', '--dump-header', '-']
    if span: command += ['-H', 'Range: ' + span]
    command.append(url)
    data = subprocess.check_output(command)
    status, headers = 0, {}
    while data.startswith(b'HTTP/'):
        head, data = data.split(b'\r\n\r\n', 1)
        lines = head.decode('iso-8859-1').split('\r\n')
        status = int(lines[0].split()[1])
        headers = dict((k.lower(), v.strip()) for k, v in (line.split(':', 1) for line in lines[1:] if ':' in line))
    return status, headers, data


def verify(base, expected_entry=None):
    start = time.monotonic()
    status, _, data = read(base + '/api/music/recommended')
    assert status == 200
    feed = json.loads(data)
    addresses = feed.get('cached_audio', [])
    assert addresses, 'Public cache address index is empty'
    songs = {(song['source'], song['id']): song for song in feed['songs']}
    tested = []
    for item in addresses[:3]:
        assert re.fullmatch(r'/api/music/stream/[a-f0-9]{64}', item['url'])
        song = songs[(item['source'], item['id'])]
        ranges = []
        for span in ('bytes=0-1', 'bytes=262144-524287'):
            begin = time.monotonic()
            status, headers, payload = read(base + item['url'], span)
            assert status == 206, 'Expected range support'
            assert headers.get('x-music-cache') == 'HIT', 'Expected local file cache'
            assert len(payload) == (2 if span == 'bytes=0-1' else 262144)
            ranges.append({'status': status, 'bytes': len(payload), 'seconds': round(time.monotonic() - begin, 3)})
        status, headers, payload = read(base + item['url'] + '?connection=release-20261017', 'bytes=1000000-1262143')
        assert status == 206 and headers.get('x-music-cache') == 'HIT' and len(payload) == 262144
        tested.append({'song': song['name'], 'ranges': ranges})
    status, _, data = read(base + '/music?v=20261017-seek')
    match = re.search(r'src="(/assets/index-[\w-]+\.js)"', data.decode())
    assert status == 200 and match, 'Missing frontend entry'
    entry = match.group(1)
    if expected_entry: assert entry == expected_entry, 'Frontend entry is not the approved build'
    status, _, data = read(base + entry)
    engine = re.search(r'assets/PlayerEngine-[\w-]+\.js', data.decode())
    assert status == 200 and engine
    status, _, data = read(base + '/' + engine.group())
    assert status == 200 and b'?connection=' in data and b'seekRevision' in data, 'Missing recovery implementation'
    print(json.dumps({'songs': len(songs), 'cached_addresses': len(addresses), 'resolve_requests': 0,
                      'tested': tested, 'fresh_connection_ranges': len(tested), 'seconds': round(time.monotonic() - start, 3), 'build': entry}, ensure_ascii=False))


if __name__ == '__main__':
    verify(sys.argv[1] if len(sys.argv) > 1 else 'https://blog.120115.xyz:8443', sys.argv[2] if len(sys.argv) > 2 else None)
