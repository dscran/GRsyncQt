"""The local destination folder: what is there, and where a download goes.

Names are compared case-insensitively, because macOS and Windows file systems
are. A camera file R0000001.JPG "name-matches" the local R0000001.JPG and the
collision names R0000001_<n>.JPG (n >= 2) that the app itself creates.
"""

import os
import re
import tempfile
from pathlib import Path

TEMP_PREFIX = ".grsync-qt-"
TEMP_SUFFIX = ".part"
FIRST_COLLISION_NUMBER = 2
COLLISION_NAME = re.compile(r"^(?P<stem>.+)_(?P<number>\d+)(?P<ext>\.[^.]*)$")


def base_name_of_collision(name: str) -> str | None:
    """Return 'stem.ext' for a collision name 'stem_<n>.ext' (n >= 2), else None."""
    match = COLLISION_NAME.match(name)
    if match is None or int(match["number"]) < FIRST_COLLISION_NUMBER:
        return None
    return match["stem"] + match["ext"]


def collision_name(file_name: str, number: int) -> str:
    stem, ext = os.path.splitext(file_name)
    return f"{stem}_{number}{ext}"


def is_temp_file(name: str) -> bool:
    return name.startswith(TEMP_PREFIX) and name.endswith(TEMP_SUFFIX)


class DestinationIndex:
    """A snapshot of the destination folder's files and their sizes."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._sizes: dict[str, int] = {}
        self._matches: dict[str, list[str]] = {}
        self.refresh()

    def refresh(self):
        """Scan the folder again; a missing folder counts as empty."""
        self._sizes = {}
        self._matches = {}
        try:
            entries = list(os.scandir(self.folder))
        except OSError:
            return
        for entry in entries:
            if entry.is_file() and not is_temp_file(entry.name):
                self._add(entry.name, entry.stat().st_size)

    def has_name_match(self, file_name: str) -> bool:
        """Whether any local file has the camera file's name or a collision name."""
        return bool(self._matches.get(file_name.casefold()))

    def is_present(self, file_name: str, size: int) -> bool:
        """Whether a name-matching local file has exactly this size."""
        names = self._matches.get(file_name.casefold(), [])
        return any(self._sizes[name] == size for name in names)

    def target_name(self, file_name: str) -> str:
        """Return a free name: the camera's, else the lowest free 'stem_<n>.ext'."""
        if file_name.casefold() not in self._sizes:
            return file_name
        number = FIRST_COLLISION_NUMBER
        while collision_name(file_name, number).casefold() in self._sizes:
            number += 1
        return collision_name(file_name, number)

    def _add(self, name: str, size: int):
        key = name.casefold()
        self._sizes[key] = size
        self._matches.setdefault(key, []).append(key)
        base_name = base_name_of_collision(key)
        if base_name is not None:
            self._matches.setdefault(base_name, []).append(key)


def create_temp_file(folder: Path) -> Path:
    """Create an empty '.grsync-qt-<random>.part' file in folder."""
    fd, path = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX, dir=folder)
    os.close(fd)
    return Path(path)


def remove_leftover_temp_files(folder: Path):
    """Delete temp files left behind by an earlier crash."""
    for path in Path(folder).glob(f"{TEMP_PREFIX}*{TEMP_SUFFIX}"):
        path.unlink(missing_ok=True)


def finalize(temp_path: Path, file_name: str) -> Path:
    """Move a finished temp file to a free name for file_name and return it.

    The name is picked from a fresh scan, so a file that appeared during the
    download is never overwritten.
    """
    index = DestinationIndex(temp_path.parent)
    target = temp_path.parent / index.target_name(file_name)
    os.replace(temp_path, target)
    return target


def is_writable(folder: Path) -> bool:
    """Whether a file can be created in folder."""
    try:
        temp_path = create_temp_file(folder)
    except OSError:
        return False
    temp_path.unlink(missing_ok=True)
    return True
