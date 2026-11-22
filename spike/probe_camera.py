"""Probe a Ricoh GR III / IIIx over Wi-Fi and record how its HTTP API behaves.

Read-only toward the camera: only GET and HEAD are ever sent, so nothing is
deleted, no setting changes and the camera is never powered off. Every probe
writes its raw responses to a timestamped folder under spike/out/ and prints a
one-line verdict; a failing probe is recorded and the run continues.
"""

import argparse
import json
import mimetypes
import platform
import sys
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import requests

DEFAULT_HOST = "http://192.168.0.1/"
DEFAULT_OUT = Path(__file__).resolve().parent / "out"
ALLOWED_METHODS = frozenset({"GET", "HEAD"})
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30
EVIDENCE_TEXT_LIMIT = 4096
DOWNLOAD_CHUNK_SIZE = 256 * 1024
FILE_TYPES = ("JPG", "DNG", "MOV")
LISTING_NAME_KEYS = ("name", "n", "file", "fileName")  # in case entries are objects
RANGE_READ_LIMIT = 1024  # stop reading if the camera ignores Range
PARALLEL_COUNTS = (2, 4)
THUMBS_DURING_DOWNLOAD = 3
THUMBS_START_AFTER_BYTES = 1024 * 1024
MB = 1024 * 1024
EXIT_UNREACHABLE = 2


class MethodNotAllowedError(Exception):
    """Raised for any HTTP method other than GET or HEAD."""


# ---------------------------------------------------------------- HTTP


@dataclass
class Exchange:
    """One recorded request/response pair."""

    method: str
    url: str
    status: int
    headers: dict[str, str]
    headers_ms: float  # until the response headers arrived
    elapsed_ms: float  # until the whole body was read
    body_size: int
    body: bytes = field(repr=False)  # empty when streamed to a file

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "").split(";")[0].strip().lower()

    def meta(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "headers": self.headers,
            "headers_ms": round(self.headers_ms, 1),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "body_size": self.body_size,
        }


def new_session() -> requests.Session:
    """Return a session that ignores proxy settings from the environment."""
    session = requests.Session()
    session.trust_env = False  # a desktop proxy must not swallow 192.168.0.1
    return session


def http_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_body_bytes: int | None = None,
    stream_to: Path | None = None,
    on_chunk: Callable[[int], None] | None = None,
) -> Exchange:
    """Send one GET or HEAD request and record it.

    Any other method raises before the network is touched, so the probe can
    never change or power off the camera. `max_body_bytes` stops reading early
    (for a Range request the camera might ignore); `stream_to` writes the body
    to a file instead of memory.
    """
    if method not in ALLOWED_METHODS:
        raise MethodNotAllowedError(f"{method} is not allowed; only GET and HEAD")
    started = time.perf_counter()
    with session.request(
        method,
        url,
        headers=headers,
        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        stream=True,
        allow_redirects=False,
    ) as response:
        headers_ms = ms_since(started)
        body, body_size = read_body(response, max_body_bytes, stream_to, on_chunk)
    return Exchange(
        method=method,
        url=url,
        status=response.status_code,
        headers=dict(response.headers),
        headers_ms=headers_ms,
        elapsed_ms=ms_since(started),
        body_size=body_size,
        body=body,
    )


def read_body(response, max_body_bytes, stream_to, on_chunk) -> tuple[bytes, int]:
    if stream_to is not None:
        return b"", stream_body_to_file(response, stream_to, on_chunk)
    if max_body_bytes is None:
        return response.content, len(response.content)
    body = b""
    for chunk in response.iter_content(chunk_size=1024):
        body += chunk
        if len(body) >= max_body_bytes:
            break
    return body, len(body)


def stream_body_to_file(response, path: Path, on_chunk) -> int:
    num_bytes = 0
    with path.open("wb") as file:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            file.write(chunk)
            num_bytes += len(chunk)
            if on_chunk:
                on_chunk(num_bytes)
    return num_bytes


def ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def parse_json(exchange: Exchange) -> Any:
    """Return the decoded JSON body, or None if it isn't JSON."""
    try:
        return json.loads(exchange.body)
    except ValueError:
        return None


# ---------------------------------------------------------------- output


class RunRecorder:
    """Owns the run folder: evidence files, results.json and run.log."""

    def __init__(self, out_root: Path, run_info: dict[str, Any]):
        self.dir = create_run_dir(out_root)
        self.run_info = run_info
        self.results: list[dict[str, Any]] = []
        self.log_file = (self.dir / "run.log").open("a", encoding="utf-8")
        self.write_results()

    def log(self, line: str):
        print(line, flush=True)
        self.log_file.write(line + "\n")
        self.log_file.flush()

    def add_result(self, result: dict[str, Any]):
        self.results.append(result)
        self.write_results()

    def write_results(self):
        # Rewritten after every probe, so a run cut short still leaves valid JSON.
        document = {**self.run_info, "results": self.results}
        temporary = self.dir / "results.json.tmp"
        temporary.write_text(
            json.dumps(document, indent=2, default=str), encoding="utf-8"
        )
        temporary.replace(self.dir / "results.json")

    def save_text(self, name: str, text: str) -> str:
        (self.dir / name).write_text(text, encoding="utf-8")
        return name

    def save_exchange(self, stem: str, exchange: Exchange) -> list[str]:
        """Write the request/response record and its body; return the file names."""
        names = [
            self.save_text(f"{stem}.http.json", json.dumps(exchange.meta(), indent=2))
        ]
        if exchange.body:
            extension, data = evidence_body(exchange)
            (self.dir / f"{stem}{extension}").write_bytes(data)
            names.append(f"{stem}{extension}")
        return names

    def finish(self, outcome: str):
        self.run_info["finished"] = datetime.now().isoformat(timespec="seconds")
        self.run_info["outcome"] = outcome
        self.write_results()
        self.log_file.close()


