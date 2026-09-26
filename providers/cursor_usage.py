#!/usr/bin/env python3
"""Read Cursor plan usage with the active Cursor app session.

Cursor does not publish a stable personal-usage API. This adapter keeps that
unstable boundary in one process: it reads Cursor's access token from the local
state database, sends it only to Cursor's fixed HTTPS origin, and returns only
normalized quota percentages. It never prints or persists the token.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STATE_KEY = 'cursorAuth/accessToken'
USAGE_URL = 'https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage'
LEGACY_URL = 'https://api2.cursor.sh/auth/usage'
MAX_RESPONSE_BYTES = 2_000_000


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            return None
    return None


def percent(value):
    value = number(value)
    return None if value is None else max(0.0, min(100.0, value))


def epoch(value):
    seconds = number(value)
    if seconds is not None:
        return seconds / 1000 if seconds > 10_000_000_000 else seconds
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace('Z', '+00:00')).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def cycle(payload):
    start = epoch(payload.get('billingCycleStart'))
    end = epoch(payload.get('billingCycleEnd'))
    minutes = (end - start) / 60 if start is not None and end is not None and end > start else 43200
    return minutes, end


def window(used, minutes, reset, slot='primary'):
    used = percent(used)
    if used is None:
        return None
    return {'used': used, 'minutes': minutes, 'reset': reset, 'slot': slot}


def normalize_dashboard(payload, captured=None):
    if not isinstance(payload, dict) or payload.get('enabled') is False:
        return None
    plan = payload.get('planUsage')
    if not isinstance(plan, dict):
        return None
    minutes, reset = cycle(payload)
    total = percent(plan.get('totalPercentUsed'))
    if total is None:
        limit = number(plan.get('limit'))
        spent = number(plan.get('totalSpend'))
        if spent is None:
            spent = number(plan.get('includedSpend'))
        if limit is not None and limit > 0 and spent is not None:
            total = percent(spent / limit * 100)
    buckets = []
    for identifier, name, used in (
        ('cursor', 'Cursor', total),
        ('cursor_models', 'Cursor Models', plan.get('autoPercentUsed')),
        ('cursor_other', 'Other Models', plan.get('apiPercentUsed')),
    ):
        item = window(used, minutes, reset)
        if item:
            buckets.append({'id': identifier, 'name': name, 'windows': [item]})
    if not buckets:
        return None
    return {'buckets': buckets, 'updated': int(captured or time.time()), 'source': 'cursor-app'}


def _pair(value):
    if not isinstance(value, dict):
        return None
    used = next((number(value.get(key)) for key in ('numRequests', 'used', 'requests') if number(value.get(key)) is not None), None)
    limit = next((number(value.get(key)) for key in ('maxRequestUsage', 'limit', 'maxRequests', 'requestLimit') if number(value.get(key)) is not None), None)
    if used is not None and limit is not None and limit > 0:
        return used, limit
    remaining = next((number(value.get(key)) for key in ('remainingRequests', 'requestsRemaining', 'requestsLeft') if number(value.get(key)) is not None), None)
    if used is not None and remaining is not None and used + remaining > 0:
        return used, used + remaining
    return None


def normalize_legacy(payload, captured=None):
    if not isinstance(payload, dict):
        return None
    start = epoch(payload.get('startOfMonth'))
    reset = start + 30 * 86400 if start is not None else None
    buckets = []
    seen = set()

    def walk(value, prefix='', depth=0):
        if depth > 3 or not isinstance(value, dict):
            return
        for key, child in value.items():
            if key in {'user', 'team', 'organization', 'metadata', 'subscription', 'plan'} or not isinstance(child, dict):
                continue
            name = f'{prefix} · {key}' if prefix else key
            pair = _pair(child)
            if pair and name not in seen:
                seen.add(name)
                used, limit = pair
                item = window(used / limit * 100, 43200, reset)
                buckets.append({'id': f'cursor_{len(buckets)}', 'name': name, 'windows': [item]})
            elif not pair:
                walk(child, name, depth + 1)

    walk(payload)
    if not buckets:
        return None
    return {'buckets': buckets, 'updated': int(captured or time.time()), 'source': 'cursor-app'}


def state_path(custom):
    path = Path(custom).expanduser() if custom else Path.home() / '.config/Cursor/User/globalStorage/state.vscdb'
    if custom and not path.is_absolute():
        raise RuntimeError('Choose an absolute Cursor state database path in settings.')
    return path


def read_token(path):
    if not path.is_file():
        raise RuntimeError('Cursor state database not found.')
    connection = sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=2)
    try:
        row = connection.execute('SELECT value FROM ItemTable WHERE key = ? LIMIT 1', (STATE_KEY,)).fetchone()
    finally:
        connection.close()
    if not row or not isinstance(row[0], (str, bytes)):
        raise RuntimeError('Cursor is not signed in.')
    token = row[0].decode() if isinstance(row[0], bytes) else row[0]
    if not token.strip():
        raise RuntimeError('Cursor is not signed in.')
    return token.strip()


def request_json(url, token, method='GET', opener=urlopen):
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'User-Agent': 'agent-pulse'}
    data = None
    if method == 'POST':
        data = b'{}'
        headers.update({'Content-Type': 'application/json', 'Connect-Protocol-Version': '1'})
    response = opener(Request(url, data=data, headers=headers, method=method), timeout=14)
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError('Unexpected Cursor response size.')
    return json.loads(body)


def read_usage(path, opener=urlopen):
    token = read_token(path)
    try:
        result = normalize_dashboard(request_json(USAGE_URL, token, 'POST', opener))
        if result:
            return result
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        pass
    result = normalize_legacy(request_json(LEGACY_URL, token, opener=opener))
    if not result:
        raise RuntimeError('Cursor returned no plan quota.')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-db', default='')
    args = parser.parse_args()
    try:
        data = read_usage(state_path(args.state_db))
    except (RuntimeError, OSError, sqlite3.Error, HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        print(json.dumps({'error': 'Usage unavailable. Sign in to the Cursor app, then try again.'}))
        return 1
    print(json.dumps(data, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
