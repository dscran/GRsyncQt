from pathlib import Path

from PySide6.QtCore import QByteArray

from grsync_qt.settings import Settings
from grsync_qt.shots import DownloadFormat


def test_values_survive_a_new_settings_object(settings_dir):
    settings = Settings()
    settings.destination = Path("/photos/GR")
    settings.download_format = DownloadFormat.RAW
    settings.geometry = QByteArray(b"geometry")
    settings.splitter_state = QByteArray(b"splitter")
    settings.thumbnail_size = 240
    settings.sync()

    reloaded = Settings()

    assert reloaded.destination == Path("/photos/GR")
    assert reloaded.download_format == DownloadFormat.RAW
    assert reloaded.geometry == QByteArray(b"geometry")
    assert reloaded.splitter_state == QByteArray(b"splitter")
    assert reloaded.thumbnail_size == 240
    assert reloaded.file_path == settings_dir / "grsync-qt" / "grsync-qt.ini"
    assert reloaded.file_path.exists()


def test_defaults(settings_dir):
    settings = Settings()

    assert settings.destination is None
    assert settings.download_format == DownloadFormat.JPG_RAW
    assert settings.thumbnail_size == 160
