import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const INTERFACE = `<node><interface name="org.gnome.Shell.Extensions.CodexQuota">
    <method name="Update"><arg type="s" direction="in"/></method>
</interface></node>`;

export default class CodexQuotaExtension extends Extension {
    enable() {
        this._button = new PanelMenu.Button(0.5, 'Codex Quota', true);
        this._button.remove_action(this._button._clickGesture);
        this._button.reactive = this._button.can_focus = false;
        this._button.add_style_class_name('codex-quota-centre-button');
        const box = new St.BoxLayout({style_class: 'panel-status-indicators-box codex-quota-panel-box'});
        const icon = Gio.File.new_for_path(GLib.build_filenamev([
            GLib.get_home_dir(), 'Applications', 'codex-quota', 'assets', 'codex-quota-symbolic.svg',
        ]));
        box.add_child(new St.Icon({gicon: new Gio.FileIcon({file: icon}), style_class: 'system-status-icon codex-quota-panel-icon'}));
        this._label = new St.Label({text: 'Codex ~%', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._label);
        this._button.add_child(box);
        try {
            const clock = Main.panel.statusArea.dateMenu.container;
            const index = Main.panel._centerBox.get_children().indexOf(clock);
            Main.panel.addToStatusArea(this.uuid, this._button, Math.max(0, index), 'center');
            this._box = Main.panel._centerBox;
            this._clock = clock;
            this._originalX = this._box.translation_x;
            this._signals = [this._box, clock, Main.panel].map(actor =>
                [actor, actor.connect('notify::allocation', () => this._centerClock())]);
            const place = () => this._box.set_child_below_sibling(this._button.container, clock);
            this._signals.push([this._box, this._box.connect('child-added', place)]);
            place();
            this._centerClock();
            this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE, this);
            this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/CodexQuota');
        } catch (error) {
            this.disable();
            throw error;
        }
    }

    Update(state) {
        let remaining;
        try {
            remaining = JSON.parse(state)?.remaining_percent;
        } catch {}
        const available = Number.isFinite(remaining) && remaining >= 0 && remaining <= 100;
        this._label.text = available ? `Codex ${Math.round(remaining)}%` : 'Codex ~%';
    }

    _centerClock() {
        if (this._box.has_allocation() && this._clock.has_allocation())
            this._box.translation_x = Main.panel.width / 2 - this._box.x - this._clock.x - this._clock.width / 2;
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
        for (const [actor, id] of this._signals ?? [])
            actor.disconnect(id);
        this._signals = [];
        if (this._box)
            this._box.translation_x = this._originalX;
        this._box = this._clock = null;
        this._button?.destroy();
        this._button = null;
        this._label = null;
    }
}
