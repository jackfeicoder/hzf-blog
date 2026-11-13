"""No live billing calls: disposable snapshots and mocked read-only API pages."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import auth
import cdt_usage as cdt
from database import Base, get_db
import models
from routers import visitors


def bill(usage='0.24287', region='华北2（北京）', **extra):
    return {'BillingItemCode': 'internet_traffic', 'Region': region, 'Usage': usage, 'UsageUnit': 'GB', **extra}


class CdtUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'usage.json'
        self.now = datetime(2026, 11, 13, 5, 30, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def success(self, now=None, amount=Decimal('0.24287'), force=False):
        return cdt.sync(self.path, now or self.now, force=force, credential_loader=lambda: {}, fetcher=lambda *args: amount)

    def test_read_never_calls_api_and_missing_data_is_not_zero(self):
        with patch.object(cdt, 'credentials', side_effect=AssertionError('network forbidden')):
            result = cdt.cached_usage(self.path, self.now)
        self.assertIsNone(result['used_gb'])
        self.assertEqual(result['status'], 'pending')
        self.assertFalse(self.path.exists())

    def test_success_survives_restart_and_preserves_decimal_usage(self):
        self.assertEqual(self.success(), 'ok')
        data = cdt.cached_usage(self.path, self.now)
        self.assertEqual(data['used_gb'], .24287)
        self.assertEqual(data['billing_cycle'], '2026-11')
        self.assertEqual(data['quota_gb'], 20)
        self.assertEqual(data['status'], 'ready')
        self.assertNotIn('AccessKey', self.path.read_text())

    def test_once_per_china_day_and_force_is_explicit(self):
        self.success()
        loader = Mock(side_effect=AssertionError('second daily call'))
        result = cdt.sync(self.path, self.now + timedelta(hours=2), credential_loader=loader)
        self.assertEqual(result, 'already_synced_today')
        loader.assert_not_called()
        self.assertEqual(self.success(self.now + timedelta(hours=17)), 'ok')
        self.assertEqual(self.success(self.now + timedelta(hours=18), force=True), 'ok')

    def test_failures_keep_last_value_and_month_rollover_hides_old_usage(self):
        self.success()
        def denied():
            raise cdt.BillingError('permission_denied')
        result = cdt.sync(self.path, self.now + timedelta(days=1), credential_loader=denied)
        self.assertEqual(result, 'permission_denied')
        data = cdt.cached_usage(self.path, self.now + timedelta(days=1))
        self.assertEqual(data['used_gb'], .24287)
        self.assertEqual(data['status'], 'stale')
        data = cdt.cached_usage(self.path, datetime(2026, 11, 30, 16, tzinfo=timezone.utc))
        self.assertEqual(data['billing_cycle'], '2026-12')
        self.assertIsNone(data['used_gb'])

    def test_unconfigured_corrupt_cache_and_invalid_values_fail_closed(self):
        def missing():
            raise cdt.BillingError('credentials_missing')
        cdt.sync(self.path, self.now, credential_loader=missing)
        self.assertEqual(cdt.cached_usage(self.path, self.now)['status'], 'unconfigured')
        self.path.write_text('{broken')
        self.assertIsNone(cdt.cached_usage(self.path, self.now)['used_gb'])
        for value in ('NaN', 'Infinity', '-1'):
            cdt.save_snapshot({'used_gb': value, 'updated_at': self.now.isoformat(), 'billing_cycle': '2026-11'}, self.path)
            self.assertIsNone(cdt.cached_usage(self.path, self.now)['used_gb'])

    def test_mainland_all_instances_free_and_paid_rows_are_summed(self):
        rows = [bill('1'), bill('2', 'cn-shanghai'), bill('.5', '杭州'),
                bill('99', 'cn-hongkong'), bill('8', 'ap-southeast-1'),
                bill('7', BillingItemCode='inter_region_traffic'), bill('6', InstanceConfig='精品BGP')]
        self.assertEqual(cdt.sum_usage(rows), Decimal('3.5'))
        self.assertEqual(cdt.sum_usage([bill('21')]), Decimal('21'))
        self.assertEqual(cdt.sum_usage([bill('0')]), Decimal('0'))
        for row in (bill(region='unknown'), bill(UsageUnit='MB'), bill(usage='NaN'), bill(BillingItemCode='unknown')):
            with self.assertRaises(cdt.BillingError):
                cdt.sum_usage([row])
        with self.assertRaises(cdt.BillingError):
            cdt.sum_usage([])

    def test_pagination_keeps_zero_charge_rows_and_uses_cdt_filter(self):
        loader = Mock(side_effect=[{'Items': [bill('1')], 'NextToken': 'page2'}, {'Items': [bill('2')]}])
        self.assertEqual(cdt.fetch_month(self.now, {}, loader), Decimal('3'))
        first, second = [call.args[0] for call in loader.call_args_list]
        self.assertEqual(first['ProductCode'], 'cdt')
        self.assertEqual(first['IsBillingItem'], 'true')
        self.assertEqual(first['IsHideZeroCharge'], 'false')
        self.assertEqual(second['NextToken'], 'page2')
        with self.assertRaises(cdt.BillingError):
            cdt.fetch_month(self.now, {}, lambda *args: {'Items': [], 'NextToken': 'loop'})

    def test_signing_uses_read_only_action_and_never_transmits_secret(self):
        credential = {'AccessKeyId': 'fixture-id', 'AccessKeySecret': 'fixture-secret-do-not-send', 'SecurityToken': 'fixture-token'}
        body = cdt.signed_body({'Action': 'PurchaseSomething', 'ProductCode': 'cdt'}, credential, self.now)
        parsed = parse_qs(body.decode())
        self.assertEqual(parsed['Action'], ['DescribeInstanceBill'])
        self.assertEqual(parsed['SecurityToken'], ['fixture-token'])
        self.assertIn('Signature', parsed)
        self.assertNotIn(credential['AccessKeySecret'].encode(), body)

    def test_metadata_uses_imdsv2_and_errors_are_sanitized(self):
        credentials = {'Code': 'Success', 'AccessKeyId': 'id', 'AccessKeySecret': 'secret', 'SecurityToken': 'token'}
        replies = [BytesIO(b'metadata-token'), BytesIO(b'BlogBillingRole'), BytesIO(json.dumps(credentials).encode())]
        with patch.dict('os.environ', {}, clear=True), patch.object(cdt.OPENER, 'open', side_effect=replies) as opener:
            self.assertEqual(cdt.credentials()['AccessKeyId'], 'id')
            self.assertEqual(opener.call_args_list[0].args[0].get_method(), 'PUT')
            self.assertTrue(all(call.args[0].full_url.startswith(cdt.METADATA) for call in opener.call_args_list))
        error = HTTPError(cdt.ENDPOINT, 403, 'private-provider-message', {}, None)
        with patch.object(cdt.OPENER, 'open', side_effect=error):
            with self.assertRaisesRegex(cdt.BillingError, '^permission_denied$'):
                cdt.query_page({}, {'AccessKeyId': 'id', 'AccessKeySecret': 'secret'})

    @unittest.skipIf(os.name == 'nt', 'File locking is exercised on the Linux deployment host')
    def test_overlapping_sync_jobs_do_not_query_twice(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set(); release.wait(2); return Decimal('1')
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(cdt.sync, self.path, self.now, False, lambda: {}, slow)
            self.assertTrue(entered.wait(2))
            try:
                second = cdt.sync(self.path, self.now, credential_loader=lambda: {}, fetcher=slow)
                self.assertEqual(second, 'busy')
            finally:
                release.set()
            self.assertEqual(first.result(), 'ok')


class CdtPermissionsTests(unittest.TestCase):
    def test_only_owner_reads_cached_snapshot_without_network(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add_all([models.User(username=name, password_hash='unused') for name in ('jackfei', 'reader')]); db.commit()
        app = FastAPI(); app.include_router(visitors.router)
        def override():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = override
        with TestClient(app) as client, patch.object(visitors, 'cached_usage', return_value={'used_gb': .24287, 'quota_gb': 20}) as cache:
            self.assertEqual(client.get('/api/visitors/traffic').status_code, 401)
            self.assertEqual(client.get('/api/visitors/traffic', headers={'Authorization': 'Bearer ' + auth.create_access_token('reader')}).status_code, 403)
            cache.assert_not_called()
            response = client.get('/api/visitors/traffic', headers={'Authorization': 'Bearer ' + auth.create_access_token('jackfei')})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['used_gb'], .24287)
            self.assertIn('no-store', response.headers['cache-control'])
        engine.dispose()
