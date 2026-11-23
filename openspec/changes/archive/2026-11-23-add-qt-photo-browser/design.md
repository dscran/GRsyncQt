# Design

## Context

See proposal.md for the motivation and specs/ for the required behavior.

Constraints that shape the approach:

- **Camera behavior is measured, not guessed** (`docs/camera-api.md`). The camera
  serves one request at a time, so parallel requests gain nothing. Thumbnails can
  load during a download without slowing it. Listing entries have no sizes or
  dates; `/info` gives `size`, `orientation` and `datetime` in about 55 ms. HEAD
  returns 404 and Range is ignored. Images carry no EXIF and aren't rotated. JPG
  thumbnails are 160×120 and letterboxed; DNG/MOV "thumbnails" are the 720×480 /
  640×360 previews. Downloads run at about 4.8 MB/s, and every response forbids
  HTTP caching.
- **Runtime:** the `general` conda env (Python 3.12, PySide6 6.12, requests,
  pytest; now with pip, but no pytest-qt yet), called directly at
  `~/miniforge3/envs/general/bin/python`. `conda run` doesn't work in Claude's
  shell.
- **Repo today:** `GRsync.py` at the root, `spike/` (probe script and fake
  camera), `docs/camera-api.md`, `.gitignore` (already covers `*.egg-info/`,
  `build/`, `dist/`). No package and no tests.
- **User decisions:** flat destination folder; distribution and command
  `grsync-qt`; session-only thumbnail cache; duplicates by name + size; never
  power off; GR III/IIIx only; `GRsync.py` removed.

## Goals / Non-Goals

**Goals:**
- A small, layered codebase. Camera access, shot grouping, image fixes and
  local file handling are plain Python/Qt-core code, testable without a window.
- The GUI never blocks on the network.
- Every camera-facing behavior in the specs is covered by tests against a fake
  camera that mimics the measured quirks.

**Non-Goals:**
- Reusing spike code. The spike stays as a reference and as a re-runnable probe.
- A generic, multi-camera abstraction.
- Video playback, and any image editing beyond rotation and letterbox removal.
- Ending the camera's Wi-Fi from the app. `POST /v1/device/wlan/finish` is
  reported to end the Wi-Fi without powering the camera off, but it is
  unverified on the GR III. It is deliberately left out to keep the app
  GET-only. It's a possible follow-up change, starting with a manual check
  against the camera.

## Decisions

### Package layout (src layout)

```
pyproject.toml               # setuptools, name grsync-qt, script grsync-qt
src/grsync_qt/
  __main__.py                # python -m grsync_qt
  app.py                     # argparse (--host, --verbose), QApplication, main()
  camera.py                  # CameraClient: GET-only HTTP, props/listing/info/images/download stream
  shots.py                   # listing -> shots, ordering, thumbnail source, download file plan
  images.py                  # letterbox removal, orientation transforms (QImage)
  destination.py             # local folder index, presence check, collision names, temp files
  request_queue.py           # one worker thread for small requests, reprioritizable
  downloader.py              # one worker thread for downloads: plan -> skip/download/verify
  settings.py                # QSettings wrapper (destination, format, geometry, splitter, thumbnail size)
  ui/main_window.py          # toolbar, status (connection, battery), size slider over the grid, splitter, download panel
  ui/shot_model.py           # QAbstractListModel over shots, plus per-shot load state
  ui/shot_delegate.py        # paints thumbnail, name, exposure line, JPG/RAW/MOV badges
  ui/shot_grid.py            # QListView: wanted range, selection kept, Ctrl+wheel size
  ui/preview_pane.py         # zoomable, pannable preview of the current shot (replaces preview_dialog.py)
  ui/formatting.py           # sizes, speeds, durations, exposure text
  ui/download_panel.py       # progress, cancel, summary
tests/
  fake_camera.py             # configurable threaded fake (fixture), records every request
  test_*.py
```

The src layout and setuptools' automatic discovery install only `grsync_qt`, so
`spike/` and `tests/` stay out of the package (spec app-installation). Python
`>=3.11`; dependencies `PySide6>=6.5`, `requests>=2.28`; extra
`dev = [pytest, pytest-qt]`. The command is a `[project.scripts]` entry
`grsync-qt = "grsync_qt.app:main"`. Alternative considered: a flat
`grsync_qt/` package at the root, which is simpler but makes it easy to import
the source tree instead of the installed package in tests.

