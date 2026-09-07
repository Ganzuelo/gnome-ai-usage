import importlib.util
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / 'providers/claude_statusline.py'

spec = importlib.util.spec_from_file_location('claude_usage', ROOT / 'providers/claude_usage.py')
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)


def write(path, payload):
    path.write_text(json.dumps(payload))
    return path


class NormalizeTests(unittest.TestCase):
    def test_session_and_weekly_share_one_bucket(self):
        result = usage.normalize({'five_hour': {'used_percentage': 44.2, 'resets_at': 1788630000},
                                  'seven_day': {'used_percentage': 5, 'resets_at': '2026-09-12T10:00:00Z'}}, 1788615072, 'statusline')
        self.assertEqual([b['id'] for b in result['buckets']], ['claude'])
        session, weekly = result['buckets'][0]['windows']
        self.assertEqual((session['used'], session['minutes'], session['slot']), (44.2, 300, 'primary'))
        self.assertEqual((weekly['minutes'], weekly['slot']), (10080, 'secondary'))
        self.assertEqual(session['reset'], 1788630000)
        self.assertEqual(weekly["reset"], datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc).timestamp())

    def test_model_windows_become_their_own_buckets(self):
        result = usage.normalize({'seven_day_opus': {'utilization': 61, 'resets_at': None},
                                  'seven_day_sonnet': {'utilization': 12, 'resets_at': None},
                                  'model_scoped': [{'display_name': 'Fable', 'utilization': 3, 'resets_at': None}]},
                                 1788615072, 'statusline')
        self.assertEqual([b['name'] for b in result['buckets']],
                         ['Opus weekly', 'Sonnet weekly', 'Fable weekly'])
        self.assertTrue(all(w['minutes'] == 10080 for b in result['buckets'] for w in b['windows']))

    def test_unavailable_is_never_reported_as_zero(self):
        for value in (None, True, 'seventy', float('nan'), float('inf')):
            self.assertIsNone(usage.normalize({'five_hour': {'utilization': value}}, 1, 'statusline'))
        self.assertIsNone(usage.normalize({'five_hour': None, 'model_scoped': [{'display_name': 'Fable'}]}, 1, 'statusline'))
        self.assertIsNone(usage.normalize({}, 1, 'statusline'))
        self.assertIsNone(usage.normalize('limits', 1, 'statusline'))

    def test_percentages_are_clamped_not_rescaled(self):
        windows = usage.normalize({'five_hour': {'used_percentage': 140}}, 1, 'statusline')['buckets'][0]['windows']
        self.assertEqual(windows[0]['used'], 100)
        self.assertEqual(usage.normalize({'five_hour': {'utilization': 0.5}}, 1, 'statusline')['buckets'][0]['windows'][0]['used'], 0.5)


class SourceTests(unittest.TestCase):
    def test_status_line_snapshot_wins_when_it_is_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = write(Path(tmp) / 'claude.json', {'captured': 2000, 'available': True,
                                                         'rate_limits': {'five_hour': {'used_percentage': 30, 'resets_at': 9}}})
            history = write(Path(tmp) / 'history.json', {'samples': [{'t': 1000_000, 'u': {'fh': 44, 'sd': 5}}]})
            self.assertEqual(usage.read_usage(snapshot, history)['source'], 'statusline')

    def test_desktop_history_covers_a_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = write(Path(tmp) / 'claude.json', {'captured': 500, 'available': True,
                                                         'rate_limits': {'five_hour': {'used_percentage': 30, 'resets_at': 9}}})
            history = write(Path(tmp) / 'history.json', {'samples': [{'t': 900_000, 'u': {'fh': 44, 'sd': 5}}]})
            result = usage.read_usage(snapshot, history)
            self.assertEqual((result['source'], result['updated']), ('desktop', 900))
            self.assertIsNone(result['buckets'][0]['windows'][0]['reset'])

    def test_missing_and_unusable_sources_raise_rather_than_invent(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'absent.json'
            with self.assertRaises(RuntimeError):
                usage.read_usage(missing, missing)
            broken = Path(tmp) / 'broken.json'
            broken.write_text('{not json')
            with self.assertRaises(RuntimeError):
                usage.read_usage(broken, broken)
            api_key = write(Path(tmp) / 'claude.json', {'captured': 2000, 'available': False, 'rate_limits': None})
            with self.assertRaises(RuntimeError):
                usage.read_usage(api_key, missing)

    def test_helper_reports_a_generic_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, str(ROOT / 'providers/claude_usage.py'),
                                   '--snapshot', f'{tmp}/none.json', '--history', f'{tmp}/none.json'],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 1)
            self.assertEqual(list(json.loads(done.stdout)), ['error'])


class StatusLineTests(unittest.TestCase):
    def run_writer(self, payload, *arguments, text=None):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / 'nested' / 'claude.json'
            done = subprocess.run([sys.executable, str(WRITER), '--snapshot', str(snapshot), *arguments],
                                  input=payload if text else json.dumps(payload), capture_output=True, text=True)
            stored = json.loads(snapshot.read_text()) if snapshot.exists() else None
            mode = stat.S_IMODE(snapshot.stat().st_mode) if snapshot.exists() else None
            return done, stored, mode

    def test_only_rate_limits_are_stored(self):
        done, stored, mode = self.run_writer({
            'rate_limits_available': True,
            'rate_limits': {'five_hour': {'used_percentage': 44.2, 'resets_at': 1788630000},
                            'seven_day': {'used_percentage': 5.1, 'resets_at': 1789000000}},
            'session': {'total_cost_usd': 1.23}, 'transcript_path': '/home/user/.claude/projects/a.jsonl',
            'workspace': {'current_dir': '/home/user/secret-project'}})
        self.assertEqual(sorted(stored), ['available', 'captured', 'rate_limits'])
        self.assertNotIn('secret-project', json.dumps(stored))
        self.assertNotIn('transcript', json.dumps(stored))
        self.assertEqual(mode, 0o600)
        self.assertEqual(done.stdout, '5h 44% · 7d 5%')

    def test_api_key_sessions_record_that_limits_do_not_apply(self):
        _, stored, _ = self.run_writer({'rate_limits_available': False, 'rate_limits': None})
        self.assertEqual((stored['available'], stored['rate_limits']), (False, None))

    def test_broken_input_never_breaks_the_status_line(self):
        done, stored, _ = self.run_writer('not json at all', text=True)
        self.assertEqual((done.returncode, done.stdout, stored), (0, '', None))

    def test_wrap_delegates_to_an_existing_status_line(self):
        done, stored, _ = self.run_writer({'rate_limits_available': True,
                                           'rate_limits': {'five_hour': {'used_percentage': 7, 'resets_at': 1}}},
                                          '--wrap', f'{sys.executable} -c "import sys;d=sys.stdin.read();print(len(d)>0 and \'mine\',end=\'\')"')
        self.assertEqual(done.stdout, 'mine')
        self.assertEqual(stored['rate_limits']['five_hour']['used_percentage'], 7)

    def test_quiet_prints_nothing_but_still_records(self):
        done, stored, _ = self.run_writer({'rate_limits_available': True,
                                           'rate_limits': {'five_hour': {'used_percentage': 7, 'resets_at': 1}}}, '--quiet')
        self.assertEqual(done.stdout, '')
        self.assertEqual(stored['available'], True)


if __name__ == '__main__':
    unittest.main()
