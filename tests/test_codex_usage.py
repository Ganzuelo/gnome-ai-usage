import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('usage', Path(__file__).resolve().parents[1] / 'providers/codex_usage.py')
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)

class UsageTests(unittest.TestCase):
    def test_multi_bucket_preferred_and_missing_window_not_zero(self):
        result = usage.normalize({'rateLimits': {'primary': {'usedPercent': 99}}, 'rateLimitsByLimitId': {
            'spark': {'primary': {'usedPercent': 12}},
            'codex': {'secondary': {'usedPercent': 58, 'windowDurationMins': 10080, 'resetsAt': 1234}}
        }})
        self.assertEqual([b['id'] for b in result['buckets']], ['codex', 'spark'])
        self.assertEqual(result['buckets'][0]['windows'], [{'used': 58, 'minutes': 10080, 'reset': 1234, 'slot': 'secondary'}])

    def test_legacy_clamp_and_unknown_reset(self):
        windows = usage.normalize({'rateLimits': {'primary': {'usedPercent': 120}}})['buckets'][0]['windows']
        self.assertEqual(windows[0]['used'], 100)
        self.assertIsNone(windows[0]['reset'])

    def test_invalid_and_unavailable_are_not_zero(self):
        for value in (None, True, '25', float('nan'), float('inf')):
            self.assertEqual(usage.normalize({'rateLimits': {'primary': {'usedPercent': value}}})['buckets'], [])
        self.assertEqual(usage.normalize({})['buckets'], [])

    def test_rpc_handshake_and_only_usage_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / 'codex'
            server.write_text('''#!/usr/bin/env python3
import json,sys
first=json.loads(sys.stdin.readline())
assert first['method']=='initialize'
print(json.dumps({'id':1,'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
assert json.loads(sys.stdin.readline())['method']=='account/rateLimits/read'
print(json.dumps({'id':2,'result':{'rateLimits':{'primary':{'usedPercent':42}}}}),flush=True)
sys.stdin.read()
''')
            server.chmod(0o755)
            data = usage.read_usage(str(server), timeout=2)
            self.assertEqual(data['buckets'][0]['windows'][0]['used'], 42)

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / 'codex'
            server.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n')
            server.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                usage.read_usage(str(server), timeout=0.1)

if __name__ == '__main__':
    unittest.main()
