"""Download a plan of camera files into the destination folder, one at a time.

Per file: skip it if a name-matching local file has its size, else stream it
into a temp file, check the byte count, and move it to a free name. An HTTP
or local write error fails just that file. A connection error stops the plan,
and the remaining files are not attempted.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from grsync_qt.signals import emit_from_worker
from grsync_qt.camera import (
    CameraClient,
    CameraHttpError,
    CameraUnreachable,
    DownloadCancelled,
    DownloadResult,
)
from grsync_qt.destination import (
    DestinationIndex,
    create_temp_file,
    finalize,
    remove_leftover_temp_files,
)

PROGRESS_INTERVAL_SECONDS = 0.25
SPEED_WINDOW_SECONDS = 5.0

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadProgress:
    """A snapshot of a running download."""

    file_name: str
    file_number: int
    total_files: int
    bytes_done: int
    bytes_per_second: float
    seconds_remaining: float | None

    @property
    def position_text(self) -> str:
        return f"{self.file_number} of {self.total_files}"


@dataclass
class DownloadSummary:
    """How a download ended, file by file ('dir/file' paths)."""

    downloaded: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    not_in_format: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # path, reason
    not_attempted: list[str] = field(default_factory=list)
    was_cancelled: bool = False
    lost_connection: bool = False


class Downloader(QObject):
    """Runs download plans on a daemon thread; reports through signals."""

    progress = Signal(object)  # DownloadProgress
    file_done = Signal(str)  # path of a file downloaded or found present
    finished = Signal(object)  # DownloadSummary
    connection_lost = Signal(str)

    def __init__(self, base_url: str, parent: QObject | None = None):
        super().__init__(parent)
        self.base_url = base_url
        self._cancel_requested = threading.Event()
        self._is_running = False
        # Connected first, so other receivers of finished see is_running False.
        self.finished.connect(self._on_finished)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _on_finished(self, summary: "DownloadSummary"):
        self._is_running = False

    def start(
        self,
        files: list[str],
        folder: Path,
        known_sizes: dict[str, int] | None = None,
        not_in_format: int = 0,
    ):
        """Download files ('dir/file' paths) into folder, in order.

        known_sizes holds sizes already fetched from /info, keyed by path.
        """
        if self.is_running:
            raise RuntimeError("a download is already running")
        self._cancel_requested.clear()
        self._is_running = True
        run = PlanRun(self, files, Path(folder), dict(known_sizes or {}))
        run.summary.not_in_format = not_in_format
        threading.Thread(target=run.run, name="downloader", daemon=True).start()

    def cancel(self):
        self._cancel_requested.set()

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()


class SpeedMeter:
    """Bytes per second over a moving window."""

    def __init__(self, window_seconds: float = SPEED_WINDOW_SECONDS):
        self._window_seconds = window_seconds
        self._samples: deque[tuple[float, int]] = deque()

    def add(self, now: float, total_bytes: int):
        self._samples.append((now, total_bytes))
        while now - self._samples[0][0] > self._window_seconds:
            self._samples.popleft()

    def bytes_per_second(self) -> float:
        (start_time, start_bytes), (end_time, end_bytes) = (
            self._samples[0],
            self._samples[-1],
        )
        if end_time <= start_time:
            return 0.0
        return (end_bytes - start_bytes) / (end_time - start_time)


class PlanRun:
    """One download plan, run on the downloader's thread."""

    def __init__(self, downloader: Downloader, files, folder: Path, known_sizes):
        self.downloader = downloader
        self.files = files
        self.folder = folder
        self.known_sizes = known_sizes
        self.client = CameraClient(downloader.base_url)
        self.summary = DownloadSummary()
        self.speed = SpeedMeter()
        self.bytes_done = 0
        self.finished_sizes: list[int] = []
        self.last_progress_time = 0.0

    def run(self):
        remove_leftover_temp_files(self.folder)
        index = DestinationIndex(self.folder)
        for position, path in enumerate(self.files):
            should_continue = self._run_file(index, position, path)
            if not should_continue:
                self.summary.not_attempted.extend(self.files[position + 1 :])
                break
        emit_from_worker(self.downloader.finished, self.summary)

    def _run_file(self, index: DestinationIndex, position: int, path: str) -> bool:
        """Handle one file and return whether the plan goes on."""
        try:
            self._get_file(index, position, path)
        except DownloadCancelled:
            self.summary.was_cancelled = True
            self.summary.not_attempted.append(path)
            return False
        except CameraUnreachable as error:
            self.summary.lost_connection = True
            self.summary.failed.append((path, "connection to the camera lost"))
            emit_from_worker(self.downloader.connection_lost, str(error))
            return False
        except CameraHttpError as error:
            self.summary.failed.append((path, f"camera answered HTTP {error.status}"))
        except SizeMismatch as error:
            self.summary.failed.append((path, str(error)))
        except OSError as error:
            self.summary.failed.append(
                (path, f"write error: {error.strerror or error}")
            )
        return True

    def _get_file(self, index: DestinationIndex, position: int, path: str):
        if self.downloader.is_cancel_requested():
            raise DownloadCancelled(path)
        file_name = path.rsplit("/", 1)[-1]
        if index.has_name_match(file_name):
            size = self._known_size(path)
            if index.is_present(file_name, size):
                self.summary.already_present.append(path)
                emit_from_worker(self.downloader.file_done, path)
                return
        self._transfer(position, path, file_name)
        index.refresh()
        self.summary.downloaded.append(path)
        emit_from_worker(self.downloader.file_done, path)

    def _known_size(self, path: str) -> int:
        if path not in self.known_sizes:
            self.known_sizes[path] = self.client.info(path).size
        return self.known_sizes[path]

    def _transfer(self, position: int, path: str, file_name: str):
        temp_path = create_temp_file(self.folder)
        try:
            result = self._stream_to(temp_path, position, path, file_name)
            check_size(result, self.known_sizes.get(path))
            target = finalize(temp_path, file_name)
        finally:
            temp_path.unlink(missing_ok=True)
        self.finished_sizes.append(result.received_size)
        log.debug("downloaded %s to %s", path, target)

    def _stream_to(self, temp_path: Path, position: int, path: str, file_name: str):
        file_bytes = 0

        def write_chunk(chunk: bytes):
            nonlocal file_bytes
            output.write(chunk)
            file_bytes += len(chunk)
            self.bytes_done += len(chunk)
            self._report(position, path, file_name, file_bytes)

        with open(temp_path, "wb") as output:
            return self.client.download(
                path, write_chunk, self.downloader.is_cancel_requested
            )

    def _report(self, position: int, path: str, file_name: str, file_bytes: int):
        now = time.monotonic()
        self.speed.add(now, self.bytes_done)
        if now - self.last_progress_time < PROGRESS_INTERVAL_SECONDS:
            return
        self.last_progress_time = now
        bytes_per_second = self.speed.bytes_per_second()
        remaining = self._estimate_remaining_bytes(position, path, file_bytes)
        seconds_remaining = remaining / bytes_per_second if bytes_per_second else None
        progress = DownloadProgress(
            file_name=file_name,
            file_number=position + 1,
            total_files=len(self.files),
            bytes_done=self.bytes_done,
            bytes_per_second=bytes_per_second,
            seconds_remaining=seconds_remaining,
        )
        emit_from_worker(self.downloader.progress, progress)

    def _estimate_remaining_bytes(self, position: int, path: str, file_bytes: int):
        """Remaining bytes, guessing unknown sizes from the files seen so far."""
        known = list(self.known_sizes.values()) + self.finished_sizes
        average_size = sum(known) / len(known) if known else file_bytes
        current_size = self.known_sizes.get(path, max(average_size, file_bytes))
        later_files = self.files[position + 1 :]
        later_bytes = sum(self.known_sizes.get(p, average_size) for p in later_files)
        return max(current_size - file_bytes, 0) + later_bytes


class SizeMismatch(Exception):
    """Fewer or more bytes arrived than the camera announced."""


def check_size(result: DownloadResult, expected_size: int | None):
    """Raise SizeMismatch unless the received bytes match every announced size."""
    for announced_size in (result.announced_size, expected_size):
        if announced_size is not None and announced_size != result.received_size:
            raise SizeMismatch(
                f"size mismatch: {result.received_size} of {announced_size} bytes"
                " arrived"
            )
