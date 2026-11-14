#!/usr/bin/env python3
"""TV Control: turn features on/off on Android TV, Google TV and Fire TV devices over the network (ADB)."""
import concurrent.futures, datetime, json, os, sys, uuid

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog  # noqa: E402
from device import ROOT, Device, NotAllowed, scan  # noqa: E402

APP_ID = "local.tvcontrol"
CONF = os.path.join(GLib.get_user_config_dir(), "tv-control")
TVHOME_APK = os.path.join(ROOT, "TVHome.apk")

CSS = """
.pending { background-color: alpha(@accent_bg_color, 0.14); }
.status-dot { font-size: 10px; }
.status-dot.on { color: @success_color; }
.status-dot.off { color: alpha(@window_fg_color, 0.3); }
"""


def plain(cls, title="", subtitle="", **kw):
    """A row showing title/subtitle as plain text (feature names contain '&', which breaks Pango markup)."""
    row = cls(use_markup=False, **kw)
    row.set_title(title)
    row.set_subtitle(subtitle)
    return row


# ---------------------------------------------------------------- storage
class Store:
    """~/.config/tv-control/devices.json plus one folder of state and backups per device."""

    def __init__(self):
        os.makedirs(CONF, exist_ok=True)
        self.path = os.path.join(CONF, "devices.json")
        if os.path.exists(self.path):
            self.devices = json.load(open(self.path))
        else:
            self.devices = []
            self._seed_sony()
            self.save()

    def _seed_sony(self):
        # The BRAVIA was debloated by hand on 2026-10-26; carry that over so "Restore" knows what was disabled.
        self.devices.append({"id": "sony-bravia", "name": "Sony BRAVIA", "host": "192.168.0.108", "port": 5555})
        listed = os.path.join(ROOT, "disabled_by_us.txt")
        pkgs = [l.strip() for l in open(listed) if l.strip() and not l.startswith("#")] if os.path.exists(listed) else []
        self.save_state("sony-bravia", {"disabled_by_app": pkgs,
                                        "stock_home": "com.google.android.tvlauncher/.MainActivity"})

    def save(self):
        json.dump(self.devices, open(self.path, "w"), indent=2)

    def dir(self, dev_id):
        d = os.path.join(CONF, dev_id)
        os.makedirs(d, exist_ok=True)
        return d

    def state(self, dev_id):
        p = os.path.join(self.dir(dev_id), "state.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def save_state(self, dev_id, state):
        json.dump(state, open(os.path.join(self.dir(dev_id), "state.json"), "w"), indent=2)


# ---------------------------------------------------------------- one device's page
class DevicePage(Adw.Bin):
    def __init__(self, win, entry):
        super().__init__()
        self.win, self.entry = win, entry
        self.store = win.store
        self.dev = Device(entry["host"], entry.get("port", 5555))
        self.worker = concurrent.futures.ThreadPoolExecutor(1)  # adb-shell connections aren't thread safe
        self.state = self.store.state(entry["id"])
        self.info, self.pkgs, self.home = {}, {}, ""
        self.desired = {}  # package -> enabled, for packages the user has changed but not applied
        self._syncing = False
        self.feature_rows, self.app_rows = {}, {}

        self.toasts = Adw.ToastOverlay()
        self.set_child(self.toasts)
        self.toolbar = Adw.ToolbarView()
        self.toasts.set_child(self.toolbar)

        # header: tab switcher + refresh + menu
        self.header = Adw.HeaderBar()
        self.views = Adw.ViewStack()
        self.switcher = Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.title = Adw.WindowTitle(title=entry["name"], subtitle=self._host())
        self.header.set_title_widget(self.title)
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload from device")
        self.refresh_btn.connect("clicked", lambda *_: self.load())
        menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append("Select recommended (privacy)", "win.recommended")
        sec.append("Re-apply my previous choices", "win.reapply")
        sec.append("Restore everything this app disabled", "win.restore")
        menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Edit device…", "win.edit")
        sec.append("Open backups folder", "win.backups")
        sec.append("Disconnect", "win.disconnect")
        sec.append("Remove device", "win.remove")
        menu.append_section(None, sec)
        self.header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        self.header.pack_end(self.refresh_btn)
        self.toolbar.add_top_bar(self.header)

        # body: disconnected / busy / ready
        self.body = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.toolbar.set_content(self.body)

        self.offline = Adw.StatusPage(icon_name="video-display-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, halign=Gtk.Align.CENTER)
        btn = Gtk.Button(label="Connect", halign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
        btn.connect("clicked", lambda *_: self.load())
        box.append(btn)
        help_group = Adw.PreferencesGroup(title="First time? Turn on debugging on the device")
        for k, v in catalog.SETUP_HELP.items():
            help_group.add(plain(Adw.ActionRow, k, v, subtitle_selectable=True))
        box.append(Adw.Clamp(maximum_size=620, child=help_group))
        self.offline.set_child(box)
        self.body.add_named(self.offline, "offline")

        busy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER,
                       halign=Gtk.Align.CENTER)
        busy.append(Adw.Spinner(width_request=48, height_request=48))
        self.busy_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=50,
                                    css_classes=["title-4"])
        self.busy_hint = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=60,
                                   css_classes=["dim-label"])
        busy.append(self.busy_label)
        busy.append(self.busy_hint)
        self.body.add_named(busy, "busy")

        ready = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.views.set_vexpand(True)
        switcher_bar = Gtk.CenterBox(margin_top=6, margin_bottom=6)
        switcher_bar.set_center_widget(self.switcher)
        ready.append(switcher_bar)
        ready.append(self.views)
        self.body.add_named(ready, "ready")

        self.features_bin = Adw.Bin()
        self.views.add_titled_with_icon(self.features_bin, "features", "Features", "preferences-system-symbolic")
        self.views.add_titled_with_icon(self._build_apps_tab(), "apps", "All apps", "view-grid-symbolic")
        self.home_bin = Adw.Bin()
        self.views.add_titled_with_icon(self.home_bin, "home", "Home screen", "go-home-symbolic")
        self.views.add_titled_with_icon(self._build_log_tab(), "log", "Log", "utilities-terminal-symbolic")

        # bottom bar: pending changes
        self.action_bar = Gtk.ActionBar(revealed=False)
        self.pending_label = Gtk.Label(css_classes=["heading"])
        self.action_bar.set_center_widget(self.pending_label)
        discard = Gtk.Button(label="Discard")
        discard.connect("clicked", lambda *_: self.discard())
        self.action_bar.pack_start(discard)
        apply = Gtk.Button(label="Apply to device", css_classes=["suggested-action"])
        apply.connect("clicked", lambda *_: self.confirm_apply())
        self.action_bar.pack_end(apply)
        self.toolbar.add_bottom_bar(self.action_bar)

        self._show_offline()

    # ---- helpers
    def _host(self):
        return f"{self.entry['host']}:{self.entry.get('port', 5555)}"

    def toast(self, text, timeout=4):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=timeout))

    def log(self, text):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), f"[{stamp}] {text.rstrip()}\n")

    def run(self, fn, done, busy=None, hint=""):
        """Run fn() on the device thread, then done(result) or an error on the UI thread."""
        if busy:
            self.busy_label.set_label(busy)
            self.busy_hint.set_label(hint)
            self.body.set_visible_child_name("busy")
        self.refresh_btn.set_sensitive(False)

        def finish(fut):
            def ui():
                self.refresh_btn.set_sensitive(True)
                try:
                    result = fut.result()
                except Exception as e:  # noqa: BLE001 - show every device error to the user
                    self.on_error(e)
                else:
                    done(result)
                return False
            GLib.idle_add(ui)
        self.worker.submit(fn).add_done_callback(finish)

    def on_error(self, e):
        msg = str(e) or type(e).__name__
        self.log(f"ERROR: {type(e).__name__}: {msg}")
        self.dev.close()
        self.win.set_online(self.entry["id"], False)
        if not self.pkgs:
            self._show_offline(f"Couldn't connect to {self._host()}", self._error_hint(e))
        else:
            self.body.set_visible_child_name("ready")
            self.toast(f"Device error: {msg[:80]}")

    def _error_hint(self, e):
        name = type(e).__name__
        if isinstance(e, NotAllowed):
            return ("The device is reachable but didn't allow this computer. Press Connect, then within 90 seconds "
                    "choose “Allow” on the TV's USB debugging prompt (tick “Always allow”).")
        if isinstance(e, (ConnectionRefusedError,)):
            return "The device is on, but ADB debugging is off. Turn it on (steps below) and try again."
        if isinstance(e, (TimeoutError, OSError)) or "Timeout" in name:
            return "No answer. Check the device is switched on, on the same Wi-Fi, and its IP address is right."
        return f"{name}: {e}"

    def _show_offline(self, title=None, desc=None):
        self.offline.set_title(title or self.entry["name"])
        self.offline.set_description(desc or f"Not connected · {self._host()}")
        self.body.set_visible_child_name("offline")

    # ---- loading
    def load(self):
        first = not self.pkgs

        def work():
            if not self.dev.connected:
                self.dev.connect()
            return self.dev.info(), self.dev.packages(), self.dev.home()
        self.run(work, self._loaded,
                 busy=f"Connecting to {self._host()}…" if first else "Refreshing…",
                 hint="First time with this device? Look at the TV and choose “Allow” on the USB debugging "
                      "prompt (tick “Always allow from this computer”)." if first else "")

    def _loaded(self, result):
        self.info, self.pkgs, self.home = result
        self.win.set_online(self.entry["id"], True)
        self.log(f"Connected: {self.info['name']} · {self.info['maker']} {self.info['model']} · Android "
                 f"{self.info['android']} · {len(self.pkgs)} packages · home {self.home}")
        if not self.entry.get("model"):
            self.entry["model"] = f"{self.info['maker']} {self.info['model']}".strip()
            if self.entry["name"] in ("", self.entry["host"]):
                self.entry["name"] = self.info["name"] or self.entry["model"]
            self.store.save()
            self.win.refresh_sidebar()
        self.title.set_title(self.entry["name"])
        self.title.set_subtitle(f"{self.kind()} · {self._host()}")
        self._snapshot()
        if self.home and not self.home.startswith(catalog.CUSTOM_HOME_PKG + "/"):
            self.state["stock_home"] = self.home
            self.store.save_state(self.entry["id"], self.state)
        self.desired = {p: v for p, v in self.desired.items() if p in self.pkgs and v != self.pkgs[p]["enabled"]}
        self._build_features()
        self._fill_apps()
        self._build_home()
        self._sync()
        self.body.set_visible_child_name("ready")

    def kind(self):
        if self.info.get("maker", "").lower() == "amazon":
            return "Fire TV"
        if "com.google.android.apps.tv.launcherx" in self.pkgs:
            return "Google TV"
        return "Android TV"

    def _snapshot(self):
        """Before the first change on a device, keep a copy of how it was."""
        if self.state.get("snapshot"):
            return
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = os.path.join(self.store.dir(self.entry["id"]), f"original_{stamp}.txt")
        with open(path, "w") as f:
            f.write(f"# {self.info['name']} {self.info['maker']} {self.info['model']} {stamp}\n# home: {self.home}\n")
            f.write("# disabled packages:\n" + "".join(f"{p}\n" for p, v in sorted(self.pkgs.items())
                                                     if not v["enabled"]))
            f.write("# all packages:\n" + "".join(f"{p}\n" for p in sorted(self.pkgs)))
            f.write("# getprop:\n" + self.info.get("props", ""))
        self.state["snapshot"] = path
        self.store.save_state(self.entry["id"], self.state)
        self.log(f"Saved the device's original state to {path}")

    # ---- model
    def enabled(self, pkg):
        return self.desired.get(pkg, self.pkgs[pkg]["enabled"])

    def set_desired(self, pkg, on):
        if pkg not in self.pkgs:
            return
        if on == self.pkgs[pkg]["enabled"]:
            self.desired.pop(pkg, None)
        else:
            self.desired[pkg] = on

    def present(self, feature):
        return [p for p in feature.packages if p in self.pkgs]

    def has_custom_home(self):
        return catalog.CUSTOM_HOME_PKG in self.pkgs and self.pkgs[catalog.CUSTOM_HOME_PKG]["enabled"]

    def _sync(self):
        """Push the model into every switch without re-triggering their handlers."""
        self._syncing = True
        for f, row in self.feature_rows.values():
            pk = self.present(f)
            on = [self.enabled(p) for p in pk]
            row.set_active(all(on))
            pending = any(p in self.desired for p in pk)
            partial = any(on) and not all(on)
            sub = f.desc + (" (partly turned off)" if partial else "")
            row.set_subtitle(sub)
            (row.add_css_class if pending else row.remove_css_class)("pending")
        for pkg, row in self.app_rows.items():
            row.set_active(self.enabled(pkg))
            (row.add_css_class if pkg in self.desired else row.remove_css_class)("pending")
        self._syncing = False
        n = len(self.desired)
        self.action_bar.set_revealed(n > 0)
        off = sum(1 for v in self.desired.values() if not v)
        parts = ([f"{off} to turn off"] if off else []) + ([f"{n - off} to turn on"] if n - off else [])
        self.pending_label.set_label(" · ".join(parts))
        self.apps_list.invalidate_filter()

    def discard(self):
        self.desired.clear()
        self._sync()

    # ---- features tab
    def _build_features(self):
        page = Adw.PreferencesPage()
        self.feature_rows = {}
        intro = Adw.PreferencesGroup(
            description="Switch a feature off to disable its apps on the device. Nothing is uninstalled; switch it "
                        "back on any time. Changes are only sent when you press “Apply to device”.")
        page.add(intro)
        for cat in catalog.CATEGORIES:
            feats = [f for f in catalog.FEATURES if f.category == cat and self.present(f)]
            if not feats:
                continue
            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(cat))
            for f in feats:
                row = plain(Adw.SwitchRow, f.name, f.desc)
                if f.warn:
                    icon = Gtk.Image(icon_name="dialog-warning-symbolic", tooltip_text=f.warn,
                                     css_classes=["warning"])
                    row.add_suffix(icon)
                row.set_tooltip_text("Apps: " + ", ".join(self.present(f)))
                row.connect("notify::active", self._feature_toggled, f)
                self.feature_rows[f.id] = (f, row)
                group.add(row)
            page.add(group)
        if not self.feature_rows:
            page.add(Adw.PreferencesGroup(
                description="None of the known features were found on this device. Use the All apps tab."))
        self.features_bin.set_child(page)

    def _feature_toggled(self, row, _pspec, f):
        if self._syncing:
            return
        on = row.get_active()
        if f.id == "stock_launcher" and not on and not self.has_custom_home():
            self.toast("Install the TVHome launcher first (Home screen tab), or the TV would have no home screen.")
            self._sync()
            return
        for p in self.present(f):
            self.set_desired(p, on)
        self._sync()

    # ---- all apps tab
    def _build_apps_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        clamp = Adw.Clamp(maximum_size=900, child=bar)
        self.search = Gtk.SearchEntry(placeholder_text="Search apps", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.apps_list.invalidate_filter())
        self.filter = Gtk.DropDown.new_from_strings(
            ["All apps", "Installed by you", "System apps", "Turned off", "Pending changes"])
        self.filter.connect("notify::selected", lambda *_: self.apps_list.invalidate_filter())
        bar.append(self.search)
        bar.append(self.filter)
        box.append(clamp)

        self.apps_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                     margin_start=12, margin_end=12, margin_top=6, margin_bottom=24, valign=Gtk.Align.START)
        self.apps_list.set_filter_func(self._app_visible)
        self.apps_list.set_placeholder(Gtk.Label(label="No matching apps", margin_top=24, margin_bottom=24,
                                                 css_classes=["dim-label"]))
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    child=Adw.Clamp(maximum_size=900, child=self.apps_list))
        box.append(scroll)
        return box

    def _fill_apps(self):
        self.apps_list.remove_all()
        self.app_rows = {}
        ours = set(self.state.get("disabled_by_app", []))
        home_pkg = self.home.split("/")[0]
        # user apps first, then system apps, alphabetically
        for pkg in sorted(self.pkgs, key=lambda p: (self.pkgs[p]["system"], p)):
            tags = ["System app" if self.pkgs[pkg]["system"] else "Installed app"]
            f = catalog.feature_for(pkg)
            if f:
                tags.append(f"Part of “{f.name}”")
            if pkg in ours and not self.pkgs[pkg]["enabled"]:
                tags.append("turned off by this app")
            reason = catalog.protected_reason(pkg) or ("Current home screen" if pkg == home_pkg else None)
            if reason:
                tags.append(f"Protected: {reason}")
            row = plain(Adw.SwitchRow, pkg, " · ".join(tags), title_selectable=True)
            row.pkg = pkg
            if reason:
                row.set_sensitive(False)
            row.connect("notify::active", self._app_toggled)
            self.app_rows[pkg] = row
            self.apps_list.append(row)

    def _app_toggled(self, row, _pspec):
        if self._syncing:
            return
        if row.pkg in catalog.STOCK_LAUNCHERS and not row.get_active() and not self.has_custom_home():
            self.toast("Install the TVHome launcher first (Home screen tab), or the TV would have no home screen.")
            self._sync()
            return
        self.set_desired(row.pkg, row.get_active())
        self._sync()

    def _app_visible(self, row):
        pkg = row.pkg
        q = self.search.get_text().strip().lower()
        if q and q not in pkg.lower() and q not in (row.get_subtitle() or "").lower():
            return False
        sel = self.filter.get_selected()
        info = self.pkgs.get(pkg, {})
        return {0: True, 1: not info.get("system"), 2: bool(info.get("system")),
                3: not self.enabled(pkg), 4: pkg in self.desired}[sel]

    # ---- home screen tab
    def _build_home(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title="This device")
        for title, val in (("Name", self.info["name"]), ("Model", f"{self.info['maker']} {self.info['model']}"),
                           ("Type", self.kind()),
                           ("Software", f"Android {self.info['android']}" +
                            (f" · Fire OS {self.info['fireos']}" if self.info["fireos"] else "")),
                           ("Address", self._host()),
                           ("Apps", f"{len(self.pkgs)} packages, "
                                    f"{sum(1 for v in self.pkgs.values() if not v['enabled'])} turned off")):
            g.add(plain(Adw.ActionRow, title, val, subtitle_selectable=True, css_classes=["property"]))
        page.add(g)

        g = Adw.PreferencesGroup(title="Home screen",
                                 description="TVHome is your own ad-free launcher: a dock of your apps over rotating "
                                             "nature photos. Hold OK on a tile to move or remove it.")
        g.add(plain(Adw.ActionRow, "Current home screen", self.home or "unknown", subtitle_selectable=True,
                            css_classes=["property"]))
        installed = catalog.CUSTOM_HOME_PKG in self.pkgs
        using = self.home.startswith(catalog.CUSTOM_HOME_PKG + "/")
        fire = self.kind() == "Fire TV"

        def button_row(title, subtitle, label, cb, style=None, sensitive=True):
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER, sensitive=sensitive)
            if style:
                b.add_css_class(style)
            b.connect("clicked", lambda *_: cb())
            row.add_suffix(b)
            g.add(row)

        if not os.path.exists(TVHOME_APK):
            g.add(Adw.ActionRow(title="TVHome.apk not found", subtitle=TVHOME_APK))
        else:
            button_row("TVHome launcher",
                       ("Installed" if installed else "Not installed") +
                       (" · Fire OS doesn't let other launchers replace its home screen" if fire else ""),
                       "Reinstall" if installed else "Install", self.install_tvhome,
                       None if installed else "suggested-action")
        if installed:
            button_row("Use TVHome", "Make TVHome the home screen", "Use", self.use_tvhome, "suggested-action",
                       sensitive=not using)
        stock = self.state.get("stock_home", "")
        button_row("Use the stock home screen", stock or "Switch back to the manufacturer's launcher",
                   "Use", self.use_stock, sensitive=using or not self.home)
        page.add(g)
        self.home_bin.set_child(page)

    def install_tvhome(self):
        def work():
            out = self.dev.install_apk(TVHOME_APK)
            return out, self.dev.packages(), self.dev.home()

        def done(r):
            out, self.pkgs, self.home = r
            self.log("Install TVHome: " + out)
            self.toast("TVHome installed" if "Success" in out else "Install failed, see Log")
            self._refresh_after_change()
        self.run(work, done, busy="Installing TVHome…", hint="Copying an 8 MB app to the device.")

    def use_tvhome(self):
        def work():
            out = self.dev.set_home(catalog.CUSTOM_HOME)
            return out, self.dev.home()
        self.run(work, lambda r: self._home_set(*r))

    def use_stock(self):
        # If the stock launcher was turned off, turn it back on first.
        launchers = [p for p in catalog.STOCK_LAUNCHERS if p in self.pkgs]

        def work():
            off = {p: True for p in launchers if not self.pkgs[p]["enabled"]}
            out = ""
            if off:
                res = self.dev.set_enabled(off)
                out += "\n".join(f"enable {p}: {m}" for p, (_, m) in res.items()) + "\n"
            comp = self.state.get("stock_home") or next(
                (c for c in (self.dev.home_component(p) for p in launchers) if c), "")
            if comp:
                out += self.dev.set_home(comp)
            else:
                out += "No stock launcher found."
            self.pkgs = self.dev.packages()
            return out, self.dev.home()
        self.run(work, lambda r: self._home_set(*r))

    def _home_set(self, out, home):
        self.home = home
        self.log(f"Set home: {out}\nHome is now {home}")
        self.toast(f"Home screen: {home.split('/')[0]}")
        self._refresh_after_change()

    def _refresh_after_change(self):
        self.desired = {p: v for p, v in self.desired.items() if p in self.pkgs and v != self.pkgs[p]["enabled"]}
        self._build_features()
        self._fill_apps()
        self._build_home()
        self._sync()
        self.body.set_visible_child_name("ready")

    # ---- log tab
    def _build_log_tab(self):
        self.log_view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                     top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        return Gtk.ScrolledWindow(child=self.log_view, vexpand=True)

    # ---- menu actions
    def select_recommended(self):
        if not self.pkgs:
            return
        for f in catalog.FEATURES:
            if f.recommend_off:
                for p in self.present(f):
                    self.set_desired(p, False)
        self._sync()
        self.toast("Selected tracking and ad features to turn off. Review, then Apply.")

    def reapply(self):
        if not self.pkgs:
            return
        back_on = [p for p in self.state.get("disabled_by_app", []) if p in self.pkgs and self.pkgs[p]["enabled"]]
        for p in back_on:
            self.set_desired(p, False)
        self._sync()
        self.toast(f"{len(back_on)} apps had been turned back on (usually by a system update). Review, then Apply."
                   if back_on else "Everything you turned off is still off.")

    def restore_all(self):
        if not self.pkgs:
            return
        ours = [p for p in self.state.get("disabled_by_app", []) if p in self.pkgs and not self.pkgs[p]["enabled"]]
        for p in ours:
            self.set_desired(p, True)
        self._sync()
        self.toast(f"Selected {len(ours)} apps to turn back on. Review, then Apply." if ours
                   else "Nothing to restore: this app hasn't turned anything off here.")

    def disconnect(self):
        self.worker.submit(self.dev.close)
        self.pkgs, self.desired = {}, {}
        self.action_bar.set_revealed(False)
        self.win.set_online(self.entry["id"], False)
        self._show_offline()

    # ---- apply
    def confirm_apply(self):
        if not self.desired:
            return
        names = []
        for p, on in sorted(self.desired.items(), key=lambda kv: kv[1]):
            f = catalog.feature_for(p)
            names.append(f"{'Turn on ' if on else 'Turn off'}  {p}" + (f"  ({f.name})" if f else ""))
        warns = {f.warn for f in catalog.FEATURES if f.warn and any(
            p in self.desired and not self.desired[p] for p in f.packages)}
        body = "\n".join(names[:14]) + (f"\n…and {len(names) - 14} more" if len(names) > 14 else "")
        if warns:
            body += "\n\nHeads up:\n" + "\n".join(f"• {w}" for w in sorted(warns))
        dlg = Adw.AlertDialog(heading=f"Apply {len(self.desired)} changes to {self.entry['name']}?", body=body)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("apply", "Apply")
        dlg.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("apply")
        dlg.connect("response", lambda _d, r: r == "apply" and self.apply())
        dlg.present(self.win)

    def apply(self):
        changes = dict(self.desired)
        launchers_off = [p for p, on in changes.items() if p in catalog.STOCK_LAUNCHERS and not on]
        launchers_on = [p for p, on in changes.items() if p in catalog.STOCK_LAUNCHERS and on]
        stock_home = self.state.get("stock_home", "")

        def work():
            log = []
            if launchers_off:  # switch home first, so the TV is never left without one
                log.append("set home: " + self.dev.set_home(catalog.CUSTOM_HOME))
            results = self.dev.set_enabled(changes)
            if launchers_on and not launchers_off:
                comp = stock_home if stock_home.split("/")[0] in launchers_on else ""
                comp = comp or self.dev.home_component(launchers_on[0])
                if comp:
                    log.append("set home: " + self.dev.set_home(comp))
            return results, log, self.dev.packages(), self.dev.home()

        self.run(work, self._applied, busy=f"Applying {len(changes)} changes…")

    def _applied(self, r):
        results, log, self.pkgs, self.home = r
        ours = set(self.state.get("disabled_by_app", []))
        failed = []
        for p, (ok, msg) in results.items():
            self.log(f"{'OK  ' if ok else 'FAIL'} {p}: {msg}")
            if ok:
                (ours.discard if self.pkgs.get(p, {}).get("enabled") else ours.add)(p)
            else:
                failed.append(p)
        for line in log:
            self.log(line)
        self.state["disabled_by_app"] = sorted(ours)
        self.store.save_state(self.entry["id"], self.state)
        self.desired.clear()
        self._refresh_after_change()
        n_ok = len(results) - len(failed)
        if failed:
            self.toast(f"{n_ok} applied, {len(failed)} refused by the device (see Log tab)", timeout=8)
        else:
            self.toast(f"Applied {n_ok} changes")