def create_run_dir(out_root: Path) -> Path:
    """Create out_root/<timestamp>/, adding -2, -3... if a run started in the same second."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_root.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 100):
        run_dir = out_root / (timestamp if attempt == 1 else f"{timestamp}-{attempt}")
        try:
            run_dir.mkdir()
            return run_dir
        except FileExistsError:
            continue
    raise FileExistsError(f"too many runs at {timestamp} in {out_root}")


def evidence_body(exchange: Exchange) -> tuple[str, bytes]:
    """Choose how to store a body: pretty JSON, a whole image, or the first 4 KB."""
    content_type = exchange.content_type
    decoded = parse_json(exchange)
    if decoded is not None:
        return ".json", json.dumps(decoded, indent=2, ensure_ascii=False).encode()
    image_extension = mimetypes.guess_extension(content_type)
    if content_type.startswith("image/") and image_extension:
        return image_extension, exchange.body
    if content_type.startswith("text/"):
        return ".txt", exchange.body[:EVIDENCE_TEXT_LIMIT]
    return ".bin", exchange.body[:EVIDENCE_TEXT_LIMIT]


def format_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "? B"
    for unit in ("B", "KB", "MB"):
        if num_bytes < 1024 or unit == "MB":
            return (
                f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
            )
        num_bytes /= 1024
    raise AssertionError("unreachable")


def format_ms(milliseconds: float) -> str:
    return f"{milliseconds:.0f} ms"


# ---------------------------------------------------------------- probe framework


@dataclass
class Outcome:
    status: str  # ok | fail | skipped
    verdict: str
    measurements: dict[str, Any] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)  # extra console lines


@dataclass
class ProbeContext:
    """State shared by the probes of one run."""

    host: str
    options: argparse.Namespace
    recorder: RunRecorder
    session: requests.Session = field(default_factory=new_session)
    stem: str = ""
    evidence: list[str] = field(default_factory=list)
    targets: dict[str, str | None] = field(default_factory=dict)
    findings: dict[str, Any] = field(default_factory=dict)  # values later probes reuse

    def fetch(
        self, method: str, path: str, suffix: str = "", session=None, **kwargs
    ) -> Exchange:
        """Request a camera path and save the exchange as evidence of the current probe."""
        exchange = http_request(
            session or self.session, method, urljoin(self.host, path), **kwargs
        )
        self.evidence += self.recorder.save_exchange(self.stem + suffix, exchange)
        if kwargs.get("stream_to"):
            self.evidence.append(kwargs["stream_to"].name)
        return exchange

    def evidence_path(self, suffix: str) -> Path:
        return self.recorder.dir / f"{self.stem}{suffix}"


def run_probe(
    ctx: ProbeContext,
    probe_id: int,
    name: str,
    probe: Callable[[], Outcome],
    *,
    file_type: str | None = None,
    target: str | None = None,
    skip_reason: str | None = None,
) -> Outcome:
    """Run one probe in isolation, record its result and print its verdict."""
    ctx.stem = "-".join(part for part in (f"{probe_id:02d}", name, file_type) if part)
    ctx.evidence = []
    if skip_reason:
        outcome = Outcome("skipped", skip_reason)
    else:
        outcome = call_isolated(ctx, probe)
    label = f"{name} {file_type or ''}".strip()
    ctx.recorder.log(
        f"{'[' + outcome.status + ']':<10}{probe_id:02d} {label:<26}{outcome.verdict}"
    )
    for line in outcome.details:
        ctx.recorder.log(f"{'':<13}{line}")
    ctx.recorder.add_result(
        {
            "id": probe_id,
            "name": name,
            "type": file_type,
            "target": target,
            "status": outcome.status,
            "verdict": outcome.verdict,
            "measurements": outcome.measurements,
            "evidence": ctx.evidence,
        }
    )
    return outcome


def call_isolated(ctx: ProbeContext, probe: Callable[[], Outcome]) -> Outcome:
    """Turn any exception into a `fail` outcome with the traceback saved."""
    try:
        return probe()
    except Exception as error:
        ctx.evidence.append(
            ctx.recorder.save_text(f"{ctx.stem}.traceback.txt", traceback.format_exc())
        )
        return Outcome("fail", f"{type(error).__name__}: {error}")


# ---------------------------------------------------------------- probes


def probe_props(ctx: ProbeContext) -> Outcome:
    """Probe 1: dump /v1/props (model, battery, other fields)."""
    exchange = ctx.fetch("GET", "v1/props")
    props = parse_json(exchange)
    if exchange.status != 200 or not isinstance(props, dict):
        return Outcome(
            "fail",
            f"{exchange.status} {exchange.content_type}: not the camera's props JSON",
        )
    measurements = {
        "http": exchange.status,
        "errCode": props.get("errCode"),
        "model": props.get("model"),
        "battery": props.get("battery"),
        "keys": sorted(props),
        "elapsed_ms": round(exchange.elapsed_ms, 1),
    }
    verdict = (
        f"200 model={props.get('model')!r} battery={props.get('battery')} "
        f"{len(props)} fields {format_ms(exchange.elapsed_ms)}"
    )
    return Outcome("ok", verdict, measurements)


def probe_props_again(ctx: ProbeContext) -> Outcome:
    """Closing check: does the camera still answer after the load of the run?"""
    outcome = probe_props(ctx)
    battery_at_start = ctx.findings.get("battery_at_start")
    outcome.measurements["battery_at_start"] = battery_at_start
    outcome.verdict += f" (battery at start {battery_at_start})"
    return outcome


def probe_listing(ctx: ProbeContext) -> Outcome:
    """Probe 2: dump /v1/photos (sizes or dates included? how do MOVs appear?)."""
    exchange = ctx.fetch("GET", "v1/photos")
    listing = parse_json(exchange)
    if exchange.status != 200 or not isinstance(listing, dict):
        return Outcome(
            "fail",
            f"{exchange.status} {exchange.content_type}: not a listing JSON",
            http_measurements(exchange),
        )
    dirs = listing.get("dirs") or []
    entries = [entry for directory in dirs for entry in directory.get("files", [])]
    files = listing_paths(dirs)
    ctx.findings["files"] = files
    extensions = dict(Counter(file_extension(path) for path in files))
    entry_types = sorted({type(entry).__name__ for entry in entries})
    measurements = {
        **http_measurements(exchange),
        "errCode": listing.get("errCode"),
        "keys": sorted(listing),
        "dir_keys": sorted(dirs[0]) if dirs else [],
        "num_dirs": len(dirs),
        "num_files": len(files),
        "extensions": extensions,
        "entry_types": entry_types,
        "sample_entries": entries[:3],
    }
    verdict = (
        f"200 {len(dirs)} dirs, {len(files)} files {extensions}, entries are "
        f"{'/'.join(entry_types) or '-'}, {format_size(exchange.body_size)} "
        f"{format_ms(exchange.elapsed_ms)}"
    )
    return Outcome("ok", verdict, measurements)


def listing_paths(dirs: list[dict]) -> list[str]:
    """Return 'DIR/FILE' for every file in a /v1/photos listing."""
    paths = []
    for directory in dirs:
        paths += [
            f"{directory.get('name')}/{entry_name(e)}"
            for e in directory.get("files", [])
        ]
    return paths


def entry_name(entry: Any) -> str:
    """Return the file name of a listing entry, which may be a string or an object."""
    if isinstance(entry, str):
        return entry
    for key in LISTING_NAME_KEYS:
        if isinstance(entry, dict) and key in entry:
            return str(entry[key])
    return json.dumps(entry)


def file_extension(path: str) -> str:
    return path.rsplit(".", 1)[-1].upper() if "." in path else ""


def path_stem(path: str) -> str:
    return path.rsplit(".", 1)[0].upper()


def choose_targets(
    files: list[str], options: argparse.Namespace
) -> dict[str, str | None]:
    """Return the file to probe per type: the --jpg/--dng/--mov override, else automatic."""
    automatic = automatic_targets(files)
    targets = {}
    for file_type in FILE_TYPES:
        override = getattr(options, file_type.lower())
        targets[file_type] = override.strip("/") if override else automatic[file_type]
    return targets


def automatic_targets(files: list[str]) -> dict[str, str | None]:
    """Pick the newest JPG that has a DNG of the same name, that DNG and the newest MOV.

    Without such a pair, the newest JPG and the newest DNG are used separately.
    """
    by_type = {
        t: sorted(f for f in files if file_extension(f) == t) for t in FILE_TYPES
    }
    dng_by_stem = {path_stem(dng): dng for dng in by_type["DNG"]}
    paired_jpgs = [jpg for jpg in by_type["JPG"] if path_stem(jpg) in dng_by_stem]
    newest = {
        file_type: (paths[-1] if paths else None)
        for file_type, paths in by_type.items()
    }
    if paired_jpgs:
        newest["JPG"] = paired_jpgs[-1]
        newest["DNG"] = dng_by_stem[path_stem(paired_jpgs[-1])]
    return newest


def probe_preview(ctx: ProbeContext, target: str, size: str) -> Outcome:
    """Probes 3-4: ?size=thumb or ?size=view for one file."""
    exchange = ctx.fetch("GET", f"v1/photos/{target}?size={size}")
    dimensions = image_dimensions(exchange.body)
    width, height = dimensions or (None, None)
    measurements = {**http_measurements(exchange), "width": width, "height": height}
    is_image = exchange.status == 200 and exchange.content_type.startswith("image/")
    pixels = f"{width}x{height}" if dimensions else "no decodable image"
    verdict = (
        f"{exchange.status} {exchange.content_type or '-'} {pixels} "
        f"{format_size(exchange.body_size)} {format_ms(exchange.elapsed_ms)}"
    )
    return Outcome("ok" if is_image else "fail", verdict, measurements)


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) if the bytes decode as an image, else None.

    Qt decodes the image, so no JPEG header parser is needed; without PySide6
    the size is simply unknown.
    """
    if not data:
        return None
    try:
        from PySide6.QtGui import QImage
    except ImportError:
        return None
    image = QImage.fromData(data)
    if image.isNull():
        return None
    return image.width(), image.height()


