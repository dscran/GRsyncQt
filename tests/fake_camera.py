"""A fake Ricoh GR III HTTP API for tests and manual runs.

It reproduces the quirks measured on a real GR III (docs/camera-api.md):
HEAD answers 404, Range headers are ignored, the JPG thumbnail is a 160x120
letterboxed image, DNG/MOV thumbnails are the same as their previews, and
image/file responses forbid caching. Switches inject failures, and every
request is logged so that tests can check what the app sent.

Run it by hand with `python tests/fake_camera.py --help`.
"""

import argparse
import json
import re
import socket
import threading
import time
import zlib
from dataclasses import dataclass, field
from functools import cache, partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

KB = 1024
CHUNK_SIZE = 64 * KB
THUMB_SIZE = (160, 120)
LETTERBOX_ROWS = 8
JPG_VIEW_SIZE = (720, 480)
MOV_VIEW_SIZE = (640, 360)
HEAD_BODY = b"404 Not Found\r\n"  # 15 bytes, like the camera
NO_CACHE = "no-store, no-cache"
SHOT_GPS_SECRET = "GPS-SECRET-OF-THE-SHOT"  # /info's gpsInfo, never shown
DEFAULT_DATETIME = "2026-11-22T12:00:00"
FILE_PATH = re.compile(r"^/v1/photos/([^/]+)/([^/]+?)(/info)?$")
PICTURE_COLORS = ["steelblue", "darkorange", "seagreen", "orchid", "goldenrod"]

SECRET_PROPS = {
    "key": "secret-wifi-password",
    "ssid": "RICOH_SECRET",
    "serialNo": "SERIAL-SECRET",
    "macAddress": "MAC-SECRET",
    "gpsInfo": "GPS-SECRET",
}


@dataclass
class FakeFile:
    """One file on the fake card."""

    dir: str
    name: str
    size: int = 300 * KB
    orientation: int = 1
    datetime: str = DEFAULT_DATETIME
    av: str = "4.5"
    tv: str = "1.4"
    sv: str = "3200"
    xv: str = "0.0"

    @property
    def path(self) -> str:
        return f"{self.dir}/{self.name}"

    @property
    def extension(self) -> str:
        return self.name.rsplit(".", 1)[-1].upper()


@dataclass
class LoggedRequest:
    method: str
    path: str


def default_props() -> dict:
    """Return camera properties like the real camera's, secrets included."""
    return {
        "errCode": 200,
        "errMsg": "OK",
        "manufacturer": "RICOH IMAGING COMPANY, LTD.",
        "model": "RICOH GR III",
        "firmwareVersion": "1.20",
        "battery": 87,
        **SECRET_PROPS,
    }


def default_card() -> list[FakeFile]:
    """Return a small card: a pair, unpaired files, a video and a portrait."""
    return [
        FakeFile("100RICOH", "R0000001.JPG"),
        FakeFile("100RICOH", "R0000001.DNG", size=600 * KB),
        FakeFile("100RICOH", "R0000002.JPG"),
        FakeFile("100RICOH", "R0000003.MOV", size=500 * KB, orientation=0),
        FakeFile("100RICOH", "R0000005.DNG", size=600 * KB),
        FakeFile("101RICOH", "R0000006.JPG", orientation=6),
        FakeFile("101RICOH", "R0000006.DNG", size=600 * KB, orientation=6),
    ]


def large_card(num_files: int) -> list[FakeFile]:
    """Return a card of JPG+DNG pairs (and a MOV every 50 shots), num_files long."""
    files = []
    number = 1
    while len(files) < num_files:
        dir_name = f"{100 + number // 1000}RICOH"
        stem = f"R{number:07d}"
        if number % 50 == 0:
            files.append(FakeFile(dir_name, f"{stem}.MOV", orientation=0))
        else:
            orientation = 6 if number % 7 == 0 else 1
            files.append(FakeFile(dir_name, f"{stem}.JPG", orientation=orientation))
            files.append(FakeFile(dir_name, f"{stem}.DNG", orientation=orientation))
        number += 1
    return files[:num_files]


