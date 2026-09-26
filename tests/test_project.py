import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_public_identity_is_consistent(self):
        metadata = json.loads((ROOT / 'metadata.json').read_text())
        self.assertEqual(metadata['uuid'], 'agent-pulse@community')
        self.assertEqual(metadata['name'], 'Agent Pulse')
        self.assertEqual(metadata['settings-schema'], 'org.gnome.shell.extensions.agent-pulse')
        self.assertEqual(metadata['url'], 'https://github.com/Ganzuelo/gnome-ai-usage')

        schema_file = ROOT / 'schemas' / 'org.gnome.shell.extensions.agent-pulse.gschema.xml'
        schema = ET.parse(schema_file).getroot().find('schema')
        self.assertEqual(schema.attrib['id'], metadata['settings-schema'])

    def test_release_identifiers_are_not_local_or_personal(self):
        metadata = (ROOT / 'metadata.json').read_text().lower()
        self.assertNotIn('@local', metadata)

    def test_cursor_is_wired_through_registry_and_schema(self):
        registry = (ROOT / 'providers' / 'index.js').read_text()
        preferences = (ROOT / 'prefs.js').read_text()
        schema = (ROOT / 'schemas' / 'org.gnome.shell.extensions.agent-pulse.gschema.xml').read_text()
        self.assertIn("{id: 'cursor', name: 'Cursor', supported: true}", registry)
        self.assertIn("if (id === 'cursor')", registry)
        self.assertIn('Cursor connection', preferences)
        self.assertIn('cursor-state-path', schema)


if __name__ == '__main__':
    unittest.main()
