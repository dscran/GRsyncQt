"""Shared helpers for tests that drive the main window."""

from grsync_qt.settings import Settings
from grsync_qt.ui.main_window import ConnectionState, MainWindow

TIMEOUT_MS = 10000


def open_window(base_url: str, qtbot) -> MainWindow:
    window = MainWindow(base_url, Settings())
    qtbot.addWidget(window)
    window.resize(900, 700)
    window.show()
    qtbot.waitExposed(window)
    return window


def connect(window, qtbot, expected=ConnectionState.CONNECTED):
    window.connect_camera()
    qtbot.waitUntil(lambda: window.state == expected, timeout=TIMEOUT_MS)


def select_rows(window, rows):
    selection = window.grid.selectionModel()
    for row in rows:
        selection.select(window.model.index(row), selection.SelectionFlag.Select)


def selected_keys(window) -> list[str]:
    return [shot.key for shot in window.grid.selected_shots()]


def make_current(window, row):
    """Make a row the current shot, as a click on it does."""
    selection = window.grid.selectionModel()
    selection.setCurrentIndex(
        window.model.index(row), selection.SelectionFlag.ClearAndSelect
    )


def wait_for_preview(window, qtbot):
    pane = window.preview_pane
    qtbot.waitUntil(lambda: pane.image is not None, timeout=TIMEOUT_MS)
    return pane
