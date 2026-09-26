import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gdk from 'gi://Gdk?version=4.0';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {PROVIDERS} from './providers/index.js';

const SUBTITLES = {
    codex: 'Read subscription limits through Codex CLI',
    claude: 'Read plan limits from Claude Code\u2019s status line',
    cursor: 'Read monthly plan limits from the signed-in Cursor app',
};

const ORDERS = [
    ['codex', 'claude', 'cursor'],
    ['codex', 'cursor', 'claude'],
    ['claude', 'codex', 'cursor'],
    ['claude', 'cursor', 'codex'],
    ['cursor', 'codex', 'claude'],
    ['cursor', 'claude', 'codex'],
];

export default class AgentUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        window.set_default_size(560, 640);
        const page = new Adw.PreferencesPage({title: 'Agent Pulse', icon_name: 'preferences-system-symbolic'});
        window.add(page);
        const appearance = new Adw.PreferencesGroup({title: 'Appearance'});
        page.add(appearance);
        const name = new Adw.EntryRow({title: 'Widget name'});
        settings.bind('widget-name', name, 'text', Gio.SettingsBindFlags.DEFAULT);
        appearance.add(name);
        const percentage = new Adw.SwitchRow({title: 'Show top-bar percentage', subtitle: 'Off by default · the bot icon stays visible'});
        settings.bind('show-percentage', percentage, 'active', Gio.SettingsBindFlags.DEFAULT);
        appearance.add(percentage);
        const interval = new Adw.SpinRow({title: 'Refresh interval (seconds)', adjustment: new Gtk.Adjustment({lower: 60, upper: 3600, step_increment: 60, page_increment: 300})});
        settings.bind('refresh-seconds', interval, 'value', Gio.SettingsBindFlags.DEFAULT);
        appearance.add(interval);
        const agents = new Adw.PreferencesGroup({title: 'Agents', description: 'Enabled agents appear as tabs.'});
        page.add(agents);
        for (const provider of PROVIDERS) {
            const toggle = new Adw.SwitchRow({title: provider.name, subtitle: SUBTITLES[provider.id] || 'Not connected · support planned', active: settings.get_strv('providers').includes(provider.id)});
            toggle.connect('notify::active', () => {
                const enabled = settings.get_strv('providers').filter(id => id !== provider.id);
                if (toggle.active) enabled.push(provider.id);
                settings.set_strv('providers', enabled);
            });
            agents.add(toggle);
        }
        const currentOrder = settings.get_strv('providers');
        const completeOrder = [...currentOrder, ...PROVIDERS.map(p => p.id).filter(id => !currentOrder.includes(id))];
        const order = new Adw.ComboRow({title: 'Tab order', model: Gtk.StringList.new(ORDERS.map(ids => ids.map(id => PROVIDERS.find(p => p.id === id).name).join(', '))), selected: Math.max(0, ORDERS.findIndex(ids => ids.every((id, index) => completeOrder[index] === id)))});
        order.connect('notify::selected', () => {
            const enabled = settings.get_strv('providers');
            settings.set_strv('providers', ORDERS[order.selected].filter(id => enabled.includes(id)));
        });
        agents.add(order);
        const initial = new Adw.ComboRow({title: 'Default tab', subtitle: 'Falls back to the first enabled agent', model: Gtk.StringList.new(PROVIDERS.map(p => p.name)), selected: Math.max(0, PROVIDERS.findIndex(p => p.id === settings.get_string('default-provider')))});
        initial.connect('notify::selected', () => settings.set_string('default-provider', PROVIDERS[initial.selected].id));
        agents.add(initial);
        const connection = new Adw.PreferencesGroup({title: 'Codex connection', description: 'Uses your existing Codex CLI login. No API key or browser cookies are collected. Codex itself manages its own authentication and runtime files.'});
        page.add(connection);
        const path = new Adw.EntryRow({title: 'Codex executable path (blank = auto)'});
        settings.bind('codex-path', path, 'text', Gio.SettingsBindFlags.DEFAULT);
        connection.add(path);
        const claude = new Adw.PreferencesGroup({title: 'Claude connection', description: 'Claude Code passes its plan limits to the status line command in ~/.claude/settings.json. Copy the command below into that setting; the widget then reads the numbers it leaves behind. No API key, token, or conversation is read. Until a Claude Code session has run once, the widget falls back to the Claude desktop app\u2019s own usage samples, which carry no reset times.'});
        page.add(claude);
        const command = `python3 ${this.path}/providers/claude_statusline.py`;
        const copy = new Adw.ActionRow({title: 'Status line command', subtitle: command});
        const button = new Gtk.Button({label: 'Copy', valign: Gtk.Align.CENTER});
        button.connect('clicked', () => {
            Gdk.Display.get_default()?.get_clipboard()?.set(command);
            button.label = 'Copied';
        });
        copy.add_suffix(button);
        claude.add(copy);
        const existing = new Adw.ActionRow({title: 'Already using a status line?', subtitle: 'Append --wrap \"your command\" so yours still renders. Add --quiet for an empty status line.'});
        existing.add_css_class('property');
        claude.add(existing);
        const snapshot = new Adw.EntryRow({title: 'Claude snapshot path (blank = default)'});
        settings.bind('claude-snapshot-path', snapshot, 'text', Gio.SettingsBindFlags.DEFAULT);
        claude.add(snapshot);
        const cursor = new Adw.PreferencesGroup({title: 'Cursor connection', description: 'Uses the active Cursor app sign-in to request plan percentages from Cursor. The local access token is read only for the request and is never stored by Agent Pulse or shown in its output. Cursor does not publish this personal-usage endpoint as a stable third-party API, so a Cursor update may temporarily break this adapter.'});
        page.add(cursor);
        const cursorState = new Adw.EntryRow({title: 'Cursor state database (blank = default)'});
        settings.bind('cursor-state-path', cursorState, 'text', Gio.SettingsBindFlags.DEFAULT);
        cursor.add(cursorState);
    }
}
