# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python modules
import os
import datetime
from PIL import Image, ImageDraw, ImageFont

# Import GTK modules
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
from loguru import logger as log
import globals as gl

class TouchBarInfoAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.last_rendered_time_str = ""

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
        # 24-hour clock switch
        self.use_24h_switch = Adw.SwitchRow(
            title=self.get_locale_text("actions.touchbar-info.use-24h.label", "Use 24-Hour Clock"),
            subtitle=self.get_locale_text("actions.touchbar-info.use-24h.subtitle", "Switch between 12-hour (AM/PM) and 24-hour time format")
        )

        # Show seconds switch
        self.show_seconds_switch = Adw.SwitchRow(
            title=self.get_locale_text("actions.touchbar-info.show-seconds.label", "Show Seconds"),
            subtitle=self.get_locale_text("actions.touchbar-info.show-seconds.subtitle", "Include seconds in the displayed time")
        )

        # Date format selector
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

        self.load_config_defaults()

        self.use_24h_switch.connect("notify::active", self.on_use_24h_toggled)
        self.show_seconds_switch.connect("notify::active", self.on_show_seconds_toggled)
        self.date_format_combo.connect("notify::selected", self.on_date_format_changed)

        return [self.use_24h_switch, self.show_seconds_switch, self.date_format_combo]

    def load_config_defaults(self):
        settings = self.get_settings()
        if settings is None:
            return

        use_24h = settings.setdefault("use_24h", False)
        show_seconds = settings.setdefault("show_seconds", False)
        date_format_idx = settings.setdefault("date_format_idx", 0)

        self.use_24h_switch.set_active(use_24h)
        self.show_seconds_switch.set_active(show_seconds)
        if 0 <= date_format_idx < len(self.date_format_options):
            self.date_format_combo.set_selected(date_format_idx)

    def on_use_24h_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["use_24h"] = switch.get_active()
            self.set_settings(settings)
            self.last_rendered_time_str = ""
            self.update_display()

    def on_show_seconds_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["show_seconds"] = switch.get_active()
            self.set_settings(settings)
            self.last_rendered_time_str = ""
            self.update_display()

    def on_date_format_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["date_format_idx"] = combo.get_selected()
            self.set_settings(settings)
            self.last_rendered_time_str = ""
            self.update_display()

    def get_font(self, size: int):
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
        combined_key = f"{date_str}|{time_str}"

        # Avoid redundant redraws if text hasn't changed
        if combined_key == self.last_rendered_time_str:
            return
        self.last_rendered_time_str = combined_key

        width, height = self.get_canvas_size()

        image = Image.new("RGBA", (width, height), (15, 16, 22, 255))
        draw = ImageDraw.Draw(image)

        # Dynamic font sizes based on canvas height
        date_font_size = max(14, int(height * 0.25))
        time_font_size = max(20, int(height * 0.45))

        font_date = self.get_font(date_font_size)
        font_time = self.get_font(time_font_size)

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

        # Draw date (smaller font, soft muted accent color)
        draw.text((center_x, date_y), date_str, fill=(170, 200, 230, 255), font=font_date, anchor="mm")
        
        # Draw time (larger font, crisp white color)
        draw.text((center_x, time_y), time_str, fill=(255, 255, 255, 255), font=font_time, anchor="mm")

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
