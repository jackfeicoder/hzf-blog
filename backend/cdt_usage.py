"""Read-only CDT public traffic sync. Never infer traffic from billing usage."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

CHINA = timezone(timedelta(hours=8))
CACHE = Path(os.getenv('CDT_USAGE_CACHE', str(Path(__file__).parent / '.runtime/cdt-usage.json')))
QUOTA = 20
ENDPOINT = 'https://cdt.aliyuncs.com/'
SOURCE = 'cdt-public-traffic-v1'
METADATA = 'http://100.100.100.200/latest/'
ERRORS = frozenset(('credentials_missing', 'permission_denied', 'api_error', 'network_error', 'unsupported_traffic_data', 'data_unavailable'))


class BillingError(Exception):
    """Only safe, fixed error codes reach logs or the browser."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def cycle(now):
    return now.astimezone(CHINA).strftime('%Y-%m')


def read_snapshot(path=CACHE):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_snapshot(value, path=CACHE):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'w', encoding='utf-8') as file:
        os.chmod(temporary, 0o600)
        json.dump(value, file, ensure_ascii=False)
        file.flush(); os.fsync(file.fileno())
    os.replace(temporary, path)


def cached_usage(path=CACHE, now=None):
    now = now or datetime.now(timezone.utc)
    saved = read_snapshot(path)
    error = saved.get('error_code')
    error = error if isinstance(error, str) and error in ERRORS else None
    data = {'billing_cycle': cycle(now), 'used_gb': None, 'quota_gb': QUOTA,
            'updated_at': None, 'status': 'pending', 'error_code': error,
            'sync_schedule': '每天北京时间13:30', 'data_source': SOURCE}
    try:
        amount = Decimal(saved['used_gb'])
        updated = datetime.fromisoformat(saved['updated_at'])
        if saved.get('data_source') == SOURCE and saved.get('billing_cycle') == cycle(now) and amount.is_finite() and amount >= 0 and updated.tzinfo:
            data.update(used_gb=float(amount), updated_at=saved['updated_at'], status='ready')
            if saved.get('error_code') or now - updated > timedelta(hours=40):
                data['status'] = 'stale'
    except (KeyError, ValueError, TypeError, InvalidOperation):
        pass
    if data['used_gb'] is None and saved.get('error_code') == 'credentials_missing':
        data['status'] = 'unconfigured'
    elif data['used_gb'] is None and saved.get('error_code'):
        data['status'] = 'error'
    return data


def credentials():
    key = os.getenv('CDT_ACCESS_KEY_ID')
    secret = os.getenv('CDT_ACCESS_KEY_SECRET')
    if key or secret:
        if not key or not secret:
            raise BillingError('credentials_missing')
        return {'AccessKeyId': key, 'AccessKeySecret': secret, 'SecurityToken': os.getenv('CDT_SECURITY_TOKEN', '')}
    try:
        request = Request(METADATA + 'api/token', method='PUT', headers={'X-aliyun-ecs-metadata-token-ttl-seconds': '60'})
        with OPENER.open(request, timeout=3) as response:
            token = response.read(4096).decode().strip()
        headers = {'X-aliyun-ecs-metadata-token': token}
        with OPENER.open(Request(METADATA + 'meta-data/ram/security-credentials/', headers=headers), timeout=3) as response:
            role = response.read(4096).decode().strip()
        if not re.fullmatch(r'[A-Za-z0-9.@_-]{1,128}', role):
            raise BillingError('credentials_missing')
        with OPENER.open(Request(METADATA + 'meta-data/ram/security-credentials/' + quote(role, safe=''), headers=headers), timeout=3) as response:
            data = json.loads(response.read(65536))
        if not isinstance(data, dict) or data.get('Code') != 'Success' or not all(data.get(k) for k in ('AccessKeyId', 'AccessKeySecret', 'SecurityToken')):
            raise BillingError('credentials_missing')
        return data
    except (OSError, URLError, ValueError):
        raise BillingError('credentials_missing') from None


