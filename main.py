"""
TouchPulse Plugin for StreamController
======================================
Author: Oscar Parada
Repository: https://github.com/oparada1988/TouchPulse
Description:
    Modular multi-widget dashboard plugin built exclusively for the Elgato Stream Deck +
    touch bar LCD (800x100 canvas). Provides hardware dial integration, MPRIS media control
    with organic audio visualizer spectrums, live system monitor graphs, and weather info.
"""

# Import gtk modules
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
from loguru import logger as log
import weakref

# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.DeckManagement.InputIdentifier import Input

# Import actions
from .actions.TouchBarInfoAction.TouchBarInfoAction import TouchBarInfoAction

class TouchBarInfoPlugin(PluginBase):
    """
    Main plugin registration entry point for StreamController.
    Binds TouchBarInfoAction exclusively to Input.Touchscreen.
    """
    def __init__(self):
        super().__init__()
        # Expose locale manager alias for localization lookups
        self.lm = self.locale_manager
        self.has_plugin_settings = True
        self.active_actions = weakref.WeakSet()

        # Register TouchPulse action exclusively for Touchscreen (Stream Deck + LCD Strip)
        self.touchbar_info_holder = ActionHolder(
            plugin_base = self,
            action_base = TouchBarInfoAction,
            action_id = "com_oparada_TouchBarInfo::TouchBarInfoAction",
            action_name = "TouchPulse",
            action_support = {
                Input.Key: ActionInputSupport.UNSUPPORTED,
                Input.Dial: ActionInputSupport.UNSUPPORTED,
                Input.Touchscreen: ActionInputSupport.SUPPORTED
            }
        )
        self.add_action_holder(self.touchbar_info_holder)

        # Register plugin metadata with StreamController PluginManager
        self.register(
            plugin_name = "TouchPulse",
            github_repo = "https://github.com/oparada1988/TouchPulse",
            plugin_version = "1.0.0",
            app_version = "1.5.0-beta"
        )

    def get_settings_area(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Performance & Display",
            description="Configure display refresh rate and hardware animation performance."
        )

        settings = self.get_settings()
        current_fps = settings.get("animation_fps", 18)

        # 1. Refresh Rate Combo Row (18 FPS vs 30 FPS)
        fps_model = Gtk.StringList.new([
            "18 FPS (Recommended - Smooth & Glitch-Free)",
            "30 FPS (High Refresh Rate - High USB Load)"
        ])
        fps_row = Adw.ComboRow(
            title="Animation Refresh Rate",
            subtitle="18 FPS prevents USB HID buffer overrun and LCD visual artifacts on Stream Deck +",
            model=fps_model
        )
        fps_row.set_selected(0 if current_fps == 18 else 1)

        def on_fps_selected(row, param):
            selected_idx = row.get_selected()
            new_fps = 18 if selected_idx == 0 else 30
            st = self.get_settings()
            st["animation_fps"] = new_fps
            self.set_settings(st)
            log.info(f"TouchPulse: Global animation FPS set to {new_fps}")
            for action in list(self.active_actions):
                if hasattr(action, "on_fps_setting_changed"):
                    action.on_fps_setting_changed(new_fps)

        fps_row.connect("notify::selected", on_fps_selected)
        group.add(fps_row)

        return group