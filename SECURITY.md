# Scope and reporting

Do not include tokens, auth files, complete Codex logs, status line payloads, or
conversation data in bug reports. The usage helpers emit only normalized quota
data or a generic failure message. Report the GNOME version, extension version, and visible status.

The extension intentionally has no telemetry, remote script loader, browser
cookie access, credential editor, automatic package installer, or settings
migration outside its own namespace. It uses Codex's existing authentication
through its local app server, and for Claude reads only local files: the quota
snapshot written by its own status line hook and, as a fallback, the Claude
desktop app's plan usage samples. The status line hook copies out rate limit
windows only and discards the rest of the payload it is handed, including
prompts, transcript and project paths, cost, and account identifiers. Codex and
Claude themselves may refresh credentials and write runtime files. No extension can enforce a sandbox within GNOME Shell.
