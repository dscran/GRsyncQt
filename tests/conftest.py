import os

# Forced (not setdefault): a desktop session may set QT_QPA_PLATFORM=xcb, and the
# tests must never open real windows. Must happen before Qt creates the app.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest  # noqa: E402
from fake_camera import FakeCamera  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402


@pytest.fixture(autouse=True)
def settings_dir(tmp_path_factory):
    """Keep every test's settings out of the user's real configuration."""
    folder = tmp_path_factory.mktemp("settings")
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder)
    )
    return folder


@pytest.fixture
def fake_camera():
    """A running fake camera with the default card."""
    camera = FakeCamera().start()
    yield camera
    camera.stop()
