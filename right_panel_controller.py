"""Right-side 200px expansion controller for KSPECGUI_expand.ui (PySide6).

Call setup_right_panel(self) immediately after self.ui.setupUi(self),
or call setup_right_panel(self, self.ui) for a separate generated UI object.
"""
from PySide6.QtCore import Qt

PANEL_WIDTH = 200


def setup_right_panel(window, ui=None):
    ui = window if ui is None else ui
    panel = ui.rightPanel
    button = ui.toolButton_expand

    panel.setMinimumWidth(0)
    panel.setMaximumWidth(0)
    button.setChecked(False)
    button.setArrowType(Qt.RightArrow)

    def toggle(checked):
        if checked:
            # Enlarge outer window first: existing controls retain their space.
            window.resize(window.width() + PANEL_WIDTH, window.height())
            panel.setMinimumWidth(PANEL_WIDTH)
            panel.setMaximumWidth(PANEL_WIDTH)
            button.setArrowType(Qt.LeftArrow)
        else:
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(0)
            window.resize(max(window.minimumWidth(), window.width() - PANEL_WIDTH), window.height())
            button.setArrowType(Qt.RightArrow)

    button.toggled.connect(toggle)


if __name__ == '__main__':
    # Standalone demonstration; install PySide6 first if necessary.
    import sys
    from pathlib import Path
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtUiTools import QUiLoader
    app = QApplication(sys.argv)
    ui_file = Path(__file__).with_name('KSPECGUI_expand.ui')
    window = QUiLoader().load(str(ui_file))
    if window is None:
        raise RuntimeError(f'Could not load {ui_file}')
    setup_right_panel(window)
    window.show()
    sys.exit(app.exec())
