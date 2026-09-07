import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const PROVIDERS = [
    {id: 'codex', name: 'Codex', supported: true},
    {id: 'claude', name: 'Claude', supported: true},
];

const FAILURES = {
    codex: 'Usage unavailable. Check Codex login, path, and connection.',
    claude: 'Usage unavailable. Add the Claude status line hook, then run Claude Code once.',
};

function run(argv, failure) {
    const process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
    let timeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 32, () => {
        timeout = 0;
        process.send_signal(15);
        return GLib.SOURCE_REMOVE;
    });
    const promise = new Promise((resolve, reject) => {
        process.communicate_utf8_async(null, null, (proc, result) => {
            if (timeout) GLib.Source.remove(timeout);
            timeout = 0;
            try {
                const [, stdout] = proc.communicate_utf8_finish(result);
                const data = JSON.parse(stdout);
                if (!proc.get_successful() || data.error) throw new Error(data.error || 'Usage unavailable');
                resolve(data);
            } catch (_) {
                reject(new Error(failure));
            }
        });
    });
    return {promise, cancel() { process.send_signal(15); }};
}

export function readCodex(path, binary) {
    return run(['python3', `${path}/providers/codex_usage.py`, '--codex-path', binary], FAILURES.codex);
}

export function readClaude(path, snapshot) {
    return run(['python3', `${path}/providers/claude_usage.py`, '--snapshot', snapshot], FAILURES.claude);
}

// Each provider owns an independent adapter; the controller only dispatches.
export function readProvider(id, path, settings) {
    if (id === 'codex') return readCodex(path, settings.get_string('codex-path'));
    if (id === 'claude') return readClaude(path, settings.get_string('claude-snapshot-path'));
    return null;
}

export const PROVIDER_FAILURE = id => FAILURES[id] || 'Usage unavailable.';
