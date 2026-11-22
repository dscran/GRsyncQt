"""One worker thread for all small camera requests, served in priority order.

The camera answers one request at a time, so one worker is all it takes.
Requests are named by keys that say what to fetch:

- "connect": camera properties, then the listing -> (CameraInfo, list of paths)
- "info:<dir/file>": the file's /info -> FileInfo
- "thumb:<dir/file>": its thumbnail, decoded, letterbox trimmed, scaled -> QImage
- "view:<dir/file>": its preview image, decoded -> QImage

Grid requests follow `set_wanted`, which reorders them and drops the ones no
longer wanted. "connect" and preview requests go before them. A connection
error pauses the queue with its pending work kept, until `resume` or
`connect_camera` is called.
"""

import logging
import threading
from collections import deque

from PySide6.QtCore import QObject, Signal

from grsync_qt.signals import emit_from_worker
from grsync_qt.camera import CameraClient, CameraError, CameraUnreachable
from grsync_qt.images import decode, prepare_thumbnail
from grsync_qt.shots import JPG, split_path

CONNECT_KEY = "connect"
THUMBNAIL_MAX_SIDE = 320  # the largest grid thumbnail

log = logging.getLogger(__name__)


def info_key(path: str) -> str:
    return f"info:{path}"


def thumb_key(path: str) -> str:
    return f"thumb:{path}"


def view_key(path: str) -> str:
    return f"view:{path}"


def is_urgent_key(key: str) -> bool:
    return key == CONNECT_KEY or key.startswith("view:")


class RequestQueue(QObject):
    """Serves keyed camera requests on a daemon thread; results come as signals."""

    result_ready = Signal(str, object)  # key, result
    request_failed = Signal(str, str)  # key, reason (an HTTP error or bad answer)
    connection_lost = Signal(str)  # reason

    def __init__(self, base_url: str, parent: QObject | None = None):
        super().__init__(parent)
        self._client = CameraClient(base_url)
        self._condition = threading.Condition()
        self._urgent: deque[str] = deque()
        self._preview_keys: list[str] = []
        self._wanted: list[str] = []
        self._in_flight: str | None = None
        self._is_paused = False
        self._is_stopped = False
        threading.Thread(target=self._run, name="request-queue", daemon=True).start()

    def connect_camera(self):
        """Fetch props and listing before anything else, and resume if paused."""
        with self._condition:
            if CONNECT_KEY in self._urgent:
                self._urgent.remove(CONNECT_KEY)
            self._urgent.appendleft(CONNECT_KEY)
            self._is_paused = False
            self._condition.notify()

    def request_preview(self, keys: list[str]):
        """Fetch these keys before any grid request.

        They replace the keys of the previous preview request that are still
        pending, so stepping quickly through shots doesn't queue them all.
        """
        with self._condition:
            for key in self._preview_keys:
                if key in self._urgent:
                    self._urgent.remove(key)
            self._preview_keys = [key for key in keys if key != self._in_flight]
            self._urgent.extend(self._preview_keys)
            self._condition.notify()

    def set_wanted(self, keys_in_order: list[str]):
        """Replace the grid requests: serve these keys in this order, drop others."""
        with self._condition:
            self._wanted = [key for key in keys_in_order if key != self._in_flight]
            self._condition.notify()

    def pause(self):
        """Stop sending requests (e.g. the downloader lost the camera)."""
        with self._condition:
            self._is_paused = True

    def resume(self):
        with self._condition:
            self._is_paused = False
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._is_stopped = True
            self._condition.notify()

    def _run(self):
        while (key := self._next_key()) is not None:
            self._serve(key)

    def _next_key(self) -> str | None:
        """Wait for work and take the next key; None once stopped."""
        with self._condition:
            while not self._is_stopped and (self._is_paused or not self._has_work()):
                self._condition.wait()
            if self._is_stopped:
                return None
            if self._urgent:
                self._in_flight = self._urgent.popleft()
            else:
                self._in_flight = self._wanted.pop(0)
            # A key can be both a preview and a grid request (large thumbnails).
            if self._in_flight in self._wanted:
                self._wanted.remove(self._in_flight)
            return self._in_flight

    def _has_work(self) -> bool:
        return bool(self._urgent or self._wanted)

    def _serve(self, key: str):
        try:
            result = self._fetch(key)
        except CameraUnreachable as error:
            log.debug("request %s: %s", key, error)
            self._pause_with(key)
            emit_from_worker(self.connection_lost, str(error))
        except CameraError as error:
            log.debug("request %s: %s", key, error)
            self._finish()
            emit_from_worker(self.request_failed, key, str(error))
        else:
            self._finish()
            emit_from_worker(self.result_ready, key, result)

    def _finish(self):
        with self._condition:
            self._in_flight = None

    def _pause_with(self, key: str):
        """Pause and keep the failed key, so it is retried after resuming."""
        with self._condition:
            self._in_flight = None
            self._is_paused = True
            if is_urgent_key(key):
                self._urgent.appendleft(key)
            else:
                self._wanted.insert(0, key)

    def _fetch(self, key: str) -> object:
        if key == CONNECT_KEY:
            return self._client.props(), self._client.listing()
        kind, path = key.split(":", 1)
        if kind == "info":
            return self._client.info(path)
        if kind == "thumb":
            return self._fetch_thumbnail(path)
        if kind == "view":
            return decode(self._client.image(path, "view"))
        raise ValueError(f"unknown request key {key!r}")

    def _fetch_thumbnail(self, path: str):
        data = self._client.image(path, "thumb")
        # Only the JPG thumbnail comes letterboxed; DNG/MOV get their preview.
        has_letterbox = split_path(path)[2] == JPG
        return prepare_thumbnail(data, has_letterbox, THUMBNAIL_MAX_SIDE)