def probe_info(ctx: ProbeContext, target: str) -> Outcome:
    """Probe 5: /info metadata for one file; does it include a size?"""
    exchange = ctx.fetch("GET", f"v1/photos/{target}/info")
    info = parse_json(exchange)
    timing = f"{format_size(exchange.body_size)} {format_ms(exchange.elapsed_ms)}"
    if exchange.status != 200 or not isinstance(info, dict):
        verdict = (
            f"{exchange.status} {exchange.content_type or '-'}: no info JSON, {timing}"
        )
        return Outcome("fail", verdict, http_measurements(exchange))
    size_fields = {key: value for key, value in info.items() if "size" in key.lower()}
    measurements = {
        **http_measurements(exchange),
        "errCode": info.get("errCode"),
        "keys": sorted(info),
        "size_fields": size_fields,
    }
    verdict = f"200 {len(info)} fields, size fields {size_fields or 'none'}, {timing}"
    return Outcome("ok", verdict, measurements)


def probe_head(ctx: ProbeContext, target: str) -> Outcome:
    """Probe 6: HEAD on a full-size file; is Content-Length returned without the body?"""
    exchange = ctx.fetch("HEAD", f"v1/photos/{target}")
    content_length = header_int(exchange, "Content-Length")
    has_size = exchange.status == 200 and content_length is not None
    measurements = {
        **http_measurements(exchange),
        "content_length": content_length,
        "accept_ranges": exchange.headers.get("Accept-Ranges"),
        "size_without_body": content_length if has_size else None,
    }
    timing = format_ms(exchange.elapsed_ms)
    if has_size:
        verdict = f"200 Content-Length {content_length} ({format_size(content_length)}) without body, {timing}"
        return Outcome("ok", verdict, measurements)
    verdict = f"{exchange.status}: no size from HEAD (Content-Length {content_length}), {timing}"
    return Outcome("fail", verdict, measurements)


