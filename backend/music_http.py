"""Bounded HTTP bridge. Connect to inspected IPs, preserving HTTPS hostname checks.

No env proxy, cookies, credentials, private/metadata networks, or unvalidated redirects.
Both script requests and audio streaming use this exact boundary.
"""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin

MAX_BODY = 2 * 1024 * 1024


def target(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url) or '\\' in url:
        raise ValueError('无效地址')
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('仅支持普通 HTTP(S) 地址')
    port = p.port or (443 if p.scheme == 'https' else 80)
    if port != (443 if p.scheme == 'https' else 80):
        raise ValueError('目标端口被限制')
    addresses = sorted({r[4][0] for r in socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast or ipaddress.ip_address(ip).is_reserved for ip in addresses):
        raise ValueError('目标地址被限制')
    return p, port, addresses


def open_http(url, method='GET', headers=None, body=None, timeout=5):
    method = str(method).upper()
    if method not in ('GET', 'POST', 'HEAD'):
        raise ValueError('请求方法被限制')
    clean = {'User-Agent': 'lx-music-desktop/2.0.0', 'Accept-Encoding': 'identity'}
    for k, v in (headers or {}).items():
        if not isinstance(k, str) or not isinstance(v, (str, int, float)):
            raise ValueError('无效请求头')
        if len(k) > 100 or len(str(v)) > 4096 or '\r' in k + str(v) or '\n' in k + str(v):
            raise ValueError('无效请求头')
        if k.lower() not in ('host', 'connection', 'cookie', 'authorization', 'proxy-authorization', 'content-length', 'transfer-encoding', 'accept-encoding'):
            clean[k] = str(v)
    for redirect in range(5):
        p, port, addresses = target(url)
        conn = http.client.HTTPConnection(p.hostname, port, timeout=timeout)
        sock = socket.create_connection((addresses[0], port), timeout=timeout)
        if p.scheme == 'https':
            try:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            except BaseException:
                sock.close()
                raise
        conn.sock = sock
        try:
            conn.request(method, p.path + ('?' + p.query if p.query else ''), body=body, headers=clean)
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                response.close(); conn.close()
                if not location:
                    raise ValueError('跳转缺少地址')
                url = urljoin(url, location)
                if response.status == 303:
                    method, body = 'GET', None
                # Never forward provider tokens or Referer across origins.
                clean = {'User-Agent': clean.get('User-Agent', ''), 'Accept-Encoding': 'identity', **({'Range': clean['Range']} if 'Range' in clean else {})}
                continue
            return response, conn, url
        except BaseException:
            conn.close()
            raise
    raise ValueError('跳转次数超限')


def fetch(url, options=None):
    import json
    from urllib.parse import urlencode
    o = options or {}
    body = o.get('body')
    headers = dict(o.get('headers') or {})
    if o.get('form') is not None:
        body = urlencode(o['form']); headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if isinstance(body, (dict, list)):
        body = json.dumps(body); headers.setdefault('Content-Type', 'application/json')
    if body is not None:
        body = str(body).encode()
        if len(body) > 128 * 1024:
            raise ValueError('请求体过大')
    start = time.monotonic()
    r, c, final = open_http(url, o.get('method', 'GET'), headers, body)
    try:
        pieces, total = [], 0
        while True:
            if time.monotonic() - start > 10:
                raise ValueError('响应超时')
            data = r.read1(min(65536, MAX_BODY + 1 - total))
            if not data:
                break
            pieces.append(data); total += len(data)
            if total > MAX_BODY:
                raise ValueError('响应过大')
        data = b''.join(pieces)
        value = data.decode('utf-8', errors='replace')
        try:
            value = json.loads(value)
        except ValueError:
            pass
        return {'statusCode': r.status, 'headers': dict(r.getheaders()), 'body': value}
    finally:
        r.close(); c.close()
