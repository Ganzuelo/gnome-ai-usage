#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests
# Validate schemas without modifying the source tree.
glib-compile-schemas --strict --dry-run schemas
mkdir -p dist
python3 - <<'PY'
from pathlib import Path
import zipfile
root=Path('.')
with zipfile.ZipFile('dist/gnome-agent-pulse.shell-extension.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for name in ('metadata.json','extension.js','prefs.js','stylesheet.css','LICENSE','README.md','SECURITY.md'):
        archive.write(name)
    for directory in ('providers','schemas','icons'):
        for path in sorted((root/directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc',) and path.name != 'gschemas.compiled':
                archive.write(path)
print('Built dist/gnome-agent-pulse.shell-extension.zip')
PY
