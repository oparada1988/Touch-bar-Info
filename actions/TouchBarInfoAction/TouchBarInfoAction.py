# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python modules
import os
import subprocess
import datetime
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
        self.update_display()

    def on_tick(self) -> None:
        self.update_display()

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

        # Widget choices (removed "Only")
        self.full_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.none", "None (Empty)"),
            self.get_locale_text("actions.touchbar-info.widget.stacked", "Stacked Date & Time"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time")
        ]
        self.split_widget_options = [
            self.get_locale_text("actions.touchbar-info.widget.none", "None (Empty)"),
            self.get_locale_text("actions.touchbar-info.widget.date", "Date"),
            self.get_locale_text("actions.touchbar-info.widget.time", "Time")
        ]

        # Helper to create Date Controls Sub-group
        def create_date_controls():
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

            return fmt_combo, fam_combo, size_spin, color_row, color_btn

        # Helper to create Time Controls Sub-group
        def create_time_controls():
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

            return sw_24h, sw_sec, fam_combo, size_spin, color_row, color_btn

        # Shared Controls instances
        self.date_fmt_combo, self.date_fam_combo, self.date_size_spin, self.date_color_row, self.date_color_btn = create_date_controls()
        self.time_24h_sw, self.time_sec_sw, self.time_fam_combo, self.time_size_spin, self.time_color_row, self.time_color_btn = create_time_controls()

        # Helper to create Section Expander with embedded in-line controls
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

            full_model = Gtk.StringList()
            for opt in self.full_widget_options: full_model.append(opt)
            full_combo = Adw.ComboRow(
                model=full_model,
                title=self.get_locale_text("actions.touchbar-info.full-widget.label", "Full Section Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.full-widget.subtitle", "Widget assigned to full section area")
            )

            top_model = Gtk.StringList()
            for opt in self.split_widget_options: top_model.append(opt)
            top_combo = Adw.ComboRow(
                model=top_model,
                title=self.get_locale_text("actions.touchbar-info.top-widget.label", "Top Subsection Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.top-widget.subtitle", "Widget assigned to top half (Y: 0-50px)")
            )

            bot_model = Gtk.StringList()
            for opt in self.split_widget_options: bot_model.append(opt)
            bot_combo = Adw.ComboRow(
                model=bot_model,
                title=self.get_locale_text("actions.touchbar-info.bottom-widget.label", "Bottom Subsection Widget"),
                subtitle=self.get_locale_text("actions.touchbar-info.bottom-widget.subtitle", "Widget assigned to bottom half (Y: 50-100px)")
            )

            expander.add_row(mode_combo)
            expander.add_row(full_combo)
            expander.add_row(top_combo)
            expander.add_row(bot_combo)

            return expander, mode_combo, full_combo, top_combo, bot_combo

        # Create 3 Section Expanders
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

        # Date & Time Settings Expander Dropdowns (Embedded under Sections)
        self.date_font_expander = Adw.ExpanderRow(
            title=self.get_locale_text("actions.touchbar-info.date-settings.label", "Date Options & Font Customization"),
            subtitle=self.get_locale_text("actions.touchbar-info.date-settings.subtitle", "Date format, font family, size, and color")
        )
        self.date_font_expander.add_row(self.date_fmt_combo)
        self.date_font_expander.add_row(self.date_fam_combo)
        self.date_font_expander.add_row(self.date_size_spin)
        self.date_font_expander.add_row(self.date_color_row)

        self.time_font_expander = Adw.ExpanderRow(
            title=self.get_locale_text("actions.touchbar-info.time-settings.label", "Time Options & Font Customization"),
            subtitle=self.get_locale_text("actions.touchbar-info.time-settings.subtitle", "Clock format, 24h mode, seconds, font family, size, and color")
        )
        self.time_font_expander.add_row(self.time_24h_sw)
        self.time_font_expander.add_row(self.time_sec_sw)
        self.time_font_expander.add_row(self.time_fam_combo)
        self.time_font_expander.add_row(self.time_size_spin)
        self.time_font_expander.add_row(self.time_color_row)

        # Append inline settings rows to Section Expanders
        self.sec_a_expander.add_row(self.date_font_expander)
        self.sec_a_expander.add_row(self.time_font_expander)

        self.load_config_defaults()

        # Connect Visibility Toggles for Section Modes and In-Line Settings
        def update_section_visibility(mode_combo, full_combo, top_combo, bot_combo, key_prefix):
            is_full = mode_combo.get_selected() == 0
            full_combo.set_visible(is_full)
            top_combo.set_visible(not is_full)
            bot_combo.set_visible(not is_full)

            # Update overall Date & Time settings expander visibility
            needs_date = False
            needs_time = False

            for mode_c, full_c, top_c, bot_c in [
                (self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo),
                (self.sec_b_mode_combo, self.sec_b_full_combo, self.sec_b_top_combo, self.sec_b_bot_combo),
                (self.sec_c_mode_combo, self.sec_c_full_combo, self.sec_c_top_combo, self.sec_c_bot_combo)
            ]:
                if mode_c.get_selected() == 0:
                    sel = full_c.get_selected()
                    if sel == 1: # Stacked Date & Time
                        needs_date = True; needs_time = True
                    elif sel == 2: # Date
                        needs_date = True
                    elif sel == 3: # Time
                        needs_time = True
                else:
                    top_s = top_c.get_selected()
                    bot_s = bot_c.get_selected()
                    if top_s == 1 or bot_s == 1: needs_date = True
                    if top_s == 2 or bot_s == 2: needs_time = True

            self.date_font_expander.set_visible(needs_date)
            self.time_font_expander.set_visible(needs_time)

        def setup_mode_listener(mode_combo, full_combo, top_combo, bot_combo, key_prefix):
            def on_mode_changed(combo, *args):
                update_section_visibility(mode_combo, full_combo, top_combo, bot_combo, key_prefix)
                settings = self.get_settings()
                if settings is not None:
                    settings[f"{key_prefix}_mode"] = combo.get_selected()
                    self.set_settings(settings)
                    self.last_rendered_key = ""
                    self.update_display()

            mode_combo.connect("notify::selected", on_mode_changed)

        setup_mode_listener(self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo, "sec_a")
        setup_mode_listener(self.sec_b_mode_combo, self.sec_b_full_combo, self.sec_b_top_combo, self.sec_b_bot_combo, "sec_b")
        setup_mode_listener(self.sec_c_mode_combo, self.sec_c_full_combo, self.sec_c_top_combo, self.sec_c_bot_combo, "sec_c")

        # Section Widget Choice Signals
        def bind_combo(combo, setting_name):
            def on_combo_change(c, *a):
                update_section_visibility(self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo, "sec_a")
                self.on_setting_combo_changed(setting_name, c.get_selected())
            combo.connect("notify::selected", on_combo_change)

        bind_combo(self.sec_a_full_combo, "sec_a_full_widget")
        bind_combo(self.sec_a_top_combo, "sec_a_top_widget")
        bind_combo(self.sec_a_bot_combo, "sec_a_bottom_widget")

        bind_combo(self.sec_b_full_combo, "sec_b_full_widget")
        bind_combo(self.sec_b_top_combo, "sec_b_top_widget")
        bind_combo(self.sec_b_bot_combo, "sec_b_bottom_widget")

        bind_combo(self.sec_c_full_combo, "sec_c_full_widget")
        bind_combo(self.sec_c_top_combo, "sec_c_top_widget")
        bind_combo(self.sec_c_bot_combo, "sec_c_bottom_widget")

        # General Option Signals
        self.time_24h_sw.connect("notify::active", self.on_use_24h_toggled)
        self.time_sec_sw.connect("notify::active", self.on_show_seconds_toggled)
        self.date_fmt_combo.connect("notify::selected", self.on_date_format_changed)

        # Font Signals
        self.date_fam_combo.connect("notify::selected", self.on_date_font_family_changed)
        self.date_size_spin.connect("notify::value", self.on_date_font_size_changed)
        self.date_color_btn.connect("color-set", self.on_date_font_color_set)

        self.time_fam_combo.connect("notify::selected", self.on_time_font_family_changed)
        self.time_size_spin.connect("notify::value", self.on_time_font_size_changed)
        self.time_color_btn.connect("color-set", self.on_time_font_color_set)

        # Initial visibility update
        update_section_visibility(self.sec_a_mode_combo, self.sec_a_full_combo, self.sec_a_top_combo, self.sec_a_bot_combo, "sec_a")

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

        # Section Defaults: B default is Full Stacked Date & Time
        sec_a_mode = settings.setdefault("sec_a_mode", 0)
        sec_a_full = settings.setdefault("sec_a_full_widget", 0)
        sec_a_top = settings.setdefault("sec_a_top_widget", 0)
        sec_a_bot = settings.setdefault("sec_a_bottom_widget", 0)

        sec_b_mode = settings.setdefault("sec_b_mode", 0)
        sec_b_full = settings.setdefault("sec_b_full_widget", 1) # Stacked
        sec_b_top = settings.setdefault("sec_b_top_widget", 1)  # Date
        sec_b_bot = settings.setdefault("sec_b_bottom_widget", 2) # Time

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

        self.time_24h_sw.set_active(use_24h)
        self.time_sec_sw.set_active(show_seconds)
        if 0 <= date_format_idx < len(self.date_format_options):
            self.date_fmt_combo.set_selected(date_format_idx)

        # Apply Section selections
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

        if 0 <= date_font_family_idx < len(self.font_families):
            self.date_fam_combo.set_selected(date_font_family_idx)
        self.date_size_spin.set_value(date_font_size)
        self.set_color_button_rgba(self.date_color_btn, date_font_color)

        if 0 <= time_font_family_idx < len(self.font_families):
            self.time_fam_combo.set_selected(time_font_family_idx)
        self.time_size_spin.set_value(time_font_size)
        self.set_color_button_rgba(self.time_color_btn, time_font_color)

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

    def on_use_24h_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["use_24h"] = switch.get_active()
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_show_seconds_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["show_seconds"] = switch.get_active()
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_format_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["date_format_idx"] = combo.get_selected()
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_font_family_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["date_font_family_idx"] = combo.get_selected()
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_font_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["date_font_size"] = int(spin.get_value())
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_date_font_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            settings["date_font_color"] = self.gdk_to_hex(rgba)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_font_family_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["time_font_family_idx"] = combo.get_selected()
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_font_size_changed(self, spin, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["time_font_size"] = int(spin.get_value())
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

    def on_time_font_color_set(self, button):
        settings = self.get_settings()
        if settings is not None:
            rgba = button.get_rgba()
            settings["time_font_color"] = self.gdk_to_hex(rgba)
            self.set_settings(settings)
            self.last_rendered_key = ""
            self.update_display()

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
        sec_b_full = settings.get("sec_b_full_widget", 1)
        sec_b_top = settings.get("sec_b_top_widget", 1)
        sec_b_bot = settings.get("sec_b_bottom_widget", 2)

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

        combined_key = f"{date_str}|{time_str}|{sec_a_mode}|{sec_a_full}|{sec_a_top}|{sec_a_bot}|{sec_b_mode}|{sec_b_full}|{sec_b_top}|{sec_b_bot}|{sec_c_mode}|{sec_c_full}|{sec_c_top}|{sec_c_bot}|{date_family}|{date_font_size}|{date_font_color_hex}|{time_family}|{time_font_size}|{time_font_color_hex}"

        # Avoid redundant redraws if settings and time text haven't changed
        if combined_key == self.last_rendered_key:
            return
        self.last_rendered_key = combined_key

        width, height = self.get_canvas_size()

        image = Image.new("RGBA", (width, height), (15, 16, 22, 255))
        draw = ImageDraw.Draw(image)

        font_date = self.get_font_for_family(date_family, date_font_size, bold=True)
        font_time = self.get_font_for_family(time_family, time_font_size, bold=True)

        date_color = self.hex_to_rgba_tuple(date_font_color_hex, default=(170, 200, 230, 255))
        time_color = self.hex_to_rgba_tuple(time_font_color_hex, default=(255, 255, 255, 255))

        # --- Section Bounding Boxes ---
        # Section A: 0..200 (Left)
        box_a_full = (0, 0, 200, 100)
        box_a_top = (0, 0, 200, 50)
        box_a_bot = (0, 50, 200, 100)

        # Section B: 200..600 (Center - full 400px width)
        box_b_full = (200, 0, 600, 100)
        box_b_top = (200, 0, 600, 50)
        box_b_bot = (200, 50, 600, 100)

        # Section C: 600..800 (Right)
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
            else: # 2 Widgets (Split Top / Bottom)
                # Top Sub-slot
                if top_choice == 1: # Date
                    self.draw_single(draw, top_box, date_str, font_date, date_color)
                elif top_choice == 2: # Time
                    self.draw_single(draw, top_box, time_str, font_time, time_color)

                # Bottom Sub-slot
                if bot_choice == 1: # Date
                    self.draw_single(draw, bot_box, date_str, font_date, date_color)
                elif bot_choice == 2: # Time
                    self.draw_single(draw, bot_box, time_str, font_time, time_color)

        # Render Section A
        render_section(sec_a_mode, sec_a_full, sec_a_top, sec_a_bot, box_a_full, box_a_top, box_a_bot)

        # Render Section B
        render_section(sec_b_mode, sec_b_full, sec_b_top, sec_b_bot, box_b_full, box_b_top, box_b_bot)

        # Render Section C
        render_section(sec_c_mode, sec_c_full, sec_c_top, sec_c_bot, box_c_full, box_c_top, box_c_bot)

        self.render_to_input(image)

    def render_to_input(self, image: Image.Image) -> None:
        if not hasattr(self, "page") or self.page is None:
            return

        # Save rendered date/time image to assets directory
        assets_dir = os.path.join(self.plugin_base.PATH, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        render_path = os.path.join(assets_dir, f"touchbar_render_{self.state}.png")

        try:
            image.save(render_path)
            # Set page background image path for touchscreen (update=False prevents recursive page reload)
            self.page.set_background_image(self.input_ident, self.state, render_path, update=False)
        except Exception as e:
            log.error(f"TouchBarInfo: Error saving touchscreen background: {e}")

        # Trigger non-recursive update on the touchscreen controller
        if hasattr(self, "deck_controller") and self.deck_controller is not None:
            c_input = self.deck_controller.get_input(self.input_ident)
            if c_input is not None and hasattr(c_input, "update"):
                try:
                    c_input.update()
                except Exception as e:
                    log.error(f"TouchBarInfo: Error updating touchscreen controller: {e}")
