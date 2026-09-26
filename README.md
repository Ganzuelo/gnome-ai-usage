# Agent Pulse

A focused GNOME top-bar widget for AI subscription usage. A filled bot icon
traced from Lucide opens a compact popup with segmented agent tabs, quota bars, and reset times.
The top-bar percentage is off by default.

Repository: <https://github.com/Ganzuelo/gnome-ai-usage>

Agent Pulse was inspired by the idea behind [Omarchy's Agents panel](https://github.com/basecamp/omarchy/blob/quattro/manual/17-ai.md), then independently implemented for GNOME Shell using GJS, St, and small Python provider adapters. [CodexBar](https://github.com/InledGroup/codexbar-gnome) was also reviewed as a GNOME design reference. Agent Pulse does not include source code from either project and keeps a separate implementation with a deliberately narrow permission scope.

## Status

First development release targeting GNOME Shell 50. Verified in an isolated
GNOME Shell 50.1 session: native popup rendering, live Codex quotas, tab
switching, stale-state retention, and disable cleanup. Preferences construction
also passed a native libadwaita smoke test. Twenty-nine automated Python tests pass.
Codex reads real usage through the installed Codex CLI. Claude reads real plan
limits from Claude Code's status line, falling back to the Claude desktop app's
own usage samples. Cursor reads plan percentages with the active Cursor app
session. No provider displays sample or fabricated usage: an
agent with no readable source stays **not connected**.

## Requirements and installation

- GNOME Shell 50 and Python 3.
- Codex: Codex CLI signed in to a ChatGPT account.
- Claude: Claude Code (terminal or desktop app) signed in to a Claude account,
  plus the one-line status line setting below.
- Cursor: Cursor signed in through the desktop app. Its personal-usage endpoint
  is not a stable, documented third-party API; see the Cursor section below.
- No Node, Homebrew, API key, browser-cookie importer, or background service.

```sh
bash scripts/package.sh
gnome-extensions install dist/gnome-agent-pulse.shell-extension.zip
```

Log out and back in if GNOME has not discovered the newly installed extension.
Then enable it:

```sh
gnome-extensions enable agent-pulse@community
gnome-extensions prefs agent-pulse@community
```

Settings include name, optional top-bar percentage, refresh interval, enabled
agents, tab order, default tab, an optional absolute Codex executable path, and
the Claude status line command with an optional snapshot path. Cursor also has
an optional state-database path for nonstandard installations.

### Connecting Claude

Claude Code hands its status line command a JSON session summary on every render,
and that summary carries the plan's rate limit windows. Point the status line at
the bundled writer, which keeps the numbers in
`~/.cache/agent-pulse/claude.json` and prints a compact `5h 44% - 7d 5%` line:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.local/share/gnome-shell/extensions/agent-pulse@community/providers/claude_statusline.py"
  }
}
```

Add it to `~/.claude/settings.json` (the Claude preferences group has a copy
button with the absolute path). Already using a status line? Append
`--wrap "your command"` and yours still renders; `--quiet` leaves it empty.
The snapshot refreshes whenever a Claude Code session renders its status line,
which is every turn you run.
Executable detection uses PATH and `~/.local/bin/codex`. No shell command strings
are evaluated. Limits unavailable on an account are shown as unavailable, not 0%.

## Data and behavior

### Codex

Each poll starts a short-lived `codex app-server --listen stdio://`, completes the
initialization handshake, and calls only `account/rateLimits/read`. It starts no
AI turns, reads no conversations, consumes no reset credits, and requests no
login/logout actions. The Codex CLI owns authentication and may update its own
runtime files or refresh its own credentials as part of normal operation.

### Claude

Each poll reads two local files and opens no network connection: the status line
snapshot above, and — when no session has run recently — the Claude desktop app's
`~/.config/Claude/plan-usage-history.json`, whose samples carry session and weekly
percentages but no reset times, so those windows read "Reset time unavailable"
rather than guessing. The newer of the two sources wins, and the footer marks
desktop-sourced numbers. The status line writer copies out only the rate limit
windows: no prompt, transcript path, project path, cost, or account identifier is
stored, and the snapshot is written `0600` through an atomic replace. A malformed
or missing payload leaves the status line empty rather than breaking the session.

### Cursor

Each poll opens Cursor's local `state.vscdb` read-only, selects only the
`cursorAuth/accessToken` value, and sends it as a bearer token to the fixed
`https://api2.cursor.sh` usage origin. Agent Pulse never saves, displays, logs,
or returns that token. The primary response supplies total monthly usage plus
separate Cursor Models and Other Models percentages; a request-count response
is supported as a fallback for older and enterprise plan shapes.

Cursor documents the dashboard values and monthly reset behavior, but does not
publish the personal endpoint as a stable third-party API. Cursor may change the
route, authentication storage, or response shape. Such a change leaves the last
good snapshot marked stale rather than guessing or showing zero. This adapter
does not refresh or alter Cursor credentials; opening Cursor and signing in
again is the recovery path for an expired session.

The widget does not write login tokens. Raw provider output is
normalized before leaving the helper; no raw server logs are displayed. Quota
snapshots stay in memory and disappear when the extension is disabled.
On a failed poll the last successful data remains visible and is marked stale.
A passed reset time does not automatically zero the bar: a successful refresh is
required. Multi-bucket accounts display each reported quota bucket.

Desktop changes are limited to the extension's panel item, scoped CSS, and its
own GSettings schema: `org.gnome.shell.extensions.agent-pulse`. Disabling it
removes the panel item and polling timer and cancels its pending usage check.
It does not change themes, shortcuts, other extensions, or startup services.
GNOME extensions are not sandboxed; these are code-level boundaries.

## Development

```sh
python3 -m unittest discover -s tests -v
bash scripts/package.sh
```

- `extension.js`: native GNOME popup and lifecycle.
- `prefs.js`: native libadwaita settings.
- `providers/index.js`: provider registry and per-provider subprocess adapters.
- `providers/codex_usage.py`: bounded read-only RPC and normalization.
- `providers/claude_usage.py`: bounded read-only snapshot reader and normalization.
- `providers/claude_statusline.py`: status line writer that records only quota numbers.
- `providers/cursor_usage.py`: read-only Cursor session lookup, bounded HTTPS request, and normalization.
- `schemas/`: extension-owned preferences.

To add a provider, add its registry entry and independent adapter, normalize its
response to `{buckets: [{id, name, windows: [{used, minutes, reset, slot}]}], updated}`,
and add provider dispatch in `readProvider`. The controller already keeps
per-provider snapshots, errors, and in-flight jobs. Never substitute token counts
or API spend for subscription quota — non-quota credits and spend totals are
deliberately dropped for that reason. Keep unavailable, stale, and disconnected
states explicit.

## License and releases

Agent Pulse is released under the MIT license. The bot icon is traced from Lucide's "bot" into a filled silhouette so GNOME can recolor it; its upstream license is preserved in `icons/LUCIDE-LICENSE`. Before advertising support for another GNOME version, test the extension on that version and add it to `metadata.json`.

Contributions are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md). Use GitHub's private security-advisory flow for vulnerabilities and follow [`SECURITY.md`](SECURITY.md).

[Codex app-server documentation](https://developers.openai.com/codex/app-server)
