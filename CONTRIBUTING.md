# Contributing

Bug reports and focused pull requests are welcome. Before submitting a change:

1. Run `python3 -m unittest discover -s tests -v`.
2. Run `bash scripts/package.sh`.
3. Verify the archive with `unzip -t dist/gnome-agent-pulse.shell-extension.zip`.
4. Test affected providers with real disconnected, stale, and multi-window states.

Never include tokens, account identifiers, auth files, conversations, complete status-line payloads, or private paths in commits and reports. Provider adapters must return normalized quota data and must not substitute token counts or API spend for subscription limits.