### HTTP: `requests` in worker threads, not QNetworkAccessManager

`CameraClient` wraps a `requests.Session` with `trust_env = False`, so desktop
proxy settings can't swallow `192.168.0.1`. Timeouts are 5 s connect and 30 s
read (measured worst case 0.42 s). It has a `_get()` that is the only method
able to send anything, so no HEAD, POST or other request is possible: the
read-only guarantee is structural. Downloads stream in 256 KB chunks and check
a cancel flag between chunks, which takes about 50 ms at 4.8 MB/s.

Why not QNetworkAccessManager: it opens up to 6 parallel connections per host
(useless here, since the camera serializes requests), has only a transfer
inactivity timeout and no separate connect timeout, and its callback plumbing
makes plain-pytest integration tests harder. The spike proved `requests`
against this camera.

### Two lanes: a small-request queue and a download worker

Measured: the camera handles one request at a time, and thumbnails during a
download don't slow it down. So:

- **`RequestQueue`**: one daemon thread serving props, listing, `/info`,
  thumbnails and previews from a priority structure. Each request has a key
  (for example `info:113RICOH/R0006483.JPG`). `set_wanted(keys_in_order)`
  replaces the priority order and drops pending requests that are no longer
  wanted, which is how scrolling reprioritizes (spec photo-browsing).
  Preview requests always go first.
- **`Downloader`**: one daemon thread that runs one download plan at a time.

Both deliver results through Qt signals on a QObject that lives in the GUI
thread. Signals emitted from a Python thread are queued to the receiver's
thread automatically, so the GUI only touches results in its own thread.
QImage decoding happens in the worker (QImage is thread-safe; QPixmap isn't).
Alternative considered: QThread with worker objects, which works too but adds
ceremony without any benefit for blocking `requests` calls.

### What a visible shot costs

For each shot entering the wanted range (visible plus one screen of margin,
recomputed 100 ms after scrolling or resizing stops):

1. `/info` of the thumbnail source file. This gives orientation, size and
   datetime. A pair shares orientation and datetime, so one call covers both.
2. `?size=thumb` of the thumbnail source (JPG if present, else DNG, else MOV);
   for a JPG above 160 px thumbnail size, `?size=view` (see Thumbnail size).
3. `/info` of the shot's other file, only if the destination folder holds a
   file with a matching name (see the presence check). Otherwise that file is
   known not to be downloaded, without asking the camera.

That is about 115 ms per shot, or about 9 shots/s, enough for lazy loading.
Results are cached in the model for the session only (user decision). A
full-card `/info` sweep is not done (an open question in `camera-api.md`,
resolved here in favor of lazy loading).

### Image fixes

- **Orientation:** a `QTransform` for EXIF values 1-8, mirrored values
  included, applied to thumbnails and previews. A missing or unknown value
  means no transform (spec: orientation unknown).
- **Letterbox:** trim rows from the top and bottom (and columns from the
  sides) while every pixel in them is near-black (max channel < 24), with at
  most 25 % trimmed per side. This handles the measured 8+8 rows and other
  aspect-ratio settings without depending on `aspectRatio`. It applies to JPG
  thumbnails only; previews aren't letterboxed (720×480 is 3:2). Alternative
  considered: cropping to the `/info` `aspectRatio`, which is fragile if the
  camera pads differently.

### Destination folder: index, presence and collision names

`DestinationIndex` scans the folder once with `os.scandir` into
`{casefolded name: size}`. It's refreshed after each completed file, when the
destination changes and on shot-list refresh. Names are compared
case-insensitively because macOS and Windows file systems are case-insensitive.

- **Name match** for a camera file `R0000001.JPG`: the local names
  `R0000001.JPG` or `R0000001_<n>.JPG` with n ≥ 2.
- **Present:** any name match with the camera file's size (spec: already
  present files skipped).
- **Target name:** the camera name if free, else `<stem>_<n><ext>` with the
  lowest free n ≥ 2 (spec: existing files never overwritten).

### Download flow

The download plan is built in the GUI thread from the selection, in grid
order: for each shot, the files matching the format (`JPG`, `RAW`,
`JPG+RAW`), with videos always included; shots without a matching file are
counted as "not in chosen format". Per file, the worker:

