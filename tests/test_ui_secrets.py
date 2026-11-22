"""The camera's secrets must never reach the window, the log or a file."""

import logging

from fake_camera import SECRET_PROPS, SHOT_GPS_SECRET
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget
from ui_helpers import (
    TIMEOUT_MS,
    connect,
    make_current,
    open_window,
    wait_for_preview,
)


def visible_texts(widget: QWidget) -> list[str]:
    texts = [widget.windowTitle(), widget.toolTip(), widget.statusTip()]
    for getter in ("text", "currentText", "placeholderText"):
        if hasattr(widget, getter):
            value = getattr(widget, getter)()
            texts.append(value if isinstance(value, str) else "")
    for action in widget.actions():
        texts += [action.text(), action.toolTip(), action.statusTip()]
    return texts


def all_texts(app: QApplication) -> str:
    return "\n".join(t for w in app.allWidgets() for t in visible_texts(w))


def test_secrets_never_exposed(fake_camera, qtbot, caplog, monkeypatch, tmp_path):
    caplog.set_level(logging.DEBUG)  # what --verbose sets up
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    window = open_window(fake_camera.url, qtbot)
    connect(window, qtbot)
    window.grid.selectAll()
    make_current(window, 0)
    wait_for_preview(window, qtbot)
    window.download_action.trigger()
    qtbot.waitUntil(lambda: not window.downloader.is_running, timeout=TIMEOUT_MS)

    texts = all_texts(QApplication.instance())
    window.close()
    settings_text = window.settings.file_path.read_text()

    assert "Battery 87 %" in texts  # the props were read and shown
    assert "GET" in caplog.text
    for secret in [*SECRET_PROPS.values(), SHOT_GPS_SECRET]:
        assert secret not in texts
        assert secret not in caplog.text
        assert secret not in settings_text
