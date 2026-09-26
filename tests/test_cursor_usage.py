import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cursor_usage', ROOT / 'providers/cursor_usage.py')
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self, _size):
        return self.payload


class CursorUsageTests(unittest.TestCase):
    def test_dashboard_maps_total_and_split_pools(self):
        result = usage.normalize_dashboard({
            'billingCycleStart': 1_788_134_400_000,
            'billingCycleEnd': 1_790_812_800_000,
            'planUsage': {'totalPercentUsed': 42.5, 'autoPercentUsed': 11, 'apiPercentUsed': 72},
        }, captured=123)
        self.assertEqual([bucket['name'] for bucket in result['buckets']], ['Cursor', 'Cursor Models', 'Other Models'])
        self.assertEqual([bucket['windows'][0]['used'] for bucket in result['buckets']], [42.5, 11, 72])
        self.assertEqual(result['buckets'][0]['windows'][0]['reset'], 1_790_812_800)
        self.assertEqual(result['updated'], 123)

    def test_dashboard_derives_total_from_spend_and_clamps(self):
        result = usage.normalize_dashboard({'planUsage': {'totalSpend': 150, 'limit': 100}})
        self.assertEqual(result['buckets'][0]['windows'][0]['used'], 100)

    def test_missing_values_are_not_zero(self):
        self.assertIsNone(usage.normalize_dashboard({'planUsage': {}}))
        self.assertIsNone(usage.normalize_dashboard({'enabled': False, 'planUsage': {'totalPercentUsed': 4}}))
        self.assertIsNone(usage.normalize_dashboard({'planUsage': {'totalPercentUsed': 'nope'}}))

    def test_legacy_request_quota_is_normalized(self):
        result = usage.normalize_legacy({
            'startOfMonth': '2026-09-01T00:00:00Z',
            'gpt-4': {'numRequests': 125, 'maxRequestUsage': 500},
        }, captured=7)
        self.assertEqual(result['buckets'][0]['windows'][0]['used'], 25)
        self.assertEqual(result['buckets'][0]['name'], 'gpt-4')
        self.assertEqual(result['buckets'][0]['windows'][0]['reset'], 1788220800 + 30 * 86400)

    def test_iso_billing_cycle_sets_reset_and_length(self):
        result = usage.normalize_dashboard({
            'billingCycleStart': '2026-09-01T00:00:00Z',
            'billingCycleEnd': '2026-10-01T00:00:00Z',
            'planUsage': {'totalPercentUsed': 12},
        }, captured=7)
        window = result['buckets'][0]['windows'][0]
        self.assertEqual((window['minutes'], window['reset']), (43200, 1790812800))

    def test_reads_only_cursor_token_and_sends_it_only_to_fixed_usage_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'state.vscdb'
            connection = sqlite3.connect(database)
            connection.execute('CREATE TABLE ItemTable (key TEXT, value TEXT)')
            connection.execute('INSERT INTO ItemTable VALUES (?, ?)', (usage.STATE_KEY, 'secret-token'))
            connection.commit()
            connection.close()
            calls = []

            def opener(request, timeout):
                calls.append((request.full_url, request.get_header('Authorization'), request.method, timeout))
                return Response({'planUsage': {'totalPercentUsed': 30}})

            result = usage.read_usage(database, opener=opener)
            self.assertEqual(result['buckets'][0]['windows'][0]['used'], 30)
            self.assertEqual(calls, [(usage.USAGE_URL, 'Bearer secret-token', 'POST', 14)])
            self.assertNotIn('secret-token', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
