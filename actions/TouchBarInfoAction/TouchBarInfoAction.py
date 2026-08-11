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

    def on_ready(self) -> None:
        self.update_display()

    def on_tick(self) -> None:
        self.update_display()

    def get_config_rows(self) -> "list[Adw.PreferencesRow]":
        # 24-hour clock switch
        self.use_24h_switch = Adw.SwitchRow(
            title=self.plugin_base.lm.get("actions.touchbar-info.use-24h.label"),
            subtitle=self.plugin_base.lm.get("actions.touchbar-info.use-24h.subtitle")
        )

        # Show seconds switch
        self.show_seconds_switch = Adw.SwitchRow(
            title=self.plugin_base.lm.get("actions.touchbar-info.show-seconds.label"),
            subtitle=self.plugin_base.lm.get("actions.touchbar-info.show-seconds.subtitle")
        )

        # Date format selector
        self.date_format_model = Gtk.StringList()
        self.date_format_combo = Adw.ComboRow(
            model=self.date_format_model,
            title=self.plugin_base.lm.get("actions.touchbar-info.date-format.label"),
            subtitle=self.plugin_base.lm.get("actions.touchbar-info.date-format.subtitle")
        )

        self.date_format_options = [
            ("%b. %d, %Y", self.plugin_base.lm.get("actions.touchbar-info.date-format.mon-day-year")),
            ("%a. %d, %Y", self.plugin_base.lm.get("actions.touchbar-info.date-format.dow-day-year")),
            ("%a. %b. %d, %Y", self.plugin_base.lm.get("actions.touchbar-info.date-format.dow-mon-day-year")),
            ("%Y-%b-%d", self.plugin_base.lm.get("actions.touchbar-info.date-format.year-mon-day"))
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
            self.update_display()

    def on_show_seconds_toggled(self, switch, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["show_seconds"] = switch.get_active()
            self.set_settings(settings)
            self.update_display()

    def on_date_format_changed(self, combo, *args):
        settings = self.get_settings()
        if settings is not None:
            settings["date_format_idx"] = combo.get_selected()
            self.set_settings(settings)
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
            if isinstance(self.input_ident, Input.Touchscreen) or getattr(self.input_ident, "input_type", "") == "touchscreens":
                if hasattr(self.deck_controller, "get_touchscreen_image_size"):
                    size = self.deck_controller.get_touchscreen_image_size()
                    if size is not None:
                        return size
                return (800, 100)
            elif hasattr(self.deck_controller, "get_key_image_size"):
                size = self.deck_controller.get_key_image_size()
                if size is not None:
                    return size
        return (800, 100)

    def update_display(self) -> None:
        settings = self.get_settings() or {}
        use_24h = settings.get("use_24h", False)
        show_seconds = settings.get("show_seconds", False)
        date_format_idx = settings.get("date_format_idx", 0)

        fmt_str, _ = self.date_format_options[min(date_format_idx, len(self.date_format_options) - 1)]

        now = datetime.datetime.now()
        date_str = now.strftime(fmt_str)

        if use_24h:
            time_fmt = "%H:%M:%S" if show_seconds else "%H:%M"
        else:
            time_fmt = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
        
        time_str = now.strftime(time_fmt).lstrip("0") if not use_24h else now.strftime(time_fmt)

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

        is_touchscreen = isinstance(self.input_ident, Input.Touchscreen) or getattr(self.input_ident, "input_type", "") == "touchscreens"

        if is_touchscreen:
            # Save rendered image as page touchscreen background image
            temp_dir = os.path.join(self.plugin_base.PATH, "assets")
            os.makedirs(temp_dir, exist_ok=True)
            render_path = os.path.join(temp_dir, f"touchbar_render_{self.state}.png")

            try:
                image.save(render_path)
                self.page.set_background_image(self.input_ident, self.state, render_path, update=True)
            except Exception as e:
                log.error(f"Failed to set touchscreen background image: {e}")

            # Direct task push for hardware deck update
            if hasattr(self, "deck_controller") and self.deck_controller is not None:
                if hasattr(self.deck_controller, "deck") and hasattr(self.deck_controller.deck, "set_touchscreen_image"):
                    try:
                        bg = Image.new("RGB", image.size, (15, 16, 22))
                        if image.mode == "RGBA":
                            bg.paste(image, (0, 0), image)
                        else:
                            bg = image
                        
                        from StreamDeck.ImageHelpers import PILHelper
                        native_img = PILHelper.to_native_touchscreen_format(self.deck_controller.deck, bg)
                        self.deck_controller.media_player.add_touchscreen_task(native_img)
                    except Exception as e:
                        log.debug(f"Direct touchscreen task push exception: {e}")
        else:
            self.set_media(image=image, update=True)
