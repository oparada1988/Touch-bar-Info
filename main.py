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