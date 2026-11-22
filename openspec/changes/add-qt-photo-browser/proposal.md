# Proposal

## Why

`GRsync.py` can only bulk-download by file name ranges from a terminal. It shows
nothing of what is on the card, and it has known bugs: a 2 s global timeout, an
automatic power-off of the camera, and broken error paths. Picking a few shots
from a full card means guessing file numbers. Now that the camera API spike has
measured how a GR III actually behaves (`docs/camera-api.md`), a desktop app can
be designed on real data: browse the card as thumbnails and download only the
chosen shots, as JPG, RAW or both.

## What Changes

- New PySide6 desktop app `grsync-qt` for the Ricoh GR III and GR IIIx over the
  camera's Wi-Fi:
  - connects to the camera, checks the model and shows the battery level, and
    offers a retry when the laptop isn't on the camera's Wi-Fi
  - shows every shot on the card in a thumbnail grid, newest first. A JPG and
    a DNG with the same name form one shot; videos (MOV) are shown too.
    Thumbnails load lazily, visible ones first, and are rotated correctly.
  - shows the card as a lighttable: the grid on the left, and a large,
    zoomable preview of the current shot in a split on the right
  - shows ISO, aperture, shutter speed and exposure compensation under each
    thumbnail and in the preview
  - lets the user change the thumbnail size with a slider or Ctrl+mouse wheel,
    like a file manager
  - downloads the selected shots as JPG, RAW (DNG) or both (videos as MOV)
    into one flat destination folder, one file at a time, with progress and
    cancel. Files already there (same name and size) are skipped, and no
    existing file is ever overwritten.
  - talks to the camera read-only: it never deletes, never changes settings and
    never powers the camera off
- The repo becomes a pip-installable package (`pip install .` from a checkout).
  It installs the `grsync-qt` command. There is no PyPI release.
- Tests: plain pytest for the logic, plus integration tests against a fake
  camera server.
- **BREAKING**: `GRsync.py` and its command-line interface are removed, and the
  README is rewritten for the app. GR II support ends with it.

Out of scope: GR II, deleting photos on the camera, changing camera settings,
ending the camera's Wi-Fi from the app (`POST /v1/device/wlan/finish`,
unverified; possible follow-up), remote shooting, a persistent thumbnail cache (thumbnails are cached for the
running session only), zooming into the full-resolution file (zoom uses the
largest preview the camera serves, 720×480; a probe found nothing larger),
resuming
interrupted downloads (the camera ignores Range), and publishing to PyPI.

## Capabilities

### New Capabilities
- `camera-connection`: finding the camera, checking the model, reporting battery
  and connection state, and the read-only guarantee toward the camera.
- `photo-browsing`: the shot list, grouping JPG/DNG/MOV files into shots,
  lazily loaded and correctly rotated thumbnails, adjustable thumbnail size,
  exposure data, the zoomable preview pane, selection and refresh.
- `photo-download`: downloading selected shots in the chosen format to a flat
  local folder, duplicate detection by name and size, safe naming when names
  collide, verification, progress, cancel and error handling.
- `app-installation`: installing the app with pip from the repo and launching
  it with the `grsync-qt` command.

### Modified Capabilities
None (no existing specs).

## Impact

- New package `src/grsync_qt/`, plus `pyproject.toml` and `tests/`.
- Removed: `GRsync.py`. Rewritten: `README.md`. `spike/` and
  `docs/camera-api.md` stay as references.
- Dependencies: `PySide6`, `requests`. Dev: `pytest`, `pytest-qt`.
- Runtime used for development: the `general` conda env (Python 3.12,
  PySide6 6.12), called directly at `~/miniforge3/envs/general/bin/python`.
- Camera API facts and limits come from `docs/camera-api.md`. GR IIIx behavior
  is assumed to match the GR III (untested).