def signed_body(params, credential, now=None):
    now = now or datetime.now(timezone.utc)
    values = {**params, 'Action': 'ListCdtInternetTraffic', 'Version': '2021-08-13', 'Format': 'JSON',
              'AccessKeyId': credential['AccessKeyId'], 'SignatureMethod': 'HMAC-SHA1', 'SignatureVersion': '1.0',
              'SignatureNonce': uuid.uuid4().hex, 'Timestamp': now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    if credential.get('SecurityToken'):
        values['SecurityToken'] = credential['SecurityToken']
    encode = lambda value: quote(str(value), safe='-_.~')
    canonical = '&'.join(encode(k) + '=' + encode(values[k]) for k in sorted(values))
    signing = 'POST&%2F&' + encode(canonical)
    values['Signature'] = base64.b64encode(hmac.new((credential['AccessKeySecret'] + '&').encode(), signing.encode(), hashlib.sha1).digest()).decode()
    return urlencode(values).encode()


def query_page(params, credential):
    request = Request(ENDPOINT, data=signed_body(params, credential), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with OPENER.open(request, timeout=10) as response:
            result = json.loads(response.read(4 * 1024 * 1024))
    except HTTPError as error:
        raise BillingError('permission_denied' if error.code in (401, 403) else 'api_error') from None
    except (OSError, URLError, ValueError):
        raise BillingError('network_error') from None
    if not isinstance(result, dict):
        raise BillingError('api_error')
    if result.get('Success') is False or result.get('Code') not in (None, 'Success', '200'):
        code = str(result.get('Code', '')).lower()
        raise BillingError('permission_denied' if any(v in code for v in ('forbidden', 'denied', 'permission')) else 'api_error')
    return result


def mainland(row):
    region = str(row.get('Region') or '')
    detail = region + ' ' + str(row.get('InstanceConfig') or '') + ' ' + str(row.get('InstanceID') or '')
    code = re.search(r'\b(cn-[a-z0-9-]+)\b', detail, re.I)
    if code:
        return code[1].lower() not in ('cn-hongkong', 'cn-macau', 'cn-taipei', 'cn-taiwan')
    if any(word in region for word in ('香港', '澳门', '台湾', '新加坡', '美国', '日本', '德国', '英国', '韩国', '印度', '澳大利亚', '马来西亚', '印度尼西亚', '菲律宾', '泰国', '阿联酋', '沙特')):
        return False
    if re.search(r'\b(?:ap|us|eu|me|sa|af|na)-[a-z]', region, re.I):
        return False
    if any(city in region for city in ('北京', '上海', '杭州', '深圳', '青岛', '张家口', '呼和浩特', '乌兰察布', '河源', '广州', '成都', '南京', '福州', '武汉', '济南', '合肥', '天津', '重庆')):
        return True
    raise BillingError('unsupported_traffic_data')


def sum_usage(rows):
    """Sum top-level mainland BGP byte totals, not duplicated tier/product data."""
    amount, matched, seen = Decimal(0), 0, set()
    for row in rows:
        region = row.get('BusinessRegionId')
        isp = row.get('ISPType')
        if not isinstance(region, str) or not isinstance(isp, str):
            raise BillingError('unsupported_traffic_data')
        if not mainland({'Region': region}):
            continue
        if isp.lower() != 'bgp':
            continue
        identity = (region.lower(), isp.lower())
        if identity in seen:
            raise BillingError('unsupported_traffic_data')
        seen.add(identity)
        try:
            value = Decimal(str(row['Traffic']))
        except (KeyError, InvalidOperation, ValueError):
            raise BillingError('unsupported_traffic_data') from None
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise BillingError('unsupported_traffic_data')
        amount += value
        matched += 1
    if not matched:
        raise BillingError('data_unavailable')
    return amount / Decimal(1024 ** 3)


def fetch_month(now, credential, page_loader=query_page):
    # The CDT endpoint returns current-month counters for all regions/products.
    page = page_loader({}, credential)
    items = page.get('TrafficDetails')
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items) or page.get('NextToken'):
        raise BillingError('unsupported_traffic_data')
    return sum_usage(items)


def sync(path=CACHE, now=None, force=False, credential_loader=credentials, fetcher=fetch_month):
    now = now or datetime.now(timezone.utc)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path.with_suffix('.lock'), 'a') as lock:
        os.chmod(lock.name, 0o600)
        if os.name != 'nt':
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 'busy'
        saved = read_snapshot(path)
        if not force:
            try:
                if saved.get('data_source') == SOURCE and datetime.fromisoformat(saved['last_attempt_at']).astimezone(CHINA).date() == now.astimezone(CHINA).date():
                    return 'already_synced_today'
            except (KeyError, TypeError, ValueError):
                pass
        try:
            amount = fetcher(now, credential_loader())
            if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
                raise BillingError('unsupported_traffic_data')
            saved.update(billing_cycle=cycle(now), used_gb=str(amount), updated_at=now.isoformat(), error_code=None, data_source=SOURCE)
        except BillingError as error:
            saved['error_code'] = str(error) if str(error) in ERRORS else 'api_error'
        saved['last_attempt_at'] = now.isoformat()
        save_snapshot(saved, path)
        return saved.get('error_code') or 'ok'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--force', action='store_true'); args = parser.parse_args()
    result = sync(force=args.force)
    print(json.dumps({'cdt_sync': result}))
