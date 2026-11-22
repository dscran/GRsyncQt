# Design

## Context

See proposal.md for the motivation and the list of probes.

Constraints that shape the approach:

- **Claude can't help during the run.** Joining the camera's Wi-Fi drops internet
  access, so the user runs the script alone and Claude reads its output afterwards.
  A script bug found only on the camera costs a full reconnect cycle.
- **Runtime:** the `general` conda env at `~/miniforge3/envs/general` (Python 3.12,
  `requests`, PySide6 6.12). `conda run -n general` doesn't work in Claude's shell,
  so the interpreter is called directly.
- **Camera:** GR III on hand. It's reached at `http://192.168.0.1/`, and the only
  known endpoints are the four used by `GRsync.py` (`/v1/props`, `/v1/photos`,
  `/v1/photos/<dir>/<file>`, `POST /v1/device/finish`).
- The repo has no `.gitignore` and no package structure. `GRsync.py` sits at the root.

## Goals / Non-Goals

**Goals:**
- One run on real hardware answers every probe question in the proposal.
- The output is complete enough to analyze offline without asking the camera again.
- The script is debugged before the user goes offline.

**Non-Goals:**
- Reusable client code for the app. The spike may be messy, and the app change will
  design its own `CameraClient`.
- Automated tests beyond a local trial run against the fake camera.
- Supporting cameras other than GR III / IIIx.

## Decisions

### File layout

```
spike/
  probe_camera.py      # the probe script
  fake_camera.py       # minimal stand-in server for trial runs
  out/<timestamp>/     # run output (gitignored)
docs/
  camera-api.md        # findings, written after the run; input to the app change
.gitignore             # new: standard Python ignores + spike/out/
```

The `.gitignore` starts as a standard Python one (bytecode, `*.egg-info/`,
`build/`, `dist/`, `.venv/`), so the later pip-installable app change only extends
it. `spike/` and `docs/` sit outside the future `src/` package and won't be
included in the installed app.

`spike/` stays in the repo after the change so the probes can be re-run after a
firmware update or on a GR IIIx. The notes go in `docs/` because they outlive the
spike. Alternatives: putting everything under `openspec/changes/...` would be
archived along with the change and hidden from the app work; the user's wiki is
written only on request.

### Only GET and HEAD can be sent

All requests go through one helper that accepts only `GET` and `HEAD`. Any other
method raises before the network is touched. That guarantees the proposal's
"read-only, never `POST /v1/device/finish`" rule, instead of relying on the script
author's care.

### HTTP library: `requests`

It's already in the env, and it makes HEAD, `Range` headers, streaming downloads
with timing, and access to raw response headers easy. Threads
(`concurrent.futures`) are enough for probes 8–9. Alternative: stdlib `urllib`,
which `GRsync.py` uses, but that means more code for HEAD and streaming and gives
no extra portability, since the env is fixed. The app may use
`QNetworkAccessManager` later, but that decision belongs to the app change.

### Choosing test files automatically, with overrides

Probe 2's listing provides the targets: the newest `.JPG` that has a `.DNG` with
the same name (so JPG/DNG thumbnails can be compared for the same shot), that DNG,
and the newest `.MOV`. Flags `--jpg`, `--dng` and `--mov` (`<dir>/<file>`)
override the choice. If a type is missing, its probes are recorded as `skipped`
with a reason rather than failing. Alternative: hard-coded file names, which would
break on any card and need an extra trip to fix.

Precondition for the user: shoot at least one JPG+DNG pair and one short video
before running.

### Order and isolation of probes

Probes run in the proposal's order. Probe 1 (props) also serves as the
connectivity check: if it fails, the script stops at once with a "not on the
camera's Wi-Fi?" message. After that, each probe runs in its own `try` block. An
exception becomes a `fail` result with the traceback saved, and the run
continues. Probes 3–7 run once per file type; probes 8–10 use the JPG thumbnail
and the DNG full file.

Probe 10 (DNG download by itself, timed) runs **before** probe 9, so probe 9
(the same download, with thumbnail requests fired during it) has a baseline for
measuring any slowdown. The two cost about 2 × 25–30 MB over Wi-Fi. That's
acceptable; `--skip-downloads` turns them off.

### Timeouts

5 s to connect, 30 s per read. That's long enough not to confuse a slow camera
with a broken endpoint (`GRsync.py`'s global 2 s caused flaky failures). Every
request records the time it took, so the app can pick its timeouts from real
data.

### Output format

Each run gets `spike/out/<YYYYmmdd-HHMMSS>/`, containing:

- `results.json`: one entry per probe and file type, with `{id, name, target,
  status: ok|fail|skipped, verdict, measurements}`.
- `NN-<probe>[-<type>].*`: raw evidence. For every request: method, URL, status,
  response headers, elapsed time, body size. Bodies are saved as JSON
  (pretty-printed), images (extension taken from `Content-Type`), or the first
  4 KB if the type is unknown. Full-size downloads are saved too, so a corrupt or
  truncated transfer would show.
- `run.log`: a copy of the console output.

The console prints one line per probe, for example
`[ok]   03 thumb JPG  200 image/jpeg 160x120 7.9 KB 84 ms`.

Image pixel sizes come from `QImage.fromData` (PySide6 is in the env; no
`QApplication` is needed). If that fails, the size is recorded as unknown. That
avoids writing a JPEG header parser.

### Fake camera for trial runs

`fake_camera.py` is a stdlib `http.server` serving canned versions of the known
endpoints: props, a listing with a JPG+DNG pair and a MOV, and `?size=` variants
returning small generated images. On request it can also answer HEAD and
`Range`, return an error, or respond slowly. A trial run against it
(`--host http://127.0.0.1:8080/`) exercises every code path, including the
`fail`/`skipped` handling, before the user goes offline. It doesn't need to match
the real camera; it only needs to make each branch of the script run.

### Analysis

After the run, Claude reads `results.json` and the saved bodies and writes
`docs/camera-api.md`. It covers: an endpoint table with real request/response
examples; a thumb/view/info matrix per file type; which size source to use for
duplicate detection (list > `/info` > HEAD > Range > abort-after-headers); how
much concurrency the camera handles and whether thumbnails must pause during
downloads; measured throughput and recommended timeouts; and any quirks.

## Risks / Trade-offs

- [The camera rejects or mishandles HEAD/Range, or drops its Wi-Fi under parallel
  load] → each probe is isolated; the props probe re-runs at the end to check the
  camera still answers. A dropped connection is itself a finding for the app.
- [The camera's auto power-off or Wi-Fi timeout fires mid-run] → the run is short
  (under 2 min apart from downloads). The user disables auto power-off or keeps
  the camera awake. Partial results are still written after each probe.
- [The card holds no MOV or no JPG+DNG pair] → precondition listed above; missing
  types are `skipped` with a clear reason, not a crash.
- [The fake camera gives false confidence] → it tests the script's code paths only;
  every API claim in `docs/camera-api.md` must cite real-camera output.
- [Probe output contains the user's photos] → `spike/out/` is gitignored and never
  committed or uploaded.
- [GR IIIx untested] → recorded as an assumption in `docs/camera-api.md`. The
  script can be re-run on a IIIx later without changes.