1. If the index has a name match, gets the size via `/info` (or the session
   cache); if present, it counts as already present.
2. Streams the GET into `<dest>/.grsync-qt-<random>.part`, reporting progress
   at most every 250 ms.
3. Checks that the byte count equals `Content-Length` (and the `/info` size if
   known). On a mismatch it deletes the temp file and records a failure.
4. Picks the target name again (the folder may have changed), then
   `os.replace`s the temp file onto it; the name is free, so nothing is
   overwritten.

A connection error or timeout stops the plan: the remaining files are counted
as not attempted, and the connection state goes to Lost. HTTP error statuses
and local write errors fail just that file. Cancel sets the flag; the current
temp file is deleted. Leftover `.grsync-qt-*.part` files from a crash are
deleted when the next download starts. Speed and time remaining come from a
moving average over the last 5 s.

### Connection state

The states are `Disconnected → Connecting → Connected → Lost` (and back to
`Connecting` on retry). Connecting means props, then a model check against
`{"RICOH GR III", "RICOH GR IIIx"}`, then the listing. Any connection error or
timeout in either lane moves to `Lost`: the request queue pauses and keeps its
pending work, and the downloader stops its plan. On retry, the listing is
merged into the model by shot key (`dir/stem`), keeping the selection for
shots still on the card.

### Secrets

`CameraClient.props()` returns a `CameraInfo` dataclass with only `model`,
`battery` and `firmware`. The raw dict never leaves `camera.py`, and logging
records URLs, status and timings, never props bodies. A test feeds the fake
camera props with marker values in `key`, `ssid`, `serialNo`, `macAddress` and
`gpsInfo`, and asserts that they never appear in the captured log output,
window texts or settings file.

### Lighttable layout

The central widget is a horizontal `QSplitter`: the grid on the left, the
preview pane on the right. The splitter state is saved in settings. The pane
follows the grid's current index (not the selection, which may hold many
shots). The preview's `view:` request goes through `RequestQueue`'s urgent
lane, and each new preview request replaces the pending preview keys instead
of adding to them, so holding an arrow key doesn't queue a preview for every
shot passed over. The separate preview dialog (task 6.4) is removed.

### Zoom

The pane is a `QGraphicsView` with one pixmap item: fit-in-view by default,
Ctrl+wheel zooms around the pointer, buttons for zoom in, zoom out, fit and
100 %, and drag to pan (`ScrollHandDrag`). The zoom resets to fit when another
shot becomes current. The zoom range runs from fit to 4× the image's pixels.

The image is the largest preview the camera serves. `docs/camera-api.md`
notes that props list `resoList: ["720x480", "1080x720"]`, but nobody knows
whether or how a 1080×720 preview can be requested. A small GET-only probe
script in `spike/` tries candidate requests against one JPG (other `size`
values and resolution parameters) and records status, type and pixel size,
closing any response that turns out to be a full file. The user runs it on
the camera; its result goes into `docs/camera-api.md`. If a 1080×720 request
exists, the pane uses it (and caches it per session like the other images);
otherwise it zooms the 720×480 preview. Zooming into the full-resolution file
is out of scope.

