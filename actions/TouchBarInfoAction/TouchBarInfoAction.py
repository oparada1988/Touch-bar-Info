# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python modules
import os
import glob
import subprocess
import datetime
from zoneinfo import ZoneInfo
import requests
import psutil
import json
import math
import random
import io
import base64
import hashlib
from urllib.parse import urlparse, unquote, quote
import dbus
import time
from threading import Thread, Timer
from PIL import Image, ImageDraw, ImageFont

# Import GTK modules
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, Gdk, GLib, Pango
from loguru import logger as log
import globals as gl

class TouchBarInfoAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.last_rendered_key = ""
        self.weather_cache = {}
        self.weather_caches = {}
        self.slot_controls = {}
        self.update_vis_callbacks = []
        self._update_scheduled = False

        # Media Player State & Animation Timer
        self.media_state = {"status": "Stopped", "title": "", "artist": "", "album": "", "art_url": "", "identity": ""}
        self.media_art_cache = {}
        self.media_fetching_urls = set()
        self.num_vis_bars = 32
        self.vis_heights = [0.04] * self.num_vis_bars
        self.vis_speeds = [random.uniform(0.75, 1.35) for _ in range(self.num_vis_bars)]
        self.vis_phases = [random.uniform(0, 6.28) for _ in range(self.num_vis_bars)]
        self.vis_tick = 0
        self.session_bus = None
        self._anim_timer_id = None
        self._last_dbus_poll = 0.0
        self._cached_bg_path = None
        self._cached_bg_image = None

        # System Monitor Stats Buffers
        self.cpu_history = [0.0] * 20
        self.ram_history = [0.0] * 20
        self.net_history = [0.0] * 20
        self.last_net_io = None
        self.net_tx_rate = 0.0
        self.net_rx_rate = 0.0
        self.process_count = 0
        self._was_locked = False
        self.init_options()

    def get_locale_text(self, key: str, default: str) -> str:
        if hasattr(self.plugin_base, "lm") and self.plugin_base.lm is not None:
            try:
                val = self.plugin_base.lm.get(key)
                if val and val != key: return val
            except Exception:
                pass
        if hasattr(self.plugin_base, "locale_manager") and self.plugin_base.locale_manager is not None:
            try:
                val = self.plugin_base.locale_manager.get(key)
                if val and val != key: return val
            except Exception:
                pass
        return default

    def get_available_media_players(self) -> list[tuple[str, str]]:
        bus_players = {}
        try:
            if not self.session_bus:
                self.session_bus = dbus.SessionBus()
            for name in self.session_bus.list_names():
                if name.startswith("org.mpris.MediaPlayer2."):
                    clean_name = name.replace("org.mpris.MediaPlayer2.", "")
                    try:
                        obj = self.session_bus.get_object(name, "/org/mpris/MediaPlayer2")
                        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                        identity = str(props.Get("org.mpris.MediaPlayer2", "Identity"))
                    except Exception:
                        identity = clean_name.capitalize()
                    bus_players[clean_name.lower()] = (clean_name, identity)
        except Exception:
            pass

        app_dirs = [
            "/run/host/usr/share/applications",
            "/run/host/usr/local/share/applications",
            "/run/host/var/lib/flatpak/exports/share/applications",
            os.path.expanduser("~/.local/share/applications"),
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
            "/usr/share/applications",
            "/usr/local/share/applications",
            "/var/lib/flatpak/exports/share/applications"
        ]

        desktop_files = []
        for d in app_dirs:
            if os.path.isdir(d):
                try:
                    desktop_files.extend(glob.glob(os.path.join(d, "*.desktop")))
                except Exception:
                    pass

        known_players = [
            ("spotify", "Spotify", ["*spotify*.desktop"]),
            ("chrome", "Chrome / Chromium", ["*google-chrome*.desktop", "*chromium*.desktop", "*brave*.desktop"]),
            ("firefox", "Firefox", ["*firefox*.desktop", "*zen*.desktop"]),
            ("vlc", "VLC Media Player", ["*vlc*.desktop"]),
            ("rhythmbox", "Rhythmbox", ["*rhythmbox*.desktop"]),
            ("cider", "Cider", ["*cider*.desktop"]),
            ("amberol", "Amberol", ["*amberol*.desktop"]),
            ("celluloid", "Celluloid", ["*celluloid*.desktop"]),
        ]

        detected = [("auto", self.get_locale_text("actions.touchbar-info.media-player-auto", "Active Player (Automatic)"))]
        seen_keys = set(["auto"])

        for key, label, patterns in known_players:
            found = False
            for p in patterns:
                for df in desktop_files:
                    fname = os.path.basename(df).lower()
                    if glob.fnmatch.fnmatch(fname, p.lower()):
                        found = True
                        break
                if found:
                    break
            if found:
                detected.append((key, label))
                seen_keys.add(key)

        for bkey, (clean_name, identity) in bus_players.items():
            matched = False
            for sk in seen_keys:
                if sk in bkey or bkey in sk:
                    matched = True
                    break
            if not matched:
                detected.append((bkey, identity))
                seen_keys.add(bkey)

        return detected

    def init_options(self):
        # Alphabetical Full Section Widget List
        self.full_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.blank", "Blank / None"),
            self.get_locale_text("actions.touchbar-info.widget.cpu", "CPU Usage"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.disk", "Disk Usage"),
            self.get_locale_text("actions.touchbar-info.widget.media", "Media Player"),
            self.get_locale_text("actions.touchbar-info.widget.network", "Network Activity"),
            self.get_locale_text("actions.touchbar-info.widget.ram", "RAM Usage"),
            self.get_locale_text("actions.touchbar-info.widget.stacked", "Stacked Date & Time"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time"),
            self.get_locale_text("actions.touchbar-info.widget.weather", "Weather"),
            self.get_locale_text("actions.touchbar-info.widget.worldclock", "World Clock")
        ]

        # Alphabetical Split Subsection Widget List
        self.split_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.blank", "Blank / None"),
            self.get_locale_text("actions.touchbar-info.widget.cpu", "CPU Usage"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.disk", "Disk Usage"),
            self.get_locale_text("actions.touchbar-info.widget.media", "Media Player"),
            self.get_locale_text("actions.touchbar-info.widget.network", "Network Activity"),
            self.get_locale_text("actions.touchbar-info.widget.ram", "RAM Usage"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time"),
            self.get_locale_text("actions.touchbar-info.widget.weather", "Weather"),
            self.get_locale_text("actions.touchbar-info.widget.worldclock", "World Clock")
        ]

        self.section_mode_options = [
            self.get_locale_text("actions.touchbar-info.mode.full", "Full Section (100px)"),
            self.get_locale_text("actions.touchbar-info.mode.split", "Split Top / Bottom (2x 50px)")
        ]

        self.date_format_options = [
            ("%a, %b %d", "Mon, Oct 24"),
            ("%A, %b %d", "Monday, Oct 24"),
            ("%b %d, %Y", "Oct 24, 2026"),
            ("%m/%d/%Y", "10/24/2026"),
            ("%d/%m/%Y", "24/10/2026"),
            ("%Y-%m-%d", "2026-10-24")
        ]

        self.weather_units = [
            self.get_locale_text("actions.touchbar-info.weather-unit.f", "Fahrenheit (°F)"),
            self.get_locale_text("actions.touchbar-info.weather-unit.c", "Celsius (°C)")
        ]

        self.weather_intervals = [
            self.get_locale_text("actions.touchbar-info.weather-ref.5m", "Every 5 minutes"),
            self.get_locale_text("actions.touchbar-info.weather-ref.10m", "Every 10 minutes"),
            self.get_locale_text("actions.touchbar-info.weather-ref.15m", "Every 15 minutes"),
            self.get_locale_text("actions.touchbar-info.weather-ref.30m", "Every 30 minutes"),
            self.get_locale_text("actions.touchbar-info.weather-ref.1h", "Every 1 hour")
        ]

        self.cpu_mode_options = [
            self.get_locale_text("actions.touchbar-info.cpu-mode.pct", "Percentage (%)"),
            self.get_locale_text("actions.touchbar-info.cpu-mode.procs", "Percentage & Process Count"),
            self.get_locale_text("actions.touchbar-info.cpu-mode.graph", "Live Activity Graph")
        ]

        self.net_mode_options = [
            self.get_locale_text("actions.touchbar-info.net-mode.rates", "Download / Upload Rates"),
            self.get_locale_text("actions.touchbar-info.net-mode.graph", "Live Bandwidth Graph")
        ]

        self.net_unit_options = [
            self.get_locale_text("actions.touchbar-info.net-unit.bytes", "Bytes/s (KB/s, MB/s)"),
            self.get_locale_text("actions.touchbar-info.net-unit.bits", "Bits/s (Kbps, Mbps)")
        ]

        self.ram_mode_options = [
            self.get_locale_text("actions.touchbar-info.ram-mode.pct", "Percentage (%)"),
            self.get_locale_text("actions.touchbar-info.ram-mode.gb", "Used / Total GB"),
            self.get_locale_text("actions.touchbar-info.ram-mode.graph", "Live Memory Graph")
        ]

        self.disk_mode_options = [
            self.get_locale_text("actions.touchbar-info.disk-mode.pct", "Percentage (%) Used"),
            self.get_locale_text("actions.touchbar-info.disk-mode.gb", "Used / Total GB"),
            self.get_locale_text("actions.touchbar-info.disk-mode.graph", "Mini Space Bar Graph")
        ]

        self.worldclock_cities = [
            ("London (UTC+0/+1)", "Europe/London"),
            ("New York (UTC-5/-4)", "America/New_York"),
            ("Los Angeles (UTC-8/-7)", "America/Los_Angeles"),
            ("Chicago (UTC-6/-5)", "America/Chicago"),
            ("Denver (UTC-7/-6)", "America/Denver"),
            ("Tokyo (UTC+9)", "Asia/Tokyo"),
            ("Paris (UTC+1/+2)", "Europe/Paris"),
            ("Berlin (UTC+1/+2)", "Europe/Berlin"),
            ("Sydney (UTC+10/+11)", "Australia/Sydney"),
            ("Auckland (UTC+12/+13)", "Pacific/Auckland"),
            ("Hong Kong (UTC+8)", "Asia/Hong_Kong"),
            ("Singapore (UTC+8)", "Asia/Singapore"),
            ("Dubai (UTC+4)", "Asia/Dubai"),
            ("Honolulu (UTC-10)", "Pacific/Honolulu"),
            ("UTC (Universal Time)", "UTC"),
            ("Custom Timezone...", "custom")
        ]

        self.worldclock_view_options = [
            self.get_locale_text("actions.touchbar-info.worldclock-view.digital", "Digital Clock Face"),
            self.get_locale_text("actions.touchbar-info.worldclock-view.analog", "Analog Clock Dial")
        ]

        self.media_vis_options = [
            self.get_locale_text("actions.touchbar-info.media-vis.bars", "Stepped Equalizer Bars"),
            self.get_locale_text("actions.touchbar-info.media-vis.waves", "Flowing Wave Curves")
        ]

        self.media_color_mode_options = [
            self.get_locale_text("actions.touchbar-info.media-colormode.solid", "Solid Color"),
            self.get_locale_text("actions.touchbar-info.media-colormode.gradient", "Dynamic Gradient (3 Colors)")
        ]

        media_players_list = self.get_available_media_players()
        self.media_player_options = [label for _, label in media_players_list]
        self.media_player_ids = [pid for pid, _ in media_players_list]

        self.disk_mounts = self.get_system_disk_mounts()

    def get_system_disk_mounts(self) -> list[tuple[str, str]]:
        disks = []
        seen = set()

        def add_target(mount_path, dev_name="", src=""):
            if not mount_path or mount_path in seen:
                return
            cleaned = os.path.normpath(mount_path)
            if cleaned != "/" and (cleaned.startswith(('/proc', '/sys', '/dev', '/run/user', '/var/lib/flatpak', '/app')) or '.flatpak' in cleaned):
                return
            seen.add(mount_path)

            if mount_path == "/":
                disp = "System Root (/)"
            elif mount_path.startswith("/home"):
                base = os.path.basename(mount_path.rstrip("/"))
                disp = f"Home ({base})" if base and base != "home" else "Home (/home)"
            else:
                base = os.path.basename(mount_path.rstrip("/"))
                disp = f"{base.capitalize()} ({mount_path})" if base else mount_path

            if dev_name and not dev_name.startswith('/dev/loop'):
                dev_base = os.path.basename(dev_name)
                disp += f" [{dev_base}]"

            disks.append((mount_path, disp))

        ignored_fstypes = {'tmpfs', 'devtmpfs', 'squashfs', 'overlay', 'proc', 'sysfs', 'securityfs', 'cgroup', 'cgroup2', 'pstore', 'bpf', 'autofs', 'ramfs', 'hugetlbfs', 'mqueue', 'debugfs', 'tracefs', 'fuse.portal', 'fuse.gvfsd-fuse'}

        host_env = dict(os.environ)
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        if "DBUS_SESSION_BUS_ADDRESS" not in host_env or not host_env["DBUS_SESSION_BUS_ADDRESS"]:
            host_env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        if "XDG_RUNTIME_DIR" not in host_env or not host_env["XDG_RUNTIME_DIR"]:
            host_env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"

        try:
            p = subprocess.run(['flatpak-spawn', '--host', '--directory=/', 'cat', '/proc/mounts'], capture_output=True, text=True, timeout=3, env=host_env)
            if p.stdout:
                for line in p.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        dev, m, fs = parts[0], parts[1], parts[2]
                        if dev.startswith('/dev/') and fs not in ignored_fstypes:
                            add_target(m, dev, "proc_mounts")
        except Exception:
            pass

        try:
            p = subprocess.run(['flatpak-spawn', '--host', '--directory=/', 'df', '-k'], capture_output=True, text=True, timeout=3, env=host_env)
            if p.stdout:
                for line in p.stdout.splitlines()[1:]:
                    parts = line.split()
                    if parts:
                        dev = parts[0]
                        m = parts[-1]
                        if dev.startswith('/dev/'):
                            add_target(m, dev, "df")
        except Exception:
            pass

        try:
            p = subprocess.run(['flatpak-spawn', '--host', '--directory=/', 'lsblk', '-r', '-o', 'NAME,MOUNTPOINT,FSTYPE'], capture_output=True, text=True, timeout=3, env=host_env)
            if p.stdout:
                for line in p.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 2:
                        dev_name, m = parts[0], parts[1]
                        fs = parts[2] if len(parts) >= 3 else 'ext4'
                        if fs not in ignored_fstypes:
                            add_target(m, f'/dev/{dev_name}', "lsblk")
        except Exception:
            pass

        try:
            p = subprocess.run(['flatpak-spawn', '--host', '--directory=/', 'ls', '-d', '/mnt/*', '/media/*', '/run/media/*/*'], capture_output=True, text=True, timeout=3, env=host_env)
            if p.stdout:
                for line in p.stdout.splitlines():
                    path = line.strip()
                    if path and not path.startswith(('/proc', '/sys', '/dev')) and '*' not in path:
                        add_target(path, "", "dir_scan")
        except Exception:
            pass

        if len(disks) <= 1:
            try:
                label_dir = "/dev/disk/by-label"
                if os.path.exists(label_dir):
                    for lbl in os.listdir(label_dir):
                        dev = os.path.realpath(os.path.join(label_dir, lbl))
                        for candidate in [f"/mnt/{lbl}", f"/media/{lbl}", f"/run/media/{lbl}", f"/media/{os.environ.get('USER', 'oscar')}/{lbl}"]:
                            if os.path.exists(candidate):
                                add_target(candidate, dev, "by_label_fallback")
                for known_path in ["/mnt/Games", "/mnt/Stuff", "/home"]:
                    if known_path not in seen and os.path.exists(known_path):
                        add_target(known_path, "", "known_fallback")
            except Exception:
                pass

        if "/" not in seen:
            add_target("/", "", "default_root")

        return disks

    def get_weather_icon_filename(self, wmo_code: int, is_day: int = 1) -> str:
        if wmo_code in [0, 1]:
            return "sunny.png" if is_day == 1 else "clear_night.png"
        elif wmo_code == 2:
            return "partly_cloudy.png" if is_day == 1 else "cloudy_night.png"
        elif wmo_code == 3:
            return "cloud.png"
        elif wmo_code in [45, 48]:
            return "foggy.png"
        elif wmo_code in [51, 53, 55, 56, 57, 61]:
            return "rainy_light.png"
        elif wmo_code in [63, 80, 81]:
            return "rainy.png"
        elif wmo_code in [65, 66, 67, 82]:
            return "rainy_heavy.png"
        elif wmo_code in [71, 73, 77]:
            return "snowy.png"
        elif wmo_code in [75, 85, 86]:
            return "cloudy-snowing.png"
        elif wmo_code in [95, 96, 99]:
            return "thunderstorm.png"
        return "sunny.png" if is_day == 1 else "clear_night.png"

    def get_slot_setting(self, settings: dict, slot_key: str, sub_key: str, default):
        if settings is None:
            return default
        full_k = f"{slot_key}_{sub_key}"
        if full_k in settings:
            return settings[full_k]
        if sub_key in settings:
            return settings[sub_key]
        return default

    def set_slot_setting(self, slot_key: str, sub_key: str, val):
        settings = self.get_settings()
        if settings is not None:
            settings[f"{slot_key}_{sub_key}"] = val
            self.set_settings(settings)
            if hasattr(self, "_font_cache"):
                self._font_cache.clear()
            self.trigger_redraw()

    def fetch_weather_async(self, force: bool = False):
        if self.handle_lock_blanking():
            return
        now_ts = datetime.datetime.now().timestamp()
        refresh_intervals = [300, 600, 900, 1800, 3600]
        settings = self.get_settings() or {}

        slots_to_check = [
            ("sec_a_full", True), ("sec_a_top", False), ("sec_a_bot", False),
            ("sec_b_full", True), ("sec_b_top", False), ("sec_b_bot", False),
            ("sec_c_full", True), ("sec_c_top", False), ("sec_c_bot", False)
        ]

        weather_targets = []
        for slot_key, is_full in slots_to_check:
            prefix = slot_key[:5] # "sec_a", "sec_b", "sec_c"
            sec_mode = self.get_slot_setting(settings, prefix, "mode", 0)
            if is_full and sec_mode != 0:
                continue
            if not is_full and sec_mode == 0:
                continue

            w_choice = self.get_slot_setting(settings, slot_key, "widget", 0)
            if (is_full and w_choice == 9) or (not is_full and w_choice == 8):
                lat = self.get_slot_setting(settings, slot_key, "weather_lat", "25.7617")
                lon = self.get_slot_setting(settings, slot_key, "weather_lon", "-80.1918")
                unit_idx = self.get_slot_setting(settings, slot_key, "weather_unit_idx", 0)
                ref_idx = self.get_slot_setting(settings, slot_key, "weather_refresh_idx", 2)
                loc_name = self.get_slot_setting(settings, slot_key, "weather_location_name", "Miami")
                interval_sec = refresh_intervals[min(ref_idx, len(refresh_intervals) - 1)]
                weather_targets.append((lat, lon, unit_idx, interval_sec, loc_name))

        if not weather_targets:
            lat = settings.get("weather_lat", "25.7617")
            lon = settings.get("weather_lon", "-80.1918")
            unit_idx = settings.get("weather_unit_idx", 0)
            ref_idx = settings.get("weather_refresh_idx", 2)
            loc_name = settings.get("weather_location_name", "Miami")
            interval_sec = refresh_intervals[min(ref_idx, len(refresh_intervals) - 1)]
            weather_targets.append((lat, lon, unit_idx, interval_sec, loc_name))

        for lat, lon, unit_idx, interval_sec, loc_name in weather_targets:
            temp_unit = "fahrenheit" if unit_idx == 0 else "celsius"
            cache_key = f"{lat}_{lon}_{temp_unit}"
            cached = self.weather_caches.get(cache_key)
            if not force and cached:
                last_ts = cached.get("last_fetch", 0)
                if (now_ts - last_ts) < interval_sec:
                    continue

            def make_task(t_lat=lat, t_lon=lon, t_unit=temp_unit, t_name=loc_name, c_key=cache_key):
                def task():
                    try:
                        url = f"https://api.open-meteo.com/v1/forecast?latitude={t_lat}&longitude={t_lon}&current=temperature_2m,weather_code,is_day&temperature_unit={t_unit}"
                        resp = requests.get(url, timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            curr = data.get("current", {})
                            temp = curr.get("temperature_2m", None)
                            code = curr.get("weather_code", 0)
                            is_day = curr.get("is_day", 1)
                            temp_str = f"{round(temp)}°" if temp is not None else "--°"
                            res_dict = {
                                "last_fetch": datetime.datetime.now().timestamp(),
                                "temp_str": temp_str,
                                "wmo_code": code,
                                "is_day": is_day,
                                "location": t_name
                            }
                            self.weather_caches[c_key] = res_dict
                            self.weather_cache = res_dict
                            GLib.idle_add(self.trigger_redraw)
                    except Exception as e:
                        log.error(f"TouchBarInfo: Failed to fetch weather for {t_name}: {e}")
                return task

            Thread(target=make_task(), daemon=True).start()

    def get_config_rows(self) -> "list[Adw.PreferencesRow]":
        self.update_vis_callbacks = []
        self.slot_controls = {}
        self.init_options()

        try:
            css_provider = Gtk.CssProvider()
            css_provider.load_from_data(b"""
                .touchbar-subhdr-row {
                    background-color: rgba(255, 255, 255, 0.05);
                    border-radius: 6px;
                    margin-top: 4px;
                    margin-bottom: 2px;
                }
            """)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception:
            pass

        # Helper to create Date controls with ExpanderRow
        def build_date_controls(slot_key: str):
            date_expander = Adw.ExpanderRow(
                title=self.get_locale_text("actions.touchbar-info.hdr-date.label", "Date Settings"),
                subtitle=self.get_locale_text("actions.touchbar-info.hdr-date.subtitle", "Format and typography configuration for date display")
            )
            date_expander.add_css_class("touchbar-subhdr-row")

            fmt_model = Gtk.StringList()
            for _, label in self.date_format_options: fmt_model.append(label)
            fmt_combo = Adw.ComboRow(
                model=fmt_model,
                title=self.get_locale_text("actions.touchbar-info.date-format.label", "Date Format"),
                subtitle=self.get_locale_text("actions.touchbar-info.date-format.subtitle", "Format style for date text")
            )
            fmt_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "date_format_idx", combo.get_selected()))

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(True)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_btn.connect("font-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "date_font_str", btn.get_font()))
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )
            fill_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "date_fill_enabled", sw.get_active()),
                fill_color_row.set_sensitive(sw.get_active())
            ))

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "date_font_color", self.gdk_to_hex(btn.get_rgba())))
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )
            out_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "date_outline_enabled", sw.get_active()),
                out_color_row.set_sensitive(sw.get_active()),
                out_size_spin.set_sensitive(sw.get_active())
            ))

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "date_outline_color", self.gdk_to_hex(btn.get_rgba())))
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))
            out_size_spin.connect("notify::value", lambda spin, pspec, sk=slot_key: self.set_slot_setting(sk, "date_outline_size", int(spin.get_value())))

            date_expander.add_row(fmt_combo)
            date_expander.add_row(font_row)
            date_expander.add_row(fill_sw)
            date_expander.add_row(fill_color_row)
            date_expander.add_row(out_sw)
            date_expander.add_row(out_color_row)
            date_expander.add_row(out_size_spin)

            return {
                "date_expander": date_expander, "fmt_combo": fmt_combo, "font_btn": font_btn,
                "fill_sw": fill_sw, "fill_color_btn": fill_color_btn, "fill_color_row": fill_color_row,
                "out_sw": out_sw, "out_color_btn": out_color_btn, "out_color_row": out_color_row,
                "out_size_spin": out_size_spin, "all_rows": [date_expander]
            }

        # Helper to create Time controls with ExpanderRow
        def build_time_controls(slot_key: str):
            time_expander = Adw.ExpanderRow(
                title=self.get_locale_text("actions.touchbar-info.hdr-time.label", "Time Settings"),
                subtitle=self.get_locale_text("actions.touchbar-info.hdr-time.subtitle", "Format and typography configuration for clock display")
            )
            time_expander.add_css_class("touchbar-subhdr-row")

            sw_24h = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.use-24h.label", "Use 24-Hour Clock"),
                subtitle=self.get_locale_text("actions.touchbar-info.use-24h.subtitle", "Switch between 12-hour (AM/PM) and 24-hour time format")
            )
            sw_24h.connect("notify::active", lambda sw, pspec, sk=slot_key: self.set_slot_setting(sk, "use_24h", sw.get_active()))

            sw_sec = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.show-seconds.label", "Show Seconds"),
                subtitle=self.get_locale_text("actions.touchbar-info.show-seconds.subtitle", "Include seconds in the displayed time")
            )
            sw_sec.connect("notify::active", lambda sw, pspec, sk=slot_key: self.set_slot_setting(sk, "show_seconds", sw.get_active()))

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(True)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_btn.connect("font-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "time_font_str", btn.get_font()))
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )
            fill_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "time_fill_enabled", sw.get_active()),
                fill_color_row.set_sensitive(sw.get_active())
            ))

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "time_font_color", self.gdk_to_hex(btn.get_rgba())))
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )
            out_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "time_outline_enabled", sw.get_active()),
                out_color_row.set_sensitive(sw.get_active()),
                out_size_spin.set_sensitive(sw.get_active())
            ))

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "time_outline_color", self.gdk_to_hex(btn.get_rgba())))
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))
            out_size_spin.connect("notify::value", lambda spin, pspec, sk=slot_key: self.set_slot_setting(sk, "time_outline_size", int(spin.get_value())))

            time_expander.add_row(sw_24h)
            time_expander.add_row(sw_sec)
            time_expander.add_row(font_row)
            time_expander.add_row(fill_sw)
            time_expander.add_row(fill_color_row)
            time_expander.add_row(out_sw)
            time_expander.add_row(out_color_row)
            time_expander.add_row(out_size_spin)

            return {
                "time_expander": time_expander, "sw_24h": sw_24h, "sw_sec": sw_sec, "font_btn": font_btn,
                "fill_sw": fill_sw, "fill_color_btn": fill_color_btn, "fill_color_row": fill_color_row,
                "out_sw": out_sw, "out_color_btn": out_color_btn, "out_color_row": out_color_row,
                "out_size_spin": out_size_spin, "all_rows": [time_expander]
            }

        # Helper to create Weather controls
        def build_weather_controls(slot_key: str):
            loc_entry = Adw.EntryRow(
                title=self.get_locale_text("actions.touchbar-info.weather-location.label", "City / Location Search")
            )
            search_btn = Gtk.Button(label=self.get_locale_text("actions.touchbar-info.weather-search.button", "Search"))
            search_btn.set_valign(Gtk.Align.CENTER)
            loc_entry.add_suffix(search_btn)

            res_model = Gtk.StringList()
            res_combo = Adw.ComboRow(
                model=res_model,
                title=self.get_locale_text("actions.touchbar-info.weather-results.label", "Select Matching Location"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-results.subtitle", "Choose city from Open-Meteo search results")
            )
            res_combo.set_visible(False)

            slot_search_data = []

            def on_search_clicked(btn):
                query = loc_entry.get_text().strip()
                if not query:
                    return
                def search_task():
                    try:
                        url = f"https://geocoding-api.open-meteo.com/v1/search?name={quote(query)}&count=5&language=en&format=json"
                        resp = requests.get(url, timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            results = data.get("results", [])
                            def update_ui():
                                slot_search_data.clear()
                                while res_model.get_n_items() > 0:
                                    res_model.remove(0)
                                if results:
                                    for item in results:
                                        c_name = item.get("name", "")
                                        admin = item.get("admin1", "")
                                        country = item.get("country", "")
                                        lat = str(item.get("latitude", ""))
                                        lon = str(item.get("longitude", ""))
                                        parts = [p for p in [c_name, admin, country] if p]
                                        label = ", ".join(parts)
                                        res_model.append(label)
                                        slot_search_data.append((c_name, lat, lon))
                                    res_combo.set_visible(True)
                                else:
                                    res_combo.set_visible(False)
                            GLib.idle_add(update_ui)
                    except Exception as e:
                        log.error(f"TouchBarInfo: Location search error: {e}")
                Thread(target=search_task, daemon=True).start()

            search_btn.connect("clicked", on_search_clicked)

            def on_res_selected(combo, pspec):
                sel = combo.get_selected()
                if 0 <= sel < len(slot_search_data):
                    c_name, lat, lon = slot_search_data[sel]
                    loc_entry.set_text(c_name)
                    settings = self.get_settings()
                    if settings is not None:
                        settings[f"{slot_key}_weather_location_name"] = c_name
                        settings[f"{slot_key}_weather_lat"] = lat
                        settings[f"{slot_key}_weather_lon"] = lon
                        self.set_settings(settings)
                        self.fetch_weather_async(force=True)
                        self.trigger_redraw()

            res_combo.connect("notify::selected", on_res_selected)

            unit_model = Gtk.StringList()
            for u in self.weather_units: unit_model.append(u)
            unit_combo = Adw.ComboRow(
                model=unit_model,
                title=self.get_locale_text("actions.touchbar-info.weather-unit.label", "Temperature Unit"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-unit.subtitle", "Select Fahrenheit (°F) or Celsius (°C)")
            )
            unit_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "weather_unit_idx", combo.get_selected()),
                self.fetch_weather_async(force=True)
            ))

            ref_model = Gtk.StringList()
            for r in self.weather_intervals: ref_model.append(r)
            ref_combo = Adw.ComboRow(
                model=ref_model,
                title=self.get_locale_text("actions.touchbar-info.weather-refresh.label", "Refresh Interval"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-refresh.subtitle", "Automatic weather update frequency")
            )
            ref_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "weather_refresh_idx", combo.get_selected()))

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(True)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_btn.connect("font-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "weather_font_str", btn.get_font()))
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )
            fill_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "weather_fill_enabled", sw.get_active()),
                fill_color_row.set_sensitive(sw.get_active())
            ))

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "weather_font_color", self.gdk_to_hex(btn.get_rgba())))
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )
            out_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "weather_outline_enabled", sw.get_active()),
                out_color_row.set_sensitive(sw.get_active()),
                out_size_spin.set_sensitive(sw.get_active())
            ))

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "weather_outline_color", self.gdk_to_hex(btn.get_rgba())))
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))
            out_size_spin.connect("notify::value", lambda spin, pspec, sk=slot_key: self.set_slot_setting(sk, "weather_outline_size", int(spin.get_value())))

            return {
                "loc_entry": loc_entry, "res_combo": res_combo, "unit_combo": unit_combo,
                "ref_combo": ref_combo, "font_btn": font_btn, "fill_sw": fill_sw,
                "fill_color_btn": fill_color_btn, "fill_color_row": fill_color_row, "out_sw": out_sw,
                "out_color_btn": out_color_btn, "out_color_row": out_color_row, "out_size_spin": out_size_spin,
                "all_rows": [loc_entry, res_combo, unit_combo, ref_combo, font_row, fill_sw, fill_color_row, out_sw, out_color_row, out_size_spin]
            }

        # Helper to create CPU controls
        def build_cpu_controls(slot_key: str):
            mode_model = Gtk.StringList()
            for opt in self.cpu_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.cpu-mode.label", "CPU Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.cpu-mode.subtitle", "Choose percentage, processes, or live graph")
            )
            mode_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "cpu_mode_idx", combo.get_selected()))
            return {"mode_combo": mode_combo, "all_rows": [mode_combo]}

        # Helper to create Network controls
        def build_net_controls(slot_key: str):
            mode_model = Gtk.StringList()
            for opt in self.net_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.net-mode.label", "Network Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.net-mode.subtitle", "Choose download/upload rates or live graph")
            )
            mode_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "net_mode_idx", combo.get_selected()))

            unit_model = Gtk.StringList()
            for opt in self.net_unit_options: unit_model.append(opt)
            unit_combo = Adw.ComboRow(
                model=unit_model,
                title=self.get_locale_text("actions.touchbar-info.net-unit.label", "Network Speed Unit"),
                subtitle=self.get_locale_text("actions.touchbar-info.net-unit.subtitle", "Choose Bytes (KB/s, MB/s) or Bits (Kbit/s, Mbit/s)")
            )
            unit_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "net_unit_idx", combo.get_selected()))

            return {"mode_combo": mode_combo, "unit_combo": unit_combo, "all_rows": [mode_combo, unit_combo]}

        # Helper to create RAM controls
        def build_ram_controls(slot_key: str):
            mode_model = Gtk.StringList()
            for opt in self.ram_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.ram-mode.label", "RAM Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.ram-mode.subtitle", "Choose percentage, GB used/total, or live graph")
            )
            mode_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "ram_mode_idx", combo.get_selected()))
            return {"mode_combo": mode_combo, "all_rows": [mode_combo]}

        # Helper to create Disk controls
        def build_disk_controls(slot_key: str):
            mount_model = Gtk.StringList()
            for _, d_name in self.disk_mounts: mount_model.append(d_name)
            mount_combo = Adw.ComboRow(
                model=mount_model,
                title=self.get_locale_text("actions.touchbar-info.disk-select.label", "Disk"),
                subtitle=self.get_locale_text("actions.touchbar-info.disk-select.subtitle", "Select storage drive to monitor")
            )
            refresh_btn = Gtk.Button(label=self.get_locale_text("actions.touchbar-info.disk-refresh.choose", "Refresh"))
            refresh_btn.set_valign(Gtk.Align.CENTER)
            refresh_btn.connect("clicked", lambda btn: self.refresh_all_disk_combos())
            mount_combo.add_suffix(refresh_btn)

            def on_mount_changed(combo, pspec):
                sel = combo.get_selected()
                if 0 <= sel < len(self.disk_mounts):
                    m_path = self.disk_mounts[sel][0]
                    settings = self.get_settings()
                    if settings is not None:
                        settings[f"{slot_key}_disk_mount_idx"] = sel
                        settings[f"{slot_key}_disk_mount_path"] = m_path
                        self.set_settings(settings)
                        self.trigger_redraw()

            mount_combo.connect("notify::selected", on_mount_changed)

            mode_model = Gtk.StringList()
            for opt in self.disk_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.disk-mode.label", "Disk Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.disk-mode.subtitle", "Choose percentage, GB used/free, or mini graph")
            )
            mode_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "disk_mode_idx", combo.get_selected()))

            browse_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.disk-custom.label", "Custom Folder / Partition"),
                subtitle=self.get_locale_text("actions.touchbar-info.disk-custom.subtitle", "Select custom folder or drive mount using native folder picker")
            )
            browse_btn = Gtk.Button(label=self.get_locale_text("actions.touchbar-info.disk-custom.choose", "Browse Folder..."))
            browse_btn.set_valign(Gtk.Align.CENTER)

            def on_browse_clicked(btn):
                def _file_dialog_callback(dialog, result):
                    try:
                        folder = dialog.select_folder_finish(result)
                        if folder is not None:
                            folder_path = folder.get_path()
                            if folder_path:
                                settings = self.get_settings()
                                if settings is not None:
                                    settings[f"{slot_key}_disk_mount_path"] = folder_path
                                    self.set_settings(settings)
                                    browse_row.set_subtitle(f"Selected: {folder_path}")
                                    self.trigger_redraw()
                    except Exception as e:
                        log.error(f"TouchBarInfo: Folder selection error: {e}")

                try:
                    native_dialog = Gtk.FileDialog.new()
                    native_dialog.set_title(self.get_locale_text("actions.touchbar-info.disk-dialog.title", "Select Folder / Partition to Monitor"))
                    native_dialog.select_folder(None, None, _file_dialog_callback)
                except Exception as e:
                    log.error(f"TouchBarInfo: Failed to open FileDialog: {e}")

            browse_btn.connect("clicked", on_browse_clicked)
            browse_row.add_suffix(browse_btn)

            return {
                "mount_combo": mount_combo, "mode_combo": mode_combo, "browse_row": browse_row,
                "all_rows": [mount_combo, mode_combo, browse_row]
            }

        # Helper to create World Clock controls
        def build_worldclock_controls(slot_key: str):
            city_model = Gtk.StringList()
            for c_name, _ in self.worldclock_cities: city_model.append(c_name)
            city_combo = Adw.ComboRow(
                model=city_model,
                title=self.get_locale_text("actions.touchbar-info.worldclock-city.label", "Target City"),
                subtitle=self.get_locale_text("actions.touchbar-info.worldclock-city.subtitle", "Select a world city for this clock")
            )
            city_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "worldclock_city_idx", combo.get_selected()),
                self.notify_visibility_change()
            ))

            view_model = Gtk.StringList()
            for opt in self.worldclock_view_options: view_model.append(opt)
            view_combo = Adw.ComboRow(
                model=view_model,
                title=self.get_locale_text("actions.touchbar-info.worldclock-view.label", "Clock View Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.worldclock-view.subtitle", "Choose Digital text or Analog round clock face")
            )
            view_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "worldclock_view", combo.get_selected()))

            label_entry = Adw.EntryRow(
                title=self.get_locale_text("actions.touchbar-info.worldclock-custom-label.label", "Custom City Label")
            )
            label_entry.connect("changed", lambda entry, sk=slot_key: self.set_slot_setting(sk, "worldclock_custom_label", entry.get_text()))

            tz_entry = Adw.EntryRow(
                title=self.get_locale_text("actions.touchbar-info.worldclock-custom-tz.label", "Custom IANA Timezone")
            )
            tz_entry.connect("changed", lambda entry, sk=slot_key: self.set_slot_setting(sk, "worldclock_custom_tz", entry.get_text()))

            sec_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.worldclock-show-seconds.label", "Show Seconds"),
                subtitle=self.get_locale_text("actions.touchbar-info.worldclock-show-seconds.subtitle", "Include seconds in the world clock display")
            )
            sec_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: self.set_slot_setting(sk, "worldclock_show_seconds", sw.get_active()))

            offset_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.worldclock-show-offset.label", "Show Time Offset and Day"),
                subtitle=self.get_locale_text("actions.touchbar-info.worldclock-show-offset.subtitle", "Display time difference relative to local time (e.g. +5h, Tomorrow)")
            )
            offset_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: self.set_slot_setting(sk, "worldclock_show_offset", sw.get_active()))

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(True)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_btn.connect("font-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "worldclock_font_str", btn.get_font()))
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )
            fill_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "worldclock_fill_enabled", sw.get_active()),
                fill_color_row.set_sensitive(sw.get_active())
            ))

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "worldclock_font_color", self.gdk_to_hex(btn.get_rgba())))
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )
            out_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "worldclock_outline_enabled", sw.get_active()),
                out_color_row.set_sensitive(sw.get_active()),
                out_size_spin.set_sensitive(sw.get_active())
            ))

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "worldclock_outline_color", self.gdk_to_hex(btn.get_rgba())))
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))
            out_size_spin.connect("notify::value", lambda spin, pspec, sk=slot_key: self.set_slot_setting(sk, "worldclock_outline_size", int(spin.get_value())))

            return {
                "city_combo": city_combo, "view_combo": view_combo, "label_entry": label_entry, "tz_entry": tz_entry,
                "sec_sw": sec_sw, "offset_sw": offset_sw, "font_btn": font_btn,
                "fill_sw": fill_sw, "fill_color_btn": fill_color_btn, "fill_color_row": fill_color_row,
                "out_sw": out_sw, "out_color_btn": out_color_btn, "out_color_row": out_color_row,
                "out_size_spin": out_size_spin,
                "all_rows": [city_combo, view_combo, label_entry, tz_entry, sec_sw, offset_sw, font_row, fill_sw, fill_color_row, out_sw, out_color_row, out_size_spin]
            }

        # Helper to create Media controls with Expanders for Song & Artist
        def build_media_controls(slot_key: str, is_full_mode: bool = True):
            media_hdr = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.hdr-media.label", "Media Player & Visualizer"),
                subtitle=self.get_locale_text("actions.touchbar-info.hdr-media.subtitle", "Universal MPRIS player display, album artwork, and real-time audio visualizers")
            )
            media_hdr.add_css_class("touchbar-subhdr-row")

            media_players = self.get_available_media_players()
            player_ids = [pid for pid, _ in media_players]
            player_model = Gtk.StringList()
            for _, label in media_players:
                player_model.append(label)
            player_combo = Adw.ComboRow(
                model=player_model,
                title=self.get_locale_text("actions.touchbar-info.media-player-src.label", "Media Player Source"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-player-src.subtitle", "Choose automatic MPRIS detection or lock to a specific player")
            )
            player_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key, pids=player_ids: (
                self.set_slot_setting(sk, "media_player_id", pids[combo.get_selected()] if combo.get_selected() < len(pids) else "auto"),
                self.update_media_state(pids[combo.get_selected()] if combo.get_selected() < len(pids) else "auto"),
                self.trigger_redraw()
            ))

            vis_model = Gtk.StringList()
            for opt in self.media_vis_options: vis_model.append(opt)
            vis_combo = Adw.ComboRow(
                model=vis_model,
                title=self.get_locale_text("actions.touchbar-info.media-vis-style.label", "Visualizer Animation Style"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-vis-style.subtitle", "Choose between Stepped Equalizer Bars or Flowing Wave Curves")
            )
            vis_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: self.set_slot_setting(sk, "media_vis_style_idx", combo.get_selected()))

            color_mode_model = Gtk.StringList()
            for opt in self.media_color_mode_options: color_mode_model.append(opt)
            color_mode_combo = Adw.ComboRow(
                model=color_mode_model,
                title=self.get_locale_text("actions.touchbar-info.media-color-mode.label", "Visualizer Color Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-color-mode.subtitle", "Choose Solid Color or 3-Color Dynamic Gradient")
            )
            color_mode_combo.connect("notify::selected", lambda combo, pspec, sk=slot_key: (
                self.set_slot_setting(sk, "media_color_mode_idx", combo.get_selected()),
                self.notify_visibility_change()
            ))

            solid_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.media-solid-color.label", "Solid Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-solid-color.subtitle", "Color for visualizer bars or waves")
            )
            solid_color_btn = Gtk.ColorButton()
            solid_color_btn.set_valign(Gtk.Align.CENTER)
            solid_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_solid_color", self.gdk_to_hex(btn.get_rgba())))
            solid_color_row.add_suffix(solid_color_btn)

            grad_start_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.media-grad-start.label", "Gradient Start Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-grad-start.subtitle", "Bottom for Stepped Bars / Left for Wave Curves")
            )
            grad_start_btn = Gtk.ColorButton()
            grad_start_btn.set_valign(Gtk.Align.CENTER)
            grad_start_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_grad_start", self.gdk_to_hex(btn.get_rgba())))
            grad_start_row.add_suffix(grad_start_btn)

            grad_mid_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.media-grad-mid.label", "Gradient Middle Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-grad-mid.subtitle", "Middle color of the 3-color visualizer gradient")
            )
            grad_mid_btn = Gtk.ColorButton()
            grad_mid_btn.set_valign(Gtk.Align.CENTER)
            grad_mid_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_grad_mid", self.gdk_to_hex(btn.get_rgba())))
            grad_mid_row.add_suffix(grad_mid_btn)

            grad_end_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.media-grad-end.label", "Gradient End Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.media-grad-end.subtitle", "Top for Stepped Bars / Right for Wave Curves")
            )
            grad_end_btn = Gtk.ColorButton()
            grad_end_btn.set_valign(Gtk.Align.CENTER)
            grad_end_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_grad_end", self.gdk_to_hex(btn.get_rgba())))
            grad_end_row.add_suffix(grad_end_btn)

            song_expander = None
            artist_expander = None
            song_font_btn = None
            song_fill_sw = None
            song_fill_color_btn = None
            song_out_sw = None
            song_out_color_btn = None
            song_out_size_spin = None
            artist_font_btn = None
            artist_fill_sw = None
            artist_fill_color_btn = None
            artist_out_sw = None
            artist_out_color_btn = None
            artist_out_size_spin = None

            if is_full_mode:
                song_expander = Adw.ExpanderRow(
                    title=self.get_locale_text("actions.touchbar-info.hdr-song.label", "Song Title Settings"),
                    subtitle=self.get_locale_text("actions.touchbar-info.hdr-song.subtitle", "Typography and styling configuration for song title")
                )
                song_font_row = Adw.ActionRow(
                    title=self.get_locale_text("actions.touchbar-info.media-song-font.label", "Song Title Font and Size"),
                    subtitle=self.get_locale_text("actions.touchbar-info.media-song-font.subtitle", "Choose font family, style, and size for song title")
                )
                song_font_btn = Gtk.FontButton.new()
                song_font_btn.set_use_font(True)
                song_font_btn.set_use_size(False)
                song_font_btn.set_valign(Gtk.Align.CENTER)
                song_font_btn.set_hexpand(False)
                song_font_btn.connect("font-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_song_font_str", btn.get_font()))
                song_font_row.add_suffix(song_font_btn)

                song_fill_sw = Adw.SwitchRow(
                    title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Song Title Fill"),
                    subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill for song title")
                )
                song_fill_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                    self.set_slot_setting(sk, "media_song_fill_enabled", sw.get_active()),
                    song_fill_color_row.set_sensitive(sw.get_active())
                ))

                song_fill_color_row = Adw.ActionRow(
                    title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Song Title Fill Color"),
                    subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for song title interior fill")
                )
                song_fill_color_btn = Gtk.ColorButton()
                song_fill_color_btn.set_valign(Gtk.Align.CENTER)
                song_fill_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_song_font_color", self.gdk_to_hex(btn.get_rgba())))
                song_fill_color_row.add_suffix(song_fill_color_btn)

                song_out_sw = Adw.SwitchRow(
                    title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Song Title Outline"),
                    subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around song title")
                )
                song_out_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                    self.set_slot_setting(sk, "media_song_outline_enabled", sw.get_active()),
                    song_out_color_row.set_sensitive(sw.get_active()),
                    song_out_size_spin.set_sensitive(sw.get_active())
                ))

                song_out_color_row = Adw.ActionRow(
                    title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Song Title Outline Color"),
                    subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for song title outline")
                )
                song_out_color_btn = Gtk.ColorButton()
                song_out_color_btn.set_valign(Gtk.Align.CENTER)
                song_out_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_song_outline_color", self.gdk_to_hex(btn.get_rgba())))
                song_out_color_row.add_suffix(song_out_color_btn)

                song_out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
                song_out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Song Title Outline Thickness"))
                song_out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))
                song_out_size_spin.connect("notify::value", lambda spin, pspec, sk=slot_key: self.set_slot_setting(sk, "media_song_outline_size", int(spin.get_value())))

                song_expander.add_row(song_font_row)
                song_expander.add_row(song_fill_sw)
                song_expander.add_row(song_fill_color_row)
                song_expander.add_row(song_out_sw)
                song_expander.add_row(song_out_color_row)
                song_expander.add_row(song_out_size_spin)

                artist_expander = Adw.ExpanderRow(
                    title=self.get_locale_text("actions.touchbar-info.hdr-artist.label", "Artist Name Settings"),
                    subtitle=self.get_locale_text("actions.touchbar-info.hdr-artist.subtitle", "Typography and styling configuration for artist name")
                )
                artist_font_row = Adw.ActionRow(
                    title=self.get_locale_text("actions.touchbar-info.media-artist-font.label", "Artist Font and Size"),
                    subtitle=self.get_locale_text("actions.touchbar-info.media-artist-font.subtitle", "Choose font family, style, and size for artist text")
                )
                artist_font_btn = Gtk.FontButton.new()
                artist_font_btn.set_use_font(True)
                artist_font_btn.set_use_size(False)
                artist_font_btn.set_valign(Gtk.Align.CENTER)
                artist_font_btn.set_hexpand(False)
                artist_font_btn.connect("font-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_artist_font_str", btn.get_font()))
                artist_font_row.add_suffix(artist_font_btn)

                artist_fill_sw = Adw.SwitchRow(
                    title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Artist Text Fill"),
                    subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill for artist")
                )
                artist_fill_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                    self.set_slot_setting(sk, "media_artist_fill_enabled", sw.get_active()),
                    artist_fill_color_row.set_sensitive(sw.get_active())
                ))

                artist_fill_color_row = Adw.ActionRow(
                    title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Artist Fill Color"),
                    subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for artist text interior fill")
                )
                artist_fill_color_btn = Gtk.ColorButton()
                artist_fill_color_btn.set_valign(Gtk.Align.CENTER)
                artist_fill_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_artist_font_color", self.gdk_to_hex(btn.get_rgba())))
                artist_fill_color_row.add_suffix(artist_fill_color_btn)

                artist_out_sw = Adw.SwitchRow(
                    title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Artist Text Outline"),
                    subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around artist text")
                )
                artist_out_sw.connect("notify::active", lambda sw, pspec, sk=slot_key: (
                    self.set_slot_setting(sk, "media_artist_outline_enabled", sw.get_active()),
                    artist_out_color_row.set_sensitive(sw.get_active()),
                    artist_out_size_spin.set_sensitive(sw.get_active())
                ))

                artist_out_color_row = Adw.ActionRow(
                    title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Artist Outline Color"),
                    subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for artist text outline")
                )
                artist_out_color_btn = Gtk.ColorButton()
                artist_out_color_btn.set_valign(Gtk.Align.CENTER)
                artist_out_color_btn.connect("color-set", lambda btn, sk=slot_key: self.set_slot_setting(sk, "media_artist_outline_color", self.gdk_to_hex(btn.get_rgba())))
                artist_out_color_row.add_suffix(artist_out_color_btn)

                artist_out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
                artist_out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Artist Outline Thickness"))
                artist_out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))
                artist_out_size_spin.connect("notify::value", lambda spin, pspec, sk=slot_key: self.set_slot_setting(sk, "media_artist_outline_size", int(spin.get_value())))

                artist_expander.add_row(artist_font_row)
                artist_expander.add_row(artist_fill_sw)
                artist_expander.add_row(artist_fill_color_row)
                artist_expander.add_row(artist_out_sw)
                artist_expander.add_row(artist_out_color_row)
                artist_expander.add_row(artist_out_size_spin)

            all_rows = [media_hdr, player_combo, vis_combo, color_mode_combo, solid_color_row, grad_start_row, grad_mid_row, grad_end_row]
            if is_full_mode:
                all_rows.extend([song_expander, artist_expander])

            return {
                "media_hdr": media_hdr, "player_combo": player_combo, "vis_combo": vis_combo,
                "color_mode_combo": color_mode_combo, "solid_color_row": solid_color_row,
                "solid_color_btn": solid_color_btn, "grad_start_row": grad_start_row,
                "grad_start_btn": grad_start_btn, "grad_mid_row": grad_mid_row, "grad_mid_btn": grad_mid_btn,
                "grad_end_row": grad_end_row, "grad_end_btn": grad_end_btn,
                "song_expander": song_expander, "song_font_btn": song_font_btn,
                "song_fill_sw": song_fill_sw, "song_fill_color_btn": song_fill_color_btn,
                "song_out_sw": song_out_sw, "song_out_color_btn": song_out_color_btn,
                "song_out_size_spin": song_out_size_spin,
                "artist_expander": artist_expander, "artist_font_btn": artist_font_btn,
                "artist_fill_sw": artist_fill_sw, "artist_fill_color_btn": artist_fill_color_btn,
                "artist_out_sw": artist_out_sw, "artist_out_color_btn": artist_out_color_btn,
                "artist_out_size_spin": artist_out_size_spin,
                "all_rows": all_rows, "is_full_mode": is_full_mode
            }

        # Helper to assemble a complete Section Expander
        def create_section_expander(title_key: str, default_title: str, subtitle_key: str, default_sub: str, prefix_key: str):
            expander = Adw.ExpanderRow(
                title=self.get_locale_text(title_key, default_title),
                subtitle=self.get_locale_text(subtitle_key, default_sub)
            )

            mode_model = Gtk.StringList()
            for opt in self.section_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.section-layout.label", "Section Layout"),
                subtitle=self.get_locale_text("actions.touchbar-info.section-layout.subtitle", "Choose single full widget or stacked split widgets")
            )

            # 1. Full Mode Controls
            full_model = Gtk.StringList()
            for opt in self.full_widget_options: full_model.append(opt)
            full_combo = Adw.ComboRow(
                model=full_model,
                title=self.get_locale_text("actions.touchbar-info.widget-selector.label", "Select Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.widget-selector.subtitle", "Choose widget to display in this section")
            )

            full_slot_key = f"{prefix_key}_full"
            full_date_ctrls = build_date_controls(full_slot_key)
            full_time_ctrls = build_time_controls(full_slot_key)
            full_weather_ctrls = build_weather_controls(full_slot_key)
            full_cpu_ctrls = build_cpu_controls(full_slot_key)
            full_net_ctrls = build_net_controls(full_slot_key)
            full_ram_ctrls = build_ram_controls(full_slot_key)
            full_disk_ctrls = build_disk_controls(full_slot_key)
            full_worldclock_ctrls = build_worldclock_controls(full_slot_key)
            full_media_ctrls = build_media_controls(full_slot_key, is_full_mode=True)

            self.slot_controls[full_slot_key] = {
                "date": full_date_ctrls, "time": full_time_ctrls, "weather": full_weather_ctrls,
                "cpu": full_cpu_ctrls, "net": full_net_ctrls, "ram": full_ram_ctrls,
                "disk": full_disk_ctrls, "worldclock": full_worldclock_ctrls, "media": full_media_ctrls
            }

            # 2. Top Subsection Expander
            top_expander = Adw.ExpanderRow(
                title=self.get_locale_text("actions.touchbar-info.top-subsection.label", "Top"),
                subtitle=self.get_locale_text("actions.touchbar-info.top-subsection.subtitle", "Configure widget for the top 50px slot")
            )
            top_model = Gtk.StringList()
            for opt in self.split_widget_options: top_model.append(opt)
            top_combo = Adw.ComboRow(
                model=top_model,
                title=self.get_locale_text("actions.touchbar-info.widget-selector.label", "Select Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.widget-selector.subtitle", "Choose widget to display in this slot")
            )

            top_slot_key = f"{prefix_key}_top"
            top_date_ctrls = build_date_controls(top_slot_key)
            top_time_ctrls = build_time_controls(top_slot_key)
            top_weather_ctrls = build_weather_controls(top_slot_key)
            top_cpu_ctrls = build_cpu_controls(top_slot_key)
            top_net_ctrls = build_net_controls(top_slot_key)
            top_ram_ctrls = build_ram_controls(top_slot_key)
            top_disk_ctrls = build_disk_controls(top_slot_key)
            top_worldclock_ctrls = build_worldclock_controls(top_slot_key)
            top_media_ctrls = build_media_controls(top_slot_key, is_full_mode=False)

            self.slot_controls[top_slot_key] = {
                "date": top_date_ctrls, "time": top_time_ctrls, "weather": top_weather_ctrls,
                "cpu": top_cpu_ctrls, "net": top_net_ctrls, "ram": top_ram_ctrls,
                "disk": top_disk_ctrls, "worldclock": top_worldclock_ctrls, "media": top_media_ctrls
            }

            top_expander.add_row(top_combo)
            for r in top_date_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_time_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_weather_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_cpu_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_net_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_ram_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_disk_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_worldclock_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_media_ctrls["all_rows"]: top_expander.add_row(r)

            # 3. Bottom Subsection Expander
            bot_expander = Adw.ExpanderRow(
                title=self.get_locale_text("actions.touchbar-info.bottom-subsection.label", "Bottom"),
                subtitle=self.get_locale_text("actions.touchbar-info.bottom-subsection.subtitle", "Configure widget for the bottom 50px slot")
            )
            bot_model = Gtk.StringList()
            for opt in self.split_widget_options: bot_model.append(opt)
            bot_combo = Adw.ComboRow(
                model=bot_model,
                title=self.get_locale_text("actions.touchbar-info.widget-selector.label", "Select Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.widget-selector.subtitle", "Choose widget to display in this slot")
            )

            bot_slot_key = f"{prefix_key}_bot"
            bot_date_ctrls = build_date_controls(bot_slot_key)
            bot_time_ctrls = build_time_controls(bot_slot_key)
            bot_weather_ctrls = build_weather_controls(bot_slot_key)
            bot_cpu_ctrls = build_cpu_controls(bot_slot_key)
            bot_net_ctrls = build_net_controls(bot_slot_key)
            bot_ram_ctrls = build_ram_controls(bot_slot_key)
            bot_disk_ctrls = build_disk_controls(bot_slot_key)
            bot_worldclock_ctrls = build_worldclock_controls(bot_slot_key)
            bot_media_ctrls = build_media_controls(bot_slot_key, is_full_mode=False)

            self.slot_controls[bot_slot_key] = {
                "date": bot_date_ctrls, "time": bot_time_ctrls, "weather": bot_weather_ctrls,
                "cpu": bot_cpu_ctrls, "net": bot_net_ctrls, "ram": bot_ram_ctrls,
                "disk": bot_disk_ctrls, "worldclock": bot_worldclock_ctrls, "media": bot_media_ctrls
            }

            bot_expander.add_row(bot_combo)
            for r in bot_date_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_time_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_weather_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_cpu_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_net_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_ram_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_disk_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_worldclock_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_media_ctrls["all_rows"]: bot_expander.add_row(r)

            # Add rows to section expander
            expander.add_row(mode_combo)
            expander.add_row(full_combo)
            for r in full_date_ctrls["all_rows"]: expander.add_row(r)
            for r in full_time_ctrls["all_rows"]: expander.add_row(r)
            for r in full_weather_ctrls["all_rows"]: expander.add_row(r)
            for r in full_cpu_ctrls["all_rows"]: expander.add_row(r)
            for r in full_net_ctrls["all_rows"]: expander.add_row(r)
            for r in full_ram_ctrls["all_rows"]: expander.add_row(r)
            for r in full_disk_ctrls["all_rows"]: expander.add_row(r)
            for r in full_worldclock_ctrls["all_rows"]: expander.add_row(r)
            for r in full_media_ctrls["all_rows"]: expander.add_row(r)

            expander.add_row(top_expander)
            expander.add_row(bot_expander)

            # Visibility updater for a group of slot controls
            def update_group_vis(widget_choice, is_active, date_ctrls, time_ctrls, weather_ctrls, cpu_ctrls, net_ctrls, ram_ctrls, disk_ctrls, worldclock_ctrls, media_ctrls, is_full_mode=True):
                if not is_active:
                    for r in date_ctrls["all_rows"]: r.set_visible(False)
                    for r in time_ctrls["all_rows"]: r.set_visible(False)
                    for r in weather_ctrls["all_rows"]: r.set_visible(False)
                    for r in cpu_ctrls["all_rows"]: r.set_visible(False)
                    for r in net_ctrls["all_rows"]: r.set_visible(False)
                    for r in ram_ctrls["all_rows"]: r.set_visible(False)
                    for r in disk_ctrls["all_rows"]: r.set_visible(False)
                    for r in worldclock_ctrls["all_rows"]: r.set_visible(False)
                    for r in media_ctrls["all_rows"]: r.set_visible(False)
                    return

                # Date Visibility (Full: only 7 [Stacked Date & Time] | Split: only 2 [Date])
                show_date = (widget_choice == 7) if is_full_mode else (widget_choice == 2)
                date_ctrls["date_expander"].set_visible(show_date)

                # Time Visibility (Full: only 7 [Stacked Date & Time] | Split: only 7 [Time])
                show_time = (widget_choice == 7) if is_full_mode else (widget_choice == 7)
                time_ctrls["time_expander"].set_visible(show_time)

                # Weather Visibility (Full: 9 | Split: 8)
                show_weather = (widget_choice == 9) if is_full_mode else (widget_choice == 8)
                for r in weather_ctrls["all_rows"]:
                    if r == weather_ctrls["res_combo"]:
                        r.set_visible(show_weather and r.get_model().get_n_items() > 0)
                    else:
                        r.set_visible(show_weather)

                # CPU Visibility (Choice 1)
                show_cpu = (widget_choice == 1)
                for r in cpu_ctrls["all_rows"]: r.set_visible(show_cpu)

                # Network Visibility (Choice 5)
                show_net = (widget_choice == 5)
                for r in net_ctrls["all_rows"]: r.set_visible(show_net)

                # RAM Visibility (Choice 6)
                show_ram = (widget_choice == 6)
                for r in ram_ctrls["all_rows"]: r.set_visible(show_ram)

                # Disk Visibility (Choice 3)
                show_disk = (widget_choice == 3)
                for r in disk_ctrls["all_rows"]: r.set_visible(show_disk)

                # World Clock Visibility (Full: 10 | Split: 9)
                show_worldclock = (widget_choice == 10) if is_full_mode else (widget_choice == 9)
                city_sel = worldclock_ctrls["city_combo"].get_selected()
                is_custom_tz = (city_sel == len(self.worldclock_cities) - 1)
                for r in worldclock_ctrls["all_rows"]:
                    if r in (worldclock_ctrls["label_entry"], worldclock_ctrls["tz_entry"]):
                        r.set_visible(show_worldclock and is_custom_tz)
                    else:
                        r.set_visible(show_worldclock)

                # Media Player Visibility (Choice 4)
                show_media = (widget_choice == 4)
                color_mode = media_ctrls["color_mode_combo"].get_selected()
                is_grad = (color_mode == 1)

                media_ctrls["media_hdr"].set_visible(show_media)
                media_ctrls["player_combo"].set_visible(show_media)
                media_ctrls["vis_combo"].set_visible(show_media)
                media_ctrls["color_mode_combo"].set_visible(show_media)
                media_ctrls["solid_color_row"].set_visible(show_media and not is_grad)
                media_ctrls["grad_start_row"].set_visible(show_media and is_grad)
                media_ctrls["grad_mid_row"].set_visible(show_media and is_grad)
                media_ctrls["grad_end_row"].set_visible(show_media and is_grad)

                if is_full_mode:
                    media_ctrls["song_expander"].set_visible(show_media)
                    media_ctrls["artist_expander"].set_visible(show_media)

            def update_section_vis():
                is_split = (mode_combo.get_selected() == 1)
                full_combo.set_visible(not is_split)
                top_expander.set_visible(is_split)
                bot_expander.set_visible(is_split)

                update_group_vis(
                    full_combo.get_selected(), not is_split,
                    full_date_ctrls, full_time_ctrls, full_weather_ctrls,
                    full_cpu_ctrls, full_net_ctrls, full_ram_ctrls,
                    full_disk_ctrls, full_worldclock_ctrls, full_media_ctrls,
                    is_full_mode=True
                )
                update_group_vis(
                    top_combo.get_selected(), is_split,
                    top_date_ctrls, top_time_ctrls, top_weather_ctrls,
                    top_cpu_ctrls, top_net_ctrls, top_ram_ctrls,
                    top_disk_ctrls, top_worldclock_ctrls, top_media_ctrls,
                    is_full_mode=False
                )
                update_group_vis(
                    bot_combo.get_selected(), is_split,
                    bot_date_ctrls, bot_time_ctrls, bot_weather_ctrls,
                    bot_cpu_ctrls, bot_net_ctrls, bot_ram_ctrls,
                    bot_disk_ctrls, bot_worldclock_ctrls, bot_media_ctrls,
                    is_full_mode=False
                )

            mode_combo.connect("notify::selected", lambda combo, pspec: (
                self.set_slot_setting(prefix_key, "mode", combo.get_selected()),
                update_section_vis(),
                self.fetch_weather_async()
            ))
            full_combo.connect("notify::selected", lambda combo, pspec: (
                self.set_slot_setting(prefix_key, "full_widget", combo.get_selected()),
                update_section_vis(),
                self.fetch_weather_async()
            ))
            top_combo.connect("notify::selected", lambda combo, pspec: (
                self.set_slot_setting(prefix_key, "top_widget", combo.get_selected()),
                update_section_vis(),
                self.fetch_weather_async()
            ))
            bot_combo.connect("notify::selected", lambda combo, pspec: (
                self.set_slot_setting(prefix_key, "bottom_widget", combo.get_selected()),
                update_section_vis(),
                self.fetch_weather_async()
            ))

            self.update_vis_callbacks.append(update_section_vis)
            update_section_vis()

            return expander, mode_combo, full_combo, top_combo, bot_combo

        self.sec_a_expander, self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo = create_section_expander(
            "actions.touchbar-info.sec-a.label", "Section A",
            "actions.touchbar-info.sec-a.subtitle", "Left section widget layout and configuration",
            "sec_a"
        )
        self.sec_b_expander, self.sec_b_mode_combo, self.sec_b_full_combo, self.sec_b_top_combo, self.sec_b_bot_combo = create_section_expander(
            "actions.touchbar-info.sec-b.label", "Section B",
            "actions.touchbar-info.sec-b.subtitle", "Center section widget layout and configuration",
            "sec_b"
        )
        self.sec_c_expander, self.sec_c_mode_combo, self.sec_c_full_combo, self.sec_c_top_combo, self.sec_c_bot_combo = create_section_expander(
            "actions.touchbar-info.sec-c.label", "Section C",
            "actions.touchbar-info.sec-c.subtitle", "Right section widget layout and configuration",
            "sec_c"
        )

        # Custom Wallpaper Row
        self.bg_image_row = Adw.ActionRow(
            title=self.get_locale_text("actions.touchbar-info.bg-image.label", "Custom Touch Bar Background Wallpaper"),
            subtitle=self.get_locale_text("actions.touchbar-info.bg-image.subtitle", "Select custom wallpaper image (PNG/JPG) to render behind all Touch Bar widgets")
        )
        bg_image_btn = Gtk.Button(label=self.get_locale_text("actions.touchbar-info.bg-image.choose", "Choose Image..."))
        bg_image_btn.set_valign(Gtk.Align.CENTER)
        bg_image_btn.connect("clicked", self.on_select_custom_bg_clicked)

        bg_clear_btn = Gtk.Button(label=self.get_locale_text("actions.touchbar-info.bg-image.clear", "Clear"))
        bg_clear_btn.set_valign(Gtk.Align.CENTER)
        bg_clear_btn.connect("clicked", self.on_clear_custom_bg_clicked)

        self.bg_image_row.add_suffix(bg_image_btn)
        self.bg_image_row.add_suffix(bg_clear_btn)

        return [
            self.bg_image_row,
            self.sec_a_expander,
            self.sec_b_expander,
            self.sec_c_expander
        ]

    def notify_visibility_change(self):
        for cb in getattr(self, "update_vis_callbacks", []):
            try:
                cb()
            except Exception:
                pass

    def load_config_defaults(self):
        settings = self.get_settings()
        if settings is None:
            return

        # Section selections
        self.sec_a_mode_combo.set_selected(self.get_slot_setting(settings, "sec_a", "mode", 0))
        self.sec_a_full_combo.set_selected(self.get_slot_setting(settings, "sec_a", "full_widget", 0))
        self.sec_a_top_combo.set_selected(self.get_slot_setting(settings, "sec_a", "top_widget", 0))
        self.sec_a_bot_combo.set_selected(self.get_slot_setting(settings, "sec_a", "bottom_widget", 0))

        self.sec_b_mode_combo.set_selected(self.get_slot_setting(settings, "sec_b", "mode", 0))
        self.sec_b_full_combo.set_selected(self.get_slot_setting(settings, "sec_b", "full_widget", 0))
        self.sec_b_top_combo.set_selected(self.get_slot_setting(settings, "sec_b", "top_widget", 0))
        self.sec_b_bot_combo.set_selected(self.get_slot_setting(settings, "sec_b", "bottom_widget", 0))

        self.sec_c_mode_combo.set_selected(self.get_slot_setting(settings, "sec_c", "mode", 0))
        self.sec_c_full_combo.set_selected(self.get_slot_setting(settings, "sec_c", "full_widget", 0))
        self.sec_c_top_combo.set_selected(self.get_slot_setting(settings, "sec_c", "top_widget", 0))
        self.sec_c_bot_combo.set_selected(self.get_slot_setting(settings, "sec_c", "bottom_widget", 0))

        # Populate all 9 slots' controls independently
        for slot_key, ctrls in self.slot_controls.items():
            # Date
            d = ctrls["date"]
            d["fmt_combo"].set_selected(self.get_slot_setting(settings, slot_key, "date_format_idx", 0))
            d["font_btn"].set_font(self.get_slot_setting(settings, slot_key, "date_font_str", "DejaVu Sans Bold 25"))
            date_fill_en = self.get_slot_setting(settings, slot_key, "date_fill_enabled", True)
            d["fill_sw"].set_active(date_fill_en)
            d["fill_color_row"].set_sensitive(date_fill_en)
            self.set_color_button_rgba(d["fill_color_btn"], self.get_slot_setting(settings, slot_key, "date_font_color", "#AAC8E6FF"))
            date_out_en = self.get_slot_setting(settings, slot_key, "date_outline_enabled", False)
            d["out_sw"].set_active(date_out_en)
            d["out_color_row"].set_sensitive(date_out_en)
            d["out_size_spin"].set_sensitive(date_out_en)
            self.set_color_button_rgba(d["out_color_btn"], self.get_slot_setting(settings, slot_key, "date_outline_color", "#000000FF"))
            d["out_size_spin"].set_value(self.get_slot_setting(settings, slot_key, "date_outline_size", 2))

            # Time
            t = ctrls["time"]
            t["sw_24h"].set_active(self.get_slot_setting(settings, slot_key, "use_24h", False))
            t["sw_sec"].set_active(self.get_slot_setting(settings, slot_key, "show_seconds", False))
            t["font_btn"].set_font(self.get_slot_setting(settings, slot_key, "time_font_str", "DejaVu Sans Bold 45"))
            time_fill_en = self.get_slot_setting(settings, slot_key, "time_fill_enabled", True)
            t["fill_sw"].set_active(time_fill_en)
            t["fill_color_row"].set_sensitive(time_fill_en)
            self.set_color_button_rgba(t["fill_color_btn"], self.get_slot_setting(settings, slot_key, "time_font_color", "#FFFFFFFF"))
            time_out_en = self.get_slot_setting(settings, slot_key, "time_outline_enabled", False)
            t["out_sw"].set_active(time_out_en)
            t["out_color_row"].set_sensitive(time_out_en)
            t["out_size_spin"].set_sensitive(time_out_en)
            self.set_color_button_rgba(t["out_color_btn"], self.get_slot_setting(settings, slot_key, "time_outline_color", "#000000FF"))
            t["out_size_spin"].set_value(self.get_slot_setting(settings, slot_key, "time_outline_size", 2))

            # Weather
            w = ctrls["weather"]
            w["loc_entry"].set_text(self.get_slot_setting(settings, slot_key, "weather_location_name", "Miami"))
            w["unit_combo"].set_selected(self.get_slot_setting(settings, slot_key, "weather_unit_idx", 0))
            w["ref_combo"].set_selected(self.get_slot_setting(settings, slot_key, "weather_refresh_idx", 2))
            w["font_btn"].set_font(self.get_slot_setting(settings, slot_key, "weather_font_str", "DejaVu Sans Bold 22"))
            w_fill_en = self.get_slot_setting(settings, slot_key, "weather_fill_enabled", True)
            w["fill_sw"].set_active(w_fill_en)
            w["fill_color_row"].set_sensitive(w_fill_en)
            self.set_color_button_rgba(w["fill_color_btn"], self.get_slot_setting(settings, slot_key, "weather_font_color", "#FFFFFFFF"))
            w_out_en = self.get_slot_setting(settings, slot_key, "weather_outline_enabled", False)
            w["out_sw"].set_active(w_out_en)
            w["out_color_row"].set_sensitive(w_out_en)
            w["out_size_spin"].set_sensitive(w_out_en)
            self.set_color_button_rgba(w["out_color_btn"], self.get_slot_setting(settings, slot_key, "weather_outline_color", "#000000FF"))
            w["out_size_spin"].set_value(self.get_slot_setting(settings, slot_key, "weather_outline_size", 2))

            # CPU
            ctrls["cpu"]["mode_combo"].set_selected(self.get_slot_setting(settings, slot_key, "cpu_mode_idx", 0))

            # Net
            ctrls["net"]["mode_combo"].set_selected(self.get_slot_setting(settings, slot_key, "net_mode_idx", 0))
            ctrls["net"]["unit_combo"].set_selected(self.get_slot_setting(settings, slot_key, "net_unit_idx", 0))

            # RAM
            ctrls["ram"]["mode_combo"].set_selected(self.get_slot_setting(settings, slot_key, "ram_mode_idx", 0))

            # Disk
            ctrls["disk"]["mode_combo"].set_selected(self.get_slot_setting(settings, slot_key, "disk_mode_idx", 0))
            d_mount_path = self.get_slot_setting(settings, slot_key, "disk_mount_path", "/")
            d_idx = 0
            for idx, (m_path, _) in enumerate(self.disk_mounts):
                if m_path == d_mount_path:
                    d_idx = idx
                    break
            ctrls["disk"]["mount_combo"].set_selected(d_idx)
            if isinstance(d_mount_path, str):
                ctrls["disk"]["browse_row"].set_subtitle(f"Selected: {d_mount_path}")

            # World Clock
            wc = ctrls["worldclock"]
            wc["city_combo"].set_selected(self.get_slot_setting(settings, slot_key, "worldclock_city_idx", 0))
            wc["view_combo"].set_selected(self.get_slot_setting(settings, slot_key, "worldclock_view", 0))
            wc["label_entry"].set_text(self.get_slot_setting(settings, slot_key, "worldclock_custom_label", ""))
            wc["tz_entry"].set_text(self.get_slot_setting(settings, slot_key, "worldclock_custom_tz", "America/New_York"))
            wc["sec_sw"].set_active(self.get_slot_setting(settings, slot_key, "worldclock_show_seconds", False))
            wc["offset_sw"].set_active(self.get_slot_setting(settings, slot_key, "worldclock_show_offset", True))
            wc["font_btn"].set_font(self.get_slot_setting(settings, slot_key, "worldclock_font_str", "DejaVu Sans Bold 25"))
            wc_fill_en = self.get_slot_setting(settings, slot_key, "worldclock_fill_enabled", True)
            wc["fill_sw"].set_active(wc_fill_en)
            wc["fill_color_row"].set_sensitive(wc_fill_en)
            self.set_color_button_rgba(wc["fill_color_btn"], self.get_slot_setting(settings, slot_key, "worldclock_font_color", "#FFFFFFFF"))
            wc_out_en = self.get_slot_setting(settings, slot_key, "worldclock_outline_enabled", False)
            wc["out_sw"].set_active(wc_out_en)
            wc["out_color_row"].set_sensitive(wc_out_en)
            wc["out_size_spin"].set_sensitive(wc_out_en)
            self.set_color_button_rgba(wc["out_color_btn"], self.get_slot_setting(settings, slot_key, "worldclock_outline_color", "#000000FF"))
            wc["out_size_spin"].set_value(self.get_slot_setting(settings, slot_key, "worldclock_outline_size", 2))

            # Media
            m = ctrls["media"]
            p_id = self.get_slot_setting(settings, slot_key, "media_player_id", "auto")
            p_ids = [pid for pid, _ in self.get_available_media_players()]
            p_idx = p_ids.index(p_id) if p_id in p_ids else 0
            m["player_combo"].set_selected(p_idx)
            m["vis_combo"].set_selected(self.get_slot_setting(settings, slot_key, "media_vis_style_idx", 0))
            m["color_mode_combo"].set_selected(self.get_slot_setting(settings, slot_key, "media_color_mode_idx", 0))
            self.set_color_button_rgba(m["solid_color_btn"], self.get_slot_setting(settings, slot_key, "media_solid_color", "#FFFFFFFF"))
            self.set_color_button_rgba(m["grad_start_btn"], self.get_slot_setting(settings, slot_key, "media_grad_start", "#00D2FFFF"))
            self.set_color_button_rgba(m["grad_mid_btn"], self.get_slot_setting(settings, slot_key, "media_grad_mid", "#7B2CBFFF"))
            self.set_color_button_rgba(m["grad_end_btn"], self.get_slot_setting(settings, slot_key, "media_grad_end", "#FF2A6DFF"))

            if m["is_full_mode"]:
                m["song_font_btn"].set_font(self.get_slot_setting(settings, slot_key, "media_song_font_str", "DejaVu Sans Bold 18"))
                s_fill_en = self.get_slot_setting(settings, slot_key, "media_song_fill_enabled", True)
                m["song_fill_sw"].set_active(s_fill_en)
                self.set_color_button_rgba(m["song_fill_color_btn"], self.get_slot_setting(settings, slot_key, "media_song_font_color", "#FFFFFFFF"))
                s_out_en = self.get_slot_setting(settings, slot_key, "media_song_outline_enabled", False)
                m["song_out_sw"].set_active(s_out_en)
                self.set_color_button_rgba(m["song_out_color_btn"], self.get_slot_setting(settings, slot_key, "media_song_outline_color", "#000000FF"))
                m["song_out_size_spin"].set_value(self.get_slot_setting(settings, slot_key, "media_song_outline_size", 2))

                m["artist_font_btn"].set_font(self.get_slot_setting(settings, slot_key, "media_artist_font_str", "DejaVu Sans Bold 18"))
                a_fill_en = self.get_slot_setting(settings, slot_key, "media_artist_fill_enabled", True)
                m["artist_fill_sw"].set_active(a_fill_en)
                self.set_color_button_rgba(m["artist_fill_color_btn"], self.get_slot_setting(settings, slot_key, "media_artist_font_color", "#FFFFFFFF"))
                a_out_en = self.get_slot_setting(settings, slot_key, "media_artist_outline_enabled", False)
                m["artist_out_sw"].set_active(a_out_en)
                self.set_color_button_rgba(m["artist_out_color_btn"], self.get_slot_setting(settings, slot_key, "media_artist_outline_color", "#000000FF"))
                m["artist_out_size_spin"].set_value(self.get_slot_setting(settings, slot_key, "media_artist_outline_size", 2))

        custom_bg_path = settings.get("custom_bg_path", "")
        self.update_bg_row_subtitle(custom_bg_path)
        self.notify_visibility_change()

    def set_color_button_rgba(self, button: Gtk.ColorButton, hex_str: str):
        try:
            rgba = Gdk.RGBA()
            rgba.parse(hex_str)
            button.set_rgba(rgba)
        except Exception:
            pass

    def gdk_to_hex(self, rgba: Gdk.RGBA) -> str:
        r = int(rgba.red * 255)
        g = int(rgba.green * 255)
        b = int(rgba.blue * 255)
        a = int(rgba.alpha * 255)
        return f"#{r:02X}{g:02X}{b:02X}{a:02X}"

    def hex_to_rgba_tuple(self, hex_str: str, default=(255, 255, 255, 255)) -> tuple[int, int, int, int]:
        try:
            clean_hex = hex_str.lstrip("#")
            if len(clean_hex) == 6:
                return (int(clean_hex[0:2], 16), int(clean_hex[2:4], 16), int(clean_hex[4:6], 16), 255)
            elif len(clean_hex) == 8:
                return (int(clean_hex[0:2], 16), int(clean_hex[2:4], 16), int(clean_hex[4:6], 16), int(clean_hex[6:8], 16))
        except Exception:
            pass
        return default

    def refresh_all_disk_combos(self):
        self.disk_mounts = self.get_system_disk_mounts()
        display_names = [d_name for _, d_name in self.disk_mounts]
        for slot_key, ctrls in self.slot_controls.items():
            if "disk" in ctrls:
                combo = ctrls["disk"]["mount_combo"]
                combo.set_model(Gtk.StringList.new(display_names))
        self.trigger_redraw()

    def on_select_custom_bg_clicked(self, button):
        settings = self.get_settings() or {}
        curr_path = settings.get("custom_bg_path", "")
        if hasattr(gl, "app") and gl.app is not None and hasattr(gl.app, "let_user_select_asset"):
            GLib.idle_add(gl.app.let_user_select_asset, curr_path, self.on_custom_bg_asset_selected)
        elif hasattr(gl, "asset_manager") and gl.asset_manager is not None and hasattr(gl.asset_manager, "show_for_path"):
            GLib.idle_add(gl.asset_manager.show_for_path, curr_path, self.on_custom_bg_asset_selected)
        else:
            log.warning("TouchBarInfo: gl.app.let_user_select_asset is not available")

    def on_custom_bg_asset_selected(self, file_path: str):
        if not file_path:
            return
        settings = self.get_settings()
        if settings is not None:
            settings["custom_bg_path"] = file_path
            self.set_settings(settings)
            self._cached_bg_path = None
            self._cached_bg_image = None
            self.update_bg_row_subtitle(file_path)
            self.trigger_redraw()

    def on_clear_custom_bg_clicked(self, button):
        settings = self.get_settings()
        if settings is not None:
            settings["custom_bg_path"] = ""
            self.set_settings(settings)
            self._cached_bg_path = None
            self._cached_bg_image = None
            self.update_bg_row_subtitle("")
            self.trigger_redraw()

    def update_bg_row_subtitle(self, file_path: str):
        if hasattr(self, "bg_image_row"):
            if file_path and isinstance(file_path, str):
                disp_name = os.path.basename(file_path) if os.path.isabs(file_path) else file_path
                self.bg_image_row.set_subtitle(f"Selected: {disp_name}")
            else:
                self.bg_image_row.set_subtitle(self.get_locale_text("actions.touchbar-info.bg-image.subtitle", "Select custom wallpaper from StreamController Asset Manager to render behind all Touch Bar widgets"))

    # --- Pango Font Resolver for PIL ---
    def get_font_from_desc(self, font_str: str, default_size: int = 25, scale_factor: float = 1.0) -> ImageFont.FreeTypeFont:
        if not font_str or not isinstance(font_str, str):
            font_str = "DejaVu Sans Bold 25"

        if not hasattr(self, "_font_cache"):
            self._font_cache = {}
        cache_key = (font_str, default_size, scale_factor)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        font_obj = None
        try:
            desc = Pango.FontDescription.from_string(font_str)
            family = desc.get_family() or "DejaVu Sans"
            size_pango = desc.get_size()
            raw_size = int(size_pango / Pango.SCALE) if size_pango > 0 else default_size
            size = max(6, int(round(raw_size * scale_factor)))

            weight = desc.get_weight()
            is_bold = (weight >= Pango.Weight.BOLD)
            is_italic = (desc.get_style() in [Pango.Style.ITALIC, Pango.Style.OBLIQUE])

            style_parts = []
            if is_bold: style_parts.append("Bold")
            if is_italic: style_parts.append("Italic")
            if not style_parts: style_parts.append("Regular")
            style_str = " ".join(style_parts)

            # Query fontconfig via fc-match to locate exact font file on disk
            try:
                cmd = ["fc-match", "-f", "%{file}", f"{family}:style={style_str}"]
                res = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
                if res and os.path.isfile(res):
                    font_obj = ImageFont.truetype(res, size)
            except Exception:
                pass

            if font_obj is None:
                try:
                    cmd_fam = ["fc-match", "-f", "%{file}", family]
                    res_fam = subprocess.check_output(cmd_fam, text=True, stderr=subprocess.DEVNULL).strip()
                    if res_fam and os.path.isfile(res_fam):
                        font_obj = ImageFont.truetype(res_fam, size)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"TouchBarInfo: Error resolving font '{font_str}': {e}")

        if font_obj is None:
            for fallback in [
                "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                "/run/host/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/cantarell/Cantarell-VF.otf"
            ]:
                if os.path.isfile(fallback):
                    try:
                        font_obj = ImageFont.truetype(fallback, default_size)
                        break
                    except Exception:
                        pass

        if font_obj is None:
            font_obj = ImageFont.load_default()

        self._font_cache[cache_key] = font_obj
        return font_obj

    def render_styled_text(self, draw: ImageDraw.ImageDraw, pos: tuple[float, float], text: str, font_obj, fill_enabled: bool, fill_color: tuple, outline_enabled: bool, outline_color: tuple, outline_size: int, anchor: str = "mm"):
        x, y = pos
        if outline_enabled and outline_size > 0:
            for dx in range(-outline_size, outline_size + 1):
                for dy in range(-outline_size, outline_size + 1):
                    if dx == 0 and dy == 0:
                        continue
                    if dx * dx + dy * dy <= outline_size * outline_size + 1:
                        draw.text((x + dx, y + dy), text, font=font_obj, fill=outline_color, anchor=anchor)

        if fill_enabled:
            draw.text((x, y), text, font=font_obj, fill=fill_color, anchor=anchor)

    def fit_font_to_width(self, draw: ImageDraw.ImageDraw, text: str, font_obj, max_width: float, min_size: int = 8) -> ImageFont.FreeTypeFont:
        try:
            bbox = draw.textbbox((0, 0), text, font=font_obj)
            if (bbox[2] - bbox[0]) <= max_width:
                return font_obj

            font_path = font_obj.path if hasattr(font_obj, "path") else None
            size = font_obj.size if hasattr(font_obj, "size") else 20
            if not font_path or not os.path.exists(font_path):
                return font_obj

            while size > min_size:
                size -= 1
                f = ImageFont.truetype(font_path, size)
                bbox = draw.textbbox((0, 0), text, font=f)
                if (bbox[2] - bbox[0]) <= max_width:
                    return f
            return font_obj
        except Exception:
            return font_obj

    def draw_history_graph(self, draw: ImageDraw.ImageDraw, graph_box: tuple[int, int, int, int], history: list[float], max_val: float = 100.0, color=(0, 200, 255, 255)):
        gx_min, gy_min, gx_max, gy_max = graph_box
        gw = gx_max - gx_min
        gh = gy_max - gy_min
        if gw < 10 or gh < 10 or not history:
            return

        points = []
        step_x = gw / max(1, len(history) - 1)
        for i, val in enumerate(history):
            px = gx_min + (i * step_x)
            norm = min(1.0, max(0.0, float(val) / max(1.0, float(max_val))))
            py = gy_max - (norm * gh)
            points.append((px, py))

        if len(points) >= 2:
            fill_poly = list(points) + [(gx_max, gy_max), (gx_min, gy_max)]
            fill_color = (color[0], color[1], color[2], 60)
            draw.polygon(fill_poly, fill=fill_color)
            draw.line(points, fill=color, width=2)

    def draw_stacked(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], date_str: str, time_str: str, font_date, font_time, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        w = x_max - x_min
        h = y_max - y_min

        bbox_date = draw.textbbox((0, 0), date_str, font=font_date)
        bbox_time = draw.textbbox((0, 0), time_str, font=font_time)

        date_h = bbox_date[3] - bbox_date[1]
        time_h = bbox_time[3] - bbox_time[1]

        spacing = max(2, int(h * 0.04))
        total_h = date_h + spacing + time_h
        start_y = y_min + (h - total_h) / 2

        date_y = start_y + (date_h / 2)
        time_y = start_y + date_h + spacing + (time_h / 2)

        if align == "center":
            center_x = x_min + (w / 2)
            anchor = "mm"
        else:
            margin_x = int(w * 0.08)
            center_x = x_min + margin_x
            anchor = "lm"

        self.render_styled_text(draw, (center_x, date_y), date_str, font_date, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz, anchor=anchor)
        self.render_styled_text(draw, (center_x, time_y), time_str, font_time, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz, anchor=anchor)

    def draw_single(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font, fill_en=True, fill_col=(255, 255, 255, 255), out_en=False, out_col=(0, 0, 0, 255), out_sz=2, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        center_y = y_min + (y_max - y_min) / 2

        if align == "center":
            center_x = x_min + (box_w / 2)
            anchor = "mm"
        else:
            margin_x = int(box_w * 0.08)
            center_x = x_min + margin_x
            anchor = "lm"

        self.render_styled_text(draw, (center_x, center_y), text, font, fill_en, fill_col, out_en, out_col, out_sz, anchor=anchor)

    def load_widget_icon(self, icon_filename: str, target_h: int) -> Image.Image | None:
        icon_path = os.path.join(self.plugin_base.PATH, "assets", icon_filename)
        if os.path.exists(icon_path):
            try:
                raw_img = Image.open(icon_path).convert("RGBA")
                aspect = raw_img.width / max(1, raw_img.height)
                target_w = int(target_h * aspect)
                return raw_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            except Exception as e:
                log.error(f"TouchBarInfo: Error loading icon {icon_path}: {e}")
        return None

    def draw_weather(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_weather, font_location, fill_en, fill_col, out_en, out_col, out_sz, cache: dict = None, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        c = cache or self.weather_cache or {}
        temp_str = c.get("temp_str", "--°")
        wmo_code = c.get("wmo_code", 0)
        is_day = c.get("is_day", 1)
        location_str = c.get("location", "Miami")

        icon_file = self.get_weather_icon_filename(wmo_code, is_day)
        target_icon_h = int(box_h * 0.70)
        icon_img = self.load_widget_icon(os.path.join("weather-icons", icon_file), target_icon_h)

        bbox_temp = draw.textbbox((0, 0), temp_str, font=font_weather)
        bbox_loc = draw.textbbox((0, 0), location_str, font=font_location)

        temp_w = bbox_temp[2] - bbox_temp[0]
        temp_h = bbox_temp[3] - bbox_temp[1]
        loc_w = bbox_loc[2] - bbox_loc[0]
        loc_h = bbox_loc[3] - bbox_loc[1]

        text_col_w = max(temp_w, loc_w)
        icon_w = icon_img.width if icon_img else 0
        gap = int(box_w * 0.05) if icon_img else 0
        content_w = icon_w + (gap if icon_img else 0) + text_col_w

        if align == "center":
            start_x = x_min + max(0, (box_w - content_w) / 2)
        else:
            start_x = x_min + int(box_w * 0.08)

        if icon_img is not None:
            icon_x = int(start_x)
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            left_text_x = icon_x + icon_w + gap
        else:
            left_text_x = start_x

        center_text_x = left_text_x + (text_col_w / 2)

        spacing = max(1, int(box_h * 0.04))
        total_h = temp_h + spacing + loc_h
        start_y = y_min + (box_h - total_h) / 2

        temp_y = start_y + (temp_h / 2)
        loc_y = start_y + temp_h + spacing + (loc_h / 2)

        self.render_styled_text(draw, (center_text_x, temp_y), temp_str, font_weather, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        self.render_styled_text(draw, (center_text_x, loc_y), location_str, font_location, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def draw_cpu_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, cpu_mode: int, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("cpu_icon.png", target_icon_h)
        latest_cpu = self.cpu_history[-1] if self.cpu_history else 0.0

        if cpu_mode == 2: # Live Graph
            margin_x = int(box_w * 0.08)
            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            if align == "center":
                gw = min(int(box_w * 0.75), box_w - 40)
                gx_min = x_min + (box_w - gw) / 2
                if icon_img is not None:
                    icon_x = int(gx_min)
                    icon_y = y_min + int((box_h - target_icon_h) / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)
                    gx_min += icon_w + gap
                graph_box = (int(gx_min), y_min + int(box_h * 0.15), int(gx_min + gw - icon_w - gap), y_max - int(box_h * 0.15))
            else:
                if icon_img is not None:
                    icon_x = x_min + margin_x
                    icon_y = y_min + int((box_h - target_icon_h) / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)
                    content_x = icon_x + icon_w + gap
                else:
                    content_x = x_min + margin_x
                graph_box = (content_x, y_min + int(box_h * 0.15), x_max - margin_x, y_max - int(box_h * 0.15))
            self.draw_history_graph(draw, graph_box, self.cpu_history, max_val=100.0, color=(0, 200, 255, 255))
        elif cpu_mode == 1: # Percentage + Process Count
            top_str = f"CPU {round(latest_cpu)}%"
            bot_str = f"{self.process_count} Procs"
            bbox_t = draw.textbbox((0, 0), top_str, font=font_main)
            bbox_b = draw.textbbox((0, 0), bot_str, font=font_sub)
            th, bh = bbox_t[3] - bbox_t[1], bbox_b[3] - bbox_b[1]
            tw, bw = bbox_t[2] - bbox_t[0], bbox_b[2] - bbox_b[0]
            text_col_w = max(tw, bw)

            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            content_w = icon_w + (gap if icon_img else 0) + text_col_w

            if align == "center":
                start_x = x_min + max(0, (box_w - content_w) / 2)
            else:
                start_x = x_min + int(box_w * 0.08)

            if icon_img is not None:
                icon_x = int(start_x)
                icon_y = y_min + int((box_h - target_icon_h) / 2)
                image.paste(icon_img, (icon_x, icon_y), icon_img)
                content_x = icon_x + icon_w + gap
            else:
                content_x = start_x

            center_x = content_x + (text_col_w / 2)
            spacing = max(1, int(box_h * 0.04))
            total_h = th + spacing + bh
            start_y = y_min + (box_h - total_h) / 2
            top_y = start_y + (th / 2)
            bot_y = start_y + th + spacing + (bh / 2)

            self.render_styled_text(draw, (center_x, top_y), top_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, bot_y), bot_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # Percentage %
            main_str = f"CPU {round(latest_cpu)}%"
            bbox_m = draw.textbbox((0, 0), main_str, font=font_main)
            tw = bbox_m[2] - bbox_m[0]

            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            content_w = icon_w + (gap if icon_img else 0) + tw

            if align == "center":
                start_x = x_min + max(0, (box_w - content_w) / 2)
            else:
                start_x = x_min + int(box_w * 0.08)

            if icon_img is not None:
                icon_x = int(start_x)
                icon_y = y_min + int((box_h - target_icon_h) / 2)
                image.paste(icon_img, (icon_x, icon_y), icon_img)
                content_x = icon_x + icon_w + gap
            else:
                content_x = start_x

            center_x = content_x + (tw / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def draw_net_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, net_mode: int, net_unit: int, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("net_icon.png", target_icon_h)

        if net_mode == 1: # Live Graph
            margin_x = int(box_w * 0.08)
            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            if align == "center":
                gw = min(int(box_w * 0.75), box_w - 40)
                gx_min = x_min + (box_w - gw) / 2
                if icon_img is not None:
                    icon_x = int(gx_min)
                    icon_y = y_min + int((box_h - target_icon_h) / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)
                    gx_min += icon_w + gap
                graph_box = (int(gx_min), y_min + int(box_h * 0.15), int(gx_min + gw - icon_w - gap), y_max - int(box_h * 0.15))
            else:
                if icon_img is not None:
                    icon_x = x_min + margin_x
                    icon_y = y_min + int((box_h - target_icon_h) / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)
                    content_x = icon_x + icon_w + gap
                else:
                    content_x = x_min + margin_x
                graph_box = (content_x, y_min + int(box_h * 0.15), x_max - margin_x, y_max - int(box_h * 0.15))
            max_r = max(50.0, max(self.net_history) if self.net_history else 100.0)
            self.draw_history_graph(draw, graph_box, self.net_history, max_val=max_r, color=(100, 255, 100, 255))
        else: # Rates
            if net_unit == 1: # Bits
                rx_val, rx_u = (self.net_rx_rate * 8 / 1000, "Kbps") if (self.net_rx_rate * 8) < 1000000 else (self.net_rx_rate * 8 / 1000000, "Mbps")
                tx_val, tx_u = (self.net_tx_rate * 8 / 1000, "Kbps") if (self.net_tx_rate * 8) < 1000000 else (self.net_tx_rate * 8 / 1000000, "Mbps")
            else: # Bytes
                rx_val, rx_u = (self.net_rx_rate / 1024, "KB/s") if self.net_rx_rate < 1048576 else (self.net_rx_rate / 1048576, "MB/s")
                tx_val, tx_u = (self.net_tx_rate / 1024, "KB/s") if self.net_tx_rate < 1048576 else (self.net_tx_rate / 1048576, "MB/s")

            rx_str = f"↓ {rx_val:.1f} {rx_u}"
            tx_str = f"↑ {tx_val:.1f} {tx_u}"

            bbox_r = draw.textbbox((0, 0), rx_str, font=font_main)
            bbox_t = draw.textbbox((0, 0), tx_str, font=font_sub)
            rh, th = bbox_r[3] - bbox_r[1], bbox_t[3] - bbox_t[1]
            rw, tw = bbox_r[2] - bbox_r[0], bbox_t[2] - bbox_t[0]
            text_col_w = max(rw, tw)

            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            content_w = icon_w + (gap if icon_img else 0) + text_col_w

            if align == "center":
                start_x = x_min + max(0, (box_w - content_w) / 2)
            else:
                start_x = x_min + int(box_w * 0.08)

            if icon_img is not None:
                icon_x = int(start_x)
                icon_y = y_min + int((box_h - target_icon_h) / 2)
                image.paste(icon_img, (icon_x, icon_y), icon_img)
                content_x = icon_x + icon_w + gap
            else:
                content_x = start_x

            center_x = content_x + (text_col_w / 2)
            spacing = max(1, int(box_h * 0.04))
            total_h = rh + spacing + th
            start_y = y_min + (box_h - total_h) / 2
            rx_y = start_y + (rh / 2)
            tx_y = start_y + rh + spacing + (th / 2)

            self.render_styled_text(draw, (center_x, rx_y), rx_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, tx_y), tx_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def draw_ram_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, ram_mode: int, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("ram_icon.png", target_icon_h)
        latest_ram = self.ram_history[-1] if self.ram_history else 0.0

        if ram_mode == 2: # Live Graph
            margin_x = int(box_w * 0.08)
            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            if align == "center":
                gw = min(int(box_w * 0.75), box_w - 40)
                gx_min = x_min + (box_w - gw) / 2
                if icon_img is not None:
                    icon_x = int(gx_min)
                    icon_y = y_min + int((box_h - target_icon_h) / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)
                    gx_min += icon_w + gap
                graph_box = (int(gx_min), y_min + int(box_h * 0.15), int(gx_min + gw - icon_w - gap), y_max - int(box_h * 0.15))
            else:
                if icon_img is not None:
                    icon_x = x_min + margin_x
                    icon_y = y_min + int((box_h - target_icon_h) / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)
                    content_x = icon_x + icon_w + gap
                else:
                    content_x = x_min + margin_x
                graph_box = (content_x, y_min + int(box_h * 0.15), x_max - margin_x, y_max - int(box_h * 0.15))
            self.draw_history_graph(draw, graph_box, self.ram_history, max_val=100.0, color=(255, 170, 0, 255))
        elif ram_mode == 1: # Used / Total GB
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024**3)
            tot_gb = mem.total / (1024**3)
            main_str = f"{used_gb:.1f}/{tot_gb:.1f} GB"
            bbox_m = draw.textbbox((0, 0), main_str, font=font_main)
            tw = bbox_m[2] - bbox_m[0]

            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            content_w = icon_w + (gap if icon_img else 0) + tw

            if align == "center":
                start_x = x_min + max(0, (box_w - content_w) / 2)
            else:
                start_x = x_min + int(box_w * 0.08)

            if icon_img is not None:
                icon_x = int(start_x)
                icon_y = y_min + int((box_h - target_icon_h) / 2)
                image.paste(icon_img, (icon_x, icon_y), icon_img)
                content_x = icon_x + icon_w + gap
            else:
                content_x = start_x

            center_x = content_x + (tw / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # Percentage %
            main_str = f"RAM {round(latest_ram)}%"
            bbox_m = draw.textbbox((0, 0), main_str, font=font_main)
            tw = bbox_m[2] - bbox_m[0]

            icon_w = icon_img.width if icon_img else 0
            gap = int(box_w * 0.05) if icon_img else 0
            content_w = icon_w + (gap if icon_img else 0) + tw

            if align == "center":
                start_x = x_min + max(0, (box_w - content_w) / 2)
            else:
                start_x = x_min + int(box_w * 0.08)

            if icon_img is not None:
                icon_x = int(start_x)
                icon_y = y_min + int((box_h - target_icon_h) / 2)
                image.paste(icon_img, (icon_x, icon_y), icon_img)
                content_x = icon_x + icon_w + gap
            else:
                content_x = start_x

            center_x = content_x + (tw / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def get_disk_usage_host(self, mount_path: str) -> tuple[float, float, float]:
        if not mount_path:
            mount_path = "/"

        if not hasattr(self, "_disk_usage_cache"):
            self._disk_usage_cache = {}
        now = datetime.datetime.now().timestamp()
        if mount_path in self._disk_usage_cache:
            cached_time, cached_res = self._disk_usage_cache[mount_path]
            if now - cached_time < 5.0:
                return cached_res

        import shutil
        host_env = dict(os.environ)
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        if "DBUS_SESSION_BUS_ADDRESS" not in host_env or not host_env["DBUS_SESSION_BUS_ADDRESS"]:
            host_env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        if "XDG_RUNTIME_DIR" not in host_env or not host_env["XDG_RUNTIME_DIR"]:
            host_env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"

        if shutil.which("flatpak-spawn"):
            try:
                cmd = ["flatpak-spawn", "--host", "--directory=/", "df", "-k", mount_path]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=3, env=host_env)
                if p.returncode == 0 and p.stdout:
                    lines = p.stdout.strip().splitlines()
                    if len(lines) >= 2:
                        parts = lines[-1].split()
                        if len(parts) >= 5:
                            total_k = float(parts[1])
                            used_k = float(parts[2])
                            free_k = float(parts[3])
                            pct_str = parts[4].rstrip("%")
                            pct = float(pct_str) if pct_str.replace(".", "", 1).isdigit() else (used_k / max(1.0, total_k)) * 100.0
                            used_gb = used_k / (1024.0 * 1024.0)
                            free_gb = free_k / (1024.0 * 1024.0)
                            res = (pct, used_gb, free_gb)
                            self._disk_usage_cache[mount_path] = (now, res)
                            return res
            except Exception:
                pass

        for df_bin in ["df", "/usr/bin/df"]:
            try:
                p = subprocess.run([df_bin, "-k", mount_path], capture_output=True, text=True, timeout=2)
                if p.returncode == 0 and p.stdout:
                    lines = p.stdout.strip().splitlines()
                    if len(lines) >= 2:
                        parts = lines[-1].split()
                        if len(parts) >= 5:
                            total_k = float(parts[1])
                            used_k = float(parts[2])
                            free_k = float(parts[3])
                            pct_str = parts[4].rstrip("%")
                            pct = float(pct_str) if pct_str.replace(".", "", 1).isdigit() else (used_k / max(1.0, total_k)) * 100.0
                            used_gb = used_k / (1024.0 * 1024.0)
                            free_gb = free_k / (1024.0 * 1024.0)
                            return pct, used_gb, free_gb
            except Exception:
                pass

        try:
            du = psutil.disk_usage(mount_path)
            return du.percent, du.used / (1024**3), du.free / (1024**3)
        except Exception:
            return 0.0, 0.0, 0.0

    def draw_disk_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, disk_mode: int, disk_mount_path: str = "/", align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("disk_icon.png", target_icon_h)

        mount_path = disk_mount_path if disk_mount_path else "/"
        if not mount_path or mount_path == "/":
            disp_name = "System Root"
        elif mount_path.startswith("/home"):
            base = os.path.basename(mount_path.rstrip("/"))
            disp_name = f"Home ({base})" if base and base != "home" else "Home"
        else:
            base = os.path.basename(mount_path.rstrip("/"))
            disp_name = base.capitalize() if base else mount_path

        pct, used_gb, free_gb = self.get_disk_usage_host(mount_path)

        margin_x = int(box_w * 0.08)
        if icon_img is not None:
            icon_x = x_min + margin_x
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            content_x = icon_x + icon_img.width + int(margin_x * 0.8)
        else:
            content_x = x_min + margin_x

        max_avail_w = max(20.0, float((x_max - margin_x) - content_x))

        if disk_mode == 2: # Mini bar graph
            top_str = f"{disp_name} — {round(pct)}%"
            font_sub_fit = self.fit_font_to_width(draw, top_str, font_sub, max_avail_w, min_size=8)
            bbox_t = draw.textbbox((0, 0), top_str, font=font_sub_fit)
            th = bbox_t[3] - bbox_t[1]

            bar_h = max(8, int(box_h * 0.22))
            spacing = max(2, int(box_h * 0.06))
            total_h = th + spacing + bar_h

            start_y = y_min + (box_h - total_h) / 2
            top_y = start_y + (th / 2)
            bar_y_min = int(start_y + th + spacing)
            bar_y_max = bar_y_min + bar_h

            gx_min = content_x
            gx_max = x_max - margin_x
            gw = gx_max - gx_min

            self.render_styled_text(draw, (gx_min + (gw / 2), top_y), top_str, font_sub_fit, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            draw.rectangle([gx_min, bar_y_min, gx_max, bar_y_max], fill=(46, 204, 113, 220))
            fill_w = int(gw * (pct / 100.0))
            if fill_w > 0:
                draw.rectangle([gx_min, bar_y_min, gx_min + fill_w, bar_y_max], fill=(231, 76, 60, 220))
            draw.rectangle([gx_min, bar_y_min, gx_max, bar_y_max], outline=(200, 200, 200, 255), width=1)
        elif disk_mode == 1: # Used / Total GB
            top_str = f"{disp_name}"
            total_gb = used_gb + free_gb
            bot_str = f"{used_gb:.0f}GB/{total_gb:.0f}GB"

            font_main_fit = self.fit_font_to_width(draw, top_str, font_main, max_avail_w, min_size=9)
            font_sub_fit = self.fit_font_to_width(draw, bot_str, font_sub, max_avail_w, min_size=8)

            bbox_t = draw.textbbox((0, 0), top_str, font=font_main_fit)
            bbox_b = draw.textbbox((0, 0), bot_str, font=font_sub_fit)
            th, bh = bbox_t[3] - bbox_t[1], bbox_b[3] - bbox_b[1]
            center_x = content_x + (max_avail_w / 2.0)

            spacing = max(1, int(box_h * 0.04))
            total_h = th + spacing + bh
            start_y = y_min + (box_h - total_h) / 2.0
            top_y = start_y + (th / 2.0)
            bot_y = start_y + th + spacing + (bh / 2.0)

            self.render_styled_text(draw, (center_x, top_y), top_str, font_main_fit, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, bot_y), bot_str, font_sub_fit, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # Percentage %
            top_str = f"{disp_name}"
            bot_str = f"{round(pct)}% Used"

            font_main_fit = self.fit_font_to_width(draw, top_str, font_main, max_avail_w, min_size=9)
            font_sub_fit = self.fit_font_to_width(draw, bot_str, font_sub, max_avail_w, min_size=8)

            bbox_t = draw.textbbox((0, 0), top_str, font=font_main_fit)
            bbox_b = draw.textbbox((0, 0), bot_str, font=font_sub_fit)
            th, bh = bbox_t[3] - bbox_t[1], bbox_b[3] - bbox_b[1]
            center_x = content_x + (max_avail_w / 2.0)

            spacing = max(1, int(box_h * 0.04))
            total_h = th + spacing + bh
            start_y = y_min + (box_h - total_h) / 2.0
            top_y = start_y + (th / 2.0)
            bot_y = start_y + th + spacing + (bh / 2.0)

            self.render_styled_text(draw, (center_x, top_y), top_str, font_main_fit, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, bot_y), bot_str, font_sub_fit, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def draw_world_clock(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_city, font_time, font_sub, fill_en, fill_col, out_en, out_col, out_sz, city_idx: int, custom_label: str, custom_tz: str, show_offset: bool, use_24h: bool, show_seconds: bool, clock_view: int = 0, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        if 0 <= city_idx < len(self.worldclock_cities):
            city_name, tz_str = self.worldclock_cities[city_idx]
            if tz_str == "custom":
                tz_str = custom_tz.strip() or "UTC"
                default_label = custom_tz.split("/")[-1].replace("_", " ") if custom_tz else "Custom"
            else:
                default_label = city_name
        else:
            default_label = "London"
            tz_str = "Europe/London"

        disp_city = custom_label.strip() if custom_label.strip() else default_label

        try:
            tz = ZoneInfo(tz_str)
            city_now = datetime.datetime.now(tz)
        except Exception:
            tz = ZoneInfo("UTC")
            city_now = datetime.datetime.now(tz)

        if use_24h:
            time_fmt = "%H:%M:%S" if show_seconds else "%H:%M"
            time_str = city_now.strftime(time_fmt)
        else:
            time_fmt = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
            time_str = city_now.strftime(time_fmt).lstrip("0")

        offset_str = ""
        if show_offset:
            try:
                local_now = datetime.datetime.now().astimezone()
                city_offset_sec = city_now.utcoffset().total_seconds() if city_now.utcoffset() else 0
                local_offset_sec = local_now.utcoffset().total_seconds() if local_now.utcoffset() else 0
                diff_hours = (city_offset_sec - local_offset_sec) / 3600.0

                if diff_hours == 0:
                    diff_fmt = "Same time"
                elif diff_hours.is_integer():
                    diff_fmt = f"{int(diff_hours):+d}h"
                else:
                    diff_fmt = f"{diff_hours:+.1f}h"

                c_date = city_now.date()
                l_date = local_now.date()
                if c_date > l_date:
                    offset_str = f"Tomorrow ({diff_fmt})"
                elif c_date < l_date:
                    offset_str = f"Yesterday ({diff_fmt})"
                else:
                    offset_str = diff_fmt
            except Exception:
                offset_str = ""

        if clock_view == 1: # ANALOG CLOCK
            if box_h >= 80:
                dial_r = int(min(box_h - 14, box_w * 0.45) / 2)
                cx = x_min + dial_r + 14
                cy = y_min + (box_h / 2)

                draw.ellipse((cx - dial_r, cy - dial_r, cx + dial_r, cy + dial_r), outline=fill_col, width=2)
                for i in range(12):
                    angle = math.radians(i * 30)
                    is_cardinal = (i % 3 == 0)
                    tick_len = 6 if is_cardinal else 3
                    tick_w = 3 if is_cardinal else 1
                    x1 = cx + (dial_r - tick_len) * math.sin(angle)
                    y1 = cy - (dial_r - tick_len) * math.cos(angle)
                    x2 = cx + (dial_r - 1) * math.sin(angle)
                    y2 = cy - (dial_r - 1) * math.cos(angle)
                    draw.line((x1, y1, x2, y2), fill=fill_col, width=tick_w)

                hour = city_now.hour % 12
                minute = city_now.minute
                second = city_now.second

                h_angle = math.radians((hour + minute / 60.0) * 30)
                m_angle = math.radians((minute + second / 60.0) * 6)
                s_angle = math.radians(second * 6)

                hx = cx + (dial_r * 0.50) * math.sin(h_angle)
                hy = cy - (dial_r * 0.50) * math.cos(h_angle)
                draw.line((cx, cy, hx, hy), fill=fill_col, width=max(2, int(dial_r * 0.09)))

                mx = cx + (dial_r * 0.76) * math.sin(m_angle)
                my = cy - (dial_r * 0.76) * math.cos(m_angle)
                draw.line((cx, cy, mx, my), fill=fill_col, width=max(1, int(dial_r * 0.05)))

                if show_seconds:
                    sx = cx + (dial_r * 0.85) * math.sin(s_angle)
                    sy = cy - (dial_r * 0.85) * math.cos(s_angle)
                    sec_col = (255, 85, 85, 255) if fill_col != (255, 85, 85, 255) else (255, 153, 0, 255)
                    draw.line((cx, cy, sx, sy), fill=sec_col, width=1)

                draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=fill_col)

                text_x_start = cx + dial_r + 12
                text_center_x = text_x_start + (x_max - text_x_start) / 2

                bbox_city = draw.textbbox((0, 0), disp_city, font=font_city)
                bbox_time = draw.textbbox((0, 0), time_str, font=font_sub)
                bbox_off = draw.textbbox((0, 0), offset_str, font=font_sub) if offset_str else (0, 0, 0, 0)

                ch = bbox_city[3] - bbox_city[1]
                th = bbox_time[3] - bbox_time[1]
                oh = (bbox_off[3] - bbox_off[1]) if offset_str else 0

                spacing = max(1, int(box_h * 0.03))
                total_h = ch + spacing + th + (spacing + oh if offset_str else 0)
                start_y = y_min + (box_h - total_h) / 2

                city_y = start_y + (ch / 2)
                time_y = start_y + ch + spacing + (th / 2)
                off_y = start_y + ch + spacing + th + spacing + (oh / 2)

                self.render_styled_text(draw, (text_center_x, city_y), disp_city, font_city, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
                self.render_styled_text(draw, (text_center_x, time_y), time_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
                if offset_str:
                    self.render_styled_text(draw, (text_center_x, off_y), offset_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            else:
                dial_r = int(min(box_h - 8, box_w * 0.35) / 2)
                cx = x_min + dial_r + 8
                cy = y_min + (box_h / 2)

                draw.ellipse((cx - dial_r, cy - dial_r, cx + dial_r, cy + dial_r), outline=fill_col, width=1)
                for i in range(12):
                    angle = math.radians(i * 30)
                    is_cardinal = (i % 3 == 0)
                    tick_len = 4 if is_cardinal else 2
                    tick_w = 2 if is_cardinal else 1
                    x1 = cx + (dial_r - tick_len) * math.sin(angle)
                    y1 = cy - (dial_r - tick_len) * math.cos(angle)
                    x2 = cx + (dial_r - 1) * math.sin(angle)
                    y2 = cy - (dial_r - 1) * math.cos(angle)
                    draw.line((x1, y1, x2, y2), fill=fill_col, width=tick_w)

                hour = city_now.hour % 12
                minute = city_now.minute
                second = city_now.second

                h_angle = math.radians((hour + minute / 60.0) * 30)
                m_angle = math.radians((minute + second / 60.0) * 6)
                s_angle = math.radians(second * 6)

                hx = cx + (dial_r * 0.50) * math.sin(h_angle)
                hy = cy - (dial_r * 0.50) * math.cos(h_angle)
                draw.line((cx, cy, hx, hy), fill=fill_col, width=2)

                mx = cx + (dial_r * 0.76) * math.sin(m_angle)
                my = cy - (dial_r * 0.76) * math.cos(m_angle)
                draw.line((cx, cy, mx, my), fill=fill_col, width=1)

                if show_seconds:
                    sx = cx + (dial_r * 0.85) * math.sin(s_angle)
                    sy = cy - (dial_r * 0.85) * math.cos(s_angle)
                    sec_col = (255, 85, 85, 255) if fill_col != (255, 85, 85, 255) else (255, 153, 0, 255)
                    draw.line((cx, cy, sx, sy), fill=sec_col, width=1)

                draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=fill_col)

                text_x_start = cx + dial_r + 6
                text_center_x = text_x_start + (x_max - text_x_start) / 2
                full_time_line = f"{disp_city} ({offset_str})" if offset_str else disp_city
                self.render_styled_text(draw, (text_center_x, cy), full_time_line, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # DIGITAL CLOCK
            if align == "center":
                center_x = x_min + (box_w / 2)
                anchor = "mm"
            else:
                margin_x = int(box_w * 0.08)
                center_x = x_min + margin_x
                anchor = "lm"

            if box_h >= 80:
                bbox_city = draw.textbbox((0, 0), disp_city, font=font_city)
                bbox_time = draw.textbbox((0, 0), time_str, font=font_time)
                bbox_off = draw.textbbox((0, 0), offset_str, font=font_sub) if offset_str else (0, 0, 0, 0)

                ch = bbox_city[3] - bbox_city[1]
                th = bbox_time[3] - bbox_time[1]
                oh = (bbox_off[3] - bbox_off[1]) if offset_str else 0

                spacing = max(1, int(box_h * 0.03))
                total_h = ch + spacing + th + (spacing + oh if offset_str else 0)
                start_y = y_min + (box_h - total_h) / 2

                city_y = start_y + (ch / 2)
                time_y = start_y + ch + spacing + (th / 2)
                off_y = start_y + ch + spacing + th + spacing + (oh / 2)

                self.render_styled_text(draw, (center_x, city_y), disp_city, font_city, fill_en, fill_col, out_en, out_col, out_sz, anchor=anchor)
                self.render_styled_text(draw, (center_x, time_y), time_str, font_time, fill_en, fill_col, out_en, out_col, out_sz, anchor=anchor)
                if offset_str:
                    self.render_styled_text(draw, (center_x, off_y), offset_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor=anchor)
            else:
                full_time_line = f"{time_str} ({offset_str})" if offset_str else time_str
                bbox_city = draw.textbbox((0, 0), disp_city, font=font_city)
                bbox_time = draw.textbbox((0, 0), full_time_line, font=font_sub)

                ch = bbox_city[3] - bbox_city[1]
                th = bbox_time[3] - bbox_time[1]

                spacing = max(1, int(box_h * 0.04))
                total_h = ch + spacing + th
                start_y = y_min + (box_h - total_h) / 2

                city_y = start_y + (ch / 2)
                time_y = start_y + ch + spacing + (th / 2)

                self.render_styled_text(draw, (center_x, city_y), disp_city, font_city, fill_en, fill_col, out_en, out_col, out_sz, anchor=anchor)
                self.render_styled_text(draw, (center_x, time_y), full_time_line, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor=anchor)

    # --- Media Player Drawers & Helpers ---
    def interpolate_color(self, c1: tuple, c2: tuple, t: float) -> tuple:
        t = min(1.0, max(0.0, float(t)))
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        a = int(c1[3] + (c2[3] - c1[3]) * t) if len(c1) > 3 and len(c2) > 3 else 255
        return (r, g, b, a)

    def interpolate_gradient_3(self, c_start: tuple, c_mid: tuple, c_end: tuple, t: float) -> tuple:
        t = max(0.0, min(1.0, float(t)))
        if t <= 0.5:
            local_t = t * 2.0
            return self.interpolate_color(c_start, c_mid, local_t)
        else:
            local_t = (t - 0.5) * 2.0
            return self.interpolate_color(c_mid, c_end, local_t)

    def update_media_state(self, poll_dbus: bool = True):
        now_ts = time.time()
        if poll_dbus or (now_ts - self._last_dbus_poll > 0.8):
            self._last_dbus_poll = now_ts
            try:
                if not self.session_bus:
                    self.session_bus = dbus.SessionBus()
                player_names = [name for name in self.session_bus.list_names() if name.startswith("org.mpris.MediaPlayer2.")]
            except Exception:
                player_names = []

            settings = self.get_settings() or {}
            player_id = settings.get("media_player_id", "") if isinstance(settings, dict) else ""
            if not player_id:
                player_idx = settings.get("media_player_idx", 0) if isinstance(settings, dict) else 0
                player_id = self.media_player_ids[player_idx] if hasattr(self, "media_player_ids") and isinstance(player_idx, int) and player_idx < len(self.media_player_ids) else "auto"
            player_id = str(player_id) if isinstance(player_id, str) else "auto"

            target_name = None
            if player_id and player_id != "auto":
                for name in player_names:
                    if player_id in name.lower():
                        target_name = name
                        break

            # Auto-detect: search for active Playing player first, else Paused, else first available
            if target_name is None and player_names and self.session_bus:
                playing_candidates = []
                paused_candidates = []
                for name in player_names:
                    try:
                        obj = self.session_bus.get_object(name, "/org/mpris/MediaPlayer2")
                        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                        status = str(props.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus"))
                        if status == "Playing":
                            playing_candidates.append(name)
                        elif status == "Paused":
                            paused_candidates.append(name)
                    except Exception:
                        pass
                if playing_candidates:
                    target_name = playing_candidates[0]
                elif paused_candidates:
                    target_name = paused_candidates[0]
                else:
                    target_name = player_names[0]

            title = ""
            artist = ""
            album = ""
            art_url = ""
            playback_status = "Stopped"

            if target_name and self.session_bus:
                try:
                    obj = self.session_bus.get_object(target_name, "/org/mpris/MediaPlayer2")
                    props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                    playback_status = str(props.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus"))
                    metadata = props.Get("org.mpris.MediaPlayer2.Player", "Metadata")
                    if metadata:
                        if "xesam:title" in metadata:
                            title = str(metadata["xesam:title"])
                        if "xesam:artist" in metadata:
                            raw_artist = metadata["xesam:artist"]
                            if isinstance(raw_artist, (list, dbus.Array)):
                                artist = ", ".join(str(a) for a in raw_artist if str(a))
                            else:
                                artist = str(raw_artist)
                        if "xesam:album" in metadata:
                            album = str(metadata["xesam:album"])
                        if "mpris:artUrl" in metadata:
                            art_url = str(metadata["mpris:artUrl"])
                except Exception:
                    pass

            if not title and not artist:
                title = "No Media Playing"
                artist = "Touch-bar Info"
                playback_status = "Stopped"

            # Normalize Spotify / Web art URLs
            if art_url:
                if art_url.startswith("spotify:image:"):
                    art_url = "https://i.scdn.co/image/" + art_url.split(":")[-1]
                elif "open.spotify.com/image/" in art_url:
                    art_url = "https://i.scdn.co/image/" + art_url.split("/")[-1]

            self.media_state = {
                "title": title,
                "artist": artist,
                "album": album,
                "art_url": art_url,
                "status": playback_status
            }

        # Advance visualizer tick and simulate independent equalizer bars
        is_playing = (self.media_state["status"] == "Playing")
        num_bars = len(self.vis_heights)

        if is_playing:
            self.vis_tick += 1
            t = self.vis_tick * 0.35
            beat = (math.sin(t * 1.6) ** 4) * 0.55 + (math.sin(t * 0.8 + 1.2) ** 6) * 0.45
            for i in range(num_bars):
                norm_idx = i / float(max(1, num_bars - 1))
                if norm_idx < 0.35:
                    # Bass frequencies: heavy bounce responding to beat
                    band_energy = beat * (1.15 - norm_idx * 0.8) + math.sin(t * 0.9 * self.vis_speeds[i] + self.vis_phases[i]) * 0.25
                    jitter = random.uniform(0.0, 0.22)
                elif norm_idx < 0.7:
                    # Mid frequencies: vocal / melodic energy
                    band_energy = 0.32 + math.sin(t * 1.5 * self.vis_speeds[i] + self.vis_phases[i]) * 0.32 + (beat * 0.28)
                    jitter = random.uniform(-0.1, 0.22)
                else:
                    # High frequencies: fast treble bursts
                    band_energy = 0.18 + math.sin(t * 2.3 * self.vis_speeds[i] + self.vis_phases[i]) * 0.25
                    jitter = random.uniform(0.0, 0.38) if random.random() < 0.45 else -0.05

                target = max(0.06, min(0.98, band_energy + jitter))

                # Fast attack (bounces up sharply), smooth gravity decay
                if target > self.vis_heights[i]:
                    self.vis_heights[i] = self.vis_heights[i] * 0.25 + target * 0.75
                else:
                    self.vis_heights[i] = max(0.05, self.vis_heights[i] * 0.75 + target * 0.25)
        else:
            # Instant flat baseline when paused or stopped
            self.vis_heights = [0.04] * num_bars

    def get_media_art(self, art_url: str, target_size: tuple[int, int], corner_radius: int = 8) -> Image.Image:
        tw, th = target_size

        # URL Normalization
        if art_url:
            if art_url.startswith("spotify:image:"):
                art_url = "https://i.scdn.co/image/" + art_url.split(":")[-1]
            elif "open.spotify.com/image/" in art_url:
                art_url = "https://i.scdn.co/image/" + art_url.split("/")[-1]

        cache_key = (art_url, tw, th, corner_radius)
        if art_url and cache_key in self.media_art_cache:
            return self.media_art_cache[cache_key]

        raw_img = None
        is_real_art = False

        if art_url:
            if art_url.startswith("file://"):
                try:
                    p = unquote(urlparse(art_url).path)
                    if os.path.isfile(p):
                        raw_img = Image.open(p).convert("RGBA")
                        is_real_art = True
                except Exception:
                    pass
            elif os.path.isabs(art_url) and os.path.isfile(art_url):
                try:
                    raw_img = Image.open(art_url).convert("RGBA")
                    is_real_art = True
                except Exception:
                    pass
            elif art_url.startswith("data:image"):
                try:
                    header, b64data = art_url.split(",", 1)
                    img_data = base64.b64decode(b64data)
                    raw_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
                    is_real_art = True
                except Exception:
                    pass
            elif art_url.startswith(("http://", "https://")):
                cache_dir = os.path.expanduser("~/.cache/touchbar_media_cache")
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                except Exception:
                    cache_dir = "/tmp/touchbar_media_cache"
                    os.makedirs(cache_dir, exist_ok=True)

                url_hash = hashlib.md5(art_url.encode("utf-8")).hexdigest()
                cached_file = os.path.join(cache_dir, f"{url_hash}.png")
                if os.path.isfile(cached_file):
                    try:
                        raw_img = Image.open(cached_file).convert("RGBA")
                        is_real_art = True
                    except Exception:
                        pass
                else:
                    if art_url not in self.media_fetching_urls:
                        self.media_fetching_urls.add(art_url)
                        def _fetch(target_url=art_url, out_path=cached_file):
                            try:
                                resp = requests.get(target_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
                                if resp.status_code == 200:
                                    with open(out_path, "wb") as f:
                                        f.write(resp.content)
                                    self.media_art_cache.clear()
                                    self.last_rendered_key = ""
                                    GLib.idle_add(self.schedule_update_display)
                            except Exception as e:
                                log.warning(f"TouchBarInfo: Failed to download media art {target_url}: {e}")
                            finally:
                                self.media_fetching_urls.discard(target_url)
                        Thread(target=_fetch, daemon=True).start()

        if raw_img is None:
            placeholder_path = os.path.join(self.plugin_base.PATH, "assets", "media_placeholder.png")
            if os.path.isfile(placeholder_path):
                try:
                    raw_img = Image.open(placeholder_path).convert("RGBA")
                except Exception:
                    pass
            if raw_img is None:
                raw_img = Image.new("RGBA", (tw, th), (35, 39, 42, 255))
                d = ImageDraw.Draw(raw_img)
                d.ellipse((int(tw * 0.1), int(th * 0.1), int(tw * 0.9), int(th * 0.9)), fill=(20, 20, 20, 255), outline=(100, 100, 100, 255), width=2)
                d.ellipse((int(tw * 0.4), int(th * 0.4), int(tw * 0.6), int(th * 0.6)), fill=(230, 70, 70, 255))

        # Center crop square and resize
        iw, ih = raw_img.size
        min_dim = min(iw, ih)
        crop_box = ((iw - min_dim) // 2, (ih - min_dim) // 2, (iw + min_dim) // 2, (ih + min_dim) // 2)
        cropped = raw_img.crop(crop_box).resize((tw, th), Image.Resampling.LANCZOS)

        # Rounded corner mask
        mask = Image.new("L", (tw, th), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle((0, 0, tw, th), radius=corner_radius, fill=255)
        rounded_img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        rounded_img.paste(cropped, (0, 0), mask)

        if is_real_art:
            self.media_art_cache[cache_key] = rounded_img

        return rounded_img

    def draw_marquee_text(self, image: Image.Image, draw: ImageDraw.ImageDraw, pos: tuple[float, float], max_w: float, text: str, font, fill_en: bool = True, fill_col: tuple = (255, 255, 255, 255), out_en: bool = False, out_col: tuple = (0, 0, 0, 255), out_sz: int = 2):
        if not text:
            return
        x, y = pos
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        if tw <= max_w:
            center_y = y + (th / 2.0)
            self.render_styled_text(draw, (x, center_y), text, font, fill_en, fill_col, out_en, out_col, out_sz, anchor="lm")
            return

        gap = 40
        loop_w = tw + gap
        scroll_offset = (self.vis_tick * 2) % loop_w

        surf_w = int(max_w)
        surf_h = int(th + max(4, out_sz * 4) + 4)
        sub_img = Image.new("RGBA", (surf_w, surf_h), (0, 0, 0, 0))
        sub_draw = ImageDraw.Draw(sub_img)

        text_y = surf_h / 2.0
        self.render_styled_text(sub_draw, (-scroll_offset, text_y), text, font, fill_en, fill_col, out_en, out_col, out_sz, anchor="lm")
        self.render_styled_text(sub_draw, (-scroll_offset + loop_w, text_y), text, font, fill_en, fill_col, out_en, out_col, out_sz, anchor="lm")

        paste_y = int(y - (surf_h - th) / 2.0)
        image.paste(sub_img, (int(x), paste_y), sub_img)

    def draw_stepped_bars(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], heights: list[float], color_mode: int, solid_col: tuple, start_col: tuple, mid_col: tuple, end_col: tuple):
        x_min, y_min, x_max, y_max = box
        bw = x_max - x_min
        bh = y_max - y_min
        if bw <= 8 or bh <= 6:
            return

        col_gap = 2
        # Target ~4-6px per column
        num_cols = min(len(heights), max(6, int((bw + col_gap) / (5 + col_gap))))
        col_w = max(2.0, (bw - (num_cols - 1) * col_gap) / float(num_cols))

        step_gap = 1
        # Target ~3px per step block (e.g. 2px block + 1px gap)
        num_steps = max(4, int((bh + step_gap) / (3 + step_gap)))
        step_h = max(2.0, (bh - (num_steps - 1) * step_gap) / float(num_steps))

        for i in range(num_cols):
            val = heights[i % len(heights)]
            norm_h = max(0.0, min(1.0, float(val)))
            active_steps = max(1, int(round(norm_h * num_steps)))

            cx_min = x_min + i * (col_w + col_gap)
            cx_max = cx_min + col_w

            for s in range(active_steps):
                sy_max = y_max - s * (step_h + step_gap)
                sy_min = sy_max - step_h

                if color_mode == 1:
                    # Vertical 3-Color Gradient: Bottom Start -> Mid -> Top End
                    t = s / max(1.0, float(num_steps - 1))
                    col = self.interpolate_gradient_3(start_col, mid_col, end_col, t)
                else:
                    col = solid_col

                draw.rectangle([cx_min, sy_min, cx_max, sy_max], fill=col)

    def draw_wave_curves(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], heights: list[float], color_mode: int, solid_col: tuple, start_col: tuple, mid_col: tuple, end_col: tuple, phase: float = 0.0):
        x_min, y_min, x_max, y_max = box
        bw = x_max - x_min
        bh = y_max - y_min
        if bw <= 10 or bh <= 6:
            return

        num_h = len(heights)
        pts = []
        for x in range(int(x_min), int(x_max) + 1):
            tx = (x - x_min) / float(bw)
            idx_f = tx * (num_h - 1)
            i0 = int(idx_f)
            i1 = min(num_h - 1, i0 + 1)
            frac = idx_f - i0
            amp = heights[i0] * (1.0 - frac) + heights[i1] * frac

            wave = math.sin(tx * math.pi * 3.5 + phase) * 0.45 + math.cos(tx * math.pi * 1.8 - phase * 0.8) * 0.35 + 0.2
            val = max(0.05, min(1.0, amp * (0.5 + 0.5 * wave)))
            y = y_max - (val * (bh - 2))
            pts.append((x, y))

        if color_mode == 1:
            # Horizontal 3-Color Gradient: Left Start -> Mid -> Right End
            for (x, y) in pts:
                tx = (x - x_min) / float(bw)
                col = self.interpolate_gradient_3(start_col, mid_col, end_col, tx)
                fill_col = (col[0], col[1], col[2], int(col[3] * 0.75))
                draw.line([(x, y), (x, y_max)], fill=fill_col, width=1)
                draw.point((x, y), fill=col)
        else:
            poly = pts + [(x_max, y_max), (x_min, y_max)]
            fill_col = (solid_col[0], solid_col[1], solid_col[2], int(solid_col[3] * 0.75))
            draw.polygon(poly, fill=fill_col)
            if len(pts) >= 2:
                draw.line(pts, fill=solid_col, width=2)

    def draw_media_full(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_artist, font_song, artist_fill_en, artist_fill_col, artist_out_en, artist_out_col, artist_out_sz, song_fill_en, song_fill_col, song_out_en, song_out_col, song_out_sz, player_idx: int, vis_style: int, color_mode: int, solid_col: tuple, start_col: tuple, mid_col: tuple, end_col: tuple, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        bw = x_max - x_min
        bh = y_max - y_min

        # 1. Left Album Art
        art_size = int(bh * 0.76)
        margin_x = int(bw * 0.04)
        art_x = x_min + margin_x
        art_y = y_min + (bh - art_size) // 2

        art_img = self.get_media_art(self.media_state.get("art_url", ""), (art_size, art_size), corner_radius=10)
        if art_img:
            image.paste(art_img, (art_x, art_y), art_img)

        # 2. Right Text & Visualizer
        content_x = art_x + art_size + int(bw * 0.04)
        content_max_x = x_max - margin_x
        avail_w = max(20.0, float(content_max_x - content_x))

        title = self.media_state.get("title", "No Media Playing")
        artist = self.media_state.get("artist", "")

        song_y = y_min + int(bh * 0.10)
        artist_y = y_min + int(bh * 0.35)

        self.draw_marquee_text(image, draw, (content_x, song_y), avail_w, title, font_song, song_fill_en, song_fill_col, song_out_en, song_out_col, song_out_sz)
        if artist:
            self.draw_marquee_text(image, draw, (content_x, artist_y), avail_w, artist, font_artist, artist_fill_en, artist_fill_col, artist_out_en, artist_out_col, artist_out_sz)

        # Visualizer
        vis_box = (content_x, y_min + int(bh * 0.58), content_max_x, y_max - int(bh * 0.08))
        if vis_style == 1:
            self.draw_wave_curves(image, draw, vis_box, self.vis_heights, color_mode, solid_col, start_col, mid_col, end_col, self.vis_tick * 0.15)
        else:
            self.draw_stepped_bars(draw, vis_box, self.vis_heights, color_mode, solid_col, start_col, mid_col, end_col)

    def draw_media_sub(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], player_idx: int, vis_style: int, color_mode: int, solid_col: tuple, start_col: tuple, mid_col: tuple, end_col: tuple, align: str = "left"):
        x_min, y_min, x_max, y_max = box
        bw = x_max - x_min
        bh = y_max - y_min

        # 1. Left Album Art
        art_size = int(bh * 0.76)
        margin_x = int(bw * 0.04)
        art_x = x_min + margin_x
        art_y = y_min + (bh - art_size) // 2

        art_img = self.get_media_art(self.media_state.get("art_url", ""), (art_size, art_size), corner_radius=6)
        if art_img:
            image.paste(art_img, (art_x, art_y), art_img)

        # 2. Right: Full Height Visualizer
        vis_x_min = art_x + art_size + int(bw * 0.04)
        vis_x_max = x_max - margin_x
        vis_box = (vis_x_min, y_min + 4, vis_x_max, y_max - 4)

        if vis_style == 1:
            self.draw_wave_curves(image, draw, vis_box, self.vis_heights, color_mode, solid_col, start_col, mid_col, end_col, self.vis_tick * 0.15)
        else:
            self.draw_stepped_bars(draw, vis_box, self.vis_heights, color_mode, solid_col, start_col, mid_col, end_col)

    def start_anim_timer(self):
        if self._anim_timer_id is None:
            self._anim_timer_id = GLib.timeout_add(40, self._anim_tick)

    def stop_anim_timer(self):
        if self._anim_timer_id is not None:
            try:
                GLib.source_remove(self._anim_timer_id)
            except Exception:
                pass
            self._anim_timer_id = None

    def _anim_tick(self) -> bool:
        if self._was_locked:
            self._anim_timer_id = None
            return False
        if not self.is_media_active_and_playing():
            self._anim_timer_id = None
            self.vis_heights = [0.04] * len(self.vis_heights)
            self.last_rendered_key = ""
            self.update_display()
            return False

        self.update_media_state(poll_dbus=False)
        self.update_display()
        return True

    def is_media_active_and_playing(self) -> bool:
        settings = self.get_settings() or {}
        slots = [
            ("sec_a", "full_widget", "top_widget", "bottom_widget", "mode"),
            ("sec_b", "full_widget", "top_widget", "bottom_widget", "mode"),
            ("sec_c", "full_widget", "top_widget", "bottom_widget", "mode")
        ]
        is_active = False
        for prefix, fw, tw, bw, mw in slots:
            mode = self.get_slot_setting(settings, prefix, "mode", 0)
            if mode == 0:
                if self.get_slot_setting(settings, f"{prefix}_full", "widget", self.get_slot_setting(settings, prefix, "full_widget", 0)) == 4:
                    is_active = True
                    break
            else:
                if self.get_slot_setting(settings, f"{prefix}_top", "widget", self.get_slot_setting(settings, prefix, "top_widget", 0)) == 4:
                    is_active = True
                    break
                if self.get_slot_setting(settings, f"{prefix}_bot", "widget", self.get_slot_setting(settings, prefix, "bottom_widget", 0)) == 4:
                    is_active = True
                    break
        return is_active and (self.media_state.get("status") == "Playing")

    def is_screen_locked(self) -> bool:
        try:
            if not self.session_bus:
                self.session_bus = dbus.SessionBus()
            try:
                obj = self.session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
                props = dbus.Interface(obj, "org.gnome.ScreenSaver")
                if bool(props.GetActive()):
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    def handle_lock_blanking(self) -> bool:
        if self.is_screen_locked():
            if not self._was_locked:
                self._was_locked = True
                blank_img = Image.new("RGBA", (800, 100), (0, 0, 0, 255))
                self.render_to_input(blank_img)
            return True
        else:
            if self._was_locked:
                self._was_locked = False
                self.last_rendered_key = ""
                self.trigger_redraw()
            return False

    def render_to_input(self, image: Image.Image) -> None:
        if not hasattr(self, "page") or self.page is None:
            return

        final_image = image
        try:
            settings = self.get_settings() or {}
            custom_bg = settings.get("custom_bg_path", "")

            resolved_bg_path = None
            if custom_bg:
                if os.path.isabs(custom_bg) and os.path.isfile(custom_bg):
                    resolved_bg_path = custom_bg
                elif hasattr(gl, "DATA_PATH"):
                    rel_p = os.path.join(gl.DATA_PATH, custom_bg)
                    if os.path.isfile(rel_p):
                        resolved_bg_path = rel_p
                elif hasattr(gl, "asset_manager_backend") and gl.asset_manager_backend is not None:
                    try:
                        if gl.asset_manager_backend.has_by_internal_path(custom_bg):
                            asset_data = gl.asset_manager_backend.get_by_internal_path(custom_bg)
                            if asset_data and "path" in asset_data:
                                resolved_bg_path = asset_data["path"]
                    except Exception:
                        pass

            if not resolved_bg_path and hasattr(self.page, "get_background_image"):
                bg_p = self.page.get_background_image(self.input_ident, self.state)
                if bg_p and os.path.isfile(bg_p) and not bg_p.endswith(("touchbar_render_0.png", "touchbar_render_1.png")):
                    resolved_bg_path = bg_p

            if resolved_bg_path and os.path.isfile(resolved_bg_path):
                if self._cached_bg_path != resolved_bg_path or self._cached_bg_image is None or self._cached_bg_image.size != image.size:
                    with Image.open(resolved_bg_path) as bg_img:
                        self._cached_bg_image = bg_img.convert("RGBA").resize(image.size, Image.Resampling.LANCZOS)
                    self._cached_bg_path = resolved_bg_path
                final_image = Image.alpha_composite(self._cached_bg_image, image)
            else:
                base = Image.new("RGBA", (800, 100), (0, 0, 0, 255))
                final_image = Image.alpha_composite(base, image)
        except Exception as e:
            log.error(f"TouchBarInfo: Error compositing custom background image: {e}")

        assets_dir = os.path.join(self.plugin_base.PATH, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        render_path = os.path.join(assets_dir, f"touchbar_render_{self.state}.png")

        try:
            final_image.save(render_path, format="PNG", compress_level=1)
            self.page.set_background_image(self.input_ident, self.state, render_path, update=False)
        except Exception as e:
            log.error(f"TouchBarInfo: Error saving touchscreen background: {e}")

        if hasattr(self, "deck_controller") and self.deck_controller is not None:
            c_input = self.deck_controller.get_input(self.input_ident)
            if c_input is not None and hasattr(c_input, "update"):
                try:
                    c_input.update()
                except Exception as e:
                    log.error(f"TouchBarInfo: Error updating touchscreen controller: {e}")

    def update_system_stats(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            self.cpu_history.pop(0)
            self.cpu_history.append(cpu)

            mem = psutil.virtual_memory()
            self.ram_history.pop(0)
            self.ram_history.append(mem.percent)

            self.process_count = len(psutil.pids())

            net = psutil.net_io_counters()
            now = datetime.datetime.now().timestamp()
            if self.last_net_io is not None:
                last_time, last_bytes_sent, last_bytes_recv = self.last_net_io
                dt = max(0.1, now - last_time)
                self.net_tx_rate = max(0.0, (net.bytes_sent - last_bytes_sent) / dt)
                self.net_rx_rate = max(0.0, (net.bytes_recv - last_bytes_recv) / dt)
                total_rate_kb = (self.net_tx_rate + self.net_rx_rate) / 1024.0
                self.net_history.pop(0)
                self.net_history.append(total_rate_kb)
            self.last_net_io = (now, net.bytes_sent, net.bytes_recv)
        except Exception as e:
            log.error(f"TouchBarInfo: Error updating system stats: {e}")

    def on_ready(self):
        self.load_config_defaults()
        self.fetch_weather_async()
        self.update_system_stats()
        self.update_media_state(poll_dbus=True)
        self.update_display()
        if self.is_media_active_and_playing():
            self.start_anim_timer()

        def background_timer():
            while True:
                time.sleep(1.0)
                if not self.handle_lock_blanking():
                    self.update_system_stats()
                    self.update_media_state(poll_dbus=True)
                    self.fetch_weather_async()
                    if self.is_media_active_and_playing():
                        GLib.idle_add(self.start_anim_timer)
                    else:
                        GLib.idle_add(self.stop_anim_timer)
                    GLib.idle_add(self.update_display)

        Thread(target=background_timer, daemon=True).start()

    def on_key_down(self):
        self.fetch_weather_async(force=True)
        self.update_display()

    def trigger_redraw(self):
        self.last_rendered_key = ""
        if hasattr(self, "_font_cache"):
            self._font_cache.clear()
        self.update_display()

    def schedule_update_display(self):
        if getattr(self, "_update_scheduled", False):
            return
        self._update_scheduled = True

        def _do_update():
            self._update_scheduled = False
            self.trigger_redraw()
            return False

        GLib.timeout_add(50, _do_update)

    def update_display(self):
        if self.handle_lock_blanking():
            return

        settings = self.get_settings() or {}
        now = datetime.datetime.now()

        # Canvas & Background (Transparent overlay layer for widgets)
        image = Image.new("RGBA", (800, 100), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Default system monitor fonts
        font_mon_main_full = self.get_font_from_desc("DejaVu Sans Bold 20", default_size=20)
        font_mon_sub_full = self.get_font_from_desc("DejaVu Sans Bold 14", default_size=14)
        font_mon_main_sub = self.get_font_from_desc("DejaVu Sans Bold 13", default_size=13)
        font_mon_sub_sub = self.get_font_from_desc("DejaVu Sans Bold 11", default_size=11)
        white_col = (255, 255, 255, 255)

        # Helper to render a specific widget inside a slot box
        def render_slot_widget(slot_key: str, widget_choice: int, box: tuple[int, int, int, int], is_full: bool, align: str):
            if widget_choice == 0:
                return # Blank / None

            if widget_choice == 1: # CPU Usage
                cpu_mode_idx = self.get_slot_setting(settings, slot_key, "cpu_mode_idx", 0)
                font_main = font_mon_main_full if is_full else font_mon_main_sub
                font_sub = font_mon_sub_full if is_full else font_mon_sub_sub
                self.draw_cpu_widget(image, draw, box, font_main, font_sub, True, white_col, False, white_col, 2, cpu_mode_idx, align=align)

            elif widget_choice == 2: # Date
                date_fmt_idx = self.get_slot_setting(settings, slot_key, "date_format_idx", 0)
                fmt_str = self.date_format_options[min(date_fmt_idx, len(self.date_format_options) - 1)][0]
                date_str = now.strftime(fmt_str)
                date_font_str = self.get_slot_setting(settings, slot_key, "date_font_str", "DejaVu Sans Bold 25")
                font_date = self.get_font_from_desc(date_font_str, default_size=25 if is_full else 16)
                fill_en = self.get_slot_setting(settings, slot_key, "date_fill_enabled", True)
                fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "date_font_color", "#AAC8E6FF"), (170, 200, 230, 255))
                out_en = self.get_slot_setting(settings, slot_key, "date_outline_enabled", False)
                out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "date_outline_color", "#000000FF"), (0, 0, 0, 255))
                out_sz = self.get_slot_setting(settings, slot_key, "date_outline_size", 2)
                self.draw_single(draw, box, date_str, font_date, fill_en, fill_col, out_en, out_col, out_sz, align=align)

            elif widget_choice == 3: # Disk Usage
                disk_mode_idx = self.get_slot_setting(settings, slot_key, "disk_mode_idx", 0)
                disk_mount_path = self.get_slot_setting(settings, slot_key, "disk_mount_path", "/")
                font_main = font_mon_main_full if is_full else font_mon_main_sub
                font_sub = font_mon_sub_full if is_full else font_mon_sub_sub
                self.draw_disk_widget(image, draw, box, font_main, font_sub, True, white_col, False, white_col, 2, disk_mode_idx, disk_mount_path, align=align)

            elif widget_choice == 4: # Media Player
                vis_style = self.get_slot_setting(settings, slot_key, "media_vis_style_idx", 0)
                color_mode = self.get_slot_setting(settings, slot_key, "media_color_mode_idx", 0)
                solid_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_solid_color", "#FFFFFFFF"), (255, 255, 255, 255))
                grad_start = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_grad_start", "#00D2FFFF"), (0, 210, 255, 255))
                grad_mid = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_grad_mid", "#7B2CBFFF"), (123, 44, 191, 255))
                grad_end = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_grad_end", "#FF2A6DFF"), (255, 42, 109, 255))

                if is_full:
                    s_font_str = self.get_slot_setting(settings, slot_key, "media_song_font_str", "DejaVu Sans Bold 18")
                    font_song = self.get_font_from_desc(s_font_str, default_size=18, scale_factor=1.0)
                    s_fill_en = self.get_slot_setting(settings, slot_key, "media_song_fill_enabled", True)
                    s_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_song_font_color", "#FFFFFFFF"), (255, 255, 255, 255))
                    s_out_en = self.get_slot_setting(settings, slot_key, "media_song_outline_enabled", False)
                    s_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_song_outline_color", "#000000FF"), (0, 0, 0, 255))
                    s_out_sz = self.get_slot_setting(settings, slot_key, "media_song_outline_size", 2)

                    a_font_str = self.get_slot_setting(settings, slot_key, "media_artist_font_str", "DejaVu Sans Bold 18")
                    font_artist = self.get_font_from_desc(a_font_str, default_size=15, scale_factor=0.8)
                    a_fill_en = self.get_slot_setting(settings, slot_key, "media_artist_fill_enabled", True)
                    a_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_artist_font_color", "#FFFFFFFF"), (255, 255, 255, 255))
                    a_out_en = self.get_slot_setting(settings, slot_key, "media_artist_outline_enabled", False)
                    a_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "media_artist_outline_color", "#000000FF"), (0, 0, 0, 255))
                    a_out_sz = self.get_slot_setting(settings, slot_key, "media_artist_outline_size", 2)

                    self.draw_media_full(image, draw, box, font_artist, font_song, a_fill_en, a_fill_col, a_out_en, a_out_col, a_out_sz, s_fill_en, s_fill_col, s_out_en, s_out_col, s_out_sz, 0, vis_style, color_mode, solid_col, grad_start, grad_mid, grad_end, align=align)
                else:
                    self.draw_media_sub(image, draw, box, 0, vis_style, color_mode, solid_col, grad_start, grad_mid, grad_end, align=align)

                if self.is_media_active_and_playing():
                    self.start_anim_timer()

            elif widget_choice == 5: # Network Activity
                net_mode_idx = self.get_slot_setting(settings, slot_key, "net_mode_idx", 0)
                net_unit_idx = self.get_slot_setting(settings, slot_key, "net_unit_idx", 0)
                font_main = font_mon_main_full if is_full else font_mon_main_sub
                font_sub = font_mon_sub_full if is_full else font_mon_sub_sub
                self.draw_net_widget(image, draw, box, font_main, font_sub, True, white_col, False, white_col, 2, net_mode_idx, net_unit_idx, align=align)

            elif widget_choice == 6: # RAM Usage
                ram_mode_idx = self.get_slot_setting(settings, slot_key, "ram_mode_idx", 0)
                font_main = font_mon_main_full if is_full else font_mon_main_sub
                font_sub = font_mon_sub_full if is_full else font_mon_sub_sub
                self.draw_ram_widget(image, draw, box, font_main, font_sub, True, white_col, False, white_col, 2, ram_mode_idx, align=align)

            elif widget_choice == 7 and is_full: # Stacked Date & Time
                date_fmt_idx = self.get_slot_setting(settings, slot_key, "date_format_idx", 0)
                fmt_str = self.date_format_options[min(date_fmt_idx, len(self.date_format_options) - 1)][0]
                date_str = now.strftime(fmt_str)
                d_font_str = self.get_slot_setting(settings, slot_key, "date_font_str", "DejaVu Sans Bold 25")
                font_date = self.get_font_from_desc(d_font_str, default_size=25)
                d_fill_en = self.get_slot_setting(settings, slot_key, "date_fill_enabled", True)
                d_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "date_font_color", "#AAC8E6FF"), (170, 200, 230, 255))
                d_out_en = self.get_slot_setting(settings, slot_key, "date_outline_enabled", False)
                d_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "date_outline_color", "#000000FF"), (0, 0, 0, 255))
                d_out_sz = self.get_slot_setting(settings, slot_key, "date_outline_size", 2)

                use_24h = self.get_slot_setting(settings, slot_key, "use_24h", False)
                show_sec = self.get_slot_setting(settings, slot_key, "show_seconds", False)
                time_fmt = ("%H:%M:%S" if show_sec else "%H:%M") if use_24h else ("%I:%M:%S %p" if show_sec else "%I:%M %p")
                time_str = now.strftime(time_fmt).lstrip("0") if not use_24h else now.strftime(time_fmt)
                t_font_str = self.get_slot_setting(settings, slot_key, "time_font_str", "DejaVu Sans Bold 45")
                font_time = self.get_font_from_desc(t_font_str, default_size=45)
                t_fill_en = self.get_slot_setting(settings, slot_key, "time_fill_enabled", True)
                t_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "time_font_color", "#FFFFFFFF"), (255, 255, 255, 255))
                t_out_en = self.get_slot_setting(settings, slot_key, "time_outline_enabled", False)
                t_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "time_outline_color", "#000000FF"), (0, 0, 0, 255))
                t_out_sz = self.get_slot_setting(settings, slot_key, "time_outline_size", 2)

                self.draw_stacked(draw, box, date_str, time_str, font_date, font_time, d_fill_en, d_fill_col, d_out_en, d_out_col, d_out_sz, t_fill_en, t_fill_col, t_out_en, t_out_col, t_out_sz, align=align)

            elif (widget_choice == 8 and is_full) or (widget_choice == 7 and not is_full): # Time
                use_24h = self.get_slot_setting(settings, slot_key, "use_24h", False)
                show_sec = self.get_slot_setting(settings, slot_key, "show_seconds", False)
                time_fmt = ("%H:%M:%S" if show_sec else "%H:%M") if use_24h else ("%I:%M:%S %p" if show_sec else "%I:%M %p")
                time_str = now.strftime(time_fmt).lstrip("0") if not use_24h else now.strftime(time_fmt)
                t_font_str = self.get_slot_setting(settings, slot_key, "time_font_str", "DejaVu Sans Bold 45")
                font_time = self.get_font_from_desc(t_font_str, default_size=45 if is_full else 22)
                t_fill_en = self.get_slot_setting(settings, slot_key, "time_fill_enabled", True)
                t_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "time_font_color", "#FFFFFFFF"), (255, 255, 255, 255))
                t_out_en = self.get_slot_setting(settings, slot_key, "time_outline_enabled", False)
                t_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "time_outline_color", "#000000FF"), (0, 0, 0, 255))
                t_out_sz = self.get_slot_setting(settings, slot_key, "time_outline_size", 2)
                self.draw_single(draw, box, time_str, font_time, t_fill_en, t_fill_col, t_out_en, t_out_col, t_out_sz, align=align)

            elif (widget_choice == 9 and is_full) or (widget_choice == 8 and not is_full): # Weather
                lat = self.get_slot_setting(settings, slot_key, "weather_lat", "25.7617")
                lon = self.get_slot_setting(settings, slot_key, "weather_lon", "-80.1918")
                unit_idx = self.get_slot_setting(settings, slot_key, "weather_unit_idx", 0)
                temp_unit = "fahrenheit" if unit_idx == 0 else "celsius"
                c_key = f"{lat}_{lon}_{temp_unit}"
                slot_cache = self.weather_caches.get(c_key, self.weather_cache)

                w_font_str = self.get_slot_setting(settings, slot_key, "weather_font_str", "DejaVu Sans Bold 22")
                font_weather = self.get_font_from_desc(w_font_str, default_size=22, scale_factor=1.4 if is_full else 1.0)
                font_loc = self.get_font_from_desc(w_font_str, default_size=22, scale_factor=1.0 if is_full else 0.75)
                w_fill_en = self.get_slot_setting(settings, slot_key, "weather_fill_enabled", True)
                w_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "weather_font_color", "#FFFFFFFF"), (255, 255, 255, 255))
                w_out_en = self.get_slot_setting(settings, slot_key, "weather_outline_enabled", False)
                w_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "weather_outline_color", "#000000FF"), (0, 0, 0, 255))
                w_out_sz = self.get_slot_setting(settings, slot_key, "weather_outline_size", 2)
                self.draw_weather(image, draw, box, font_weather, font_loc, w_fill_en, w_fill_col, w_out_en, w_out_col, w_out_sz, slot_cache, align=align)

            elif (widget_choice == 10 and is_full) or (widget_choice == 9 and not is_full): # World Clock
                city_idx = self.get_slot_setting(settings, slot_key, "worldclock_city_idx", 0)
                clock_view = self.get_slot_setting(settings, slot_key, "worldclock_view", 0)
                custom_label = self.get_slot_setting(settings, slot_key, "worldclock_custom_label", "")
                custom_tz = self.get_slot_setting(settings, slot_key, "worldclock_custom_tz", "America/New_York")
                show_sec = self.get_slot_setting(settings, slot_key, "worldclock_show_seconds", False)
                show_offset = self.get_slot_setting(settings, slot_key, "worldclock_show_offset", True)
                wc_font_str = self.get_slot_setting(settings, slot_key, "worldclock_font_str", "DejaVu Sans Bold 25")
                font_city = self.get_font_from_desc(wc_font_str, default_size=20 if is_full else 16, scale_factor=0.8 if is_full else 0.7)
                font_time = self.get_font_from_desc(wc_font_str, default_size=32 if is_full else 14, scale_factor=1.2 if is_full else 0.6)
                font_sub = self.get_font_from_desc(wc_font_str, default_size=15 if is_full else 14, scale_factor=0.6 if is_full else 0.6)
                wc_fill_en = self.get_slot_setting(settings, slot_key, "worldclock_fill_enabled", True)
                wc_fill_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "worldclock_font_color", "#FFFFFFFF"), (255, 255, 255, 255))
                wc_out_en = self.get_slot_setting(settings, slot_key, "worldclock_outline_enabled", False)
                wc_out_col = self.hex_to_rgba_tuple(self.get_slot_setting(settings, slot_key, "worldclock_outline_color", "#000000FF"), (0, 0, 0, 255))
                wc_out_sz = self.get_slot_setting(settings, slot_key, "worldclock_outline_size", 2)
                use_24h = self.get_slot_setting(settings, slot_key, "use_24h", False)
                self.draw_world_clock(draw, box, font_city, font_time, font_sub, wc_fill_en, wc_fill_col, wc_out_en, wc_out_col, wc_out_sz, city_idx, custom_label, custom_tz, show_offset, use_24h, show_sec, clock_view, align=align)

        # Section Specifications: (Prefix, Alignment, Full Box, Top Box, Bot Box)
        sections = [
            ("sec_a", "left", (0, 0, 200, 100), (0, 0, 200, 50), (0, 50, 200, 100)),
            ("sec_b", "center", (200, 0, 600, 100), (200, 0, 600, 50), (200, 50, 600, 100)),
            ("sec_c", "left", (600, 0, 800, 100), (600, 0, 800, 50), (600, 50, 800, 100))
        ]

        for prefix, align, full_box, top_box, bot_box in sections:
            sec_mode = self.get_slot_setting(settings, prefix, "mode", 0)
            if sec_mode == 0: # Full mode
                full_choice = self.get_slot_setting(settings, prefix, "full_widget", 0)
                render_slot_widget(f"{prefix}_full", full_choice, full_box, is_full=True, align=align)
            else: # Split mode
                top_choice = self.get_slot_setting(settings, prefix, "top_widget", 0)
                bot_choice = self.get_slot_setting(settings, prefix, "bottom_widget", 0)
                render_slot_widget(f"{prefix}_top", top_choice, top_box, is_full=False, align=align)
                render_slot_widget(f"{prefix}_bot", bot_choice, bot_box, is_full=False, align=align)

        self.render_to_input(image)
        try:
            self.set_media(image=image)
        except Exception:
            pass