def probe_range(ctx: ProbeContext, target: str) -> Outcome:
    """Probe 7: GET with Range bytes=0-0; 206 with Content-Range?"""
    exchange = ctx.fetch(
        "GET",
        f"v1/photos/{target}",
        headers={"Range": "bytes=0-0"},
        max_body_bytes=RANGE_READ_LIMIT,
    )
    content_range = exchange.headers.get("Content-Range")
    total_size = total_from_content_range(content_range)
    content_length = header_int(exchange, "Content-Length")
    measurements = {
        **http_measurements(exchange),
        "content_range": content_range,
        "content_length": content_length,
        "total_size": total_size,
    }
    timing = format_ms(exchange.elapsed_ms)
    if exchange.status == 206 and total_size is not None:
        measurements["size_without_body"] = total_size
        verdict = f"206 Content-Range {content_range!r} -> size {total_size} without body, {timing}"
        return Outcome("ok", verdict, measurements)
    if exchange.status == 200:
        # The size is still known from the headers if the client hangs up early.
        measurements["size_without_body"] = content_length
        verdict = (
            f"200: Range ignored, Content-Length {content_length}; "
            f"stopped reading after {format_size(exchange.body_size)}, {timing}"
        )
        return Outcome("fail", verdict, measurements)
    verdict = f"{exchange.status} Content-Range {content_range!r}: no size from Range, {timing}"
    return Outcome("fail", verdict, measurements)


def header_int(exchange: Exchange, name: str) -> int | None:
    value = exchange.headers.get(name)
    return int(value) if value and value.isdigit() else None


