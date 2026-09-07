#!/usr/bin/env python3
"""Claude Code status line hook: keeps a plan-limit snapshot for Agent Pulse.

Claude Code passes this command a JSON session summary on stdin and prints whatever
it writes to stdout in the status line. Only the plan rate-limit numbers are copied
out; no prompt, transcript path, project path, cost, or account identifier is stored.

    claude_statusline.py                 write the snapshot, print a short usage line
    claude_statusline.py --quiet         write the snapshot, print nothing
    claude_statusline.py --wrap "CMD"    write the snapshot, then run CMD on the same
                                         input and print its output instead
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

MAX_INPUT_BYTES = 4_000_000
LABELS = (('five_hour', '5h'), ('seven_day', '7d'))


def snapshot_path(custom):
    if custom:
        return Path(custom)
    cache = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(cache) / 'agent-pulse' / 'claude.json'


def store(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.claude-', suffix='.tmp')
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, 'w') as stream:
            json.dump(payload, stream, allow_nan=False)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def summary(limits):
    parts = []
    for key, label in LABELS:
        window = limits.get(key) if isinstance(limits, dict) else None
        if not isinstance(window, dict):
            continue
        for field in ('used_percentage', 'utilization'):
            used = window.get(field)
            if isinstance(used, (int, float)) and not isinstance(used, bool):
                parts.append(f'{label} {round(max(0, min(100, used)))}%')
                break
    return ' · '.join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', default='')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--wrap', default='')
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES)
    limits = None
    try:
        session = json.loads(raw)
        if not isinstance(session, dict):
            raise ValueError('Unexpected status line input.')
        limits = session.get('rate_limits')
        store(snapshot_path(args.snapshot), {
            'captured': int(time.time()),
            'available': session.get('rate_limits_available', limits is not None),
            'rate_limits': limits if isinstance(limits, dict) else None,
        })
    except (ValueError, UnicodeError, OSError):
        pass  # A status line must never break the session it renders in.
    if args.wrap:
        try:
            delegated = subprocess.run(args.wrap, shell=True, input=raw, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, timeout=5)
            sys.stdout.buffer.write(delegated.stdout)
            return 0
        except (OSError, subprocess.SubprocessError):
            return 0
    if not args.quiet:
        print(summary(limits), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
