"""Probe whether a Ricoh GR III serves a preview larger than 720x480.

The camera's props list `resoList: ["720x480", "1080x720"]`, but nobody knows
how (or whether) a 1080x720 preview can be requested. This script tries a set
of candidate GET requests for one JPG and records, for each, the status, the
content type, the byte size and the pixel size of the image it returns.

Read-only toward the camera: only GET is sent. Camera props are never fetched,
so no secret ends up in the output. A response as large as the full file is
closed right after its headers. Results go to a timestamped folder under
spike/out/ (gitignored: it holds a picture from the card).

    python spike/probe_preview_sizes.py [--host URL] [--file DIR/NAME.JPG]
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import requests
from PySide6.QtGui import QImage

DEFAULT_HOST = "http://192.168.0.1/"
DEFAULT_OUT = Path(__file__).resolve().parent / "out"
TIMEOUTS = (5, 30)  # connect, read seconds
MAX_PREVIEW_BYTES = 5 * 1024 * 1024  # anything larger is not a preview
EXIT_UNREACHABLE = 2

# Query strings (after '?') or path suffixes (starting with '/') to try.
CANDIDATES = [
    "size=thumb",  # baseline: 160x120
    "size=view",  # baseline: 720x480
    "size=xs",
    "size=s",
    "size=m",
    "size=l",
    "size=xl",
    "size=large",
    "size=full",
    "size=hd",
    "size=fullhd",
    "size=preview",
    "size=1080",
    "size=1080x720",
    "size=720x480",
    "size=view&reso=1080x720",
    "size=view&resolution=1080x720",
    "size=view&res=1080x720",
    "size=view&width=1080",
    "reso=1080x720",
    "resolution=1080x720",
    "/view",
    "/preview",
]


@dataclass
class Result:
    candidate: str
    url: str
    status: int | None
    content_type: str
    content_length: int | None
    bytes_read: int
    width: int | None
    height: int | None
    elapsed_ms: float
    verdict: str


def get(session: requests.Session, url: str) -> requests.Response:
    """The only way this script talks to the camera."""
    return session.get(url, timeout=TIMEOUTS, stream=True)


def candidate_url(base_url: str, path: str, candidate: str) -> str:
    if candidate.startswith("/"):
        return f"{base_url}v1/photos/{path}{candidate}"
    return f"{base_url}v1/photos/{path}?{candidate}"


def probe(session, url: str, candidate: str, full_size: int, out_dir: Path) -> Result:
    started = time.monotonic()
    try:
        response = get(session, url)
    except requests.RequestException as error:
        elapsed_ms = (time.monotonic() - started) * 1000
        verdict = f"error: {type(error).__name__}"
        return Result(
            candidate, url, None, "", None, 0, None, None, elapsed_ms, verdict
        )
    with response:
        return read_result(response, candidate, url, full_size, out_dir, started)


def read_result(response, candidate, url, full_size, out_dir, started) -> Result:
    length_header = response.headers.get("Content-Length")
    content_length = int(length_header) if length_header else None
    content_type = response.headers.get("Content-Type", "")
    body = b""
    is_full_file = content_length == full_size
    is_too_large = content_length is not None and content_length > MAX_PREVIEW_BYTES
    if response.ok and not (is_full_file or is_too_large):
        body = response.content
    elapsed_ms = (time.monotonic() - started) * 1000
    image = QImage()
    is_image = bool(body) and image.loadFromData(body)
    if is_image:
        (out_dir / f"{safe_name(candidate)}.jpg").write_bytes(body)
    verdict = judge(response.status_code, is_full_file, is_too_large, is_image)
    return Result(
        candidate=candidate,
        url=url,
        status=response.status_code,
        content_type=content_type,
        content_length=content_length,
        bytes_read=len(body),
        width=image.width() if is_image else None,
        height=image.height() if is_image else None,
        elapsed_ms=round(elapsed_ms, 1),
        verdict=verdict,
    )


def judge(status: int, is_full_file: bool, is_too_large: bool, is_image: bool) -> str:
    if status >= 400:
        return f"HTTP {status}"
    if is_full_file:
        return "full file (closed after headers)"
    if is_too_large:
        return "too large for a preview (closed after headers)"
    return "image" if is_image else "not an image"


def safe_name(candidate: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in candidate).strip("_")


def newest_jpg(session, base_url: str) -> str:
    listing = get(session, base_url + "v1/photos").json()
    paths = [
        f"{d['name']}/{name}"
        for d in listing.get("dirs", [])
        for name in d.get("files", [])
        if name.upper().endswith(".JPG")
    ]
    if not paths:
        sys.exit("No JPG on the card; take a JPG (or JPG+RAW) shot first.")
    return paths[-1]


def print_table(results: list[Result]):
    print(f"{'candidate':34} {'status':>6} {'bytes':>9} {'pixels':>11}  verdict")
    for r in results:
        pixels = f"{r.width}x{r.height}" if r.width else "-"
        status = r.status if r.status is not None else "-"
        print(
            f"{r.candidate:34} {status:>6} {r.bytes_read:>9} {pixels:>11}  {r.verdict}"
        )


def print_summary(results: list[Result]):
    images = [r for r in results if r.width]
    if not images:
        print("\nNo candidate returned an image.")
        return
    largest = max(images, key=lambda r: r.width * r.height)
    print(
        f"\nLargest preview: {largest.width}x{largest.height} from ?{largest.candidate}"
    )
    if largest.width <= 720:
        print("No request returned anything larger than 720x480.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=DEFAULT_HOST, help="camera base URL")
    parser.add_argument("--file", help="DIR/NAME.JPG to probe (default: newest JPG)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main():
    options = parse_args()
    base_url = options.host.rstrip("/") + "/"
    session = requests.Session()
    session.trust_env = False  # desktop proxies must not swallow 192.168.0.1
    try:
        path = options.file or newest_jpg(session, base_url)
        full_size = int(get(session, f"{base_url}v1/photos/{path}/info").json()["size"])
    except requests.RequestException as error:
        print(f"Camera not reachable at {base_url}: {error}", file=sys.stderr)
        sys.exit(EXIT_UNREACHABLE)
    out_dir = options.out / f"{datetime.now():%Y%m%d-%H%M%S}-preview-sizes"
    out_dir.mkdir(parents=True)
    print(f"Probing {path} ({full_size} bytes) at {base_url}\n")
    results = []
    for candidate in CANDIDATES:
        url = candidate_url(base_url, path, candidate)
        results.append(probe(session, url, candidate, full_size, out_dir))
    print_table(results)
    print_summary(results)
    report = {
        "file": path,
        "full_size": full_size,
        "results": [asdict(r) for r in results],
    }
    (out_dir / "results.json").write_text(json.dumps(report, indent=2))
    print(f"\nResults in {out_dir}")


if __name__ == "__main__":
    main()
