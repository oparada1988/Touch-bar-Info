# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python modules
import os
import subprocess
import datetime
import requests
import psutil
import json
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
        self.city_search_timer = None
        self.update_vis_callbacks = []

        # System Monitor Stats Buffers
        self.cpu_history = [0.0] * 20
        self.ram_history = [0.0] * 20
        self.net_history = [0.0] * 20
        self.last_net_io = None
        self.net_tx_rate = 0.0
        self.net_rx_rate = 0.0
        self.process_count = 0

    def get_locale_text(self, key: str, default: str) -> str:
        if hasattr(self.plugin_base, "lm") and self.plugin_base.lm is not None:
            try:
                val = self.plugin_base.lm.get(key)
                if val: return val
            except Exception:
                pass
        if hasattr(self.plugin_base, "locale_manager") and self.plugin_base.locale_manager is not None:
            try:
                val = self.plugin_base.locale_manager.get(key)
                if val: return val
            except Exception:
                pass
        return default

    def on_ready(self) -> None:
        self.collect_system_stats()
        self.fetch_weather_async(force=True)
        self.update_display()

    def on_tick(self) -> None:
        self.collect_system_stats()
        self.fetch_weather_async(force=False)
        self.update_display()

    def on_remove(self) -> None:
        self.clear_background()

    def on_removed_from_cache(self) -> None:
        self.clear_background()

    def clear_background(self) -> None:
        if hasattr(self, "page") and self.page is not None:
            try:
                self.page.set_background_image(self.input_ident, self.state, "", update=False)
                render_path = os.path.join(self.plugin_base.PATH, "assets", f"touchbar_render_{self.state}.png")
                if os.path.exists(render_path):
                    os.remove(render_path)
            except Exception as e:
                log.error(f"TouchBarInfo: Error clearing background on removal: {e}")

        if hasattr(self, "deck_controller") and self.deck_controller is not None:
            try:
                c_input = self.deck_controller.get_input(self.input_ident)
                if c_input is not None:
                    empty_img = Image.new("RGBA", (800, 100), (0, 0, 0, 0))
                    if hasattr(c_input, "set_ui_image"):
                        c_input.set_ui_image(empty_img)
                    if hasattr(c_input, "update"):
                        c_input.update()
            except Exception as e:
                log.error(f"TouchBarInfo: Error resetting touchscreen display on removal: {e}")

    def trigger_redraw(self):
        self.last_rendered_key = ""
        self.update_display()

    # --- System Stats Collection ---
    def collect_system_stats(self):
        try:
            # CPU
            cpu_pct = psutil.cpu_percent(interval=None)
            self.cpu_history.append(float(cpu_pct))
            if len(self.cpu_history) > 20: self.cpu_history.pop(0)

            # RAM
            ram_info = psutil.virtual_memory()
            self.ram_history.append(float(ram_info.percent))
            if len(self.ram_history) > 20: self.ram_history.pop(0)

            # Network
            net_io = psutil.net_io_counters()
            now_ts = datetime.datetime.now().timestamp()
            if hasattr(self, "last_net_io") and self.last_net_io is not None:
                old_sent, old_recv, old_ts = self.last_net_io
                dt = max(0.1, now_ts - old_ts)
                self.net_tx_rate = max(0.0, (net_io.bytes_sent - old_sent) / dt)
                self.net_rx_rate = max(0.0, (net_io.bytes_recv - old_recv) / dt)
            else:
                self.net_tx_rate = 0.0
                self.net_rx_rate = 0.0
            self.last_net_io = (net_io.bytes_sent, net_io.bytes_recv, now_ts)

            tot_rate = self.net_tx_rate + self.net_rx_rate
            self.net_history.append(float(tot_rate))
            if len(self.net_history) > 20: self.net_history.pop(0)

            # Processes
            self.process_count = len(psutil.pids())
        except Exception as e:
            log.error(f"TouchBarInfo: Error updating system stats: {e}")

    def get_system_disk_mounts(self) -> list[tuple[str, str]]:
        disks = []
        seen = set()

        lsblk_cmds = [
            ['flatpak-spawn', '--host', '/usr/bin/lsblk', '-J', '-o', 'NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,MOUNTPOINTS'],
            ['flatpak-spawn', '--host', 'lsblk', '-J', '-o', 'NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,MOUNTPOINTS'],
            ['flatpak-spawn', '--host', 'lsblk', '-J']
        ]

        for cmd in lsblk_cmds:
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if p.stdout and p.stdout.strip().startswith('{'):
                    data = json.loads(p.stdout)

                    def parse_devs(dev_list):
                        for item in dev_list:
                            name = item.get("name", "")
                            label = item.get("label", "")
                            fstype = item.get("fstype", "")

                            raw_mounts = list(item.get("mountpoints") or [])
                            if item.get("mountpoint"):
                                raw_mounts.append(item.get("mountpoint"))

                            valid_mounts = [m for m in raw_mounts if m and not m.startswith(("/boot", "/run", "/sys", "/proc", "/dev"))]

                            for mount in valid_mounts:
                                if mount not in seen and fstype not in ["swap", "squashfs", "iso9660"]:
                                    seen.add(mount)
                                    disp_name = f"{label} ({mount} — {name})" if label else f"{mount} ({name})"
                                    disks.append((mount, disp_name))

                            if "children" in item:
                                parse_devs(item["children"])

                    parse_devs(data.get("blockdevices", []))
                    if disks:
                        break
            except Exception:
                pass

        if not disks:
            for df_bin in ['/usr/bin/df', 'df']:
                try:
                    cmd = ['flatpak-spawn', '--host', df_bin, '-k']
                    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                    if p.stdout:
                        lines = p.stdout.strip().splitlines()[1:]
                        for line in lines:
                            parts = line.split()
                            if len(parts) >= 6:
                                dev, mount = parts[0], parts[5]
                                if dev.startswith('/dev/') and not mount.startswith(('/boot', '/run', '/sys', '/proc', '/dev')):
                                    if mount not in seen:
                                        seen.add(mount)
                                        disks.append((mount, f"{mount} ({dev})"))
                        if disks:
                            break
                except Exception:
                    pass

        if not disks:
            seen_devs = set()
            try:
                for p in psutil.disk_partitions(all=False):
                    if p.device.startswith("/dev/") and not p.mountpoint.startswith(("/usr", "/app", "/var", "/etc", "/run", "/dev", "/sys", "/proc")):
                        if p.device not in seen_devs:
                            seen_devs.add(p.device)
                            disks.append((p.mountpoint, f"{p.mountpoint} ({p.device})"))
            except Exception:
                pass

        if not disks:
            disks = [("/", "/ (System Root)")]

        return disks

    # --- Weather Fetcher & WMO Mapping ---
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

    def fetch_weather_async(self, force: bool = False):
        now_ts = datetime.datetime.now().timestamp()
        refresh_intervals = [300, 600, 900, 1800, 3600]
        settings = self.get_settings() or {}
        ref_idx = settings.get("weather_refresh_idx", 2)
        interval_sec = refresh_intervals[min(ref_idx, len(refresh_intervals)-1)]

        if not force and hasattr(self, "weather_cache") and self.weather_cache:
            last_ts = self.weather_cache.get("last_fetch", 0)
            if (now_ts - last_ts) < interval_sec:
                return

        def task():
            try:
                lat = settings.get("weather_lat", "25.7617")
                lon = settings.get("weather_lon", "-80.1918")
                unit_idx = settings.get("weather_unit_idx", 0)
                temp_unit = "fahrenheit" if unit_idx == 0 else "celsius"

                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,is_day&temperature_unit={temp_unit}"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    curr = data.get("current", {})
                    temp = curr.get("temperature_2m", None)
                    code = curr.get("weather_code", 0)
                    is_day = curr.get("is_day", 1)

                    temp_str = f"{round(temp)}°" if temp is not None else "--°"
                    location_name = settings.get("weather_location_name", "Miami")

                    self.weather_cache = {
                        "last_fetch": datetime.datetime.now().timestamp(),
                        "temp_str": temp_str,
                        "wmo_code": code,
                        "is_day": is_day,
                        "location": location_name
                    }
                    GLib.idle_add(self.trigger_redraw)
            except Exception as e:
                log.error(f"TouchBarInfo: Failed to fetch weather data: {e}")

        Thread(target=task, daemon=True).start()

    def get_config_rows(self) -> "list[Adw.PreferencesRow]":
        self.update_vis_callbacks = []

        # Date Format Options
        self.date_format_options = [
            ("%b. %d, %Y", self.get_locale_text("actions.touchbar-info.date-format.mon-day-year", "Mon. Day, Year (Aug. 11, 2026)")),
            ("%a. %d, %Y", self.get_locale_text("actions.touchbar-info.date-format.dow-day-year", "DayOfWeek. Day, Year (Tue. 11, 2026)")),
            ("%a. %b. %d, %Y", self.get_locale_text("actions.touchbar-info.date-format.dow-mon-day-year", "DayOfWeek. Mon. Day, Year (Tue. Aug. 11, 2026)")),
            ("%Y-%b-%d", self.get_locale_text("actions.touchbar-info.date-format.year-mon-day", "Year-Mon-Day (2026-Aug-11)"))
        ]

        # Mode Options
        self.mode_options = [
            self.get_locale_text("actions.touchbar-info.mode.full", "1 Widget (Full Section — 100px)"),
            self.get_locale_text("actions.touchbar-info.mode.split", "2 Widgets (Split Top/Bottom — 50px each)")
        ]

        # Widget choices
        self.full_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.none", "None (Empty)"),
            self.get_locale_text("actions.touchbar-info.widget.stacked", "Stacked Date and Time"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time"),
            self.get_locale_text("actions.touchbar-info.widget.weather", "Weather"),
            self.get_locale_text("actions.touchbar-info.widget.cpu", "CPU Usage"),
            self.get_locale_text("actions.touchbar-info.widget.net", "Network Activity"),
            self.get_locale_text("actions.touchbar-info.widget.ram", "RAM Usage"),
            self.get_locale_text("actions.touchbar-info.widget.disk", "Disk Usage")
        ]
        self.split_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.none", "None (Empty)"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time"),
            self.get_locale_text("actions.touchbar-info.widget.weather", "Weather"),
            self.get_locale_text("actions.touchbar-info.widget.cpu", "CPU Usage"),
            self.get_locale_text("actions.touchbar-info.widget.net", "Network Activity"),
            self.get_locale_text("actions.touchbar-info.widget.ram", "RAM Usage"),
            self.get_locale_text("actions.touchbar-info.widget.disk", "Disk Usage")
        ]

        # CPU Mode Options
        self.cpu_mode_options = [
            self.get_locale_text("actions.touchbar-info.cpu-mode.pct", "Percentage (%)"),
            self.get_locale_text("actions.touchbar-info.cpu-mode.pct-procs", "Percentage and Process Count"),
            self.get_locale_text("actions.touchbar-info.cpu-mode.graph", "Live CPU Graph")
        ]

        # Network Mode & Unit Options
        self.net_mode_options = [
            self.get_locale_text("actions.touchbar-info.net-mode.rates", "Download / Upload Rates"),
            self.get_locale_text("actions.touchbar-info.net-mode.graph", "Live Network Graph")
        ]
        self.net_unit_options = [
            "Bytes (KB/s, MB/s)",
            "Bits (Kbit/s, Mbit/s)"
        ]

        # RAM Mode Options
        self.ram_mode_options = [
            self.get_locale_text("actions.touchbar-info.ram-mode.pct", "Percentage (%)"),
            self.get_locale_text("actions.touchbar-info.ram-mode.used-total", "Used / Total Memory (GB)"),
            self.get_locale_text("actions.touchbar-info.ram-mode.graph", "Live RAM Graph")
        ]

        # Disk Mode & Mount Options
        self.disk_mode_options = [
            self.get_locale_text("actions.touchbar-info.disk-mode.pct", "Percentage (%)"),
            self.get_locale_text("actions.touchbar-info.disk-mode.used-free", "Used / Free Space (GB)"),
            self.get_locale_text("actions.touchbar-info.disk-mode.graph", "Disk Usage Graph")
        ]
        self.disk_mounts = self.get_system_disk_mounts()

        # Weather Options
        self.weather_units = ["Fahrenheit (°F)", "Celsius (°C)"]
        self.weather_intervals = ["5 Minutes", "10 Minutes", "15 Minutes", "30 Minutes", "60 Minutes"]

        # Control Widget trackers for global syncing
        self.all_date_fmt_combos = []
        self.all_date_font_btns = []
        self.all_date_fill_switches = []
        self.all_date_fill_color_btns = []
        self.all_date_out_switches = []
        self.all_date_out_color_btns = []
        self.all_date_out_size_spins = []

        self.all_time_24h_switches = []
        self.all_time_sec_switches = []
        self.all_time_font_btns = []
        self.all_time_fill_switches = []
        self.all_time_fill_color_btns = []
        self.all_time_out_switches = []
        self.all_time_out_color_btns = []
        self.all_time_out_size_spins = []

        self.all_weather_loc_entries = []
        self.all_weather_res_combos = []
        self.all_weather_unit_combos = []
        self.all_weather_ref_combos = []
        self.all_weather_font_btns = []
        self.all_weather_fill_switches = []
        self.all_weather_fill_color_btns = []
        self.all_weather_out_switches = []
        self.all_weather_out_color_btns = []
        self.all_weather_out_size_spins = []

        # System Monitor Global Trackers
        self.all_cpu_mode_combos = []
        self.all_net_mode_combos = []
        self.all_net_unit_combos = []
        self.all_ram_mode_combos = []
        self.all_disk_mode_combos = []
        self.all_disk_mount_combos = []

        self.search_results_data = []

        # Helper to create Date controls
        def build_date_controls():
            fmt_model = Gtk.StringList()
            for _, label in self.date_format_options: fmt_model.append(label)
            fmt_combo = Adw.ComboRow(
                model=fmt_model,
                title=self.get_locale_text("actions.touchbar-info.date-format.label", "Date Format"),
                subtitle=self.get_locale_text("actions.touchbar-info.date-format.subtitle", "Format style for date text")
            )

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(False)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))

            self.all_date_fmt_combos.append(fmt_combo)
            self.all_date_font_btns.append(font_btn)
            self.all_date_fill_switches.append(fill_sw)
            self.all_date_fill_color_btns.append(fill_color_btn)
            self.all_date_out_switches.append(out_sw)
            self.all_date_out_color_btns.append(out_color_btn)
            self.all_date_out_size_spins.append(out_size_spin)

            return {
                "fmt_combo": fmt_combo, "font_row": font_row, "fill_sw": fill_sw,
                "fill_color_row": fill_color_row, "out_sw": out_sw,
                "out_color_row": out_color_row, "out_size_spin": out_size_spin,
                "all_rows": [fmt_combo, font_row, fill_sw, fill_color_row, out_sw, out_color_row, out_size_spin]
            }

        # Helper to create Time controls
        def build_time_controls():
            sw_24h = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.use-24h.label", "Use 24-Hour Clock"),
                subtitle=self.get_locale_text("actions.touchbar-info.use-24h.subtitle", "Switch between 12-hour (AM/PM) and 24-hour time format")
            )

            sw_sec = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.show-seconds.label", "Show Seconds"),
                subtitle=self.get_locale_text("actions.touchbar-info.show-seconds.subtitle", "Include seconds in the displayed time")
            )

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(False)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))

            self.all_time_24h_switches.append(sw_24h)
            self.all_time_sec_switches.append(sw_sec)
            self.all_time_font_btns.append(font_btn)
            self.all_time_fill_switches.append(fill_sw)
            self.all_time_fill_color_btns.append(fill_color_btn)
            self.all_time_out_switches.append(out_sw)
            self.all_time_out_color_btns.append(out_color_btn)
            self.all_time_out_size_spins.append(out_size_spin)

            return {
                "sw_24h": sw_24h, "sw_sec": sw_sec, "font_row": font_row, "fill_sw": fill_sw,
                "fill_color_row": fill_color_row, "out_sw": out_sw,
                "out_color_row": out_color_row, "out_size_spin": out_size_spin,
                "all_rows": [sw_24h, sw_sec, font_row, fill_sw, fill_color_row, out_sw, out_color_row, out_size_spin]
            }

        # Helper to create Weather controls
        def build_weather_controls():
            loc_entry = Adw.EntryRow(
                title=self.get_locale_text("actions.touchbar-info.weather-location.label", "City / Location Search")
            )

            res_model = Gtk.StringList()
            res_combo = Adw.ComboRow(
                model=res_model,
                title=self.get_locale_text("actions.touchbar-info.weather-results.label", "Select Matching Location"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-results.subtitle", "Choose city from Open-Meteo search results")
            )
            res_combo.set_visible(False)

            unit_model = Gtk.StringList()
            for u in self.weather_units: unit_model.append(u)
            unit_combo = Adw.ComboRow(
                model=unit_model,
                title=self.get_locale_text("actions.touchbar-info.weather-unit.label", "Temperature Unit"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-unit.subtitle", "Select Fahrenheit (°F) or Celsius (°C)")
            )

            ref_model = Gtk.StringList()
            for r in self.weather_intervals: ref_model.append(r)
            ref_combo = Adw.ComboRow(
                model=ref_model,
                title=self.get_locale_text("actions.touchbar-info.weather-refresh.label", "Refresh Interval"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-refresh.subtitle", "Automatic weather update frequency")
            )

            font_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.font-chooser.label", "Font and Size Picker"),
                subtitle=self.get_locale_text("actions.touchbar-info.font-chooser.subtitle", "Choose font family, style, and size using GTK font picker")
            )
            font_btn = Gtk.FontButton.new()
            font_btn.set_use_font(False)
            font_btn.set_use_size(False)
            font_btn.set_valign(Gtk.Align.CENTER)
            font_btn.set_hexpand(False)
            font_row.add_suffix(font_btn)

            fill_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-fill.label", "Enable Font Fill"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-fill.subtitle", "Draw solid interior text fill")
            )

            fill_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.fill-color.label", "Font Fill Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.fill-color.subtitle", "Color for text interior fill")
            )
            fill_color_btn = Gtk.ColorButton()
            fill_color_btn.set_valign(Gtk.Align.CENTER)
            fill_color_row.add_suffix(fill_color_btn)

            out_sw = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.enable-outline.label", "Enable Text Outline"),
                subtitle=self.get_locale_text("actions.touchbar-info.enable-outline.subtitle", "Draw stroke outline around text")
            )

            out_color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.outline-color.label", "Outline Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.outline-color.subtitle", "Color for text stroke outline")
            )
            out_color_btn = Gtk.ColorButton()
            out_color_btn.set_valign(Gtk.Align.CENTER)
            out_color_row.add_suffix(out_color_btn)

            out_size_spin = Adw.SpinRow.new_with_range(1, 10, 1)
            out_size_spin.set_title(self.get_locale_text("actions.touchbar-info.outline-size.label", "Outline Thickness"))
            out_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.outline-size.subtitle", "Stroke thickness in pixels (1-10px)"))

            self.all_weather_loc_entries.append(loc_entry)
            self.all_weather_res_combos.append(res_combo)
            self.all_weather_unit_combos.append(unit_combo)
            self.all_weather_ref_combos.append(ref_combo)
            self.all_weather_font_btns.append(font_btn)
            self.all_weather_fill_switches.append(fill_sw)
            self.all_weather_fill_color_btns.append(fill_color_btn)
            self.all_weather_out_switches.append(out_sw)
            self.all_weather_out_color_btns.append(out_color_btn)
            self.all_weather_out_size_spins.append(out_size_spin)

            return {
                "loc_entry": loc_entry, "res_combo": res_combo, "unit_combo": unit_combo,
                "ref_combo": ref_combo, "font_row": font_row, "fill_sw": fill_sw,
                "fill_color_row": fill_color_row, "out_sw": out_sw,
                "out_color_row": out_color_row, "out_size_spin": out_size_spin,
                "all_rows": [loc_entry, res_combo, unit_combo, ref_combo, font_row, fill_sw, fill_color_row, out_sw, out_color_row, out_size_spin]
            }

        # Helper to create CPU controls
        def build_cpu_controls():
            mode_model = Gtk.StringList()
            for opt in self.cpu_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.cpu-mode.label", "CPU Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.cpu-mode.subtitle", "Choose percentage, processes, or live graph")
            )
            self.all_cpu_mode_combos.append(mode_combo)
            return {"mode_combo": mode_combo, "all_rows": [mode_combo]}

        # Helper to create Network controls
        def build_net_controls():
            mode_model = Gtk.StringList()
            for opt in self.net_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.net-mode.label", "Network Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.net-mode.subtitle", "Choose download/upload rates or live graph")
            )

            unit_model = Gtk.StringList()
            for opt in self.net_unit_options: unit_model.append(opt)
            unit_combo = Adw.ComboRow(
                model=unit_model,
                title=self.get_locale_text("actions.touchbar-info.net-unit.label", "Network Speed Unit"),
                subtitle=self.get_locale_text("actions.touchbar-info.net-unit.subtitle", "Choose Bytes (KB/s, MB/s) or Bits (Kbit/s, Mbit/s)")
            )

            self.all_net_mode_combos.append(mode_combo)
            self.all_net_unit_combos.append(unit_combo)
            return {"mode_combo": mode_combo, "unit_combo": unit_combo, "all_rows": [mode_combo, unit_combo]}

        # Helper to create RAM controls
        def build_ram_controls():
            mode_model = Gtk.StringList()
            for opt in self.ram_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.ram-mode.label", "RAM Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.ram-mode.subtitle", "Choose percentage, GB used/total, or live graph")
            )
            self.all_ram_mode_combos.append(mode_combo)
            return {"mode_combo": mode_combo, "all_rows": [mode_combo]}

        # Helper to create Disk controls
        def build_disk_controls():
            mount_model = Gtk.StringList()
            for m_path, m_disp in self.disk_mounts: mount_model.append(m_disp)
            mount_combo = Adw.ComboRow(
                model=mount_model,
                title=self.get_locale_text("actions.touchbar-info.disk-select.label", "System Disk Mount"),
                subtitle=self.get_locale_text("actions.touchbar-info.disk-select.subtitle", "Select system disk partition to monitor")
            )

            mode_model = Gtk.StringList()
            for opt in self.disk_mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.disk-mode.label", "Disk Display Mode"),
                subtitle=self.get_locale_text("actions.touchbar-info.disk-mode.subtitle", "Choose percentage, GB used/free, or mini graph")
            )

            self.all_disk_mount_combos.append(mount_combo)
            self.all_disk_mode_combos.append(mode_combo)
            return {"mount_combo": mount_combo, "mode_combo": mode_combo, "all_rows": [mount_combo, mode_combo]}

        # Helper to create Section Expander with clean subsection expanders for split mode
        def create_section_expander(title_key, default_title, subtitle_key, default_sub, prefix_key):
            expander = Adw.ExpanderRow(
                title=self.get_locale_text(title_key, default_title),
                subtitle=self.get_locale_text(subtitle_key, default_sub)
            )

            mode_model = Gtk.StringList()
            for opt in self.mode_options: mode_model.append(opt)
            mode_combo = Adw.ComboRow(
                model=mode_model,
                title=self.get_locale_text("actions.touchbar-info.widget-mode.label", "Number of Widgets"),
                subtitle=self.get_locale_text("actions.touchbar-info.widget-mode.subtitle", "Choose full section height or split top/bottom subsections")
            )

            # --- 1. Full Section Group ---
            full_model = Gtk.StringList()
            for opt in self.full_widget_options: full_model.append(opt)
            full_combo = Adw.ComboRow(
                model=full_model,
                title=self.get_locale_text("actions.touchbar-info.full-widget.label", "Full Section Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.full-widget.subtitle", "Widget assigned to full section area")
            )
            full_date_ctrls = build_date_controls()
            full_time_ctrls = build_time_controls()
            full_weather_ctrls = build_weather_controls()
            full_cpu_ctrls = build_cpu_controls()
            full_net_ctrls = build_net_controls()
            full_ram_ctrls = build_ram_controls()
            full_disk_ctrls = build_disk_controls()

            # --- 2. Top Subsection Expander ---
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
            top_date_ctrls = build_date_controls()
            top_time_ctrls = build_time_controls()
            top_weather_ctrls = build_weather_controls()
            top_cpu_ctrls = build_cpu_controls()
            top_net_ctrls = build_net_controls()
            top_ram_ctrls = build_ram_controls()
            top_disk_ctrls = build_disk_controls()

            top_expander.add_row(top_combo)
            for r in top_date_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_time_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_weather_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_cpu_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_net_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_ram_ctrls["all_rows"]: top_expander.add_row(r)
            for r in top_disk_ctrls["all_rows"]: top_expander.add_row(r)

            # --- 3. Bottom Subsection Expander ---
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
            bot_date_ctrls = build_date_controls()
            bot_time_ctrls = build_time_controls()
            bot_weather_ctrls = build_weather_controls()
            bot_cpu_ctrls = build_cpu_controls()
            bot_net_ctrls = build_net_controls()
            bot_ram_ctrls = build_ram_controls()
            bot_disk_ctrls = build_disk_controls()

            bot_expander.add_row(bot_combo)
            for r in bot_date_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_time_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_weather_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_cpu_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_net_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_ram_ctrls["all_rows"]: bot_expander.add_row(r)
            for r in bot_disk_ctrls["all_rows"]: bot_expander.add_row(r)

            # Add rows to parent section expander
            expander.add_row(mode_combo)

            expander.add_row(full_combo)
            for r in full_date_ctrls["all_rows"]: expander.add_row(r)
            for r in full_time_ctrls["all_rows"]: expander.add_row(r)
            for r in full_weather_ctrls["all_rows"]: expander.add_row(r)
            for r in full_cpu_ctrls["all_rows"]: expander.add_row(r)
            for r in full_net_ctrls["all_rows"]: expander.add_row(r)
            for r in full_ram_ctrls["all_rows"]: expander.add_row(r)
            for r in full_disk_ctrls["all_rows"]: expander.add_row(r)

            expander.add_row(top_expander)
            expander.add_row(bot_expander)

            # --- Unified Group Visibility Helper ---
            def update_group_vis(widget_choice, is_active, date_ctrls, time_ctrls, weather_ctrls, cpu_ctrls, net_ctrls, ram_ctrls, disk_ctrls, is_full_mode=True):
                # Hide all if group is not active
                if not is_active:
                    for r in date_ctrls["all_rows"]: r.set_visible(False)
                    for r in time_ctrls["all_rows"]: r.set_visible(False)
                    for r in weather_ctrls["all_rows"]: r.set_visible(False)
                    for r in cpu_ctrls["all_rows"]: r.set_visible(False)
                    for r in net_ctrls["all_rows"]: r.set_visible(False)
                    for r in ram_ctrls["all_rows"]: r.set_visible(False)
                    for r in disk_ctrls["all_rows"]: r.set_visible(False)
                    return

                # Date Visibility (Full: 1, 2 | Split: 1)
                show_date = (widget_choice in [1, 2]) if is_full_mode else (widget_choice == 1)
                date_ctrls["fmt_combo"].set_visible(show_date)
                date_ctrls["font_row"].set_visible(show_date)
                date_ctrls["fill_sw"].set_visible(show_date)
                date_ctrls["fill_color_row"].set_visible(show_date and date_ctrls["fill_sw"].get_active())
                date_ctrls["out_sw"].set_visible(show_date)
                date_ctrls["out_color_row"].set_visible(show_date and date_ctrls["out_sw"].get_active())
                date_ctrls["out_size_spin"].set_visible(show_date and date_ctrls["out_sw"].get_active())

                # Time Visibility (Full: 1, 3 | Split: 2)
                show_time = (widget_choice in [1, 3]) if is_full_mode else (widget_choice == 2)
                time_ctrls["sw_24h"].set_visible(show_time)
                time_ctrls["sw_sec"].set_visible(show_time)
                time_ctrls["font_row"].set_visible(show_time)
                time_ctrls["fill_sw"].set_visible(show_time)
                time_ctrls["fill_color_row"].set_visible(show_time and time_ctrls["fill_sw"].get_active())
                time_ctrls["out_sw"].set_visible(show_time)
                time_ctrls["out_color_row"].set_visible(show_time and time_ctrls["out_sw"].get_active())
                time_ctrls["out_size_spin"].set_visible(show_time and time_ctrls["out_sw"].get_active())

                # Weather Visibility (Full: 4 | Split: 3)
                show_weather = (widget_choice == 4) if is_full_mode else (widget_choice == 3)
                weather_ctrls["loc_entry"].set_visible(show_weather)
                weather_ctrls["res_combo"].set_visible(show_weather and len(self.search_results_data) > 0)
                weather_ctrls["unit_combo"].set_visible(show_weather)
                weather_ctrls["ref_combo"].set_visible(show_weather)
                weather_ctrls["font_row"].set_visible(show_weather)
                weather_ctrls["fill_sw"].set_visible(show_weather)
                weather_ctrls["fill_color_row"].set_visible(show_weather and weather_ctrls["fill_sw"].get_active())
                weather_ctrls["out_sw"].set_visible(show_weather)
                weather_ctrls["out_color_row"].set_visible(show_weather and weather_ctrls["out_sw"].get_active())
                weather_ctrls["out_size_spin"].set_visible(show_weather and weather_ctrls["out_sw"].get_active())

                # CPU Visibility (Full: 5 | Split: 4)
                show_cpu = (widget_choice == 5) if is_full_mode else (widget_choice == 4)
                for r in cpu_ctrls["all_rows"]: r.set_visible(show_cpu)

                # Network Visibility (Full: 6 | Split: 5)
                show_net = (widget_choice == 6) if is_full_mode else (widget_choice == 5)
                for r in net_ctrls["all_rows"]: r.set_visible(show_net)

                # RAM Visibility (Full: 7 | Split: 6)
                show_ram = (widget_choice == 7) if is_full_mode else (widget_choice == 6)
                for r in ram_ctrls["all_rows"]: r.set_visible(show_ram)

                # Disk Visibility (Full: 8 | Split: 7)
                show_disk = (widget_choice == 8) if is_full_mode else (widget_choice == 7)
                for r in disk_ctrls["all_rows"]: r.set_visible(show_disk)

            # Main Section Visibility Controller
            def update_visibility():
                is_full = (mode_combo.get_selected() == 0)
                full_combo.set_visible(is_full)
                top_expander.set_visible(not is_full)
                bot_expander.set_visible(not is_full)

                # 1. Update Full Section Controls Visibility
                update_group_vis(
                    full_combo.get_selected(),
                    is_active=is_full,
                    date_ctrls=full_date_ctrls,
                    time_ctrls=full_time_ctrls,
                    weather_ctrls=full_weather_ctrls,
                    cpu_ctrls=full_cpu_ctrls,
                    net_ctrls=full_net_ctrls,
                    ram_ctrls=full_ram_ctrls,
                    disk_ctrls=full_disk_ctrls,
                    is_full_mode=True
                )

                # 2. Update Top Subsection Controls Visibility
                update_group_vis(
                    top_combo.get_selected(),
                    is_active=(not is_full),
                    date_ctrls=top_date_ctrls,
                    time_ctrls=top_time_ctrls,
                    weather_ctrls=top_weather_ctrls,
                    cpu_ctrls=top_cpu_ctrls,
                    net_ctrls=top_net_ctrls,
                    ram_ctrls=top_ram_ctrls,
                    disk_ctrls=top_disk_ctrls,
                    is_full_mode=False
                )

                # 3. Update Bottom Subsection Controls Visibility
                update_group_vis(
                    bot_combo.get_selected(),
                    is_active=(not is_full),
                    date_ctrls=bot_date_ctrls,
                    time_ctrls=bot_time_ctrls,
                    weather_ctrls=bot_weather_ctrls,
                    cpu_ctrls=bot_cpu_ctrls,
                    net_ctrls=bot_net_ctrls,
                    ram_ctrls=bot_ram_ctrls,
                    disk_ctrls=bot_disk_ctrls,
                    is_full_mode=False
                )

            # Connect Mode & Widget Combo Signals
            mode_combo.connect("notify::selected", lambda *a: update_visibility())
            full_combo.connect("notify::selected", lambda *a: update_visibility())
            top_combo.connect("notify::selected", lambda *a: update_visibility())
            bot_combo.connect("notify::selected", lambda *a: update_visibility())

            # Connect Sub-switch Signals to update_visibility
            for ctrls in [full_date_ctrls, full_time_ctrls, full_weather_ctrls, top_date_ctrls, top_time_ctrls, top_weather_ctrls, bot_date_ctrls, bot_time_ctrls, bot_weather_ctrls]:
                ctrls["fill_sw"].connect("notify::active", lambda *a: update_visibility())
                ctrls["out_sw"].connect("notify::active", lambda *a: update_visibility())

            self.update_vis_callbacks.append(update_visibility)
            update_visibility()

            return expander, mode_combo, full_combo, top_combo, bot_combo

        # Create Section Expanders
        self.sec_a_expander, self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo = create_section_expander(
            "actions.touchbar-info.section-a.label", "Left (200px)",
            "actions.touchbar-info.section-a.subtitle", "Configure widgets for the left Touch Bar section", "sec_a"
        )

        self.sec_b_expander, self.sec_b_mode_combo, self.sec_b_full_combo, self.sec_b_top_combo, self.sec_b_bot_combo = create_section_expander(
            "actions.touchbar-info.section-b.label", "Center (400px)",
            "actions.touchbar-info.section-b.subtitle", "Configure widgets for the center Touch Bar section", "sec_b"
        )

        self.sec_c_expander, self.sec_c_mode_combo, self.sec_c_full_combo, self.sec_c_top_combo, self.sec_c_bot_combo = create_section_expander(
            "actions.touchbar-info.section-c.label", "Right (200px)",
            "actions.touchbar-info.section-c.subtitle", "Configure widgets for the right Touch Bar section", "sec_c"
        )

        self.load_config_defaults()

        # Mode Change Listeners
        def bind_mode(combo, key_prefix):
            combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed(f"{key_prefix}_mode", c.get_selected()))

        bind_mode(self.sec_a_mode_combo, "sec_a")
        bind_mode(self.sec_b_mode_combo, "sec_b")
        bind_mode(self.sec_c_mode_combo, "sec_c")

        # Widget Combo Listeners
        def bind_combo(combo, setting_name):
            combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed(setting_name, c.get_selected()))

        bind_combo(self.sec_a_full_combo, "sec_a_full_widget")
        bind_combo(self.sec_a_top_combo, "sec_a_top_widget")
        bind_combo(self.sec_a_bot_combo, "sec_a_bottom_widget")

        bind_combo(self.sec_b_full_combo, "sec_b_full_widget")
        bind_combo(self.sec_b_top_combo, "sec_b_top_widget")
        bind_combo(self.sec_b_bot_combo, "sec_b_bottom_widget")

        bind_combo(self.sec_c_full_combo, "sec_c_full_widget")
        bind_combo(self.sec_c_top_combo, "sec_c_top_widget")
        bind_combo(self.sec_c_bot_combo, "sec_c_bottom_widget")

        # Global Option Signals synced across all instances
        for sw in self.all_time_24h_switches: sw.connect("notify::active", self.on_use_24h_toggled)
        for sw in self.all_time_sec_switches: sw.connect("notify::active", self.on_show_seconds_toggled)
        for combo in self.all_date_fmt_combos: combo.connect("notify::selected", self.on_date_format_changed)

        # Date Font Signals
        for fb in self.all_date_font_btns: fb.connect("font-set", self.on_date_font_set)
        for sw in self.all_date_fill_switches: sw.connect("notify::active", self.on_date_fill_toggled)
        for btn in self.all_date_fill_color_btns: btn.connect("color-set", self.on_date_fill_color_set)
        for sw in self.all_date_out_switches: sw.connect("notify::active", self.on_date_out_toggled)
        for btn in self.all_date_out_color_btns: btn.connect("color-set", self.on_date_out_color_set)
        for spin in self.all_date_out_size_spins: spin.connect("notify::value", self.on_date_out_size_changed)

        # Time Font Signals
        for fb in self.all_time_font_btns: fb.connect("font-set", self.on_time_font_set)
        for sw in self.all_time_fill_switches: sw.connect("notify::active", self.on_time_fill_toggled)
        for btn in self.all_time_fill_color_btns: btn.connect("color-set", self.on_time_fill_color_set)
        for sw in self.all_time_out_switches: sw.connect("notify::active", self.on_time_out_toggled)
        for btn in self.all_time_out_color_btns: btn.connect("color-set", self.on_time_out_color_set)
        for spin in self.all_time_out_size_spins: spin.connect("notify::value", self.on_time_out_size_changed)

        # Weather Signals
        for entry in self.all_weather_loc_entries: entry.connect("changed", self.on_weather_location_entry_changed)
        for combo in self.all_weather_res_combos: combo.connect("notify::selected", self.on_weather_result_selected)
        for combo in self.all_weather_unit_combos: combo.connect("notify::selected", self.on_weather_unit_changed)
        for combo in self.all_weather_ref_combos: combo.connect("notify::selected", self.on_weather_refresh_changed)

        for fb in self.all_weather_font_btns: fb.connect("font-set", self.on_weather_font_set)
        for sw in self.all_weather_fill_switches: sw.connect("notify::active", self.on_weather_fill_toggled)
        for btn in self.all_weather_fill_color_btns: btn.connect("color-set", self.on_weather_fill_color_set)
        for sw in self.all_weather_out_switches: sw.connect("notify::active", self.on_weather_out_toggled)
        for btn in self.all_weather_out_color_btns: btn.connect("color-set", self.on_weather_out_color_set)
        for spin in self.all_weather_out_size_spins: spin.connect("notify::value", self.on_weather_out_size_changed)

        # System Monitor Signals
        for combo in self.all_cpu_mode_combos: combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed("cpu_mode_idx", c.get_selected()))
        for combo in self.all_net_mode_combos: combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed("net_mode_idx", c.get_selected()))
        for combo in self.all_net_unit_combos: combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed("net_unit_idx", c.get_selected()))
        for combo in self.all_ram_mode_combos: combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed("ram_mode_idx", c.get_selected()))
        for combo in self.all_disk_mode_combos: combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed("disk_mode_idx", c.get_selected()))
        for combo in self.all_disk_mount_combos: combo.connect("notify::selected", lambda c, *a: self.on_setting_combo_changed("disk_mount_idx", c.get_selected()))

        return [
            self.sec_a_expander,
            self.sec_b_expander,
            self.sec_c_expander
        ]

    def load_config_defaults(self):
        settings = self.get_settings()
        if settings is None:
            return

        use_24h = settings.setdefault("use_24h", False)
        show_seconds = settings.setdefault("show_seconds", False)
        date_format_idx = settings.setdefault("date_format_idx", 0)

        sec_a_mode = settings.setdefault("sec_a_mode", 0)
        sec_a_full = settings.setdefault("sec_a_full_widget", 0)
        sec_a_top = settings.setdefault("sec_a_top_widget", 0)
        sec_a_bot = settings.setdefault("sec_a_bottom_widget", 0)

        sec_b_mode = settings.setdefault("sec_b_mode", 0)
        sec_b_full = settings.setdefault("sec_b_full_widget", 0)
        sec_b_top = settings.setdefault("sec_b_top_widget", 0)
        sec_b_bot = settings.setdefault("sec_b_bottom_widget", 0)

        sec_c_mode = settings.setdefault("sec_c_mode", 0)
        sec_c_full = settings.setdefault("sec_c_full_widget", 0)
        sec_c_top = settings.setdefault("sec_c_top_widget", 0)
        sec_c_bot = settings.setdefault("sec_c_bottom_widget", 0)

        # System Monitor Defaults
        cpu_mode_idx = settings.setdefault("cpu_mode_idx", 0)
        net_mode_idx = settings.setdefault("net_mode_idx", 0)
        net_unit_idx = settings.setdefault("net_unit_idx", 0)
        ram_mode_idx = settings.setdefault("ram_mode_idx", 0)
        disk_mode_idx = settings.setdefault("disk_mode_idx", 0)
        disk_mount_idx = settings.setdefault("disk_mount_idx", 0)

        # Date Font & Fill/Outline Defaults
        date_font_str = settings.setdefault("date_font_str", "DejaVu Sans Bold 25")
        date_fill_enabled = settings.setdefault("date_fill_enabled", True)
        date_font_color = settings.setdefault("date_font_color", "#AAC8E6FF")
        date_outline_enabled = settings.setdefault("date_outline_enabled", False)
        date_outline_color = settings.setdefault("date_outline_color", "#000000FF")
        date_outline_size = settings.setdefault("date_outline_size", 2)

        # Time Font & Fill/Outline Defaults
        time_font_str = settings.setdefault("time_font_str", "DejaVu Sans Bold 45")
        time_fill_enabled = settings.setdefault("time_fill_enabled", True)
        time_font_color = settings.setdefault("time_font_color", "#FFFFFFFF")
        time_outline_enabled = settings.setdefault("time_outline_enabled", False)
        time_outline_color = settings.setdefault("time_outline_color", "#000000FF")
        time_outline_size = settings.setdefault("time_outline_size", 2)

        # Weather Location & Units
        weather_location_name = settings.setdefault("weather_location_name", "Miami")
        weather_unit_idx = settings.setdefault("weather_unit_idx", 0)
        weather_refresh_idx = settings.setdefault("weather_refresh_idx", 2)

        # Weather Font & Fill/Outline Defaults
        weather_font_str = settings.setdefault("weather_font_str", "DejaVu Sans Bold 22")
        weather_fill_enabled = settings.setdefault("weather_fill_enabled", True)
        weather_font_color = settings.setdefault("weather_font_color", "#FFFFFFFF")
        weather_outline_enabled = settings.setdefault("weather_outline_enabled", False)
        weather_outline_color = settings.setdefault("weather_outline_color", "#000000FF")
        weather_outline_size = settings.setdefault("weather_outline_size", 2)

        # Sync Date/Time basic controls
        for sw in self.all_time_24h_switches: sw.set_active(use_24h)
        for sw in self.all_time_sec_switches: sw.set_active(show_seconds)
        for combo in self.all_date_fmt_combos:
            if 0 <= date_format_idx < len(self.date_format_options): combo.set_selected(date_format_idx)

        # Section selections
        self.sec_a_mode_combo.set_selected(sec_a_mode)
        self.sec_a_full_combo.set_selected(sec_a_full)
        self.sec_a_top_combo.set_selected(sec_a_top)
        self.sec_a_bot_combo.set_selected(sec_a_bot)

        self.sec_b_mode_combo.set_selected(sec_b_mode)
        self.sec_b_full_combo.set_selected(sec_b_full)
        self.sec_b_top_combo.set_selected(sec_b_top)
        self.sec_b_bot_combo.set_selected(sec_b_bot)

        self.sec_c_mode_combo.set_selected(sec_c_mode)
        self.sec_c_full_combo.set_selected(sec_c_full)
        self.sec_c_top_combo.set_selected(sec_c_top)
        self.sec_c_bot_combo.set_selected(sec_c_bot)

        # Sync System Monitor Combos
        for combo in self.all_cpu_mode_combos:
            if 0 <= cpu_mode_idx < len(self.cpu_mode_options): combo.set_selected(cpu_mode_idx)
        for combo in self.all_net_mode_combos:
            if 0 <= net_mode_idx < len(self.net_mode_options): combo.set_selected(net_mode_idx)
        for combo in self.all_net_unit_combos:
            if 0 <= net_unit_idx < len(self.net_unit_options): combo.set_selected(net_unit_idx)
        for combo in self.all_ram_mode_combos:
            if 0 <= ram_mode_idx < len(self.ram_mode_options): combo.set_selected(ram_mode_idx)
        for combo in self.all_disk_mode_combos:
            if 0 <= disk_mode_idx < len(self.disk_mode_options): combo.set_selected(disk_mode_idx)
        for combo in self.all_disk_mount_combos:
            if 0 <= disk_mount_idx < len(self.disk_mounts): combo.set_selected(disk_mount_idx)

        # Sync Date Font & Fill/Outline Controls
        for fb in self.all_date_font_btns: fb.set_font(date_font_str)
        for sw in self.all_date_fill_switches: sw.set_active(date_fill_enabled)
        for btn in self.all_date_fill_color_btns: self.set_color_button_rgba(btn, date_font_color)
        for sw in self.all_date_out_switches: sw.set_active(date_outline_enabled)
        for btn in self.all_date_out_color_btns: self.set_color_button_rgba(btn, date_outline_color)
        for spin in self.all_date_out_size_spins: spin.set_value(date_outline_size)

        # Sync Time Font & Fill/Outline Controls
        for fb in self.all_time_font_btns: fb.set_font(time_font_str)
        for sw in self.all_time_fill_switches: sw.set_active(time_fill_enabled)
        for btn in self.all_time_fill_color_btns: self.set_color_button_rgba(btn, time_font_color)
        for sw in self.all_time_out_switches: sw.set_active(time_outline_enabled)
        for btn in self.all_time_out_color_btns: self.set_color_button_rgba(btn, time_outline_color)
        for spin in self.all_time_out_size_spins: spin.set_value(time_outline_size)

        # Sync Weather Controls
        for entry in self.all_weather_loc_entries: entry.set_text(weather_location_name)
        for combo in self.all_weather_unit_combos:
            if 0 <= weather_unit_idx < len(self.weather_units): combo.set_selected(weather_unit_idx)
        for combo in self.all_weather_ref_combos:
            if 0 <= weather_refresh_idx < len(self.weather_intervals): combo.set_selected(weather_refresh_idx)
        for fb in self.all_weather_font_btns: fb.set_font(weather_font_str)
        for sw in self.all_weather_fill_switches: sw.set_active(weather_fill_enabled)
        for btn in self.all_weather_fill_color_btns: self.set_color_button_rgba(btn, weather_font_color)
        for sw in self.all_weather_out_switches: sw.set_active(weather_outline_enabled)
        for btn in self.all_weather_out_color_btns: self.set_color_button_rgba(btn, weather_outline_color)
        for spin in self.all_weather_out_size_spins: spin.set_value(weather_outline_size)

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

    def on_setting_combo_changed(self, setting_name: str, value: int):
        settings = self.get_settings()
        if settings is not None:
            settings[setting_name] = value
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    # --- Date Font / Fill / Outline Callbacks ---
    def on_date_font_set(self, font_btn):
        settings = self.get_settings()
        if settings is not None:
            val = font_btn.get_font()
            settings["date_font_str"] = val
            for fb in self.all_date_font_btns:
                if fb != font_btn: fb.set_font(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_fill_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["date_fill_enabled"] = val
            for sw in self.all_date_fill_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_fill_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["date_font_color"] = hex_val
            for btn in self.all_date_fill_color_btns:
                if btn != button: self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_out_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["date_outline_enabled"] = val
            for sw in self.all_date_out_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_out_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["date_outline_color"] = hex_val
            for btn in self.all_date_out_color_btns:
                if btn != button: self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_out_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            val = int(spin.get_value())
            settings["date_outline_size"] = val
            for s in self.all_date_out_size_spins:
                if s != spin and int(s.get_value()) != val: s.set_value(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    # --- Time Font / Fill / Outline Callbacks ---
    def on_time_font_set(self, font_btn):
        settings = self.get_settings()
        if settings is not None:
            val = font_btn.get_font()
            settings["time_font_str"] = val
            for fb in self.all_time_font_btns:
                if fb != font_btn: fb.set_font(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_fill_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["time_fill_enabled"] = val
            for sw in self.all_time_fill_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_fill_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["time_font_color"] = hex_val
            for btn in self.all_time_fill_color_btns:
                if btn != button: self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_out_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["time_outline_enabled"] = val
            for sw in self.all_time_out_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_out_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["time_outline_color"] = hex_val
            for btn in self.all_time_out_color_btns:
                if btn != button: self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_out_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            val = int(spin.get_value())
            settings["time_outline_size"] = val
            for s in self.all_time_out_size_spins:
                if s != spin and int(s.get_value()) != val: s.set_value(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    # --- Weather Callbacks & Font Signals ---
    def on_weather_location_entry_changed(self, entry, *args):
        text = entry.get_text().strip()
        if len(text) < 3:
            for combo in self.all_weather_res_combos: combo.set_visible(False)
            return

        if hasattr(self, "city_search_timer") and self.city_search_timer is not None:
            self.city_search_timer.cancel()

        self.city_search_timer = Timer(0.6, self.perform_open_meteo_search, args=(text,))
        self.city_search_timer.start()

    def perform_open_meteo_search(self, query: str):
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": query, "count": 5, "language": "en", "format": "json"}
        try:
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                def update_ui():
                    self.search_results_data = []
                    string_list = Gtk.StringList()
                    for item in results:
                        name = item.get("name", "")
                        country = item.get("country", "")
                        admin1 = item.get("admin1", "")
                        lat = float(item.get("latitude", 0.0))
                        lon = float(item.get("longitude", 0.0))

                        parts = [name]
                        if admin1: parts.append(admin1)
                        if country: parts.append(country)
                        disp_str = f"{', '.join(parts)}"
                        string_list.append(disp_str)
                        self.search_results_data.append((disp_str, str(lat), str(lon), name))

                    for combo in self.all_weather_res_combos:
                        combo.set_model(string_list)

                    for cb in self.update_vis_callbacks:
                        cb()

                GLib.idle_add(update_ui)
        except Exception as e:
            log.error(f"TouchBarInfo: City search failed: {e}")

    def on_weather_result_selected(self, combo, *args):
        sel = combo.get_selected()
        if 0 <= sel < len(self.search_results_data):
            disp_str, lat_str, lon_str, city_name = self.search_results_data[sel]
            settings = self.get_settings()
            if settings is not None:
                settings["weather_lat"] = lat_str
                settings["weather_lon"] = lon_str
                settings["weather_location_name"] = city_name
                self.set_settings(settings)

                for entry in self.all_weather_loc_entries:
                    if entry.get_text() != city_name:
                        entry.set_text(city_name)

                self.fetch_weather_async(force=True)

    def on_weather_unit_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["weather_unit_idx"] = val
            for c in self.all_weather_unit_combos:
                if c != combo and c.get_selected() != val:
                    c.set_selected(val)
            self.set_settings(settings)
            self.fetch_weather_async(force=True)

    def on_weather_refresh_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["weather_refresh_idx"] = val
            for c in self.all_weather_ref_combos:
                if c != combo and c.get_selected() != val:
                    c.set_selected(val)
            self.set_settings(settings)

    def on_weather_font_set(self, font_btn):
        settings = self.get_settings()
        if settings is not None:
            val = font_btn.get_font()
            settings["weather_font_str"] = val
            for fb in self.all_weather_font_btns:
                if fb != font_btn: fb.set_font(val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_fill_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["weather_fill_enabled"] = val
            for sw in self.all_weather_fill_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_fill_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["weather_font_color"] = hex_val
            for btn in self.all_weather_fill_color_btns:
                if btn != button: self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_out_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["weather_outline_enabled"] = val
            for sw in self.all_weather_out_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_out_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["weather_outline_color"] = hex_val
            for btn in self.all_weather_out_color_btns:
                if btn != button: self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_out_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            val = int(spin.get_value())
            settings["weather_outline_size"] = val
            for s in self.all_weather_out_size_spins:
                if s != spin and int(s.get_value()) != val: s.set_value(val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_use_24h_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["use_24h"] = val
            for sw in self.all_time_24h_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_show_seconds_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["show_seconds"] = val
            for sw in self.all_time_sec_switches:
                if sw != switch and sw.get_active() != val: sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_format_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["date_format_idx"] = val
            for c in self.all_date_fmt_combos:
                if c != combo and c.get_selected() != val: c.set_selected(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    # --- Pango Font Resolver for PIL ---
    def get_font_from_desc(self, font_str: str, default_size: int = 25, scale_factor: float = 1.0):
        try:
            desc = Pango.FontDescription.from_string(font_str)
            family = desc.get_family() or "DejaVu Sans"
            size_pango = desc.get_size()
            raw_size = int(size_pango / Pango.SCALE) if size_pango > 0 else default_size
            size = max(10, int(raw_size * scale_factor))

            weight = desc.get_weight()
            is_bold = weight >= Pango.Weight.BOLD
            is_italic = desc.get_style() in [Pango.Style.ITALIC, Pango.Style.OBLIQUE]

            style_parts = []
            if is_bold: style_parts.append("Bold")
            if is_italic: style_parts.append("Italic")
            if not style_parts: style_parts.append("Regular")
            style_str = " ".join(style_parts)

            cmd = ["fc-match", "-f", "%{file}", f"{family}:style={style_str}"]
            res = subprocess.check_output(cmd, text=True).strip()
            if res and os.path.isfile(res):
                return ImageFont.truetype(res, size)
        except Exception as e:
            log.error(f"TouchBarInfo: Error loading font '{font_str}': {e}")

        return ImageFont.load_default()

    def get_canvas_size(self) -> tuple[int, int]:
        if hasattr(self, "deck_controller") and self.deck_controller is not None:
            if hasattr(self.deck_controller, "get_touchscreen_image_size"):
                size = self.deck_controller.get_touchscreen_image_size()
                if size is not None:
                    return size
        return (800, 100)

    # --- PIL Render Helpers ---
    def render_styled_text(self, draw: ImageDraw.ImageDraw, pos: tuple[float, float], text: str, font, fill_enabled: bool = True, fill_color: tuple = (255, 255, 255, 255), outline_enabled: bool = False, outline_color: tuple = (0, 0, 0, 255), outline_size: int = 2, anchor: str = "mm"):
        fill = fill_color if fill_enabled else (0, 0, 0, 0)
        stroke_w = outline_size if outline_enabled else 0
        stroke_f = outline_color if outline_enabled else None
        draw.text(pos, text, fill=fill, font=font, stroke_width=stroke_w, stroke_fill=stroke_f, anchor=anchor)

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

    def draw_stacked(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], date_str: str, time_str: str, font_date, font_time, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz):
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

        center_x = x_min + (w / 2)
        date_y = start_y + (date_h / 2)
        time_y = start_y + date_h + spacing + (time_h / 2)

        self.render_styled_text(draw, (center_x, date_y), date_str, font_date, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz, anchor="mm")
        self.render_styled_text(draw, (center_x, time_y), time_str, font_time, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz, anchor="mm")

    def draw_single(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font, fill_en=True, fill_col=(255, 255, 255, 255), out_en=False, out_col=(0, 0, 0, 255), out_sz=2):
        x_min, y_min, x_max, y_max = box
        center_x = x_min + (x_max - x_min) / 2
        center_y = y_min + (y_max - y_min) / 2
        self.render_styled_text(draw, (center_x, center_y), text, font, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

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

    def draw_weather(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_weather, font_location, fill_en, fill_col, out_en, out_col, out_sz):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        cache = self.weather_cache or {}
        temp_str = cache.get("temp_str", "--°")
        wmo_code = cache.get("wmo_code", 0)
        is_day = cache.get("is_day", 1)
        location_str = cache.get("location", "Miami")

        icon_file = self.get_weather_icon_filename(wmo_code, is_day)
        target_icon_h = int(box_h * 0.70)
        icon_img = self.load_widget_icon(os.path.join("weather-icons", icon_file), target_icon_h)

        margin_x = int(box_w * 0.08)
        if icon_img is not None:
            icon_x = x_min + margin_x
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            left_text_x = icon_x + icon_img.width + int(margin_x * 0.8)
        else:
            left_text_x = x_min + margin_x

        bbox_temp = draw.textbbox((0, 0), temp_str, font=font_weather)
        bbox_loc = draw.textbbox((0, 0), location_str, font=font_location)

        temp_w = bbox_temp[2] - bbox_temp[0]
        temp_h = bbox_temp[3] - bbox_temp[1]
        loc_w = bbox_loc[2] - bbox_loc[0]
        loc_h = bbox_loc[3] - bbox_loc[1]

        text_column_w = max(temp_w, loc_w)
        center_text_x = left_text_x + (text_column_w / 2)

        spacing = max(1, int(box_h * 0.04))
        total_h = temp_h + spacing + loc_h
        start_y = y_min + (box_h - total_h) / 2

        temp_y = start_y + (temp_h / 2)
        loc_y = start_y + temp_h + spacing + (loc_h / 2)

        self.render_styled_text(draw, (center_text_x, temp_y), temp_str, font_weather, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        self.render_styled_text(draw, (center_text_x, loc_y), location_str, font_location, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    # --- System Widget Drawers ---
    def draw_cpu_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, cpu_mode: int):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("cpu_icon.png", target_icon_h)

        margin_x = int(box_w * 0.08)
        if icon_img is not None:
            icon_x = x_min + margin_x
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            content_x = icon_x + icon_img.width + int(margin_x * 0.8)
        else:
            content_x = x_min + margin_x

        latest_cpu = self.cpu_history[-1] if self.cpu_history else 0.0

        if cpu_mode == 2: # Live Graph
            graph_box = (content_x, y_min + int(box_h * 0.15), x_max - margin_x, y_max - int(box_h * 0.15))
            self.draw_history_graph(draw, graph_box, self.cpu_history, max_val=100.0, color=(0, 200, 255, 255))
        elif cpu_mode == 1: # Percentage + Process Count
            top_str = f"CPU {round(latest_cpu)}%"
            bot_str = f"{self.process_count} Procs"
            bbox_t = draw.textbbox((0, 0), top_str, font=font_main)
            bbox_b = draw.textbbox((0, 0), bot_str, font=font_sub)
            th, bh = bbox_t[3] - bbox_t[1], bbox_b[3] - bbox_b[1]
            tw, bw = bbox_t[2] - bbox_t[0], bbox_b[2] - bbox_b[0]
            center_x = content_x + (max(tw, bw) / 2)

            spacing = max(1, int(box_h * 0.04))
            total_h = th + spacing + bh
            start_y = y_min + (box_h - total_h) / 2
            top_y = start_y + (th / 2)
            bot_y = start_y + th + spacing + (bh / 2)

            self.render_styled_text(draw, (center_x, top_y), top_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, bot_y), bot_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # Percentage %
            main_str = f"CPU {round(latest_cpu)}%"
            center_x = content_x + ((x_max - margin_x - content_x) / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def draw_net_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, net_mode: int, net_unit: int):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("net_icon.png", target_icon_h)

        margin_x = int(box_w * 0.08)
        if icon_img is not None:
            icon_x = x_min + margin_x
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            content_x = icon_x + icon_img.width + int(margin_x * 0.8)
        else:
            content_x = x_min + margin_x

        if net_mode == 1: # Live Graph
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
            center_x = content_x + (max(rw, tw) / 2)

            spacing = max(1, int(box_h * 0.04))
            total_h = rh + spacing + th
            start_y = y_min + (box_h - total_h) / 2
            rx_y = start_y + (rh / 2)
            tx_y = start_y + rh + spacing + (th / 2)

            self.render_styled_text(draw, (center_x, rx_y), rx_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, tx_y), tx_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def draw_ram_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, ram_mode: int):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("ram_icon.png", target_icon_h)

        margin_x = int(box_w * 0.08)
        if icon_img is not None:
            icon_x = x_min + margin_x
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            content_x = icon_x + icon_img.width + int(margin_x * 0.8)
        else:
            content_x = x_min + margin_x

        latest_ram = self.ram_history[-1] if self.ram_history else 0.0

        if ram_mode == 2: # Live Graph
            graph_box = (content_x, y_min + int(box_h * 0.15), x_max - margin_x, y_max - int(box_h * 0.15))
            self.draw_history_graph(draw, graph_box, self.ram_history, max_val=100.0, color=(255, 170, 0, 255))
        elif ram_mode == 1: # Used / Total GB
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024**3)
            tot_gb = mem.total / (1024**3)
            main_str = f"{used_gb:.1f} / {tot_gb:.1f} GB"
            center_x = content_x + ((x_max - margin_x - content_x) / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # Percentage %
            main_str = f"RAM {round(latest_ram)}%"
            center_x = content_x + ((x_max - margin_x - content_x) / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def get_disk_usage_host(self, mount_path: str) -> tuple[float, float, float]:
        for df_bin in ['/usr/bin/df', 'df']:
            try:
                cmd = ['flatpak-spawn', '--host', df_bin, '-B1', mount_path]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if p.stdout:
                    lines = p.stdout.strip().splitlines()
                    if len(lines) >= 2:
                        parts = lines[-1].split()
                        if len(parts) >= 5:
                            total_b = float(parts[1])
                            used_b = float(parts[2])
                            free_b = float(parts[3])
                            pct_str = parts[4].rstrip('%')
                            pct = float(pct_str) if pct_str.replace('.', '', 1).isdigit() else (used_b / max(1.0, total_b)) * 100.0
                            return pct, used_b / (1024**3), free_b / (1024**3)
            except Exception:
                pass

        try:
            du = psutil.disk_usage(mount_path)
            return du.percent, du.used / (1024**3), du.free / (1024**3)
        except Exception:
            return 0.0, 0.0, 0.0

    def draw_disk_widget(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_main, font_sub, fill_en, fill_col, out_en, out_col, out_sz, disk_mode: int, disk_mount_idx: int):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        target_icon_h = int(box_h * 0.65)
        icon_img = self.load_widget_icon("disk_icon.png", target_icon_h)

        margin_x = int(box_w * 0.08)
        if icon_img is not None:
            icon_x = x_min + margin_x
            icon_y = y_min + int((box_h - target_icon_h) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)
            content_x = icon_x + icon_img.width + int(margin_x * 0.8)
        else:
            content_x = x_min + margin_x

        mount_path = "/"
        if hasattr(self, "disk_mounts") and 0 <= disk_mount_idx < len(self.disk_mounts):
            mount_path, _ = self.disk_mounts[disk_mount_idx]

        pct, used_gb, free_gb = self.get_disk_usage_host(mount_path)

        if disk_mode == 2: # Mini bar graph
            graph_box = (content_x, y_min + int(box_h * 0.25), x_max - margin_x, y_max - int(box_h * 0.25))
            gx_min, gy_min, gx_max, gy_max = graph_box
            gw = gx_max - gx_min
            gh = gy_max - gy_min

            # Fill entire bar background with Emerald Green for Available Space
            draw.rectangle([gx_min, gy_min, gx_max, gy_max], fill=(46, 204, 113, 220))

            # Fill left portion with Coral Red for Used Space
            fill_w = int(gw * (pct / 100.0))
            if fill_w > 0:
                draw.rectangle([gx_min, gy_min, gx_min + fill_w, gy_max], fill=(231, 76, 60, 220))

            # Clean silver border outline
            draw.rectangle([gx_min, gy_min, gx_max, gy_max], outline=(200, 200, 200, 255), width=1)
        elif disk_mode == 1: # Used / Free GB
            top_str = f"{used_gb:.0f}G Used"
            bot_str = f"{free_gb:.0f}G Free"
            bbox_t = draw.textbbox((0, 0), top_str, font=font_main)
            bbox_b = draw.textbbox((0, 0), bot_str, font=font_sub)
            th, bh = bbox_t[3] - bbox_t[1], bbox_b[3] - bbox_b[1]
            tw, bw = bbox_t[2] - bbox_t[0], bbox_b[2] - bbox_b[0]
            center_x = content_x + (max(tw, bw) / 2)

            spacing = max(1, int(box_h * 0.04))
            total_h = th + spacing + bh
            start_y = y_min + (box_h - total_h) / 2
            top_y = start_y + (th / 2)
            bot_y = start_y + th + spacing + (bh / 2)

            self.render_styled_text(draw, (center_x, top_y), top_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
            self.render_styled_text(draw, (center_x, bot_y), bot_str, font_sub, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")
        else: # Percentage %
            main_str = f"Disk {round(pct)}%"
            center_x = content_x + ((x_max - margin_x - content_x) / 2)
            center_y = y_min + (box_h / 2)
            self.render_styled_text(draw, (center_x, center_y), main_str, font_main, fill_en, fill_col, out_en, out_col, out_sz, anchor="mm")

    def update_display(self) -> None:
        settings = self.get_settings() or {}
        use_24h = settings.get("use_24h", False)
        show_seconds = settings.get("show_seconds", False)
        date_format_idx = settings.get("date_format_idx", 0)

        # Section Selections
        sec_a_mode = settings.get("sec_a_mode", 0)
        sec_a_full = settings.get("sec_a_full_widget", 0)
        sec_a_top = settings.get("sec_a_top_widget", 0)
        sec_a_bot = settings.get("sec_a_bottom_widget", 0)

        sec_b_mode = settings.get("sec_b_mode", 0)
        sec_b_full = settings.get("sec_b_full_widget", 0)
        sec_b_top = settings.get("sec_b_top_widget", 0)
        sec_b_bot = settings.get("sec_b_bottom_widget", 0)

        sec_c_mode = settings.get("sec_c_mode", 0)
        sec_c_full = settings.get("sec_c_full_widget", 0)
        sec_c_top = settings.get("sec_c_top_widget", 0)
        sec_c_bot = settings.get("sec_c_bottom_widget", 0)

        # System Monitor Modes
        cpu_mode_idx = settings.get("cpu_mode_idx", 0)
        net_mode_idx = settings.get("net_mode_idx", 0)
        net_unit_idx = settings.get("net_unit_idx", 0)
        ram_mode_idx = settings.get("ram_mode_idx", 0)
        disk_mode_idx = settings.get("disk_mode_idx", 0)
        disk_mount_idx = settings.get("disk_mount_idx", 0)

        # Date Font & Fill/Outline Settings
        date_font_str = settings.get("date_font_str", "DejaVu Sans Bold 25")
        date_fill_en = settings.get("date_fill_enabled", True)
        date_fill_col_hex = settings.get("date_font_color", "#AAC8E6FF")
        date_out_en = settings.get("date_outline_enabled", False)
        date_out_col_hex = settings.get("date_outline_color", "#000000FF")
        date_out_sz = settings.get("date_outline_size", 2)

        # Time Font & Fill/Outline Settings
        time_font_str = settings.get("time_font_str", "DejaVu Sans Bold 45")
        time_fill_en = settings.get("time_fill_enabled", True)
        time_fill_col_hex = settings.get("time_font_color", "#FFFFFFFF")
        time_out_en = settings.get("time_outline_enabled", False)
        time_out_col_hex = settings.get("time_outline_color", "#000000FF")
        time_out_sz = settings.get("time_outline_size", 2)

        # Weather Font & Fill/Outline Settings
        weather_font_str = settings.get("weather_font_str", "DejaVu Sans Bold 22")
        weather_fill_en = settings.get("weather_fill_enabled", True)
        weather_fill_col_hex = settings.get("weather_font_color", "#FFFFFFFF")
        weather_out_en = settings.get("weather_outline_enabled", False)
        weather_out_col_hex = settings.get("weather_outline_color", "#000000FF")
        weather_out_sz = settings.get("weather_outline_size", 2)

        date_options = [
            ("%b. %d, %Y", "Mon. Day, Year"),
            ("%a. %d, %Y", "DayOfWeek. Day, Year"),
            ("%a. %b. %d, %Y", "DayOfWeek. Mon. Day, Year"),
            ("%Y-%b-%d", "Year-Mon-Day")
        ]
        fmt_str, _ = date_options[min(date_format_idx, len(date_options) - 1)]

        now = datetime.datetime.now()
        date_str = now.strftime(fmt_str)

        if use_24h:
            time_fmt = "%H:%M:%S" if show_seconds else "%H:%M"
        else:
            time_fmt = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
        
        time_str = now.strftime(time_fmt).lstrip("0") if not use_24h else now.strftime(time_fmt)

        cache_temp = self.weather_cache.get("temp_str", "--°") if hasattr(self, "weather_cache") else "--°"
        cache_loc = self.weather_cache.get("location", "") if hasattr(self, "weather_cache") else ""
        latest_cpu = self.cpu_history[-1] if self.cpu_history else 0.0
        latest_ram = self.ram_history[-1] if self.ram_history else 0.0

        combined_key = f"{date_str}|{time_str}|{cache_temp}|{cache_loc}|{latest_cpu:.1f}|{latest_ram:.1f}|{self.net_tx_rate:.0f}|{self.net_rx_rate:.0f}|{sec_a_mode}|{sec_a_full}|{sec_a_top}|{sec_a_bot}|{sec_b_mode}|{sec_b_full}|{sec_b_top}|{sec_b_bot}|{sec_c_mode}|{sec_c_full}|{sec_c_top}|{sec_c_bot}|{cpu_mode_idx}|{net_mode_idx}|{net_unit_idx}|{ram_mode_idx}|{disk_mode_idx}|{disk_mount_idx}|{date_font_str}|{date_fill_en}|{date_fill_col_hex}|{date_out_en}|{date_out_col_hex}|{date_out_sz}|{time_font_str}|{time_fill_en}|{time_fill_col_hex}|{time_out_en}|{time_out_col_hex}|{time_out_sz}|{weather_font_str}|{weather_fill_en}|{weather_fill_col_hex}|{weather_out_en}|{weather_out_col_hex}|{weather_out_sz}"

        if combined_key == self.last_rendered_key:
            return
        self.last_rendered_key = combined_key

        width, height = self.get_canvas_size()

        # 100% Transparent Background Canvas
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        font_date = self.get_font_from_desc(date_font_str, default_size=25)
        font_time = self.get_font_from_desc(time_font_str, default_size=45)

        font_weather_full = self.get_font_from_desc(weather_font_str, default_size=22, scale_factor=1.4)
        font_loc_full = self.get_font_from_desc(weather_font_str, default_size=22, scale_factor=1.0)

        font_weather_sub = self.get_font_from_desc(weather_font_str, default_size=22, scale_factor=1.0)
        font_loc_sub = self.get_font_from_desc(weather_font_str, default_size=22, scale_factor=0.75)

        # Monitor Fonts
        font_mon_main_full = self.get_font_from_desc("DejaVu Sans Bold 22", default_size=22, scale_factor=1.3)
        font_mon_sub_full = self.get_font_from_desc("DejaVu Sans Bold 16", default_size=16, scale_factor=1.0)

        font_mon_main_sub = self.get_font_from_desc("DejaVu Sans Bold 18", default_size=18, scale_factor=1.0)
        font_mon_sub_sub = self.get_font_from_desc("DejaVu Sans Bold 13", default_size=13, scale_factor=1.0)

        date_fill_col = self.hex_to_rgba_tuple(date_fill_col_hex, default=(170, 200, 230, 255))
        date_out_col = self.hex_to_rgba_tuple(date_out_col_hex, default=(0, 0, 0, 255))

        time_fill_col = self.hex_to_rgba_tuple(time_fill_col_hex, default=(255, 255, 255, 255))
        time_out_col = self.hex_to_rgba_tuple(time_out_col_hex, default=(0, 0, 0, 255))

        weather_fill_col = self.hex_to_rgba_tuple(weather_fill_col_hex, default=(255, 255, 255, 255))
        weather_out_col = self.hex_to_rgba_tuple(weather_out_col_hex, default=(0, 0, 0, 255))

        white_col = (255, 255, 255, 255)

        # --- Section Bounding Boxes ---
        box_a_full = (0, 0, 200, 100)
        box_a_top = (0, 0, 200, 50)
        box_a_bot = (0, 50, 200, 100)

        box_b_full = (200, 0, 600, 100)
        box_b_top = (200, 0, 600, 50)
        box_b_bot = (200, 50, 600, 100)

        box_c_full = (600, 0, 800, 100)
        box_c_top = (600, 0, 800, 50)
        box_c_bot = (600, 50, 800, 100)

        def render_section(mode, full_choice, top_choice, bot_choice, full_box, top_box, bot_box):
            if mode == 0: # 1 Widget (Full Section)
                if full_choice == 1: # Stacked Date & Time
                    self.draw_stacked(draw, full_box, date_str, time_str, font_date, font_time, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz)
                elif full_choice == 2: # Date
                    self.draw_single(draw, full_box, date_str, font_date, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz)
                elif full_choice == 3: # Time
                    self.draw_single(draw, full_box, time_str, font_time, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz)
                elif full_choice == 4: # Weather
                    self.draw_weather(image, draw, full_box, font_weather_full, font_loc_full, weather_fill_en, weather_fill_col, weather_out_en, weather_out_col, weather_out_sz)
                elif full_choice == 5: # CPU Usage
                    self.draw_cpu_widget(image, draw, full_box, font_mon_main_full, font_mon_sub_full, True, white_col, False, white_col, 2, cpu_mode_idx)
                elif full_choice == 6: # Network Activity
                    self.draw_net_widget(image, draw, full_box, font_mon_main_full, font_mon_sub_full, True, white_col, False, white_col, 2, net_mode_idx, net_unit_idx)
                elif full_choice == 7: # RAM Usage
                    self.draw_ram_widget(image, draw, full_box, font_mon_main_full, font_mon_sub_full, True, white_col, False, white_col, 2, ram_mode_idx)
                elif full_choice == 8: # Disk Usage
                    self.draw_disk_widget(image, draw, full_box, font_mon_main_full, font_mon_sub_full, True, white_col, False, white_col, 2, disk_mode_idx, disk_mount_idx)
            else: # 2 Widgets (Split Top / Bottom)
                # Top Sub-slot
                if top_choice == 1: # Date
                    self.draw_single(draw, top_box, date_str, font_date, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz)
                elif top_choice == 2: # Time
                    self.draw_single(draw, top_box, time_str, font_time, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz)
                elif top_choice == 3: # Weather
                    self.draw_weather(image, draw, top_box, font_weather_sub, font_loc_sub, weather_fill_en, weather_fill_col, weather_out_en, weather_out_col, weather_out_sz)
                elif top_choice == 4: # CPU Usage
                    self.draw_cpu_widget(image, draw, top_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, cpu_mode_idx)
                elif top_choice == 5: # Network Activity
                    self.draw_net_widget(image, draw, top_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, net_mode_idx, net_unit_idx)
                elif top_choice == 6: # RAM Usage
                    self.draw_ram_widget(image, draw, top_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, ram_mode_idx)
                elif top_choice == 7: # Disk Usage
                    self.draw_disk_widget(image, draw, top_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, disk_mode_idx, disk_mount_idx)

                # Bottom Sub-slot
                if bot_choice == 1: # Date
                    self.draw_single(draw, bot_box, date_str, font_date, date_fill_en, date_fill_col, date_out_en, date_out_col, date_out_sz)
                elif bot_choice == 2: # Time
                    self.draw_single(draw, bot_box, time_str, font_time, time_fill_en, time_fill_col, time_out_en, time_out_col, time_out_sz)
                elif bot_choice == 3: # Weather
                    self.draw_weather(image, draw, bot_box, font_weather_sub, font_loc_sub, weather_fill_en, weather_fill_col, weather_out_en, weather_out_col, weather_out_sz)
                elif bot_choice == 4: # CPU Usage
                    self.draw_cpu_widget(image, draw, bot_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, cpu_mode_idx)
                elif bot_choice == 5: # Network Activity
                    self.draw_net_widget(image, draw, bot_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, net_mode_idx, net_unit_idx)
                elif bot_choice == 6: # RAM Usage
                    self.draw_ram_widget(image, draw, bot_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, ram_mode_idx)
                elif bot_choice == 7: # Disk Usage
                    self.draw_disk_widget(image, draw, bot_box, font_mon_main_sub, font_mon_sub_sub, True, white_col, False, white_col, 2, disk_mode_idx, disk_mount_idx)

        render_section(sec_a_mode, sec_a_full, sec_a_top, sec_a_bot, box_a_full, box_a_top, box_a_bot)
        render_section(sec_b_mode, sec_b_full, sec_b_top, sec_b_bot, box_b_full, box_b_top, box_b_bot)
        render_section(sec_c_mode, sec_c_full, sec_c_top, sec_c_bot, box_c_full, box_c_top, box_c_bot)

        self.render_to_input(image)

    def render_to_input(self, image: Image.Image) -> None:
        if not hasattr(self, "page") or self.page is None:
            return

        final_image = image
        try:
            custom_bg_path = None
            if hasattr(self.page, "get_background_image"):
                bg_p = self.page.get_background_image(self.input_ident, self.state)
                if bg_p and os.path.isfile(bg_p) and not bg_p.endswith(("touchbar_render_0.png", "touchbar_render_1.png")):
                    custom_bg_path = bg_p

            if custom_bg_path:
                with Image.open(custom_bg_path) as bg_img:
                    bg_conv = bg_img.convert("RGBA").resize(image.size, Image.Resampling.LANCZOS)
                    final_image = Image.alpha_composite(bg_conv, image)
        except Exception as e:
            log.error(f"TouchBarInfo: Error compositing custom background image: {e}")

        assets_dir = os.path.join(self.plugin_base.PATH, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        render_path = os.path.join(assets_dir, f"touchbar_render_{self.state}.png")

        try:
            final_image.save(render_path)
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