Result (task 9.4, 2026-11-22): the GR III serves no preview larger than
720×480. Resolution parameters are ignored, and other `size` values answer
with a short JSON body or the full file (`docs/camera-api.md`, "No preview
larger than 720×480"). The pane zooms the 720×480 `?size=view` image.

### Exposure data

`/info` carries `av`, `tv`, `sv` and `xv` as strings. `FileInfo` gains these
four fields, and `ui/formatting.py` turns them into
`ISO 3200 · f/4.5 · 1/4 s · 0 EV`:

- `sv` is the ISO; `auto` (videos) or empty means no ISO.
- `av` is the f-number; `0.0` means none.
- `tv` is `numerator.denominator` seconds: the probe's `"1.4"` is 1/4 s, which
  matches the EXIF ExposureTime of the downloaded probe DNG. `n.1` shows as
  `n s`, `0.0` as none, and anything unparseable as the raw string.
- `xv` is the compensation in EV, shown with a sign (`+0.7 EV`, `−1.3 EV`,
  `0 EV`).

Videos show no exposure line. No request is added: the thumbnail source's
`/info` is already fetched for the orientation. `/info` also has a `gpsInfo`
field; like the props secrets, it never leaves `camera.py`.

### Thumbnail size

A slider at the top of the grid pane (where the preview pane has its zoom
buttons) and Ctrl+wheel over the grid set the thumbnail side
from 96 to 320 px in 16 px steps; the value is saved in settings. The
delegate's cell size and the grid size follow it, and after the change the
grid scrolls the current shot back into view and recomputes the wanted range.

Up to 160 px, JPG shots use `?size=thumb` (160×120). Above 160 px they use
`?size=view` (720×480, 54 KB, about 80 ms instead of 58 ms), which is also the
preview pane's image, so the cache is shared. DNG and MOV thumbnails are
already the 720×480 / 640×360 previews, so their source doesn't change. The
worker scales grid images to fit 320 px; the delegate scales them down to the
current size.

### Settings

`QSettings` in INI format (on every platform, so tests can read the file)
under `grsync-qt/grsync-qt.ini` stores the destination folder, the download
format, the window geometry, the splitter state and the thumbnail size.
Nothing else persists (no thumbnail cache).

### Fake camera for tests

`tests/fake_camera.py` is a new fixture, not the spike's script. It runs a
threaded `http.server` on an ephemeral port and serves a configurable card
(files with sizes, orientation and datetime). It reproduces the measured
quirks: HEAD 404, Range ignored, letterboxed 160×120 JPG thumbnails,
DNG/MOV thumb identical to view, and no-cache headers. Switches allow injected
error statuses, a dropped connection mid-body, delays, and a "camera gone"
mode. Every request is recorded, so tests can assert GET-only and that
`/v1/device/finish` is never called. GUI tests use pytest-qt with
`QT_QPA_PLATFORM=offscreen`.

### Removing GRsync.py

Done last, together with the README rewrite, once the app covers downloading.
Its git history keeps it available.

## Risks / Trade-offs

- [Long sessions are untested: the Wi-Fi may drop or the camera may sleep
  during hour-long downloads] → the Lost state stops cleanly and Retry
  continues with a new plan, where already present files are skipped. The
  README tells users to disable auto power-off.
- [A blocked `requests` read can't be interrupted, so quitting during a stalled
  transfer may wait up to the 30 s read timeout] → the worker threads are
  daemons, and the app doesn't join them on quit. Leftover temp files are
  removed on the next download.
- [`/info` per visible shot doubles the requests compared with thumbnails
  alone] → measured cost is about 55 ms, and it's needed for correct
  rotation. It's cached for the session.
- [Letterbox trimming could eat dark image borders] → limited to JPG
  thumbnails and 25 % per side, and only rows that are completely near-black
  are trimmed.
- [GR IIIx untested] → the model check accepts its expected model string. A
  different string shows "not a supported camera" with the reported model,
  which is easy to diagnose and fix.
- [Case-insensitive presence check on Linux could treat `r0001.jpg` and
  `R0001.JPG` as the same name] → they get distinct sizes or a collision name;
  no data is lost either way.
- [Shutter speed parsing rests on one real sample (`"1.4"` = 1/4 s)] → the
  formatter falls back to the raw string when it can't parse a value, and the
  hardware re-check compares a few shots (a long exposure among them) with
  the camera's display.
- [Large thumbnails cost more] → at 320 px a JPG shot loads 54 KB instead of
  7 KB, about 7 shots/s instead of 9; the images are shared with the preview
  pane.
- [pytest-qt isn't in the env yet] → installed through the `dev` extra
  (`pip install -e ".[dev]"`), which needs network access once.

## Migration Plan

1. Build the app alongside `GRsync.py` until downloads work end to end against
   the fake camera, then on the real GR III.
2. Remove `GRsync.py`, rewrite the README (install, run, camera Wi-Fi, auto
   power-off advice, note that the CLI is gone, GR II unsupported).
3. Rollback: revert the change's commits. `GRsync.py` returns from history.

## Open Questions

- The exact model string of a GR IIIx is assumed to be `RICOH GR IIIx`. If a
  IIIx reports something else, only the accepted-model set changes.
- ~~Whether the camera serves a 1080×720 preview~~: resolved by the
  preview-size probe (task 9.4). It doesn't; the largest preview is 720×480.
