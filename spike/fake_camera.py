"""Minimal stand-in for the GR III HTTP API, for trial runs of probe_camera.py.

It does not try to match the real camera. It only has to make every branch of
the probe script run, including the fail and skip paths (see the switches).
"""

import argparse
import json
import re
import time
from functools import cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

DEFAULT_PORT = 8080
DIR_NAME = "100RICOH"
MB = 1024 * 1024
FILE_SIZES = {
    "R0000001.JPG": 3 * MB,
    "R0000001.DNG": 6 * MB,
    "R0000002.JPG": 2 * MB,
    "R0000003.MOV": 8 * MB,
}
PREVIEW_SIZES = {"thumb": (160, 120), "view": (640, 480)}
SLOW_DELAY_SECONDS = 0.5
SLOW_CHUNK_DELAY_SECONDS = 0.03  # ~2 MB/s, so a download lasts long enough to overlap
CHUNK_SIZE = 64 * 1024
FILE_PATH = re.compile(r"^/v1/photos/([^/]+)/([^/]+?)(/info)?$")
RANGE_HEADER = re.compile(r"^bytes=(\d+)-(\d*)$")

PROPS = {
    "errCode": 200,
    "errMsg": "OK",
    "model": "RICOH GR III",
    "serialNo": "00000000",
    "firmwareVersion": "fake",
    "battery": 87,
    "storages": [{"name": "in", "equipped": True, "remain": 1234}],
}


def build_listing(include_mov: bool) -> dict:
    """Return the /v1/photos body, optionally without the MOV file."""
    files = [name for name in FILE_SIZES if include_mov or not name.endswith(".MOV")]
    return {
        "errCode": 200,
        "errMsg": "OK",
        "dirs": [{"name": DIR_NAME, "files": files}],
    }


@cache
def generated_jpeg(width: int, height: int) -> bytes:
    """Return a solid-color JPEG of the given pixel size."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG")
    return bytes(data)


def parse_range(header: str, total_size: int) -> tuple[int, int] | None:
    """Return the inclusive (start, end) of a single 'bytes=a-b' range, or None."""
    match = RANGE_HEADER.match(header or "")
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else total_size - 1
    return start, min(end, total_size - 1)


class FakeCameraHandler(BaseHTTPRequestHandler):
    options: argparse.Namespace  # set by make_handler

    def do_GET(self):
        self.handle_request(send_body=True)

    def do_HEAD(self):
        if self.options.no_head:
            self.send_json(405, {"errCode": 405, "errMsg": "Method Not Allowed"})
            return
        self.handle_request(send_body=False)

    def do_POST(self):
        # The probe script must never send this; make it loud if it does.
        print(f"!!! unexpected POST {self.path}")
        self.send_json(405, {"errCode": 405, "errMsg": "Method Not Allowed"})

    def handle_request(self, send_body: bool):
        if self.options.slow:
            time.sleep(SLOW_DELAY_SECONDS)
        if self.options.fail and self.options.fail in self.path:
            self.send_json(
                500, {"errCode": 500, "errMsg": "Injected failure"}, send_body
            )
            return
        self.route(urlsplit(self.path), send_body)

    def route(self, url, send_body: bool):
        if url.path == "/v1/props":
            self.send_json(200, PROPS, send_body)
            return
        if url.path == "/v1/photos":
            self.send_json(200, build_listing(not self.options.no_mov), send_body)
            return
        match = FILE_PATH.match(url.path)
        if not match or not self.file_exists(match.group(1), match.group(2)):
            self.send_json(404, {"errCode": 404, "errMsg": "Not Found"}, send_body)
            return
        dir_name, file_name, is_info = match.groups()
        if is_info:
            self.send_json(200, self.file_info(dir_name, file_name), send_body)
            return
        size = parse_qs(url.query).get("size", [None])[0]
        if size in PREVIEW_SIZES:
            self.send_bytes(
                200, "image/jpeg", generated_jpeg(*PREVIEW_SIZES[size]), send_body
            )
            return
        self.send_full_file(file_name, send_body)

    def file_exists(self, dir_name: str, file_name: str) -> bool:
        if dir_name != DIR_NAME or file_name not in FILE_SIZES:
            return False
        return not (self.options.no_mov and file_name.endswith(".MOV"))

    def file_info(self, dir_name: str, file_name: str) -> dict:
        return {
            "errCode": 200,
            "errMsg": "OK",
            "dir": dir_name,
            "file": file_name,
            "size": FILE_SIZES[file_name],
            "datetime": "2026-11-22T12:00:00",
        }

    def send_full_file(self, file_name: str, send_body: bool):
        total_size = FILE_SIZES[file_name]
        byte_range = None
        if not self.options.no_range:
            byte_range = parse_range(self.headers.get("Range"), total_size)
        if byte_range is None:
            self.send_filler(200, file_name, 0, total_size - 1, send_body)
            return
        start, end = byte_range
        self.send_filler(206, file_name, start, end, send_body, total_size)

    def send_filler(self, status, file_name, start, end, send_body, total_size=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type_for(file_name))
        self.send_header("Content-Length", str(end - start + 1))
        if total_size is not None:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
        self.end_headers()
        if send_body:
            self.write_filler(end - start + 1)

    def write_filler(self, num_bytes: int):
        chunk = b"\0" * CHUNK_SIZE
        try:
            while num_bytes > 0:
                self.wfile.write(chunk[:num_bytes])
                num_bytes -= CHUNK_SIZE
                if self.options.slow:
                    time.sleep(SLOW_CHUNK_DELAY_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client hung up early, e.g. after the headers it wanted

    def send_json(self, status: int, body: dict, send_body: bool = True):
        self.send_bytes(
            status, "application/json", json.dumps(body).encode(), send_body
        )

    def send_bytes(self, status: int, content_type: str, body: bytes, send_body: bool):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)


def content_type_for(file_name: str) -> str:
    """Return the MIME type the fake serves for a full-size file."""
    extension = file_name.rsplit(".", 1)[-1]
    return {"JPG": "image/jpeg", "DNG": "image/x-adobe-dng", "MOV": "video/quicktime"}[
        extension
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-head", action="store_true", help="answer HEAD with 405")
    parser.add_argument("--no-range", action="store_true", help="ignore Range headers")
    parser.add_argument("--no-mov", action="store_true", help="no MOV on the card")
    parser.add_argument(
        "--slow", action="store_true", help="delay every response, throttle full files"
    )
    parser.add_argument(
        "--fail", metavar="SUBSTRING", help="answer 500 when the path contains it"
    )
    return parser.parse_args()


def main():
    options = parse_args()
    handler = type("Handler", (FakeCameraHandler,), {"options": options})
    server = ThreadingHTTPServer(("127.0.0.1", options.port), handler)
    print(f"fake camera on http://127.0.0.1:{options.port}/  options: {vars(options)}")
    server.serve_forever()


if __name__ == "__main__":
    main()