# ---------------------------------------------------------------- add / edit dialog
class DeviceDialog(Adw.Dialog):
    def __init__(self, win, entry=None):
        super().__init__(title="Edit device" if entry else "Add a device", content_width=480, content_height=600)
        self.win, self.entry = win, entry
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.save_btn = Gtk.Button(label="Save" if entry else "Add", css_classes=["suggested-action"])
        self.save_btn.connect("clicked", lambda *_: self.save())
        header.pack_end(self.save_btn)
        tv.add_top_bar(header)

        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(description="The device must have ADB / network debugging turned on. "
                                             "Its IP address is under Settings → Network on the TV.")
        self.name = Adw.EntryRow(title="Name (optional)", text=entry["name"] if entry else "")
        self.host = Adw.EntryRow(title="IP address", text=entry["host"] if entry else "")
        self.port = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.port.set_title("Port")
        self.port.set_value(entry.get("port", 5555) if entry else 5555)
        self.host.connect("changed", lambda *_: self._validate())
        self.host.connect("entry-activated", lambda *_: self.save())
        for w in (self.name, self.host, self.port):
            g.add(w)
        page.add(g)

        if not entry:
            self.found = Adw.PreferencesGroup(title="On your network",
                                              description="Devices with ADB debugging turned on (port 5555).")
            self.scan_btn = Gtk.Button(label="Scan", valign=Gtk.Align.CENTER, css_classes=["flat"])
            self.scan_btn.connect("clicked", lambda *_: self.scan())
            self.found.set_header_suffix(self.scan_btn)
            page.add(self.found)
            self.found_rows = []
            GLib.idle_add(self.scan)
        tv.set_content(page)
        self.set_child(tv)
        self._validate()

    def _validate(self):
        self.save_btn.set_sensitive(bool(self.host.get_text().strip()))

    def scan(self):
        for r in self.found_rows:
            self.found.remove(r)
        self.found_rows = []
        self.scan_btn.set_sensitive(False)
        spin_row = Adw.ActionRow(title="Scanning…")
        spinner = Adw.Spinner()
        spin_row.add_prefix(spinner)
        self.found.add(spin_row)
        self.found_rows.append(spin_row)
        known = {(d["host"], d.get("port", 5555)) for d in self.win.store.devices}

        def add(ip, name):
            def ui():
                row = plain(Adw.ActionRow, name or ip, ip if name else "", activatable=True)
                row.add_prefix(Gtk.Image(icon_name="video-display-symbolic"))
                if (ip, 5555) in known:
                    row.add_suffix(Gtk.Label(label="already added", css_classes=["dim-label"]))
                row.connect("activated", lambda *_: self._pick(ip, name))
                self.found.add(row)
                self.found_rows.append(row)
                return False
            GLib.idle_add(ui)

        def done(fut):
            def ui():
                spin_row.set_title(f"Found {len(fut.result())} device(s)" if not fut.exception()
                                   else "Scan failed")
                spin_row.set_subtitle("Not listed? Make sure debugging is on, or type the IP address above.")
                spinner.set_visible(False)
                self.scan_btn.set_sensitive(True)
                self.scan_btn.set_label("Scan again")
                return False
            GLib.idle_add(ui)
        self.win.scanner.submit(scan, 5555, add).add_done_callback(done)
        return False

    def _pick(self, ip, name):
        self.host.set_text(ip)
        self.port.set_value(5555)
        if not self.name.get_text() and name:
            self.name.set_text(name.split(".")[0])

    def save(self):
        host = self.host.get_text().strip()
        if not host:
            return
        name = self.name.get_text().strip() or host
        port = int(self.port.get_value())
        if self.entry:
            self.win.update_device(self.entry, name, host, port)
        else:
            self.win.add_device(name, host, port)
        self.close()


