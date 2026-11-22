"""HTTP client for the Ricoh GR III / GR IIIx camera API.

The client is read-only by construction: `_get` is the only method that sends
anything, so no HEAD, POST or other request can reach the camera. Camera
properties contain secrets (the Wi-Fi password among them), so the raw props
never leave this module and response bodies are never logged.

A requests.Session isn't thread-safe: use one client per worker thread.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

SUPPORTED_MODELS = frozenset({"RICOH GR III", "RICOH GR IIIx"})
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_SIZE = 256 * 1024
UNKNOWN_ORIENTATION = 0
BROKEN_TRANSFER_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

log = logging.getLogger(__name__)


class CameraError(Exception):
    """Base class of all camera errors."""


class CameraUnreachable(CameraError):
    """The camera didn't answer, or the connection broke off."""


class UnsupportedCamera(CameraError):
    """The address answered, but not as a supported camera."""

    def __init__(self, model: str | None):
        self.model = model
        if model:
            super().__init__(f"Not a supported camera: {model}")
        else:
            super().__init__("Not a supported camera: no camera model reported")


class CameraHttpError(CameraError):
    """The camera answered a request with an error status."""

    def __init__(self, status: int, path: str):
        self.status = status
        super().__init__(f"HTTP {status} for {path}")


class DownloadCancelled(CameraError):
    """The download was cancelled by the caller."""


@dataclass(frozen=True)
class CameraInfo:
    """The non-secret camera properties the app uses."""

    model: str
    battery: int | None
    firmware: str


@dataclass(frozen=True)
class FileInfo:
    """Details of one file on the card, from its /info."""

    size: int
    orientation: int
    datetime: str
    # Exposure as the camera reports it: f-number, shutter speed as
    # "numerator.denominator" seconds, ISO (or "auto"), compensation in EV.
    aperture: str = ""
    shutter_speed: str = ""
    iso: str = ""
    exposure_compensation: str = ""


@dataclass(frozen=True)
class DownloadResult:
    announced_size: int | None
    received_size: int


class CameraClient:
    """Read-only access to one camera at base_url."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"
        self._session = requests.Session()
        # Desktop proxy settings must not swallow the camera's private address.
        self._session.trust_env = False

    def props(self) -> CameraInfo:
        """Return the camera's model, battery and firmware.

        Raises UnsupportedCamera if the answer isn't from a GR III or IIIx.
        """
        props = self._get_props()
        model = props.get("model")
        if model not in SUPPORTED_MODELS:
            raise UnsupportedCamera(model if isinstance(model, str) else None)
        return CameraInfo(
            model=model,
            battery=props.get("battery"),
            firmware=str(props.get("firmwareVersion", "")),
        )

    def listing(self) -> list[str]:
        """Return every file on the card as 'dir/file', in the camera's order."""
        body = self._get("v1/photos").json()
        return [
            f"{directory['name']}/{file_name}"
            for directory in body.get("dirs", [])
            for file_name in directory.get("files", [])
        ]

    def info(self, path: str) -> FileInfo:
        """Return size, orientation, capture time and exposure of 'dir/file'.

        The body's gpsInfo is deliberately left out: it's the shot's position.
        """
        body = self._get(f"v1/photos/{path}/info").json()
        return FileInfo(
            size=int(body["size"]),
            orientation=int(body.get("orientation") or UNKNOWN_ORIENTATION),
            datetime=str(body.get("datetime", "")),
            aperture=str(body.get("av", "")),
            shutter_speed=str(body.get("tv", "")),
            iso=str(body.get("sv", "")),
            exposure_compensation=str(body.get("xv", "")),
        )

    def image(self, path: str, size: str) -> bytes:
        """Return the 'thumb' or 'view' JPEG of the file at 'dir/file'."""
        return self._get(f"v1/photos/{path}?size={size}").content

    def download(
        self,
        path: str,
        on_chunk: Callable[[bytes], None],
        is_cancelled: Callable[[], bool],
    ) -> DownloadResult:
        """Stream the full file at 'dir/file' to on_chunk, 256 KB at a time.

        Checks is_cancelled before each chunk and raises DownloadCancelled.
        """
        response = self._get(f"v1/photos/{path}", stream=True)
        with response:
            received_size = self._stream(response, on_chunk, is_cancelled)
        announced = response.headers.get("Content-Length")
        announced_size = int(announced) if announced is not None else None
        return DownloadResult(announced_size, received_size)

    def _stream(self, response, on_chunk, is_cancelled) -> int:
        received_size = 0
        try:
            for chunk in response.iter_content(DOWNLOAD_CHUNK_SIZE):
                if is_cancelled():
                    raise DownloadCancelled(response.url)
                on_chunk(chunk)
                received_size += len(chunk)
        except BROKEN_TRANSFER_ERRORS as error:
            raise CameraUnreachable("Connection lost during download") from error
        return received_size

    def _get_props(self) -> dict:
        response = self._get("v1/props")
        try:
            props = response.json()
        except ValueError:
            raise UnsupportedCamera(None) from None
        if not isinstance(props, dict):
            raise UnsupportedCamera(None)
        return props

    def _get(self, path: str, stream: bool = False) -> requests.Response:
        """Send a GET request; the only way this client talks to the camera."""
        url = self.base_url + path
        started = time.monotonic()
        try:
            response = self._session.get(
                url,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                stream=stream,
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            log.debug("GET %s failed: %s", url, type(error).__name__)
            raise CameraUnreachable(
                f"Camera not reachable at {self.base_url}"
            ) from error
        elapsed_ms = (time.monotonic() - started) * 1000
        log.debug("GET %s -> %d in %.0f ms", url, response.status_code, elapsed_ms)
        if response.status_code >= 400:
            response.close()
            raise CameraHttpError(response.status_code, path)
        return response
