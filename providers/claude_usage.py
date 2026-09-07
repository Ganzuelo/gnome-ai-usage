#!/usr/bin/env python3
"""Read-only Claude usage reader. Never reads or returns credentials or conversations.

Claude Code publishes plan rate limits to its status line on every render. A tiny
writer (claude_statusline.py) keeps the numbers in a local snapshot; this helper
only reads that snapshot, plus the Claude desktop app's own plan-usage history as
a reset-less fallback. It opens no network connection and starts no AI turn.
"""
import argparse
import json
import math
import os
from pathlib import Path

MINUTES = {
    'five_hour': 300,
    'seven_day': 10080,
    'seven_day_opus': 10080,
    'seven_day_sonnet': 10080,
    'seven_day_oauth_apps': 10080,
}
# Buckets rendered in order; each holds up to a primary and a secondary window.
LAYOUT = (
    ('claude', 'Claude', ('five_hour', 'seven_day')),
    ('claude_opus', 'Opus weekly', ('seven_day_opus',)),
    ('claude_sonnet', 'Sonnet weekly', ('seven_day_sonnet',)),
    ('claude_oauth_apps', 'Connected apps weekly', ('seven_day_oauth_apps',)),
)
MAX_SNAPSHOT_BYTES = 1_000_000


def snapshot_path(custom):
    if custom:
        return Path(custom)
    cache = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(cache) / 'agent-pulse' / 'claude.json'


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def percent(window):
    # Status line reports used_percentage; the control protocol reports utilization.
    # Both are already 0-100, so neither is rescaled here.
    for key in ('used_percentage', 'utilization'):
        used = number(window.get(key))
        if used is not None:
            return max(0.0, min(100.0, used))
    return None


def reset(window):
    value = window.get('resets_at')
    seconds = number(value)
    if seconds is not None:
        return seconds
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:  # ISO 8601, with or without a trailing Z.
        from datetime import datetime
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def window_of(limits, key, slot):
    window = limits.get(key)
    if not isinstance(window, dict):
        return None
    used = percent(window)
    if used is None:
        return None
    return {'used': used, 'minutes': MINUTES.get(key), 'reset': reset(window), 'slot': slot}


def normalize(limits, captured, source):
    if not isinstance(limits, dict):
        return None
    output = []
    for identifier, name, keys in LAYOUT:
        windows = []
        for index, key in enumerate(keys):
            window = window_of(limits, key, 'primary' if index == 0 else 'secondary')
            if window:
                windows.append(window)
        if windows:
            output.append({'id': identifier, 'name': name, 'windows': windows})
    scoped = limits.get('model_scoped')
    if isinstance(scoped, list):
        for index, entry in enumerate(scoped):
            if not isinstance(entry, dict):
                continue
            used = percent(entry)
            if used is None:
                continue
            label = entry.get('display_name')
            label = str(label) if isinstance(label, str) and label.strip() else f'Model {index + 1}'
            output.append({
                'id': f'claude_model_{index}',
                'name': f'{label} weekly',
                'windows': [{'used': used, 'minutes': 10080, 'reset': reset(entry), 'slot': 'primary'}],
            })
    if not output:
        return None
    return {'buckets': output, 'updated': int(captured), 'source': source}


def read_snapshot(path):
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise RuntimeError('Unexpected snapshot size.')
        payload = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    captured = number(payload.get('captured'))
    if captured is None:
        return None
    if payload.get('available') is False:
        raise RuntimeError('Plan rate limits do not apply to this Claude session.')
    return normalize(payload.get('rate_limits'), captured, 'statusline')


def read_history(path):
    """Fallback: the Claude desktop app's own plan-usage samples. No reset times."""
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None
        payload = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeError):
        return None
    samples = payload.get('samples') if isinstance(payload, dict) else None
    if not isinstance(samples, list) or not samples:
        return None
    latest = samples[-1]
    if not isinstance(latest, dict):
        return None
    stamp = number(latest.get('t'))
    used = latest.get('u')
    if stamp is None or not isinstance(used, dict):
        return None
    limits = {}
    for key, field in (('fh', 'five_hour'), ('sd', 'seven_day')):
        value = number(used.get(key))
        if value is not None:
            limits[field] = {'used_percentage': value, 'resets_at': None}
    return normalize(limits, stamp / 1000, 'desktop')


def read_usage(snapshot, history):
    live = read_snapshot(snapshot)
    cached = read_history(history)
    if live and cached:
        return live if live['updated'] >= cached['updated'] else cached
    if live or cached:
        return live or cached
    raise RuntimeError('No Claude usage snapshot found.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', default='')
    parser.add_argument('--history', default=str(Path.home() / '.config/Claude/plan-usage-history.json'))
    args = parser.parse_args()
    try:
        data = read_usage(snapshot_path(args.snapshot), Path(args.history))
    except (RuntimeError, OSError):
        # No file contents, environment, or account identifiers leave this helper.
        print(json.dumps({'error': 'Usage unavailable. Add the Claude status line hook, then run Claude Code once.'}))
        return 1
    print(json.dumps(data, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
