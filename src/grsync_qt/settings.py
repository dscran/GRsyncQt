"""Settings kept across sessions: destination, format and window layout.

Nothing else is stored; in particular no camera data and no thumbnails.
"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from grsync_qt.shots import DownloadFormat

ORGANIZATION = APPLICATION = "grsync-qt"
DESTINATION_KEY = "destination"
FORMAT_KEY = "format"
GEOMETRY_KEY = "geometry"
SPLITTER_KEY = "splitter"
THUMBNAIL_SIZE_KEY = "thumbnail_size"
DEFAULT_THUMBNAIL_SIZE = 160


class Settings:
    """Typed access to the app's QSettings."""

    def __init__(self, settings: QSettings | None = None):
        # An INI file on every platform, so its content can be checked.
        self._settings = settings or QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            ORGANIZATION,
            APPLICATION,
        )

    @property
    def destination(self) -> Path | None:
        value = self._settings.value(DESTINATION_KEY)
        return Path(value) if value else None

    @destination.setter
    def destination(self, folder: Path):
        self._settings.setValue(DESTINATION_KEY, str(folder))

    @property
    def download_format(self) -> DownloadFormat:
        value = self._settings.value(FORMAT_KEY, DownloadFormat.JPG_RAW.value)
        try:
            return DownloadFormat(value)
        except ValueError:
            return DownloadFormat.JPG_RAW

    @download_format.setter
    def download_format(self, download_format: DownloadFormat):
        self._settings.setValue(FORMAT_KEY, download_format.value)

    @property
    def geometry(self) -> QByteArray | None:
        return self._settings.value(GEOMETRY_KEY)

    @geometry.setter
    def geometry(self, geometry: QByteArray):
        self._settings.setValue(GEOMETRY_KEY, geometry)

    @property
    def splitter_state(self) -> QByteArray | None:
        return self._settings.value(SPLITTER_KEY)

    @splitter_state.setter
    def splitter_state(self, state: QByteArray):
        self._settings.setValue(SPLITTER_KEY, state)

    @property
    def thumbnail_size(self) -> int:
        value = self._settings.value(THUMBNAIL_SIZE_KEY, DEFAULT_THUMBNAIL_SIZE)
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULT_THUMBNAIL_SIZE

    @thumbnail_size.setter
    def thumbnail_size(self, size: int):
        self._settings.setValue(THUMBNAIL_SIZE_KEY, size)

    @property
    def file_path(self) -> Path:
        return Path(self._settings.fileName())

    def sync(self):
        self._settings.sync()
