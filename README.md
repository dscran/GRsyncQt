# GRsync

GRsync is a desktop app (`grsync-qt`) for the **Ricoh GR III and GR IIIx**. Over
the camera's Wi-Fi, it shows the photos and videos on the card as thumbnails,
and downloads the shots you pick as JPG, RAW (DNG) or both.

- Browse every shot on the card like a lighttable, newest first. A JPG and a
  DNG with the same name are one shot. Videos (MOV) are shown too. Thumbnails
  load as you scroll and are shown upright, with ISO, aperture, shutter speed
  and exposure compensation under each one.
- Change the thumbnail size with the slider above the grid, or with
  Ctrl+mouse wheel over the grid (96 to 320 pixels).
- The shot you click (or move to with the arrow keys) appears large in the
  preview pane on the right, with its file names, sizes, capture date and
  exposure. Zoom with Ctrl+mouse wheel or the −, +, Fit and 100 % buttons, and
  drag to pan. Drag the divider to give the grid or the preview more room.
- Select shots (click, Ctrl/Shift-click, Select all) and download them as JPG,
  RAW or JPG+RAW into one folder, with progress and cancel. Videos are always
  downloaded as MOV.
- Files already in the folder are skipped, and existing files are never
  overwritten.
- The app only reads from the camera. It never deletes photos, never changes
  settings and never turns the camera off.

## Install

You need Python 3.11 or newer with pip. From a checkout of this repository:

```bash
pip install .
```

This installs the `grsync-qt` command, and PySide6 and requests if they are
missing. For development (editable install plus pytest and pytest-qt):

```bash
pip install -e ".[dev]"
```

## Use

1. On the camera, turn on Wi-Fi (smartphone connection). For long downloads,
   set the camera's auto power-off to off, or the camera may turn off halfway.
2. Join the camera's Wi-Fi network (the camera shows its name and password
   in its Wi-Fi settings) on your computer.
3. Start the app:

   ```bash
   grsync-qt
   ```

   or `python -m grsync_qt`. It connects to the camera at
   `http://192.168.0.1/`. If the computer isn't on the camera's Wi-Fi yet,
   join it and choose **Retry**.
4. Select shots, pick the format (JPG, RAW or JPG+RAW), and choose
   **Download**. The first time, the app asks for the destination folder; it
   remembers it, and the format, for next time.

`grsync-qt --help` lists the options. `--host URL` talks to another address
(for testing), and `--verbose` logs every camera request.

### Where files go

All files are saved directly in the destination folder, under the camera's
file name (`R0006483.JPG`, `R0006483.DNG`), without camera subfolders.

- A file is skipped as **already present** when the folder holds a file with
  the same name and the same size.
- If the folder holds a *different* file with that name, the download is saved
  as `R0006483_2.JPG` (the lowest free number from 2 up). Nothing is ever
  overwritten.
- A file only appears once all its bytes have arrived and match the size the
  camera announced. An interrupted transfer leaves nothing behind; download it
  again (the camera can't resume transfers).

The grid marks each file of a shot (JPG, RAW, MOV) that is already in the
destination folder with a filled badge.

## Development

Run the tests (they use a fake camera and never open a window):

```bash
python -m pytest
ruff check src tests
ruff format --check src tests
```

To try the app without a camera, start the fake camera and point the app at
it:

```bash
python tests/fake_camera.py --port 8080 --files 1243 --chunk-delay 0.013
grsync-qt --host http://127.0.0.1:8080/
```

- `docs/camera-api.md` describes how a real GR III's HTTP API behaves, as
  measured by the probe in `spike/`.
- `spike/` holds that probe script (see `spike/README.md`) and its own fake
  camera. It isn't part of the installed app.

## No longer supported

The command-line script `GRsync` and the Ricoh GR II are no longer supported.
To use the old script, check out a revision before it was removed.

## Credits

Based on [clyang/GRsync](https://github.com/clyang/GRsync). Thanks to
[@imkojima](https://github.com/imkojima) for the original GR III fix.
