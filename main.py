# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.DeckManagement.InputIdentifier import Input

# Import actions
from .actions.TouchBarInfoAction.TouchBarInfoAction import TouchBarInfoAction

class TouchBarInfoPlugin(PluginBase):
    def __init__(self):
        super().__init__()
        # Expose locale manager alias
        self.lm = self.locale_manager

        ## Register action exclusively for Touchscreen (Stream Deck Plus Touch Bar)
        self.touchbar_info_holder = ActionHolder(
            plugin_base = self,
            action_base = TouchBarInfoAction,
            action_id = "com_core447_TouchBarInfo::TouchBarInfoAction",
            action_name = "Touch Bar Info",
            action_support = {
                Input.Key: ActionInputSupport.UNSUPPORTED,
                Input.Dial: ActionInputSupport.UNSUPPORTED,
                Input.Touchscreen: ActionInputSupport.SUPPORTED
            }
        )
        self.add_action_holder(self.touchbar_info_holder)

        # Register plugin
        self.register(
            plugin_name = "Touch Bar Info",
            github_repo = "https://github.com/oparada1988/Touch-bar-Info",
            plugin_version = "1.0.0",
            app_version = "1.5.0-beta"
        )