# ---------------------------------------------------------------- window
class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="TV Control", default_width=1100, default_height=760)
        self.store = Store()
        self.pages, self.rows, self.online = {}, {}, set()
        self.scanner = concurrent.futures.ThreadPoolExecutor(1)

        split = Adw.NavigationSplitView(min_sidebar_width=240, max_sidebar_width=300)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(split, "collapsed", True)
        self.add_breakpoint(bp)
        self.split = split

        # sidebar
        side = Adw.ToolbarView()
        sh = Adw.HeaderBar()
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add a device")
        add.connect("clicked", lambda *_: DeviceDialog(self).present(self))
        sh.pack_start(add)
        side.add_top_bar(sh)
        self.dev_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.dev_list.connect("row-selected", self._selected)
        side.set_content(Gtk.ScrolledWindow(child=self.dev_list, vexpand=True))
        split.set_sidebar(Adw.NavigationPage(child=side, title="Devices"))

        # content
        self.content = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        empty_tv = Adw.ToolbarView()
        empty_tv.add_top_bar(Adw.HeaderBar(show_title=False))
        b = Gtk.Button(label="Add a device", halign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
        b.connect("clicked", lambda *_: DeviceDialog(self).present(self))
        empty_tv.set_content(Adw.StatusPage(title="No devices", icon_name="video-display-symbolic",
                                            description="Add an Android TV, Google TV, Chromecast or Fire TV.",
                                            child=b))
        self.content.add_named(empty_tv, "empty")
        self.content_page = Adw.NavigationPage(child=self.content, title="TV Control")
        split.set_content(self.content_page)
        self.set_content(split)

        for name, fn in (("recommended", "select_recommended"), ("reapply", "reapply"),
                         ("restore", "restore_all"), ("disconnect", "disconnect")):
            self._action(name, lambda f=fn: self.current() and getattr(self.current(), f)())
        self._action("edit", lambda: self.current() and DeviceDialog(self, self.current().entry).present(self))
        self._action("backups", lambda: self.current() and Gio.AppInfo.launch_default_for_uri(
            GLib.filename_to_uri(self.store.dir(self.current().entry["id"])), None))
        self._action("remove", self.confirm_remove)

        self.refresh_sidebar()

    def _action(self, name, fn):
        a = Gio.SimpleAction.new(name, None)
        a.connect("activate", lambda *_: fn())
        self.add_action(a)

    def current(self):
        row = self.dev_list.get_selected_row()
        return self.pages.get(row.dev_id) if row else None

    def refresh_sidebar(self):
        selected = self.current()
        sel_id = selected.entry["id"] if selected else None
        self.dev_list.remove_all()
        self.rows = {}
        for d in self.store.devices:
            row = plain(Adw.ActionRow, d["name"], d.get("model") or f"{d['host']}:{d.get('port', 5555)}")
            row.add_prefix(Gtk.Image(icon_name="video-display-symbolic"))
            dot = Gtk.Label(label="●", css_classes=["status-dot", "on" if d["id"] in self.online else "off"],
                            tooltip_text="Connected" if d["id"] in self.online else "Not connected")
            row.add_suffix(dot)
            row.dot = dot
            lbr = Gtk.ListBoxRow(child=row)
            lbr.dev_id = d["id"]
            self.rows[d["id"]] = lbr
            self.dev_list.append(lbr)
        if not self.store.devices:
            self.content.set_visible_child_name("empty")
        target = self.rows.get(sel_id) or (self.dev_list.get_row_at_index(0) if self.store.devices else None)
        if target:
            self.dev_list.select_row(target)

    def set_online(self, dev_id, online):
        (self.online.add if online else self.online.discard)(dev_id)
        row = self.rows.get(dev_id)
        if row:
            dot = row.get_child().dot
            dot.remove_css_class("on" if not online else "off")
            dot.add_css_class("on" if online else "off")
            dot.set_tooltip_text("Connected" if online else "Not connected")

    def _selected(self, _lb, row):
        if not row:
            return
        entry = next(d for d in self.store.devices if d["id"] == row.dev_id)
        if entry["id"] not in self.pages:
            page = DevicePage(self, entry)
            self.pages[entry["id"]] = page
            self.content.add_named(page, entry["id"])
        self.content.set_visible_child_name(entry["id"])
        self.content_page.set_title(entry["name"])
        self.split.set_show_content(True)

    def add_device(self, name, host, port):
        entry = {"id": uuid.uuid4().hex[:12], "name": name, "host": host, "port": port}
        self.store.devices.append(entry)
        self.store.save()
        self.refresh_sidebar()
        self.dev_list.select_row(self.rows[entry["id"]])
        self.pages[entry["id"]].load()

    def update_device(self, entry, name, host, port):
        moved = (host, port) != (entry["host"], entry.get("port", 5555))
        entry.update(name=name, host=host, port=port)
        self.store.save()
        page = self.pages.get(entry["id"])
        if page and moved:
            page.disconnect()
            page.dev = Device(host, port)
        if page:
            page.title.set_title(name)
        self.refresh_sidebar()

    def confirm_remove(self):
        page = self.current()
        if not page:
            return
        dlg = Adw.AlertDialog(heading=f"Remove {page.entry['name']}?",
                              body="This only removes it from this list. Nothing changes on the device, and its "
                                   "backups stay in ~/.config/tv-control.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("remove", "Remove")
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r != "remove":
                return
            page.disconnect()
            self.store.devices = [d for d in self.store.devices if d["id"] != page.entry["id"]]
            self.store.save()
            self.content.remove(page)
            del self.pages[page.entry["id"]]
            self.refresh_sidebar()
        dlg.connect("response", resp)
        dlg.present(self)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        quit_ = Gio.SimpleAction.new("quit", None)
        quit_.connect("activate", lambda *_: self.quit())
        self.add_action(quit_)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
