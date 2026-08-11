# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python modules
import os
import subprocess
import datetime
import requests
from threading import Thread, Timer
from PIL import Image, ImageDraw, ImageFont

# Import GTK modules
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk, GLib
from loguru import logger as log
import globals as gl

class TouchBarInfoAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.last_rendered_key = ""
        self.weather_cache = {}
        self.city_search_timer = None

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
        self.fetch_weather_async(force=True)
        self.update_display()

    def on_tick(self) -> None:
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
        refresh_intervals = [300, 600, 900, 1800, 3600] # 5m, 10m, 15m, 30m, 60m
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
        # Available font families
        self.font_families = ["DejaVu Sans", "Liberation Sans", "Ubuntu", "Noto Sans", "Monospace", "Serif", "Sans"]

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
            self.get_locale_text("actions.touchbar-info.widget.weather", "Weather")
        ]
        self.split_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.none", "None (Empty)"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time"),
            self.get_locale_text("actions.touchbar-info.widget.weather", "Weather")
        ]

        # Temperature Units
        self.weather_units = ["Fahrenheit (°F)", "Celsius (°C)"]
        self.weather_intervals = ["5 Minutes", "10 Minutes", "15 Minutes", "30 Minutes", "60 Minutes"]

        # Control Widget trackers for global syncing
        self.all_date_fmt_combos = []
        self.all_date_fam_combos = []
        self.all_date_size_spins = []
        self.all_date_color_btns = []

        self.all_time_24h_switches = []
        self.all_time_sec_switches = []
        self.all_time_fam_combos = []
        self.all_time_size_spins = []
        self.all_time_color_btns = []

        self.all_weather_loc_entries = []
        self.all_weather_res_combos = []
        self.all_weather_unit_combos = []
        self.all_weather_ref_combos = []
        self.all_weather_fam_combos = []
        self.all_weather_size_spins = []
        self.all_weather_color_btns = []
        self.search_results_data = []

        # Helper to create flat Date controls
        def build_date_controls():
            fmt_model = Gtk.StringList()
            for _, label in self.date_format_options: fmt_model.append(label)
            fmt_combo = Adw.ComboRow(
                model=fmt_model,
                title=self.get_locale_text("actions.touchbar-info.date-format.label", "Date Format"),
                subtitle=self.get_locale_text("actions.touchbar-info.date-format.subtitle", "Format style for date text")
            )

            fam_model = Gtk.StringList()
            for fam in self.font_families: fam_model.append(fam)
            fam_combo = Adw.ComboRow(
                model=fam_model,
                title=self.get_locale_text("actions.touchbar-info.date-font-family.label", "Date Font Family"),
                subtitle=self.get_locale_text("actions.touchbar-info.date-font-family.subtitle", "Select font typeface for date text")
            )

            size_spin = Adw.SpinRow.new_with_range(10, 80, 1)
            size_spin.set_title(self.get_locale_text("actions.touchbar-info.date-font-size.label", "Date Font Size"))
            size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.date-font-size.subtitle", "Font size in pixels for date text"))

            color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.date-font-color.label", "Date Font Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.date-font-color.subtitle", "Text color for date text")
            )
            color_btn = Gtk.ColorButton()
            color_btn.set_valign(Gtk.Align.CENTER)
            color_row.add_suffix(color_btn)

            self.all_date_fmt_combos.append(fmt_combo)
            self.all_date_fam_combos.append(fam_combo)
            self.all_date_size_spins.append(size_spin)
            self.all_date_color_btns.append(color_btn)

            return fmt_combo, fam_combo, size_spin, color_row, color_btn

        # Helper to create flat Time controls
        def build_time_controls():
            sw_24h = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.use-24h.label", "Use 24-Hour Clock"),
                subtitle=self.get_locale_text("actions.touchbar-info.use-24h.subtitle", "Switch between 12-hour (AM/PM) and 24-hour time format")
            )

            sw_sec = Adw.SwitchRow(
                title=self.get_locale_text("actions.touchbar-info.show-seconds.label", "Show Seconds"),
                subtitle=self.get_locale_text("actions.touchbar-info.show-seconds.subtitle", "Include seconds in the displayed time")
            )

            fam_model = Gtk.StringList()
            for fam in self.font_families: fam_model.append(fam)
            fam_combo = Adw.ComboRow(
                model=fam_model,
                title=self.get_locale_text("actions.touchbar-info.time-font-family.label", "Time Font Family"),
                subtitle=self.get_locale_text("actions.touchbar-info.time-font-family.subtitle", "Select font typeface for time text")
            )

            size_spin = Adw.SpinRow.new_with_range(10, 100, 1)
            size_spin.set_title(self.get_locale_text("actions.touchbar-info.time-font-size.label", "Time Font Size"))
            size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.time-font-size.subtitle", "Font size in pixels for time text"))

            color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.time-font-color.label", "Time Font Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.time-font-color.subtitle", "Text color for time text")
            )
            color_btn = Gtk.ColorButton()
            color_btn.set_valign(Gtk.Align.CENTER)
            color_row.add_suffix(color_btn)

            self.all_time_24h_switches.append(sw_24h)
            self.all_time_sec_switches.append(sw_sec)
            self.all_time_fam_combos.append(fam_combo)
            self.all_time_size_spins.append(size_spin)
            self.all_time_color_btns.append(color_btn)

            return sw_24h, sw_sec, fam_combo, size_spin, color_row, color_btn

        # Helper to create flat Weather controls
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

            fam_model = Gtk.StringList()
            for fam in self.font_families: fam_model.append(fam)
            fam_combo = Adw.ComboRow(
                model=fam_model,
                title=self.get_locale_text("actions.touchbar-info.weather-font-family.label", "Weather Font Family"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-font-family.subtitle", "Select font typeface for weather text")
            )

            size_spin = Adw.SpinRow.new_with_range(10, 80, 1)
            size_spin.set_title(self.get_locale_text("actions.touchbar-info.weather-font-size.label", "Weather Font Size"))
            size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.weather-font-size.subtitle", "Font size in pixels for weather text"))

            color_row = Adw.ActionRow(
                title=self.get_locale_text("actions.touchbar-info.weather-font-color.label", "Weather Font Color"),
                subtitle=self.get_locale_text("actions.touchbar-info.weather-font-color.subtitle", "Text color for weather text")
            )
            color_btn = Gtk.ColorButton()
            color_btn.set_valign(Gtk.Align.CENTER)
            color_row.add_suffix(color_btn)

            self.all_weather_loc_entries.append(loc_entry)
            self.all_weather_res_combos.append(res_combo)
            self.all_weather_unit_combos.append(unit_combo)
            self.all_weather_ref_combos.append(ref_combo)
            self.all_weather_fam_combos.append(fam_combo)
            self.all_weather_size_spins.append(size_spin)
            self.all_weather_color_btns.append(color_btn)

            return loc_entry, res_combo, unit_combo, ref_combo, fam_combo, size_spin, color_row, color_btn

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
            fd_fmt, fd_fam, fd_size, fd_col_row, _ = build_date_controls()
            ft_24h, ft_sec, ft_fam, ft_size, ft_col_row, _ = build_time_controls()
            fw_loc, fw_res, fw_unit, fw_ref, fw_fam, fw_size, fw_col_row, _ = build_weather_controls()
            full_date_rows = [fd_fmt, fd_fam, fd_size, fd_col_row]
            full_time_rows = [ft_24h, ft_sec, ft_fam, ft_size, ft_col_row]
            full_weather_rows = [fw_loc, fw_res, fw_unit, fw_ref, fw_fam, fw_size, fw_col_row]

            # --- 2. Top Subsection Expander ---
            top_expander = Adw.ExpanderRow(
                title=self.get_locale_text("actions.touchbar-info.top-subsection.label", "Top Subsection (Y: 0-50px)"),
                subtitle=self.get_locale_text("actions.touchbar-info.top-subsection.subtitle", "Configure widget for top half of section")
            )
            top_model = Gtk.StringList()
            for opt in self.split_widget_options: top_model.append(opt)
            top_combo = Adw.ComboRow(
                model=top_model,
                title=self.get_locale_text("actions.touchbar-info.widget-selector.label", "Select Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.widget-selector.subtitle", "Choose widget to display in this subsection")
            )
            td_fmt, td_fam, td_size, td_col_row, _ = build_date_controls()
            tt_24h, tt_sec, tt_fam, tt_size, tt_col_row, _ = build_time_controls()
            tw_loc, tw_res, tw_unit, tw_ref, tw_fam, tw_size, tw_col_row, _ = build_weather_controls()
            top_date_rows = [td_fmt, td_fam, td_size, td_col_row]
            top_time_rows = [tt_24h, tt_sec, tt_fam, tt_size, tt_col_row]
            top_weather_rows = [tw_loc, tw_res, tw_unit, tw_ref, tw_fam, tw_size, tw_col_row]

            top_expander.add_row(top_combo)
            for r in top_date_rows: top_expander.add_row(r)
            for r in top_time_rows: top_expander.add_row(r)
            for r in top_weather_rows: top_expander.add_row(r)

            # --- 3. Bottom Subsection Expander ---
            bot_expander = Adw.ExpanderRow(
                title=self.get_locale_text("actions.touchbar-info.bottom-subsection.label", "Bottom Subsection (Y: 50-100px)"),
                subtitle=self.get_locale_text("actions.touchbar-info.bottom-subsection.subtitle", "Configure widget for bottom half of section")
            )
            bot_model = Gtk.StringList()
            for opt in self.split_widget_options: bot_model.append(opt)
            bot_combo = Adw.ComboRow(
                model=bot_model,
                title=self.get_locale_text("actions.touchbar-info.widget-selector.label", "Select Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.widget-selector.subtitle", "Choose widget to display in this subsection")
            )
            bd_fmt, bd_fam, bd_size, bd_col_row, _ = build_date_controls()
            bt_24h, bt_sec, bt_fam, bt_size, bt_col_row, _ = build_time_controls()
            bw_loc, bw_res, bw_unit, bw_ref, bw_fam, bw_size, bw_col_row, _ = build_weather_controls()
            bot_date_rows = [bd_fmt, bd_fam, bd_size, bd_col_row]
            bot_time_rows = [bt_24h, bt_sec, bt_fam, bt_size, bt_col_row]
            bot_weather_rows = [bw_loc, bw_res, bw_unit, bw_ref, bw_fam, bw_size, bw_col_row]

            bot_expander.add_row(bot_combo)
            for r in bot_date_rows: bot_expander.add_row(r)
            for r in bot_time_rows: bot_expander.add_row(r)
            for r in bot_weather_rows: bot_expander.add_row(r)

            # Add rows to parent section expander
            expander.add_row(mode_combo)

            expander.add_row(full_combo)
            for r in full_date_rows: expander.add_row(r)
            for r in full_time_rows: expander.add_row(r)
            for r in full_weather_rows: expander.add_row(r)

            expander.add_row(top_expander)
            expander.add_row(bot_expander)

            # Section Visibility Controller
            def update_visibility():
                is_full = mode_combo.get_selected() == 0
                full_combo.set_visible(is_full)

                # Full Section Settings Visibility
                if is_full:
                    f_sel = full_combo.get_selected()
                    show_date = f_sel in [1, 2] # 1: Stacked, 2: Date
                    show_time = f_sel in [1, 3] # 1: Stacked, 3: Time
                    show_weather = (f_sel == 4) # 4: Weather

                    for r in full_date_rows: r.set_visible(show_date)
                    for r in full_time_rows: r.set_visible(show_time)
                    for r in full_weather_rows:
                        if r == fw_res:
                            r.set_visible(show_weather and len(self.search_results_data) > 0)
                        else:
                            r.set_visible(show_weather)
                else:
                    for r in full_date_rows: r.set_visible(False)
                    for r in full_time_rows: r.set_visible(False)
                    for r in full_weather_rows: r.set_visible(False)

                # Split Subsection Rows Visibility
                top_expander.set_visible(not is_full)
                bot_expander.set_visible(not is_full)

                if not is_full:
                    t_sel = top_combo.get_selected()
                    show_t_date = (t_sel == 1) # 1: Date
                    show_t_time = (t_sel == 2) # 2: Time
                    show_t_weather = (t_sel == 3) # 3: Weather

                    for r in top_date_rows: r.set_visible(show_t_date)
                    for r in top_time_rows: r.set_visible(show_t_time)
                    for r in top_weather_rows:
                        if r == tw_res:
                            r.set_visible(show_t_weather and len(self.search_results_data) > 0)
                        else:
                            r.set_visible(show_t_weather)

                    b_sel = bot_combo.get_selected()
                    show_b_date = (b_sel == 1) # 1: Date
                    show_b_time = (b_sel == 2) # 2: Time
                    show_b_weather = (b_sel == 3) # 3: Weather

                    for r in bot_date_rows: r.set_visible(show_b_date)
                    for r in bot_time_rows: r.set_visible(show_b_time)
                    for r in bot_weather_rows:
                        if r == bw_res:
                            r.set_visible(show_b_weather and len(self.search_results_data) > 0)
                        else:
                            r.set_visible(show_b_weather)
                else:
                    for r in top_date_rows: r.set_visible(False)
                    for r in top_time_rows: r.set_visible(False)
                    for r in top_weather_rows: r.set_visible(False)
                    for r in bot_date_rows: r.set_visible(False)
                    for r in bot_time_rows: r.set_visible(False)
                    for r in bot_weather_rows: r.set_visible(False)

            mode_combo.connect("notify::selected", lambda *a: update_visibility())
            full_combo.connect("notify::selected", lambda *a: update_visibility())
            top_combo.connect("notify::selected", lambda *a: update_visibility())
            bot_combo.connect("notify::selected", lambda *a: update_visibility())

            update_visibility()

            return expander, mode_combo, full_combo, top_combo, bot_combo

        # Create Section Expanders
        self.sec_a_expander, self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo = create_section_expander(
            "actions.touchbar-info.section-a.label", "Section A (Left — 200px)",
            "actions.touchbar-info.section-a.subtitle", "Configure widgets for the left Touch Bar section", "sec_a"
        )

        self.sec_b_expander, self.sec_b_mode_combo, self.sec_b_full_combo, self.sec_b_top_combo, self.sec_b_bot_combo = create_section_expander(
            "actions.touchbar-info.section-b.label", "Section B (Center — 400px)",
            "actions.touchbar-info.section-b.subtitle", "Configure widgets for the center Touch Bar section", "sec_b"
        )

        self.sec_c_expander, self.sec_c_mode_combo, self.sec_c_full_combo, self.sec_c_top_combo, self.sec_c_bot_combo = create_section_expander(
            "actions.touchbar-info.section-c.label", "Section C (Right — 200px)",
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

        for combo in self.all_date_fam_combos: combo.connect("notify::selected", self.on_date_font_family_changed)
        for spin in self.all_date_size_spins: spin.connect("notify::value", self.on_date_font_size_changed)
        for btn in self.all_date_color_btns: btn.connect("color-set", self.on_date_font_color_set)

        for combo in self.all_time_fam_combos: combo.connect("notify::selected", self.on_time_font_family_changed)
        for spin in self.all_time_size_spins: spin.connect("notify::value", self.on_time_font_size_changed)
        for btn in self.all_time_color_btns: btn.connect("color-set", self.on_time_font_color_set)

        # Weather Signals
        for entry in self.all_weather_loc_entries: entry.connect("changed", self.on_weather_location_entry_changed)
        for combo in self.all_weather_res_combos: combo.connect("notify::selected", self.on_weather_result_selected)
        for combo in self.all_weather_unit_combos: combo.connect("notify::selected", self.on_weather_unit_changed)
        for combo in self.all_weather_ref_combos: combo.connect("notify::selected", self.on_weather_refresh_changed)
        for combo in self.all_weather_fam_combos: combo.connect("notify::selected", self.on_weather_font_family_changed)
        for spin in self.all_weather_size_spins: spin.connect("notify::value", self.on_weather_font_size_changed)
        for btn in self.all_weather_color_btns: btn.connect("color-set", self.on_weather_font_color_set)

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

        date_font_family_idx = settings.setdefault("date_font_family_idx", 0)
        date_font_size = settings.setdefault("date_font_size", 25)
        date_font_color = settings.setdefault("date_font_color", "#AAC8E6FF")

        time_font_family_idx = settings.setdefault("time_font_family_idx", 0)
        time_font_size = settings.setdefault("time_font_size", 45)
        time_font_color = settings.setdefault("time_font_color", "#FFFFFFFF")

        weather_location_name = settings.setdefault("weather_location_name", "Miami")
        weather_unit_idx = settings.setdefault("weather_unit_idx", 0)
        weather_refresh_idx = settings.setdefault("weather_refresh_idx", 2) # 15m
        weather_font_family_idx = settings.setdefault("weather_font_family_idx", 0)
        weather_font_size = settings.setdefault("weather_font_size", 22)
        weather_font_color = settings.setdefault("weather_font_color", "#FFFFFFFF")

        # Sync Date/Time controls
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

        for combo in self.all_date_fam_combos:
            if 0 <= date_font_family_idx < len(self.font_families): combo.set_selected(date_font_family_idx)
        for spin in self.all_date_size_spins: spin.set_value(date_font_size)
        for btn in self.all_date_color_btns: self.set_color_button_rgba(btn, date_font_color)

        for combo in self.all_time_fam_combos:
            if 0 <= time_font_family_idx < len(self.font_families): combo.set_selected(time_font_family_idx)
        for spin in self.all_time_size_spins: spin.set_value(time_font_size)
        for btn in self.all_time_color_btns: self.set_color_button_rgba(btn, time_font_color)

        # Sync Weather controls
        for entry in self.all_weather_loc_entries: entry.set_text(weather_location_name)
        for combo in self.all_weather_unit_combos:
            if 0 <= weather_unit_idx < len(self.weather_units): combo.set_selected(weather_unit_idx)
        for combo in self.all_weather_ref_combos:
            if 0 <= weather_refresh_idx < len(self.weather_intervals): combo.set_selected(weather_refresh_idx)
        for combo in self.all_weather_fam_combos:
            if 0 <= weather_font_family_idx < len(self.font_families): combo.set_selected(weather_font_family_idx)
        for spin in self.all_weather_size_spins: spin.set_value(weather_font_size)
        for btn in self.all_weather_color_btns: self.set_color_button_rgba(btn, weather_font_color)

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

    # --- Date / Time Callbacks ---
    def on_use_24h_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["use_24h"] = val
            for sw in self.all_time_24h_switches:
                if sw != switch and sw.get_active() != val:
                    sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_show_seconds_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            val = switch.get_active()
            settings["show_seconds"] = val
            for sw in self.all_time_sec_switches:
                if sw != switch and sw.get_active() != val:
                    sw.set_active(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_format_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["date_format_idx"] = val
            for c in self.all_date_fmt_combos:
                if c != combo and c.get_selected() != val:
                    c.set_selected(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_font_family_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["date_font_family_idx"] = val
            for c in self.all_date_fam_combos:
                if c != combo and c.get_selected() != val:
                    c.set_selected(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_font_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            val = int(spin.get_value())
            settings["date_font_size"] = val
            for s in self.all_date_size_spins:
                if s != spin and int(s.get_value()) != val:
                    s.set_value(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_font_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["date_font_color"] = hex_val
            for btn in self.all_date_color_btns:
                if btn != button:
                    self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_font_family_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["time_font_family_idx"] = val
            for c in self.all_time_fam_combos:
                if c != combo and c.get_selected() != val:
                    c.set_selected(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_font_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            val = int(spin.get_value())
            settings["time_font_size"] = val
            for s in self.all_time_size_spins:
                if s != spin and int(s.get_value()) != val:
                    s.set_value(val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_font_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["time_font_color"] = hex_val
            for btn in self.all_time_color_btns:
                if btn != button:
                    self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    # --- Weather Callbacks ---
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
                        if len(results) > 0:
                            combo.set_model(string_list)
                            combo.set_visible(True)
                        else:
                            combo.set_visible(False)
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

    def on_weather_font_family_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            val = combo.get_selected()
            settings["weather_font_family_idx"] = val
            for c in self.all_weather_fam_combos:
                if c != combo and c.get_selected() != val:
                    c.set_selected(val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_font_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            val = int(spin.get_value())
            settings["weather_font_size"] = val
            for s in self.all_weather_size_spins:
                if s != spin and int(s.get_value()) != val:
                    s.set_value(val)
            self.set_settings(settings)
            self.trigger_redraw()

    def on_weather_font_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            hex_val = self.gdk_to_hex(rgba)
            settings["weather_font_color"] = hex_val
            for btn in self.all_weather_color_btns:
                if btn != button:
                    self.set_color_button_rgba(btn, hex_val)
            self.set_settings(settings)
            self.trigger_redraw()

    def get_font_for_family(self, family_name: str, size: int, bold: bool = True):
        style = "Bold" if bold else "Regular"
        cmd = ["fc-match", "-f", "%{file}", f"{family_name}:style={style}"]
        try:
            res = subprocess.check_output(cmd, text=True).strip()
            if res and os.path.isfile(res):
                return ImageFont.truetype(res, size)
        except Exception:
            pass

        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
        ]
        for path in font_paths:
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def get_canvas_size(self) -> tuple[int, int]:
        if hasattr(self, "deck_controller") and self.deck_controller is not None:
            if hasattr(self.deck_controller, "get_touchscreen_image_size"):
                size = self.deck_controller.get_touchscreen_image_size()
                if size is not None:
                    return size
        return (800, 100)

    # --- Render Helpers ---
    def draw_stacked(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], date_str: str, time_str: str, font_date, font_time, date_color, time_color):
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

        draw.text((center_x, date_y), date_str, fill=date_color, font=font_date, anchor="mm")
        draw.text((center_x, time_y), time_str, fill=time_color, font=font_time, anchor="mm")

    def draw_single(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font, color):
        x_min, y_min, x_max, y_max = box
        center_x = x_min + (x_max - x_min) / 2
        center_y = y_min + (y_max - y_min) / 2
        draw.text((center_x, center_y), text, fill=color, font=font, anchor="mm")

    def draw_weather(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font_weather, font_location, color):
        x_min, y_min, x_max, y_max = box
        box_w = x_max - x_min
        box_h = y_max - y_min

        cache = self.weather_cache or {}
        temp_str = cache.get("temp_str", "--°")
        wmo_code = cache.get("wmo_code", 0)
        is_day = cache.get("is_day", 1)
        location_str = cache.get("location", "Miami")

        icon_file = self.get_weather_icon_filename(wmo_code, is_day)
        icon_path = os.path.join(self.plugin_base.PATH, "assets", "weather-icons", icon_file)

        # Scale weather icon to fit section height
        target_icon_h = int(box_h * 0.70)
        icon_img = None

        if os.path.exists(icon_path):
            try:
                raw_img = Image.open(icon_path).convert("RGBA")
                aspect = raw_img.width / max(1, raw_img.height)
                target_icon_w = int(target_icon_h * aspect)
                icon_img = raw_img.resize((target_icon_w, target_icon_h), Image.Resampling.LANCZOS)
            except Exception as e:
                log.error(f"TouchBarInfo: Failed loading weather icon {icon_path}: {e}")

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

        # Calculate text column center to align temperature in the center above location name
        text_column_w = max(temp_w, loc_w)
        center_text_x = left_text_x + (text_column_w / 2)

        spacing = max(1, int(box_h * 0.04))
        total_h = temp_h + spacing + loc_h
        start_y = y_min + (box_h - total_h) / 2

        temp_y = start_y + (temp_h / 2)
        loc_y = start_y + temp_h + spacing + (loc_h / 2)

        draw.text((center_text_x, temp_y), temp_str, fill=color, font=font_weather, anchor="mm")
        draw.text((center_text_x, loc_y), location_str, fill=color, font=font_location, anchor="mm")

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

        date_font_family_idx = settings.get("date_font_family_idx", 0)
        date_font_size = settings.get("date_font_size", 25)
        date_font_color_hex = settings.get("date_font_color", "#AAC8E6FF")

        time_font_family_idx = settings.get("time_font_family_idx", 0)
        time_font_size = settings.get("time_font_size", 45)
        time_font_color_hex = settings.get("time_font_color", "#FFFFFFFF")

        weather_font_family_idx = settings.get("weather_font_family_idx", 0)
        weather_font_size = settings.get("weather_font_size", 22)
        weather_font_color_hex = settings.get("weather_font_color", "#FFFFFFFF")

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

        date_family = self.font_families[min(date_font_family_idx, len(self.font_families) - 1)] if hasattr(self, "font_families") else "DejaVu Sans"
        time_family = self.font_families[min(time_font_family_idx, len(self.font_families) - 1)] if hasattr(self, "font_families") else "DejaVu Sans"
        weather_family = self.font_families[min(weather_font_family_idx, len(self.font_families) - 1)] if hasattr(self, "font_families") else "DejaVu Sans"

        cache_temp = self.weather_cache.get("temp_str", "--°") if hasattr(self, "weather_cache") else "--°"
        cache_loc = self.weather_cache.get("location", "") if hasattr(self, "weather_cache") else ""

        combined_key = f"{date_str}|{time_str}|{cache_temp}|{cache_loc}|{sec_a_mode}|{sec_a_full}|{sec_a_top}|{sec_a_bot}|{sec_b_mode}|{sec_b_full}|{sec_b_top}|{sec_b_bot}|{sec_c_mode}|{sec_c_full}|{sec_c_top}|{sec_c_bot}|{date_family}|{date_font_size}|{date_font_color_hex}|{time_family}|{time_font_size}|{time_font_color_hex}|{weather_family}|{weather_font_size}|{weather_font_color_hex}"

        if combined_key == self.last_rendered_key:
            return
        self.last_rendered_key = combined_key

        width, height = self.get_canvas_size()

        image = Image.new("RGBA", (width, height), (15, 16, 22, 255))
        draw = ImageDraw.Draw(image)

        font_date = self.get_font_for_family(date_family, date_font_size, bold=True)
        font_time = self.get_font_for_family(time_family, time_font_size, bold=True)

        font_weather_full = self.get_font_for_family(weather_family, int(weather_font_size * 1.5), bold=True)
        font_loc_full = self.get_font_for_family(weather_family, weather_font_size, bold=True)

        font_weather_sub = self.get_font_for_family(weather_family, weather_font_size, bold=True)
        font_loc_sub = self.get_font_for_family(weather_family, max(10, int(weather_font_size * 0.75)), bold=True)

        date_color = self.hex_to_rgba_tuple(date_font_color_hex, default=(170, 200, 230, 255))
        time_color = self.hex_to_rgba_tuple(time_font_color_hex, default=(255, 255, 255, 255))
        weather_color = self.hex_to_rgba_tuple(weather_font_color_hex, default=(255, 255, 255, 255))

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
                    self.draw_stacked(draw, full_box, date_str, time_str, font_date, font_time, date_color, time_color)
                elif full_choice == 2: # Date
                    self.draw_single(draw, full_box, date_str, font_date, date_color)
                elif full_choice == 3: # Time
                    self.draw_single(draw, full_box, time_str, font_time, time_color)
                elif full_choice == 4: # Weather
                    self.draw_weather(image, draw, full_box, font_weather_full, font_loc_full, weather_color)
            else: # 2 Widgets (Split Top / Bottom)
                # Top Sub-slot
                if top_choice == 1: # Date
                    self.draw_single(draw, top_box, date_str, font_date, date_color)
                elif top_choice == 2: # Time
                    self.draw_single(draw, top_box, time_str, font_time, time_color)
                elif top_choice == 3: # Weather
                    self.draw_weather(image, draw, top_box, font_weather_sub, font_loc_sub, weather_color)

                # Bottom Sub-slot
                if bot_choice == 1: # Date
                    self.draw_single(draw, bot_box, date_str, font_date, date_color)
                elif bot_choice == 2: # Time
                    self.draw_single(draw, bot_box, time_str, font_time, time_color)
                elif bot_choice == 3: # Weather
                    self.draw_weather(image, draw, bot_box, font_weather_sub, font_loc_sub, weather_color)

        render_section(sec_a_mode, sec_a_full, sec_a_top, sec_a_bot, box_a_full, box_a_top, box_a_bot)
        render_section(sec_b_mode, sec_b_full, sec_b_top, sec_b_bot, box_b_full, box_b_top, box_b_bot)
        render_section(sec_c_mode, sec_c_full, sec_c_top, sec_c_bot, box_c_full, box_c_top, box_c_bot)

        self.render_to_input(image)

    def render_to_input(self, image: Image.Image) -> None:
        if not hasattr(self, "page") or self.page is None:
            return

        assets_dir = os.path.join(self.plugin_base.PATH, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        render_path = os.path.join(assets_dir, f"touchbar_render_{self.state}.png")

        try:
            image.save(render_path)
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
