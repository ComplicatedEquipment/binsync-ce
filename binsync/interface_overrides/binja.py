import logging
from collections import defaultdict

from libbs.plugin_installer import PluginInstaller
from libbs.decompilers.binja.interface import BinjaInterface

from binsync.controller import BSController

l = logging.getLogger(__name__)


def _load_binja_ui_components():
    try:
        from binaryninjaui import (
            UIAction,
            UIActionHandler,
            Menu,
            SidebarWidget,
            SidebarWidgetType,
            Sidebar,
        )
    except Exception as exc:
        l.warning("BinSync BN UI unavailable during binaryninjaui import: %s", exc)
        return None

    try:
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QVBoxLayout
    except Exception as exc:
        l.warning("BinSync BN UI unavailable during PySide6 import: %s", exc)
        return None

    try:
        from binsync.ui.control_panel import ControlPanel
        from binsync.ui.config_dialog import ConfigureBSDialog
    except Exception as exc:
        l.warning("BinSync BN UI unavailable during BinSync UI import: %s", exc)
        return None

    class BinSyncSidebarWidget(SidebarWidget):
        def __init__(self, bv, bs_interface, name="BinSync"):
            super().__init__(name)
            self._controller = bs_interface.controllers[bv]
            self._controller.bv = bv
            self._widget = ControlPanel(self._controller)

            layout = QVBoxLayout()
            layout.addWidget(self._widget)
            self.setLayout(layout)

    class BinSyncSidebarWidgetType(SidebarWidgetType):
        def __init__(self, bn_plugin):
            binsync_files = PluginInstaller.find_pkg_files("binsync")
            if not binsync_files or not binsync_files.exists():
                raise FileNotFoundError("Failed to find the BinSync package! Is your install corrupted?")

            bs_img_path = binsync_files / "stub_files" / "binsync_binja_logo.png"
            if not bs_img_path.exists():
                raise FileNotFoundError("Could not find BinSync logo image!")

            self._bs_logo = QImage(str(bs_img_path))
            self.plugin = bn_plugin
            super().__init__(self._bs_logo, "BinSync")

        def createWidget(self, frame, data):
            return BinSyncSidebarWidget(data, self.plugin)

    return {
        "UIAction": UIAction,
        "UIActionHandler": UIActionHandler,
        "Menu": Menu,
        "Sidebar": Sidebar,
        "BinSyncSidebarWidgetType": BinSyncSidebarWidgetType,
        "ConfigureBSDialog": ConfigureBSDialog,
    }


class BinjaBSInterface(BinjaInterface):
    """
    This is fairly complicated due to the way you make plugins in Binary Ninja. Every plugin is supposed to be aware
    of BV, which it uses to interact with the BN core. This BS Interface it to first create a UI that loads into
    binary ninja regardless of what binary you are interacting with. Then, inside the config launcher a new
    BS Interface is created to watch artifacts for THAT specific BN BV.
    """

    def __init__(self, *args, **kwargs):
        self.controllers = defaultdict(BSController)
        self.sidebar_widget_type = None
        self._ui_components = None
        self._ui_import_failed = False
        super().__init__(*args, **kwargs)

    def _get_ui_components(self):
        if self._ui_components is not None:
            return self._ui_components

        if self._ui_import_failed:
            return None

        self._ui_components = _load_binja_ui_components()
        self._ui_import_failed = self._ui_components is None
        return self._ui_components

    def _init_gui_components(self, *args, **kwargs):
        if not super()._init_gui_components(*args, **kwargs):
            return False

        ui_components = self._get_ui_components()
        if ui_components is None:
            return False

        configure_binsync_id = "BinSync: Configure..."
        ui_components["UIAction"].registerAction(configure_binsync_id)
        ui_components["UIActionHandler"].globalActions().bindAction(
            configure_binsync_id, ui_components["UIAction"](self._launch_bs_config)
        )
        ui_components["Menu"].mainMenu("Plugins").addAction(configure_binsync_id, "BinSync")

        self.sidebar_widget_type = ui_components["BinSyncSidebarWidgetType"](self)
        ui_components["Sidebar"].addSidebarWidgetType(self.sidebar_widget_type)
        return True

    def _launch_bs_config(self, bn_context):
        ui_components = self._get_ui_components()
        if ui_components is None:
            self.warning("BinSync UI is unavailable; skipping config dialog launch.")
            return

        current_view = bn_context.context.getCurrentView()
        if current_view is None:
            self.warning("BinSync configure requested without an active BinaryView.")
            self.gui_popup_text("Open a binary view before configuring BinSync.", title="BinSync")
            return

        bv = current_view.getData()
        if bv is None:
            self.warning("BinSync configure requested without BinaryView data.")
            self.gui_popup_text("Open a binary view before configuring BinSync.", title="BinSync")
            return

        bs_controller = self.controllers[bv]

        # exit early if we already configured
        if bs_controller.check_client() and bs_controller.deci.bv is not None:
            return

        # configure
        self.bv = bv
        bs_controller.deci.bv = bv
        dialog = ui_components["ConfigureBSDialog"](bs_controller)
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec_()

        # if the config was successful start the artifact watchers
        if bs_controller.check_client():
            bs_controller.deci.start_artifact_watchers()
