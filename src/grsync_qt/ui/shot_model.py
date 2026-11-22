"""The list of shots on the card, with what is known about each of them.

Everything fetched from the camera (/info and thumbnails) is cached here for
the session, keyed by file path, so a shot is never fetched twice.
"""

from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QImage

from grsync_qt.camera import FileInfo
from grsync_qt.destination import DestinationIndex
from grsync_qt.images import apply_orientation, fit_within
from grsync_qt.request_queue import THUMBNAIL_MAX_SIDE, info_key, thumb_key, view_key
from grsync_qt.shots import DNG, JPG, MOV, Shot, split_path
from grsync_qt.ui.formatting import format_exposure

SHOT_ROLE = Qt.ItemDataRole.UserRole + 1
IMAGE_ROLE = Qt.ItemDataRole.UserRole + 2
BADGES_ROLE = Qt.ItemDataRole.UserRole + 3
EXPOSURE_ROLE = Qt.ItemDataRole.UserRole + 4

JPG_THUMBNAIL_SIDE = 160  # the camera's JPG thumbnail is 160x120

BADGE_LABELS = {JPG: "JPG", DNG: "RAW", MOV: "MOV"}
UNKNOWN_ORIENTATION = 0


def file_name_of(path: str) -> str:
    return path.rsplit("/", 1)[-1]


class ShotModel(QAbstractListModel):
    """Rows of shots; caches /info and thumbnails; knows what is downloaded."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._shots: list[Shot] = []
        self._rows_by_path: dict[str, int] = {}
        self.infos: dict[str, FileInfo] = {}
        self._thumbnails: dict[str, QImage] = {}
        self._upright: dict[str, QImage] = {}
        self._upright_large: dict[str, QImage] = {}
        self.previews: dict[str, QImage] = {}
        self.thumbnail_side = JPG_THUMBNAIL_SIDE
        self._failed_keys: set[str] = set()
        self._destination: DestinationIndex | None = None

    # Qt model interface

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._shots)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        shot = self._shots[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return shot.stem
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(filter(None, [shot.stem, self.exposure_text(shot)]))
        if role == SHOT_ROLE:
            return shot
        if role == IMAGE_ROLE:
            return self.upright_thumbnail(shot)
        if role == BADGES_ROLE:
            return self.badges(shot)
        if role == EXPOSURE_ROLE:
            return self.exposure_text(shot)
        return None

    # Shots

    @property
    def shots(self) -> list[Shot]:
        return self._shots

    def set_shots(self, shots: list[Shot]):
        """Replace the shots; cached details of files still on the card stay."""
        self.beginResetModel()
        self._shots = list(shots)
        self._rows_by_path = {
            path: row for row, shot in enumerate(shots) for path in shot.files.values()
        }
        self.endResetModel()

    def row_of_key(self, shot_key: str) -> int | None:
        for row, shot in enumerate(self._shots):
            if shot.key == shot_key:
                return row
        return None

    # Requests and results

    def wanted_keys(self, rows: list[int]) -> list[str]:
        """Request keys still needed to show these rows, in row order."""
        keys = []
        for row in rows:
            keys.extend(self._missing_keys(self._shots[row]))
        return [key for key in keys if key not in self._failed_keys]

    def _missing_keys(self, shot: Shot) -> list[str]:
        source = shot.thumbnail_source
        keys = []
        if source not in self.infos:
            keys.append(info_key(source))
        keys.extend(self._missing_image_keys(source))
        # Other files only need a size if a local file could be their copy.
        for path in shot.other_files:
            if path not in self.infos and self._has_name_match(path):
                keys.append(info_key(path))
        return keys

    def _missing_image_keys(self, source: str) -> list[str]:
        if self._uses_preview_image(source):
            return [] if source in self.previews else [view_key(source)]
        return [] if source in self._thumbnails else [thumb_key(source)]

    def _uses_preview_image(self, source: str) -> bool:
        """Large JPG thumbnails come from the 720x480 preview, so they stay sharp."""
        is_large = self.thumbnail_side > JPG_THUMBNAIL_SIDE
        is_jpg = split_path(source)[2] == JPG
        return is_large and is_jpg and view_key(source) not in self._failed_keys

    def set_thumbnail_side(self, side: int):
        """Show thumbnails of this size; above 160 px JPGs need their preview."""
        self.thumbnail_side = side
        self._emit_all_changed()

    def handle_result(self, key: str, result: object):
        """Store an info or thumb result from the request queue."""
        kind, _, path = key.partition(":")
        if kind == "info":
            self.infos[path] = result
        elif kind == "thumb":
            self._thumbnails[path] = result
        elif kind == "view":
            self.previews[path] = result
        else:
            return
        self._upright.pop(path, None)
        self._upright_large.pop(path, None)
        self._emit_changed(path)

    def handle_failure(self, key: str, reason: str = ""):
        """Remember a failed info or image request, so it isn't asked again."""
        kind, _, path = key.partition(":")
        if kind not in ("info", "thumb", "view"):
            return
        self._failed_keys.add(key)
        self._emit_changed(path)

    def _emit_changed(self, path: str):
        row = self._rows_by_path.get(path)
        if row is not None:
            index = self.index(row)
            self.dataChanged.emit(index, index)

    # Thumbnails

    def upright_thumbnail(self, shot: Shot) -> QImage | None:
        """The shot's grid image turned upright; None while it is loading.

        Until a large thumbnail's preview arrives, the small one stands in.
        """
        source = shot.thumbnail_source
        is_info_settled = source in self.infos or info_key(source) in self._failed_keys
        if not is_info_settled:
            return None
        if self._uses_preview_image(source) and source in self.previews:
            return self._cached_upright(self._upright_large, source, self.previews)
        if source in self._thumbnails:
            return self._cached_upright(self._upright, source, self._thumbnails)
        return None

    def _cached_upright(self, cache: dict, source: str, images: dict) -> QImage:
        if source not in cache:
            info = self.infos.get(source)
            orientation = info.orientation if info else UNKNOWN_ORIENTATION
            image = fit_within(images[source], THUMBNAIL_MAX_SIDE)
            cache[source] = apply_orientation(image, orientation)
        return cache[source]

    def exposure_text(self, shot: Shot) -> str:
        """ISO, aperture, shutter speed and compensation; '' if not known."""
        info = self.infos.get(shot.thumbnail_source)
        return format_exposure(info) if info else ""

    # Downloaded markers

    def set_destination(self, folder: Path | None):
        """Judge the downloaded markers against another folder."""
        self._destination = DestinationIndex(folder) if folder else None
        self._emit_all_changed()

    def refresh_destination(self):
        """Scan the destination again, e.g. after a file was downloaded."""
        if self._destination is not None:
            self._destination.refresh()
        self._emit_all_changed()

    def _emit_all_changed(self):
        if self._shots:
            self.dataChanged.emit(self.index(0), self.index(len(self._shots) - 1))

    def _has_name_match(self, path: str) -> bool:
        if self._destination is None:
            return False
        return self._destination.has_name_match(file_name_of(path))

    def is_downloaded(self, path: str) -> bool:
        """Whether a local file has this file's name and size (size known)."""
        info = self.infos.get(path)
        if self._destination is None or info is None:
            return False
        return self._destination.is_present(file_name_of(path), info.size)

    def badges(self, shot: Shot) -> list[tuple[str, bool]]:
        """(label, is_downloaded) for each file of the shot: JPG, RAW, MOV."""
        return [
            (BADGE_LABELS[extension], self.is_downloaded(shot.files[extension]))
            for extension in (JPG, DNG, MOV)
            if extension in shot.files
        ]
