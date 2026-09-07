#!/usr/bin/env python3
"""Read-only Codex RPC client. Never reads or returns credentials or conversations."""
import argparse
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time


def normalize(result):
    buckets = result.get('rateLimitsByLimitId')
    if not isinstance(buckets, dict) or not buckets:
        legacy = result.get('rateLimits')
        buckets = {'codex': legacy} if isinstance(legacy, dict) else {}
    output = []
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        windows = []
        for slot in ('primary', 'secondary'):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            used = window.get('usedPercent')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
                continue
            duration = window.get('windowDurationMins')
            duration = duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0 else None
            reset = window.get('resetsAt')
            reset = reset if isinstance(reset, (int, float)) and not isinstance(reset, bool) and math.isfinite(reset) else None
            windows.append({'used': max(0, min(100, used)), 'minutes': duration, 'reset': reset, 'slot': slot})
        if windows:
            output.append({'id': str(key), 'name': str(bucket.get('limitName') or key), 'windows': windows})
    output.sort(key=lambda bucket: bucket['id'] != 'codex')
    return {'buckets': output, 'updated': int(time.time())}


def executable(custom):
    if custom:
        path = Path(custom)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError('Choose an executable absolute Codex path in settings.')
        return str(path)
    for candidate in (shutil.which('codex'), str(Path.home() / '.local/bin/codex')):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError('Codex CLI not found. Set its executable path in settings.')


def read_usage(binary, timeout=25):
    # Own process group: cancellation only terminates the server we started.
    proc = subprocess.Popen([binary, 'app-server', '--listen', 'stdio://'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    def stop(*_):
        raise InterruptedError('Usage check cancelled.')
    old = signal.signal(signal.SIGTERM, stop)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    buffer = b''
    def send(payload):
        proc.stdin.write((json.dumps(payload) + '\n').encode())
        proc.stdin.flush()
    def receive(wanted):
        nonlocal buffer
        while time.monotonic() < deadline:
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if message.get('id') == wanted:
                    if 'error' in message:
                        raise RuntimeError('Codex could not read usage. Check your Codex login and connection.')
                    return message.get('result', {})
                if 'id' in message and 'method' in message:
                    send({'id': message['id'], 'error': {'code': -32601, 'message': 'Usage-only client'}})
            if not selector.select(max(0, deadline - time.monotonic())):
                break
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('Codex app server exited before returning usage.')
            buffer += chunk
            if len(buffer) > 2_000_000:
                raise RuntimeError('Unexpected Codex response size.')
        raise RuntimeError('Codex usage check timed out. Last known values are preserved.')
    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'agent_pulse', 'title': 'Agent Pulse', 'version': '0.1.0'}}})
        receive(1)
        send({'method': 'initialized'})
        send({'id': 2, 'method': 'account/rateLimits/read'})
        return normalize(receive(2))
    finally:
        selector.close()
        signal.signal(signal.SIGTERM, old)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        except ProcessLookupError:
            proc.wait()
        for stream in (proc.stdin, proc.stdout):
            stream.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex-path', default='')
    args = parser.parse_args()
    try:
        data = read_usage(executable(args.codex_path))
    except (RuntimeError, OSError, InterruptedError):
        # No raw RPC errors, environment, tokens, or subprocess logs leave this helper.
        print(json.dumps({'error': 'Usage unavailable. Check Codex login, executable path, and network connection.'}))
        return 1
    print(json.dumps(data, allow_nan=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
