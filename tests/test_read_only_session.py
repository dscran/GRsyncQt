"""A whole session must send the camera nothing but GET requests."""

import pytest
from fake_camera import FakeCamera, large_card
from PySide6.QtWidgets import QFileDialog
from ui_helpers import (
    TIMEOUT_MS,
    connect,
    make_current,
    open_window,
    select_rows,
    wait_for_preview,
)

from grsync_qt.shots import DownloadFormat


@pytest.fixture
def camera():
    camera = FakeCamera(card=large_card(200)).start()
    yield camera
    camera.stop()


def test_whole_session_is_get_only(camera, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    window = open_window(camera.url, qtbot)
    connect(window, qtbot)

    window.grid.scrollTo(window.model.index(60))
    qtbot.wait(300)
    make_current(window, 60)
    wait_for_preview(window, qtbot)
    window.format_combo.setCurrentIndex(
        window.format_combo.findData(DownloadFormat.JPG_RAW)
    )
    select_rows(window, [58, 59, 60])
    window.download_action.trigger()
    qtbot.waitUntil(lambda: not window.downloader.is_running, timeout=TIMEOUT_MS)
    window.close()

    downloaded = sorted(p.name for p in tmp_path.iterdir())
    assert len(downloaded) == 6 and downloaded[0].endswith(".DNG")
    assert {entry.method for entry in camera.log} == {"GET"}
    assert not [e for e in camera.log if e.path.startswith("/v1/device")]
