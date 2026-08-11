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
        # 1. 24-hour clock switch
        self.use_24h_switch = Adw.SwitchRow(
            title=self.get_locale_text("actions.touchbar-info.use-24h.label", "Use 24-Hour Clock"),
            subtitle=self.get_locale_text("actions.touchbar-info.use-24h.subtitle", "Switch between 12-hour (AM/PM) and 24-hour time format")
        )

        # 2. Show seconds switch
        self.show_seconds_switch = Adw.SwitchRow(
            title=self.get_locale_text("actions.touchbar-info.show-seconds.label", "Show Seconds"),
            subtitle=self.get_locale_text("actions.touchbar-info.show-seconds.subtitle", "Include seconds in the displayed time")
        )

        # 3. Date format selector
        self.date_format_model = Gtk.StringList()
        self.date_format_combo = Adw.ComboRow(
            model=self.date_format_model,
            title=self.get_locale_text("actions.touchbar-info.date-format.label", "Date Format"),
            subtitle=self.get_locale_text("actions.touchbar-info.date-format.subtitle", "Format style for top date line")
        )

        self.date_format_options = [
            ("%b. %d, %Y", self.get_locale_text("actions.touchbar-info.date-format.mon-day-year", "Mon. Day, Year (Aug. 11, 2026)")),
            ("%a. %d, %Y", self.get_locale_text("actions.touchbar-info.date-format.dow-day-year", "DayOfWeek. Day, Year (Tue. 11, 2026)")),
            ("%a. %b. %d, %Y", self.get_locale_text("actions.touchbar-info.date-format.dow-mon-day-year", "DayOfWeek. Mon. Day, Year (Tue. Aug. 11, 2026)")),
            ("%Y-%b-%d", self.get_locale_text("actions.touchbar-info.date-format.year-mon-day", "Year-Mon-Day (2026-Aug-11)"))
        ]

        for _, label in self.date_format_options:
            self.date_format_model.append(label)

        # Available font families
        self.font_families = ["DejaVu Sans", "Liberation Sans", "Ubuntu", "Noto Sans", "Monospace", "Serif", "Sans"]

        # --- Date Font Expander Dropdown ---
        self.date_expander = Adw.ExpanderRow(
            title=self.get_locale_text("actions.touchbar-info.date-settings.label", "Date Font Customization"),
            subtitle=self.get_locale_text("actions.touchbar-info.date-settings.subtitle", "Font family, size, and color for top date text")
        )

        # Date Font Family
        self.date_font_family_model = Gtk.StringList()
        self.date_font_family_combo = Adw.ComboRow(
            model=self.date_font_family_model,
            title=self.get_locale_text("actions.touchbar-info.date-font-family.label", "Date Font Family"),
            subtitle=self.get_locale_text("actions.touchbar-info.date-font-family.subtitle", "Select font typeface for the top date text")
        )
        for fam in self.font_families:
            self.date_font_family_model.append(fam)

        # Date Font Size
        self.date_font_size_spin = Adw.SpinRow.new_with_range(10, 80, 1)
        self.date_font_size_spin.set_title(self.get_locale_text("actions.touchbar-info.date-font-size.label", "Date Font Size"))
        self.date_font_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.date-font-size.subtitle", "Font size in pixels for the date line"))

        # Date Font Color
        self.date_font_color_row = Adw.ActionRow(
            title=self.get_locale_text("actions.touchbar-info.date-font-color.label", "Date Font Color"),
            subtitle=self.get_locale_text("actions.touchbar-info.date-font-color.subtitle", "Text color for the top date line")
        )
        self.date_font_color_button = Gtk.ColorButton()
        self.date_font_color_button.set_valign(Gtk.Align.CENTER)
        self.date_font_color_row.add_suffix(self.date_font_color_button)

        self.date_expander.add_row(self.date_font_family_combo)
        self.date_expander.add_row(self.date_font_size_spin)
        self.date_expander.add_row(self.date_font_color_row)

        # --- Time Font Expander Dropdown ---
        self.time_expander = Adw.ExpanderRow(
            title=self.get_locale_text("actions.touchbar-info.time-settings.label", "Time Font Customization"),
            subtitle=self.get_locale_text("actions.touchbar-info.time-settings.subtitle", "Font family, size, and color for bottom time text")
        )

        # Time Font Family
        self.time_font_family_model = Gtk.StringList()
        self.time_font_family_combo = Adw.ComboRow(
            model=self.time_font_family_model,
            title=self.get_locale_text("actions.touchbar-info.time-font-family.label", "Time Font Family"),
            subtitle=self.get_locale_text("actions.touchbar-info.time-font-family.subtitle", "Select font typeface for the bottom time text")
        )
        for fam in self.font_families:
            self.time_font_family_model.append(fam)

        # Time Font Size
        self.time_font_size_spin = Adw.SpinRow.new_with_range(10, 100, 1)
        self.time_font_size_spin.set_title(self.get_locale_text("actions.touchbar-info.time-font-size.label", "Time Font Size"))
        self.time_font_size_spin.set_subtitle(self.get_locale_text("actions.touchbar-info.time-font-size.subtitle", "Font size in pixels for the time line"))

        # Time Font Color
        self.time_font_color_row = Adw.ActionRow(
            title=self.get_locale_text("actions.touchbar-info.time-font-color.label", "Time Font Color"),
            subtitle=self.get_locale_text("actions.touchbar-info.time-font-color.subtitle", "Text color for the bottom time line")
        )
        self.time_font_color_button = Gtk.ColorButton()
        self.time_font_color_button.set_valign(Gtk.Align.CENTER)
        self.time_font_color_row.add_suffix(self.time_font_color_button)

        self.time_expander.add_row(self.time_font_family_combo)
        self.time_expander.add_row(self.time_font_size_spin)
        self.time_expander.add_row(self.time_font_color_row)

        self.load_config_defaults()

        # Signals
        self.use_24h_switch.connect("notify::active", self.on_use_24h_toggled)
        self.show_seconds_switch.connect("notify::active", self.on_show_seconds_toggled)
        self.date_format_combo.connect("notify::selected", self.on_date_format_changed)
        
        self.date_font_family_combo.connect("notify::selected", self.on_date_font_family_changed)
        self.date_font_size_spin.connect("notify::value", self.on_date_font_size_changed)
        self.date_font_color_button.connect("color-set", self.on_date_font_color_set)

        self.time_font_family_combo.connect("notify::selected", self.on_time_font_family_changed)
        self.time_font_size_spin.connect("notify::value", self.on_time_font_size_changed)
        self.time_font_color_button.connect("color-set", self.on_time_font_color_set)

        return [
            self.use_24h_switch,
            self.show_seconds_switch,
            self.date_format_combo,
            self.date_expander,
            self.time_expander
        ]

    def load_config_defaults(self):
        settings = self.get_settings()
        if settings is None:
            return

        use_24h = settings.setdefault("use_24h", False)
        show_seconds = settings.setdefault("show_seconds", False)
        date_format_idx = settings.setdefault("date_format_idx", 0)

        date_font_family_idx = settings.setdefault("date_font_family_idx", 0)
        date_font_size = settings.setdefault("date_font_size", 25)
        date_font_color = settings.setdefault("date_font_color", "#AAC8E6FF")

        time_font_family_idx = settings.setdefault("time_font_family_idx", 0)
        time_font_size = settings.setdefault("time_font_size", 45)
        time_font_color = settings.setdefault("time_font_color", "#FFFFFFFF")

        self.use_24h_switch.set_active(use_24h)
        self.show_seconds_switch.set_active(show_seconds)
        if 0 <= date_format_idx < len(self.date_format_options):
            self.date_format_combo.set_selected(date_format_idx)

        if 0 <= date_font_family_idx < len(self.font_families):
            self.date_font_family_combo.set_selected(date_font_family_idx)
        self.date_font_size_spin.set_value(date_font_size)
        self.set_color_button_rgba(self.date_font_color_button, date_font_color)

        if 0 <= time_font_family_idx < len(self.font_families):
            self.time_font_family_combo.set_selected(time_font_family_idx)
        self.time_font_size_spin.set_value(time_font_size)
        self.set_color_button_rgba(self.time_font_color_button, time_font_color)

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

    def update_display(self) -> None:
        settings = self.get_settings() or {}
        use_24h = settings.get("use_24h", False)
        show_seconds = settings.get("show_seconds", False)
        date_format_idx = settings.get("date_format_idx", 0)

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

        combined_key = f"{date_str}|{time_str}|{date_family}|{date_font_size}|{date_font_color_hex}|{time_family}|{time_font_size}|{time_font_color_hex}"

        # Avoid redundant redraws if settings and time text haven't changed
        if combined_key == self.last_rendered_key:
            return
        self.last_rendered_key = combined_key

        width, height = self.get_canvas_size()

        image = Image.new("RGBA", (width, height), (15, 16, 22, 255))
        draw = ImageDraw.Draw(image)

        font_date = self.get_font_for_family(date_family, date_font_size, bold=True)
        font_time = self.get_font_for_family(time_family, time_font_size, bold=True)

        bbox_date = draw.textbbox((0, 0), date_str, font=font_date)
        bbox_time = draw.textbbox((0, 0), time_str, font=font_time)

        date_h = bbox_date[3] - bbox_date[1]
        time_h = bbox_time[3] - bbox_time[1]

        spacing = max(2, int(height * 0.04))
        total_h = date_h + spacing + time_h
        start_y = (height - total_h) / 2

        center_x = width / 2
        date_y = start_y + (date_h / 2)
        time_y = start_y + date_h + spacing + (time_h / 2)

        date_color = self.hex_to_rgba_tuple(date_font_color_hex, default=(170, 200, 230, 255))
        time_color = self.hex_to_rgba_tuple(time_font_color_hex, default=(255, 255, 255, 255))

        # Draw date line
        draw.text((center_x, date_y), date_str, fill=date_color, font=font_date, anchor="mm")
        
        # Draw time line
        draw.text((center_x, time_y), time_str, fill=time_color, font=font_time, anchor="mm")

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