def total_from_content_range(content_range: str | None) -> int | None:
    """Return N from 'bytes a-b/N', or None."""
    if not content_range or "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[1].strip()
    return int(total) if total.isdigit() else None


def http_measurements(exchange: Exchange) -> dict[str, Any]:
    return {
        "http": exchange.status,
        "content_type": exchange.content_type,
        "bytes": exchange.body_size,
        "headers_ms": round(exchange.headers_ms, 1),
        "elapsed_ms": round(exchange.elapsed_ms, 1),
    }


def probe_parallel_thumbs(ctx: ProbeContext, count: int) -> Outcome:
    """Probe 8: `count` thumbnail requests at once; handled, queued or failed?"""
    paths = thumb_paths(ctx, count)
    sessions = [new_session() for _ in paths]
    suffixes = [f"-thumb{number}" for number in range(1, count + 1)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=count) as pool:
        records = list(pool.map(partial(timed_thumb, ctx), paths, sessions, suffixes))
    wall_ms = ms_since(started)
    single_ms = ctx.findings.get("single_thumb_ms")
    measurements = {
        "requests": records,
        "wall_ms": round(wall_ms, 1),
        "single_thumb_ms": single_ms,
    }
    num_ok = sum(record["status"] == 200 for record in records)
    verdict = (
        f"{num_ok}/{count} ok, {thumb_time_range(records)}, wall {format_ms(wall_ms)} "
        f"(single thumb {format_ms(single_ms) if single_ms else '?'})"
    )
    status = "ok" if num_ok == count else "fail"
    return Outcome(status, verdict, measurements, [thumb_line(r) for r in records])


def thumb_paths(ctx: ProbeContext, count: int) -> list[str]:
    """Return `count` JPG paths, the newest first, repeating if the card has fewer."""
    files = ctx.findings.get("files", [])
    jpgs = sorted(path for path in files if file_extension(path) == "JPG")[-count:]
    jpgs = jpgs or [ctx.targets["JPG"]]
    return [jpgs[index % len(jpgs)] for index in range(count)]


def timed_thumb(
    ctx: ProbeContext, path: str, session: requests.Session, suffix: str
) -> dict:
    """Fetch one thumbnail; return its timing, or the error instead of raising."""
    record: dict[str, Any] = {"path": path, "suffix": suffix}
    try:
        exchange = ctx.fetch("GET", f"v1/photos/{path}?size=thumb", suffix, session)
    except Exception as error:
        return {**record, "status": None, "error": f"{type(error).__name__}: {error}"}
    return {
        **record,
        **http_measurements(exchange),
        "status": exchange.status,
        "error": None,
    }


def thumb_time_range(records: list[dict]) -> str:
    times = [record["elapsed_ms"] for record in records if record.get("elapsed_ms")]
    if not times:
        return "no timings"
    return f"each {min(times):.0f}-{max(times):.0f} ms"


def thumb_line(record: dict) -> str:
    result = record["error"] or f"{record['status']} {format_ms(record['elapsed_ms'])}"
    return f"{record['suffix'].lstrip('-')} {record['path']}: {result}"


def probe_download(ctx: ProbeContext, target: str) -> Outcome:
    """Probe 10: timed full download of one file, the baseline for probe 9."""
    destination = ctx.evidence_path(Path(target).suffix.lower())
    exchange = ctx.fetch("GET", f"v1/photos/{target}", stream_to=destination)
    measurements = download_measurements(exchange)
    ctx.findings["download_mb_per_s"] = measurements["mb_per_s"]
    verdict = download_verdict(measurements)
    return Outcome(
        "ok" if download_is_complete(measurements) else "fail", verdict, measurements
    )


