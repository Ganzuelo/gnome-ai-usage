import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {PROVIDERS, PROVIDER_FAILURE, readProvider} from './providers/index.js';

const EMPTY = {
    codex: {title: 'Usage unavailable', hint: 'Sign in with Codex CLI to read limits.', reading: 'Reading Codex usage…'},
    claude: {title: 'Not connected', hint: 'Add the status line hook in Settings, then run Claude Code once.', reading: 'Reading Claude usage…'},
};

function label(text, style = '') {
    return new St.Label({text, style_class: style, y_align: Clutter.ActorAlign.CENTER});
}
function row(left, right) {
    const box = new St.BoxLayout({style_class: 'au-row'});
    left.x_expand = true;
    box.add_child(left);
    box.add_child(right);
    return box;
}
function resetText(timestamp) {
    if (!timestamp) return 'Reset time unavailable';
    const seconds = timestamp - Date.now() / 1000;
    if (seconds <= 0) return 'Reset due · refresh to update';
    if (seconds < 86400) {
        const minutes = Math.ceil(seconds / 60);
        return `Resets in ${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    }
    return `Resets ${GLib.DateTime.new_from_unix_local(Math.floor(timestamp)).format('%a at %H:%M')}`;
}
function windowName(window) {
    if (window.minutes === 10080) return 'Weekly';
    if (window.minutes === 300) return 'Session · 5 hours';
    if (window.minutes) return `${window.minutes < 60 ? `${window.minutes} minutes` : `${Math.round(window.minutes / 60 * 10) / 10} hours`}`;
    return window.slot === 'primary' ? 'Primary limit' : 'Secondary limit';
}

export default class AgentPulse extends Extension {
    enable() {
        this._alive = true;
        this._settings = this.getSettings();
        this._data = new Map();
        this._errors = new Map();
        this._jobs = new Map();
        this._selected = this._settings.get_string('default-provider');
        this._button = new PanelMenu.Button(0.0, this._settings.get_string('widget-name'));
        const box = new St.BoxLayout({style_class: 'au-panel-box'});
        box.add_child(new St.Icon({gicon: Gio.icon_new_for_string(`${this.path}/icons/bot-symbolic.svg`), style_class: 'system-status-icon'}));
        this._percent = label('');
        box.add_child(this._percent);
        this._button.add_child(box);
        this._button.add_style_class_name('au-panel-button');
        this._button.menu.box.add_style_class_name('au-popup');
        Main.panel.addToStatusArea(this.uuid, this._button);
        this._settings.connectObject('changed', (_s, key) => {
            if (key === 'default-provider') this._selected = this._settings.get_string(key);
            this._button.accessible_name = this._settings.get_string('widget-name');
            this._render();
            this._schedule();
            if (key === 'providers') this._refreshAll();
            if (key === 'codex-path') this._restart('codex');
            if (key === 'claude-snapshot-path') this._restart('claude');
        }, this);
        this._button.menu.connect('open-state-changed', (_menu, open) => {
            if (open) this._render();
        });
        this._render();
        this._schedule();
        this._refreshAll();
    }
    _enabled() {
        return this._settings.get_strv('providers').map(id => PROVIDERS.find(p => p.id === id)).filter(Boolean);
    }
    _schedule() {
        if (this._timer) GLib.Source.remove(this._timer);
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, this._settings.get_int('refresh-seconds'), () => {
            this._refreshAll();
            return GLib.SOURCE_CONTINUE;
        });
    }
    _restart(id) {
        const running = this._jobs.get(id);
        if (running) { running.cancel(); this._jobs.delete(id); }
        this._refresh(id);
    }
    _refreshAll() {
        for (const provider of this._enabled()) this._refresh(provider.id);
    }
    async _refresh(id) {
        if (this._jobs.has(id) || !this._alive || !this._enabled().some(p => p.id === id)) return;
        let job;
        try {
            job = readProvider(id, this.path, this._settings);
            if (!job) return;
            this._jobs.set(id, job);
            this._render();
            const data = await job.promise;
            if (this._alive && this._jobs.get(id) === job) { this._data.set(id, data); this._errors.delete(id); }
        } catch (_) {
            if (this._alive && (!job || this._jobs.get(id) === job)) this._errors.set(id, PROVIDER_FAILURE(id));
        } finally {
            if (this._alive && (!job || this._jobs.get(id) === job)) { this._jobs.delete(id); this._render(); }
        }
    }
    _render() {
        const providers = this._enabled();
        if (!providers.some(p => p.id === this._selected)) this._selected = providers[0]?.id;
        const selected = this._selected;
        const data = selected ? this._data.get(selected) : null;
        const busy = selected ? this._jobs.has(selected) : false;
        const error = selected ? this._errors.get(selected) : null;
        const percentage = data?.buckets?.[0]?.windows?.[0]?.used;
        this._percent.visible = this._settings.get_boolean('show-percentage') && !!selected;
        this._percent.text = percentage === undefined ? '—' : `${Math.round(percentage)}%${error ? ' ·' : ''}`;
        this._button.menu.removeAll();
        const section = new PopupMenu.PopupMenuSection();
        this._button.menu.addMenuItem(section);
        const heading = row(label(this._settings.get_string('widget-name') || 'Agent Pulse', 'au-title'), this._action('emblem-system-symbolic', 'Settings', () => this.openPreferences()));
        heading.add_style_class_name('au-heading');
        section.box.add_child(heading);
        const tabs = new St.BoxLayout({style_class: 'au-tabs', x_expand: true});
        for (const provider of providers) {
            const tab = new St.Button({label: provider.name, style_class: 'au-tab', can_focus: true, x_expand: true, accessible_name: `${provider.name}${provider.id === selected ? ', selected' : ''}`});
            if (provider.id === selected) tab.add_style_class_name('au-selected');
            tab.connect('clicked', () => {
                this._selected = provider.id;
                this._render();
                if (!this._data.has(provider.id)) this._refresh(provider.id);
            });
            tabs.add_child(tab);
        }
        if (providers.length) section.box.add_child(tabs);
        const content = new St.BoxLayout({vertical: true, style_class: 'au-content'});
        section.box.add_child(content);
        const empty = EMPTY[selected] || {title: 'Usage unavailable', hint: 'No adapter for this agent.', reading: 'Reading usage…'};
        if (!providers.length) content.add_child(label('Enable an agent in Settings.', 'au-muted'));
        else if (!data) {
            content.add_child(label(busy ? empty.reading : empty.title, 'au-title'));
            content.add_child(label(empty.hint, 'au-muted'));
        } else if (!data.buckets.length) content.add_child(label('No quota windows reported.', 'au-muted'));
        else {
            content.add_child(row(label('Subscription usage'), label('Used', 'au-muted')));
            for (const bucket of data.buckets) {
                if (data.buckets.length > 1) content.add_child(label(bucket.name, 'au-bucket'));
                for (const window of bucket.windows) {
                    const meter = new St.BoxLayout({vertical: true, style_class: 'au-meter'});
                    meter.add_child(row(label(windowName(window)), label(`${Math.round(window.used)}%`)));
                    const track = new St.Widget({style_class: 'au-track', x_expand: true, height: 7, accessible_name: `${windowName(window)}: ${Math.round(window.used)} percent used`});
                    const fill = new St.Widget({style_class: `au-fill${window.used >= 90 ? ' au-warning' : ''}`, height: 7});
                    track.add_child(fill);
                    track.connect('notify::width', () => fill.set_width(track.width * window.used / 100));
                    meter.add_child(track);
                    meter.add_child(label(resetText(window.reset), 'au-muted'));
                    content.add_child(meter);
                }
            }
        }
        let status = 'Enable an agent in Settings';
        if (selected) {
            const age = data ? Math.max(0, Math.floor((Date.now() / 1000 - data.updated) / 60)) : null;
            status = busy ? 'Refreshing…' : error ? (age === null ? 'Could not refresh' : `Stale · checked ${age}m ago`) : age === null ? 'Not connected' : age === 0 ? 'Updated just now' : `Updated ${age}m ago`;
            if (data && !busy && !error && data.source === 'desktop') status += ' · Claude app';
        }
        const refresh = this._action('view-refresh-symbolic', 'Refresh usage', () => this._refresh(selected));
        refresh.reactive = !!selected && !busy;
        refresh.can_focus = refresh.reactive;
        const footer = row(label(status, 'au-muted'), refresh);
        footer.add_style_class_name('au-footer');
        section.box.add_child(footer);
    }
    _action(icon, name, callback) {
        const button = new St.Button({style_class: 'au-action', can_focus: true, accessible_name: name, child: new St.Icon({icon_name: icon, icon_size: 16})});
        button.connect('clicked', callback);
        return button;
    }
    disable() {
        this._alive = false;
        if (this._timer) GLib.Source.remove(this._timer);
        this._timer = null;
        for (const job of this._jobs.values()) job.cancel();
        this._jobs.clear();
        this._settings?.disconnectObject(this);
        this._button?.destroy();
        this._button = null;
        this._settings = null;
        this._data?.clear();
        this._data = null;
        this._errors?.clear();
        this._errors = null;
    }
}