def file_content(file: FakeFile) -> bytes:
    """Return the full-size content the fake serves for a file."""
    pattern = file.path.encode() * (CHUNK_SIZE // len(file.path) + 1)
    repeats = file.size // len(pattern) + 1
    return (pattern * repeats)[: file.size]


@cache
def encoded_jpeg(width: int, height: int, color: str, black_rows: int = 0) -> bytes:
    """Return a JPEG filled with color, with black_rows black rows top and bottom."""
    picture = QImage(width, height - 2 * black_rows, QImage.Format.Format_RGB32)
    picture.fill(QColor(color))
    # copy() fills the area outside the picture with zeros, which is black.
    image = picture.copy(0, -black_rows, width, height)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG", 95)
    return bytes(data)


def preview_jpeg(file: FakeFile, size: str) -> bytes:
    """Return the ?size=thumb or ?size=view image of a file, as the camera does."""
    color = PICTURE_COLORS[zlib.crc32(file.path.encode()) % len(PICTURE_COLORS)]
    if file.extension == "MOV":
        return encoded_jpeg(*MOV_VIEW_SIZE, color)
    if size == "thumb" and file.extension == "JPG":
        return encoded_jpeg(*THUMB_SIZE, color, LETTERBOX_ROWS)
    return encoded_jpeg(*JPG_VIEW_SIZE, color)


@dataclass
class FakeCamera:
    """A fake camera server with a configurable card and failure switches.

    Switches (change them at any time):
    - errors: full request path (with query) -> HTTP status to answer with
    - drops: full request paths whose body is cut off halfway
    - delay: seconds to wait before answering any request
    - chunk_delay: seconds to wait between 64 KB chunks of a full file
    - gone: close every connection without answering
    - props_raw: if set, served instead of the props JSON (e.g. a router page)
    """

    card: list[FakeFile] = field(default_factory=default_card)
    props: dict = field(default_factory=default_props)
    errors: dict[str, int] = field(default_factory=dict)
    drops: set[str] = field(default_factory=set)
    delay: float = 0.0
    chunk_delay: float = 0.0
    gone: bool = False
    props_raw: bytes | None = None
    log: list[LoggedRequest] = field(default_factory=list)
    max_concurrent: int = 0

    def __post_init__(self):
        self._lock = threading.Lock()
        self._in_flight = 0
        self._server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/"

    def start(self, port: int = 0) -> "FakeCamera":
        """Start serving on 127.0.0.1 (an ephemeral port by default)."""
        handler = type("Handler", (FakeCameraHandler,), {"camera": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._server.daemon_threads = True
        serve = partial(self._server.serve_forever, poll_interval=0.05)
        threading.Thread(target=serve, daemon=True).start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def find(self, dir_name: str, file_name: str) -> FakeFile | None:
        for file in self.card:
            if file.dir == dir_name and file.name == file_name:
                return file
        return None

    def file(self, path: str) -> FakeFile:
        dir_name, file_name = path.split("/")
        return self.find(dir_name, file_name)

    def paths_requested(self, method: str = "GET") -> list[str]:
        return [entry.path for entry in self.log if entry.method == method]

    def clear_log(self):
        with self._lock:
            self.log.clear()
            self.max_concurrent = 0

    def listing(self) -> dict:
        dirs: dict[str, list[str]] = {}
        for file in self.card:
            dirs.setdefault(file.dir, []).append(file.name)
        return {
            "errCode": 200,
            "errMsg": "OK",
            "dirs": [{"name": name, "files": dirs[name]} for name in sorted(dirs)],
        }

    def request_started(self, method: str, path: str):
        with self._lock:
            self.log.append(LoggedRequest(method, path))
            self._in_flight += 1
            self.max_concurrent = max(self.max_concurrent, self._in_flight)

    def request_finished(self):
        with self._lock:
            self._in_flight -= 1


def info_body(file: FakeFile) -> dict:
    is_video = file.extension == "MOV"
    return {
        "errCode": 200,
        "errMsg": "OK",
        "cameraModel": "" if is_video else "RICOH GR III",
        "dir": file.dir,
        "file": file.name,
        "size": file.size,
        "datetime": file.datetime,
        "orientation": file.orientation,
        "aspectRatio": "4:3" if is_video else "3:2",
        # Videos report no exposure, as measured on the GR III.
        "av": "0.0" if is_video else file.av,
        "tv": "0.0" if is_video else file.tv,
        "sv": "auto" if is_video else file.sv,
        "xv": "0.0" if is_video else file.xv,
        "gpsInfo": SHOT_GPS_SECRET,
    }


class FakeCameraHandler(BaseHTTPRequestHandler):
    camera: FakeCamera  # set by FakeCamera.start

    def log_message(self, format, *args):
        pass  # keep test output quiet

    def do_GET(self):
        self.serve("GET", self.answer_get)

    def do_HEAD(self):
        self.serve("HEAD", self.answer_head)

    def do_POST(self):
        self.serve("POST", self.answer_not_allowed)

    def do_PUT(self):
        self.serve("PUT", self.answer_not_allowed)

    def do_DELETE(self):
        self.serve("DELETE", self.answer_not_allowed)

    def serve(self, method: str, answer):
        self.camera.request_started(method, self.path)
        try:
            if self.camera.gone:
                self.hang_up()
                return
            time.sleep(self.camera.delay)
            status = self.camera.errors.get(self.path)
            if status is not None:
                self.send_json(status, {"errCode": status, "errMsg": "Injected"})
                return
            answer()
        finally:
            self.camera.request_finished()

    def hang_up(self):
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR)

    def answer_head(self):
        self.send_bytes(404, "text/plain", HEAD_BODY, send_body=False)

    def answer_not_allowed(self):
        self.send_json(405, {"errCode": 405, "errMsg": "Method Not Allowed"})

    def answer_get(self):
        url = urlsplit(self.path)
        if url.path == "/v1/props":
            self.answer_props()
            return
        if url.path == "/v1/photos":
            self.send_json(200, self.camera.listing())
            return
        match = FILE_PATH.match(url.path)
        file = self.camera.find(match.group(1), match.group(2)) if match else None
        if file is None:
            self.send_json(404, {"errCode": 404, "errMsg": "Not Found"})
            return
        if match.group(3):
            self.send_json(200, info_body(file))
            return
        size = parse_qs(url.query).get("size", [None])[0]
        if size in ("thumb", "view"):
            self.send_image(preview_jpeg(file, size))
            return
        self.send_file(file)

    def answer_props(self):
        if self.camera.props_raw is None:
            self.send_json(200, self.camera.props)
            return
        self.send_bytes(200, "text/html", self.camera.props_raw)

    def send_image(self, body: bytes):
        self.send_bytes(200, "image/jpeg", body, cache_control=NO_CACHE)

    def send_file(self, file: FakeFile):
        content = file_content(file)
        self.send_response_only(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", NO_CACHE)
        self.end_headers()
        if self.path in self.camera.drops:
            content = content[: len(content) // 2]
        try:
            self.write_chunks(content)
        except (BrokenPipeError, ConnectionResetError):
            return  # the client hung up, e.g. after cancelling
        if self.path in self.camera.drops:
            self.hang_up()

    def write_chunks(self, content: bytes):
        for start in range(0, len(content), CHUNK_SIZE):
            self.wfile.write(content[start : start + CHUNK_SIZE])
            time.sleep(self.camera.chunk_delay)

    def send_json(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_bytes(status, "application/json", payload, server_header=True)

    def send_bytes(
        self,
        status: int,
        content_type: str,
        body: bytes,
        send_body: bool = True,
        cache_control: str | None = None,
        server_header: bool = False,
    ):
        self.send_response_only(status)
        if server_header:
            self.send_header("Server", "Crow/0.1")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        if send_body:
            self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--files", type=int, help="serve a generated card with this many files"
    )
    parser.add_argument("--battery", type=int, default=87)
    parser.add_argument("--delay", type=float, default=0.0, help="seconds per request")
    parser.add_argument(
        "--chunk-delay",
        type=float,
        default=0.0,
        help="seconds per 64 KB chunk of a download (0.013 is about 4.8 MB/s)",
    )
    return parser.parse_args()


def main():
    options = parse_args()
    card = large_card(options.files) if options.files else default_card()
    camera = FakeCamera(card=card, delay=options.delay, chunk_delay=options.chunk_delay)
    camera.props["battery"] = options.battery
    camera.start(options.port)
    print(
        f"fake camera with {len(card)} files on {camera.url} (Ctrl+C to stop)",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        camera.stop()


if __name__ == "__main__":
    main()