def probe_download_with_thumbs(ctx: ProbeContext, target: str) -> Outcome:
    """Probe 9: the same download with thumbnail requests fired during it."""
    destination = ctx.evidence_path("-download" + Path(target).suffix.lower())
    started = threading.Event()

    def note_progress(num_bytes: int):
        if num_bytes >= THUMBS_START_AFTER_BYTES:
            started.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        download = pool.submit(
            ctx.fetch,
            "GET",
            f"v1/photos/{target}",
            "-download",
            stream_to=destination,
            on_chunk=note_progress,
        )
        while not started.wait(0.1) and not download.done():
            pass
        thumbs = fetch_thumbs_during(ctx, download)
        exchange = download.result()
    return download_with_thumbs_outcome(ctx, exchange, thumbs)


def fetch_thumbs_during(ctx: ProbeContext, download: Future) -> list[dict]:
    """Fetch thumbnails one after another, noting whether the download still ran."""
    session = new_session()
    records = []
    for number, path in enumerate(thumb_paths(ctx, THUMBS_DURING_DOWNLOAD), start=1):
        download_was_running = not download.done()
        record = timed_thumb(ctx, path, session, f"-thumb{number}")
        records.append({**record, "download_running": download_was_running})
    return records


def download_with_thumbs_outcome(
    ctx: ProbeContext, exchange: Exchange, thumbs: list[dict]
) -> Outcome:
    measurements = download_measurements(exchange)
    baseline = ctx.findings.get("download_mb_per_s")
    measurements["baseline_mb_per_s"] = baseline
    if baseline:
        change = (measurements["mb_per_s"] / baseline - 1) * 100
        measurements["throughput_change_percent"] = round(change, 1)
    measurements["thumbs"] = thumbs
    num_ok = sum(thumb["status"] == 200 for thumb in thumbs)
    num_overlapping = sum(thumb["download_running"] for thumb in thumbs)
    verdict = (
        f"{download_verdict(measurements)} (alone {baseline} MB/s, "
        f"{measurements.get('throughput_change_percent', '?')}%); thumbs {num_ok}/{len(thumbs)} ok, "
        f"{thumb_time_range(thumbs)}, {num_overlapping}/{len(thumbs)} during the download"
    )
    is_ok = download_is_complete(measurements) and num_ok == len(thumbs)
    return Outcome(
        "ok" if is_ok else "fail",
        verdict,
        measurements,
        [thumb_line(t) for t in thumbs],
    )


def download_measurements(exchange: Exchange) -> dict[str, Any]:
    content_length = header_int(exchange, "Content-Length")
    seconds = exchange.elapsed_ms / 1000
    return {
        **http_measurements(exchange),
        "content_length": content_length,
        "size_matches": content_length == exchange.body_size,
        "seconds": round(seconds, 2),
        "mb_per_s": round(exchange.body_size / MB / seconds, 2) if seconds else None,
    }


def download_is_complete(measurements: dict[str, Any]) -> bool:
    return measurements["http"] == 200 and measurements["size_matches"]


def download_verdict(measurements: dict[str, Any]) -> str:
    match = "matches" if measurements["size_matches"] else "DOES NOT match"
    return (
        f"{measurements['http']} {format_size(measurements['bytes'])} in "
        f"{measurements['seconds']} s = {measurements['mb_per_s']} MB/s, "
        f"size {match} Content-Length {measurements['content_length']}"
    )


# ---------------------------------------------------------------- main


def run_all_probes(ctx: ProbeContext) -> str:
    """Run the probes in order; return how the run ended."""
    props = run_probe(ctx, 1, "props", partial(probe_props, ctx))
    if props.status != "ok":
        ctx.recorder.log(
            f"Cannot reach the camera at {ctx.host}: not on the camera's Wi-Fi? Stopping."
        )
        return "unreachable"
    ctx.findings["battery_at_start"] = props.measurements.get("battery")
    run_probe(ctx, 2, "listing", partial(probe_listing, ctx))
    select_targets(ctx)
    run_preview_and_info_probes(ctx)
    run_typed_probe(ctx, 6, "head", probe_head, "DNG")
    run_typed_probe(ctx, 7, "range", probe_range, "DNG")
    run_parallel_probes(ctx)
    run_download_probes(ctx)
    run_probe(ctx, 11, "props-again", partial(probe_props_again, ctx))
    return "completed"


