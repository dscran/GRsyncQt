# Proposal

## Why

The planned PySide6 photo browser for the Ricoh GR III / GR IIIx relies on camera
HTTP behavior that nobody has checked against a real camera: thumbnail and preview
sizes per file type, whether file sizes can be read without downloading the file,
and how many requests the camera's server can handle at once. `GRsync.py` uses only
four endpoints and is buggy, so it can't answer these questions. A short hardware
spike will settle them before the app is designed, so the design starts from real
data instead of assumptions.

## What Changes

- Add a standalone probe script that runs a fixed set of checks against a
  connected GR III / IIIx and records the results:
  1. `GET /v1/props`: full dump (model string for III vs IIIx, battery, other fields)
  2. `GET /v1/photos`: raw dump (are sizes or dates included? how do MOV files appear?)
  3. `?size=thumb` on a JPG, a DNG and a MOV: works or not, byte size, pixel size, latency
  4. `?size=view` on a JPG, a DNG and a MOV: the same
  5. `GET /v1/photos/<dir>/<file>/info` on a JPG, a DNG and a MOV: metadata fields, whether a size is included
  6. `HEAD` on a full-size file: is `Content-Length` returned without the body?
  7. `GET` with `Range: bytes=0-0`: `206` + `Content-Range`? (size check, future resume)
  8. 2-4 parallel thumbnail requests: does the server handle them, queue them, or fail?
  9. A thumbnail request during a full download: does it stall either transfer?
  10. Timed full download of one DNG: real throughput, a sensible timeout
- The script works fully offline. Joining the camera's Wi-Fi cuts internet access,
  so Claude can't watch the run. Each probe writes its raw responses (JSON, headers,
  images) to an output folder and prints a one-line verdict. Probes that fail are
  recorded, and the run continues.
- Read-only toward the camera: no deletes, no settings changes, and never
  `POST /v1/device/finish` (no power-off). Full downloads (probes 9-10) go only to
  the output folder.
- After the run, with internet back, write the findings into a camera API notes
  document. That document is the input for the follow-up PySide6 app change.
- `GRsync.py` is not modified. Its bugs were catalogued during exploration and don't
  matter for the spike.

Out of scope: GR II support, any Qt/GUI code, download logic for the app,
duplicate detection (decided separately: file name + size comparison, with the
size source chosen based on probes 2, 5, 6 and 7).

## Capabilities

### New Capabilities
None. This is a one-off investigation tool and does not add lasting product behavior.

### Modified Capabilities
None.

The change should therefore set `skip_specs: true` in its `.openspec.yaml`.

## Impact

- New files: probe script and camera API notes (exact location decided in design).
- Probe output contains thumbnails and full-size copies of the user's photos, so it
  should not be committed.
- Runtime: the existing `general` conda env (Python 3.12, `requests` available).
  No new dependencies, so nothing needs installing while offline on the camera Wi-Fi.
- Hardware: a GR III (available). GR IIIx behavior is assumed to match; the model
  string reported by `/v1/props` is the only IIIx-specific fact needed now.
