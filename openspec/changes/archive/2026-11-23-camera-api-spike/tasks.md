# Tasks

Interpreter for every command: `~/miniforge3/envs/general/bin/python` (written as `PY` below).

## 1. Setup

- [x] 1.1 Create `spike/` and `docs/`, and add a standard Python `.gitignore` (`__pycache__/`, `*.py[cod]`, `*.egg-info/`, `build/`, `dist/`, `.venv/`) plus `spike/out/`; verify `git check-ignore spike/out/x.jpg spike/__pycache__/x.pyc` prints both paths and `git check-ignore spike/probe_camera.py` prints nothing

## 2. Fake camera

- [x] 2.1 Write `spike/fake_camera.py` (stdlib `http.server`, `--port`, default 8080) serving `/v1/props` and `/v1/photos` (one dir with a JPG+DNG pair, a JPG-only shot and a MOV); verify with `curl -s 127.0.0.1:8080/v1/photos` while it runs
- [x] 2.2 Serve `/v1/photos/<dir>/<file>` with `?size=thumb|view` (small generated JPEGs) and full files (a few MB of filler), plus `/info`; answer HEAD and `Range: bytes=0-0` with a `206`; verify with `curl -I` and `curl -r 0-0 -D -`
- [x] 2.3 Add switches (`--no-head`, `--no-range`, `--no-mov`, `--slow`, `--fail <path-substring>`) so fail/skip paths can be triggered; verify each switch changes the curl response as expected

## 3. Probe script framework

- [x] 3.1 Write `spike/probe_camera.py` with CLI `--host` (default `http://192.168.0.1/`), `--out`, `--jpg/--dng/--mov`, `--skip-downloads`; verify `PY spike/probe_camera.py --help`
- [x] 3.2 Add the request helper that allows only GET/HEAD (5 s connect / 30 s read timeouts) and records method, URL, status, headers, elapsed time and body size; verify that a call with `POST` raises before any network I/O (quick inline check)
- [x] 3.3 Add run output: a timestamped dir under `spike/out/`, an evidence writer (pretty JSON / image by Content-Type / first 4 KB otherwise), an incrementally written `results.json`, `run.log` and one-line console verdicts; verify an empty run against the fake camera produces the dir, the log and a valid `results.json`
- [x] 3.4 Add per-probe isolation (exception becomes `fail` with traceback saved, missing target becomes `skipped`) and the early abort when props is unreachable; verify against a closed port that the script exits with the "not on the camera's Wi-Fi?" message

## 4. Probes

- [x] 4.1 Probes 1–2 (props dump, listing dump) plus automatic choice of the JPG+DNG pair and the MOV, with `--jpg/--dng/--mov` overrides; verify the chosen targets against the fake camera, and with `--no-mov`
- [x] 4.2 Probes 3–5 (thumb, view, info) per file type, with pixel size via `QImage.fromData`; verify all `ok` against the fake camera, and `fail` lines with `--fail size=view`
- [x] 4.3 Probes 6–7 (HEAD, Range 0-0) on the full DNG, recording whether a size was obtainable without the body; verify `ok` normally and a clear verdict with `--no-head` / `--no-range`
- [x] 4.4 Probe 8 (2 and 4 parallel thumb requests, per-request timing and errors); verify against the fake camera with `--slow` that timings show up per request
- [x] 4.5 Probe 10 (timed full DNG download, MB/s) then probe 9 (the same download with thumbnail requests fired during it, comparing throughput to probe 10), both off with `--skip-downloads`, then a closing props re-check; verify the downloaded file size matches Content-Length against the fake camera

## 5. Trial run and run instructions

- [x] 5.1 Full trial run against the fake camera with default switches, then with `--no-mov --no-head --no-range --fail size=view`; verify the run completes both times with no unhandled exception and the expected ok/fail/skipped mix in `results.json`
- [x] 5.2 Write `spike/README.md` for the offline run: preconditions (shoot a JPG+DNG pair and a short video, battery charged, auto power-off disabled or long), joining the camera Wi-Fi, the exact command with the full interpreter path, what to bring back; verify by following it against the fake camera with only the host changed

## 6. Hardware run (user, offline)

- [x] 6.1 User runs `spike/probe_camera.py` on the GR III over its Wi-Fi following `spike/README.md`, reconnects to the internet and reports back; verify a `spike/out/<timestamp>/results.json` exists with an entry for every probe

## 7. Analysis

- [x] 7.1 Review `results.json` and the evidence files; if a probe failed for a script reason (not a camera finding), fix it and request a re-run of only that probe; verify every probe has a camera-based verdict
- [x] 7.2 Write `docs/camera-api.md`: endpoint table with real examples, thumb/view/info matrix per file type, chosen size source for duplicate detection, concurrency and download-pause guidance, measured throughput and recommended timeouts, quirks, GR IIIx assumption; verify each claim cites a file in the run output
- [x] 7.3 List the decisions the PySide6 app change can now make and the ones still open; verify they appear in a "For the app" section of `docs/camera-api.md`

## Workflow follow-up

- Start the PySide6 photo browser change (`/opsx:propose`) from `docs/camera-api.md`.
- Archive `camera-api-spike` once the notes are reviewed.