def select_targets(ctx: ProbeContext):
    ctx.targets = choose_targets(ctx.findings.get("files", []), ctx.options)
    ctx.recorder.run_info["targets"] = ctx.targets
    ctx.recorder.write_results()
    chosen = ", ".join(f"{t}={path or '-'}" for t, path in ctx.targets.items())
    ctx.recorder.log(f"{'':<13}targets: {chosen}")


def run_preview_and_info_probes(ctx: ProbeContext):
    """Probes 3-5, each for a JPG, a DNG and a MOV."""
    probes = (
        (3, "thumb", partial(probe_preview, size="thumb")),
        (4, "view", partial(probe_preview, size="view")),
        (5, "info", probe_info),
    )
    for probe_id, name, probe in probes:
        for file_type in FILE_TYPES:
            outcome = run_typed_probe(ctx, probe_id, name, probe, file_type)
            if name == "thumb" and file_type == "JPG":
                ctx.findings["single_thumb_ms"] = outcome.measurements.get("elapsed_ms")


def run_parallel_probes(ctx: ProbeContext):
    for count in PARALLEL_COUNTS:
        run_probe(
            ctx,
            8,
            f"parallel-x{count}",
            partial(probe_parallel_thumbs, ctx, count),
            skip_reason=missing_target_reason(ctx, "JPG"),
        )


def run_download_probes(ctx: ProbeContext):
    """Probe 10 first, so probe 9 has a baseline to compare against."""
    skip_reason = "--skip-downloads" if ctx.options.skip_downloads else None
    run_typed_probe(ctx, 10, "download", probe_download, "DNG", skip_reason)
    run_typed_probe(
        ctx,
        9,
        "download-with-thumbs",
        probe_download_with_thumbs,
        "DNG",
        skip_reason or missing_target_reason(ctx, "JPG"),
    )


def run_typed_probe(
    ctx: ProbeContext,
    probe_id: int,
    name: str,
    probe: Callable[..., Outcome],
    file_type: str,
    skip_reason: str | None = None,
) -> Outcome:
    """Run a probe against the chosen file of one type, or skip it if there is none."""
    target = ctx.targets[file_type]
    return run_probe(
        ctx,
        probe_id,
        name,
        partial(probe, ctx, target),
        file_type=file_type,
        target=target,
        skip_reason=skip_reason or missing_target_reason(ctx, file_type),
    )


def missing_target_reason(ctx: ProbeContext, file_type: str) -> str | None:
    if ctx.targets.get(file_type):
        return None
    return f"no {file_type} on the card (shoot one, or pass --{file_type.lower()} DIR/FILE)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"camera base URL (default {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="output root (default spike/out/)"
    )
    for file_type in FILE_TYPES:
        parser.add_argument(
            f"--{file_type.lower()}",
            metavar="DIR/FILE",
            help=f"{file_type} to probe instead of the automatic choice, e.g. 100RICOH/R0000001.{file_type}",
        )
    parser.add_argument(
        "--skip-downloads", action="store_true", help="skip the two full DNG downloads"
    )
    options = parser.parse_args()
    if not options.host.endswith("/"):
        options.host += "/"
    return options


def main() -> int:
    options = parse_args()
    run_info = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "host": options.host,
        "argv": sys.argv[1:],
        "python": platform.python_version(),
        "requests": requests.__version__,
    }
    recorder = RunRecorder(options.out, run_info)
    recorder.log(f"Probing {options.host} -> {recorder.dir}")
    ctx = ProbeContext(host=options.host, options=options, recorder=recorder)
    outcome = "interrupted"
    try:
        outcome = run_all_probes(ctx)
    finally:
        recorder.log(f"Run {outcome}. Results: {recorder.dir / 'results.json'}")
        recorder.finish(outcome)
    return EXIT_UNREACHABLE if outcome == "unreachable" else 0


if __name__ == "__main__":
    sys.exit(main())
