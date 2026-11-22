# Ricoh GR III HTTP API: measured behavior

Findings from one probe run of `spike/probe_camera.py` against a real GR III
(firmware 1.20) over its Wi-Fi on 2026-11-22. This document is the input for the
PySide6 app change.

**Evidence.** Each claim cites a file from that run, written as `[file]` and
relative to `spike/out/20261122-181334/`. That folder is gitignored because it
holds photos and camera secrets, so it exists only on the machine that ran the
probe. To check a claim elsewhere, re-run the spike (`spike/README.md`).

**Test setup.** The card held 620 JPG+DNG pairs and 3 MOVs in two folders
(`112RICOH`, `113RICOH`). The probed files were `113RICOH/R0006483.JPG`/`.DNG`
(a portrait shot, 10.3 MB JPG and 30.8 MB DNG) and `113RICOH/R0006484.MOV`
(8.9 MB) [results.json: `targets`]. The whole run took 15 s [results.json:
`started`, `finished`].

## Endpoints

Base URL `http://192.168.0.1/`. Server header `Crow/0.1` [01-props.http.json].
Only GET requests work (see HEAD below).

| Request | Result | Typical time | Evidence |
|---|---|---|---|
| `GET /v1/props` | 200 JSON, 62 fields | 341–349 ms | [01-props.json], [11-props-again.json] |
| `GET /v1/photos` | 200 JSON, all files, names only | 421 ms (1243 files, 40 KB) | [02-listing.json], [02-listing.http.json] |
| `GET /v1/photos/<dir>/<file>?size=thumb` | 200 `image/jpeg` | 58–88 ms | [03-thumb-*.http.json] |
| `GET /v1/photos/<dir>/<file>?size=view` | 200 `image/jpeg` | 78–109 ms | [04-view-*.http.json] |
| `GET /v1/photos/<dir>/<file>/info` | 200 JSON, 14 fields incl. `size` | 52–61 ms | [05-info-*.json] |
| `GET /v1/photos/<dir>/<file>` | 200 full file with `Content-Length` | headers in 40 ms, 4.8 MB/s | [10-download-DNG.http.json] |
| `HEAD /v1/photos/<dir>/<file>` | **404**, `Content-Length: 15` | 4 ms | [06-head-DNG.http.json] |
| `GET` + `Range: bytes=0-0` | **Range ignored**: 200 with the full `Content-Length` | 41 ms to headers | [07-range-DNG.http.json] |

### `/v1/props`

Selected fields (secrets redacted) [01-props.json]:

```json
{
  "errCode": 200, "errMsg": "OK",
  "manufacturer": "RICOH IMAGING COMPANY, LTD.",
  "model": "RICOH GR III",
  "firmwareVersion": "1.20",
  "battery": 100,
  "hot": false,
  "storages": [
    {"name": "in",  "equipped": true, "available": false, "numOfPhotos": 0,   "numOfMovies": 0},
    {"name": "sd1", "equipped": true, "available": true,  "numOfPhotos": 620, "numOfMovies": 3}
  ],
  "datetime": "2026-11-22T19:49:10",
  "operationMode": "capture",
  "resoList": ["720x480", "1080x720"]
}
```

**props holds secrets.** It also returns the Wi-Fi password (`key`), the
SSID, the serial number, the MAC address and the last GPS position (`gpsInfo`).
The app must never log or display the raw props.

`numOfPhotos` counts shots, not files: 620 matches the 620 JPG+DNG pairs
[01-props.json], [02-listing.json].

### `/v1/photos`

```json
{"errCode": 200, "errMsg": "OK",
 "dirs": [{"name": "112RICOH", "files": ["R0005797.JPG", "R0005797.DNG", ...]},
          {"name": "113RICOH", "files": [..., "R0006483.DNG", "R0006484.MOV"]}]}
```

- Entries are plain strings: **no sizes, no dates** [02-listing.json].
- Order is folder, then file number. A shot's JPG comes directly before its DNG
  [02-listing.json].
- The listing doesn't say which storage the files are on. `in` was unavailable,
  so all of them were on `sd1` [01-props.json].

### `/info`

```json
{"errCode": 200, "errMsg": "OK", "cameraModel": "RICOH GR III",
 "dir": "113RICOH", "file": "R0006483.JPG", "size": 10285531,
 "datetime": "2026-11-22T18:29:32", "orientation": 6, "aspectRatio": "3:2",
 "av": "4.5", "tv": "1.4", "sv": "3200", "xv": "0.0", "gpsInfo": ""}
```

The same 14 fields come back for JPG, DNG and MOV. For the MOV, `cameraModel`
is `""`, `orientation` is 0 and `aspectRatio` is `4:3` [05-info-MOV.json].
`size` equals the downloaded byte count exactly (DNG: 30802725) [05-info-DNG.json],
[10-download-DNG.http.json].

## Thumbnails and previews per file type

| Type | `?size=thumb` | `?size=view` | Evidence |
|---|---|---|---|
| JPG | 160×120, 7.0 KB, 58 ms | 720×480, 54.0 KB, 78 ms | [03-thumb-JPG.jpg], [04-view-JPG.jpg] |
| DNG | 720×480, 54.0 KB, 79 ms (**same as view**) | 720×480, 54.0 KB, 92 ms | [03-thumb-DNG.jpg], [04-view-DNG.jpg] |
| MOV | 640×360, 126.8 KB, 88 ms (**same as view**) | 640×360, 126.8 KB, 108 ms | [03-thumb-MOV.jpg], [04-view-MOV.jpg] |

- Only JPGs have a real small thumbnail. For DNG and MOV, `thumb` returns the
  same bytes as `view`, and for a JPG+DNG pair the two `view` images are
  byte-identical too (checked with `cmp`).
- **Images are not rotated and carry no EXIF.** The portrait shot
  (`orientation: 6`) comes back landscape, and Qt's auto-transform finds nothing
  to apply. Rotation has to come from the `/info` `orientation` field
  (EXIF semantics: 6 means rotate 90° clockwise) [03-thumb-JPG.jpg],
  [04-view-JPG.jpg], [05-info-JPG.json].
- **The JPG thumbnail is letterboxed.** The 3:2 picture sits in a 4:3 frame with
  8 black rows at the top and bottom, so 160×104 is picture [03-thumb-JPG.jpg].
- Every image and file response sends `Cache-Control: no-store, no-cache`
  [03-thumb-JPG.http.json], so any caching is up to the app.

### No preview larger than 720×480

A second probe, `spike/probe_preview_sizes.py`, ran on the same GR III on
2026-11-22 against `113RICOH/R0006483.JPG`. It tried 23 GET requests for a
larger preview [`spike/out/20261122-200738-preview-sizes/results.json`]:

- Only `?size=thumb` (160×120) and `?size=view` (720×480, 55 KB) return
  preview images. Extra parameters (`reso`, `resolution`, `res`, `width`
  with `1080x720` or `1080`) are ignored: the answer is the same 720×480
  `view` image.
- Other `size` values (`xs`, `s`, `m`, `l`, `xl`, `large`, `hd`, `fullhd`,
  `preview`, `1080`, `1080x720`, `720x480`) answer 200 with a 51-byte JSON
  body instead of an image (the probe didn't save the body).
- `?size=full`, and a query without `size` (`?reso=1080x720`), return the
  full file (Content-Length 10285531).
- The path suffixes `/view` and `/preview` answer 404.

So `resoList` doesn't apply to stored photos (it's probably the live view's
resolutions). The largest preview is 720×480; anything sharper means
downloading the full file.

### Exposure fields in `/info`

`av` is the f-number, `sv` the ISO (`auto` for videos), `xv` the exposure
compensation in EV, and `tv` the shutter speed as `numerator.denominator`
seconds: `"1.4"` for R0006483 matches its EXIF ExposureTime of 1/4 s
[05-info-JPG.json], [10-download-DNG.dng]. Videos report `av` `0.0`,
`tv` `0.0`, `sv` `auto` and `xv` `0.0` [05-info-MOV.json].

## File size without downloading (duplicate detection)

| Source | Works? | Evidence |
|---|---|---|
| Listing | no, names only | [02-listing.json] |
| `/info` `size` | **yes**, exact, 52–61 ms per file | [05-info-*.json] |
| HEAD | no, 404 | [06-head-DNG.http.json] |
| Range `bytes=0-0` | no, ignored, full 200 response | [07-range-DNG.http.json] |
| GET, close after headers | yes, `Content-Length` arrives in about 40 ms | [07-range-DNG.http.json] |

**Use `/info` `size`.** It's exact and as fast as the abort-after-headers trick,
without leaving a transfer half open. Since name + size decides duplicates,
the app only needs a size for files whose name already exists locally.

## Concurrency

- **The camera serves one request at a time.** Four parallel thumbnail requests
  all succeeded, but finished at 57, 98, 143 and 234 ms, and the batch took
  238 ms. That's the same as four in a row (4 × 58 ms). Two in parallel: 62 and
  106 ms, 108 ms in total [08-parallel-x4-thumb*.http.json],
  [08-parallel-x2-thumb*.http.json], [results.json: probe 8]. Parallel requests
  cause no errors, but they gain nothing either.
- **Thumbnails don't need to pause during downloads.** With three thumbnail
  requests during a DNG download, the download ran at 4.85 MB/s versus 4.81 MB/s
  alone, and the thumbnails took 63–127 ms versus 58 ms alone. All three really
  ran during the download [results.json: probes 9 and 10],
  [09-download-with-thumbs-DNG-thumb*.http.json].
- Sample sizes were small: one download and 2–4 requests per test.

## Throughput and timeouts

- Full download: 30802725 bytes in 6.11 s, **4.8 MB/s**. The size matched
  `Content-Length` and `/info` `size` [10-download-DNG.http.json],
  [10-download-DNG.dng]. At that rate a 10 MB JPG takes about 2 s and a
  30 MB DNG about 6 s, so all 620 pairs (around 25 GB) would take about 1.4 h.
- No resume: Range is ignored, so a broken transfer starts again from zero
  [07-range-DNG.http.json].
- Slowest time to headers: the listing at 412 ms (1243 files; it grows with
  the card) [02-listing.http.json]. props takes about 345 ms; everything else
  under 110 ms.
- Recommended timeouts: **5 s connect, 30 s read** (the spike's values). The
  slowest observed wait was 0.42 s, so neither ever came close, and the read
  timeout applies per chunk for downloads.

## Quirks

- `HEAD` returns 404 even for files that exist [06-head-DNG.http.json].
- The `Date` header says GMT but carries the camera's local clock: `19:49:11 GMT`
  next to props `datetime` `19:49:10` [01-props.json], [02-listing.http.json].
- The camera clock was about 1 h 36 min ahead of the laptop: props said
  `19:49:10` when the run started at `18:13:34` laptop time [01-props.json],
  [results.json: `started`]. `/info` `datetime` has no time zone. It's fine for
  display and sorting, but not for comparing with computer times.
- `Server`, `Date` and `Connection: Keep-Alive` appear on JSON and error
  responses only; image and file responses send none of them
  [02-listing.http.json], [06-head-DNG.http.json], [03-thumb-JPG.http.json].
- The camera kept answering after the whole run, with the battery still at
  100 % [11-props-again.json].

## GR IIIx

Not tested. It is assumed to behave the same, and to report
`model: "RICOH GR IIIx"`, the string the former `GRsync.py` script listed in `SUPPORT_DEVICE`.
To confirm, re-run `spike/probe_camera.py` on a IIIx unchanged.

## For the app

### Decisions the app change can make now

1. **Camera check:** `GET /v1/props`, accepting `model` values `RICOH GR III`
   and `RICOH GR IIIx`. Show `battery`. Never log or display raw props (they
   contain the Wi-Fi password).
2. **Shot list:** one `GET /v1/photos`, grouping each JPG and DNG with the same
   name into one shot; MOVs are shots of their own. The listing has no
   size or date, so these come from `/info` when needed.
3. **Grid thumbnails:** a shot with a JPG uses the JPG's `?size=thumb` (7 KB).
   A DNG-only shot uses the DNG's `?size=thumb` (actually 720×480, 54 KB) and a
   MOV its `?size=thumb` (640×360, 127 KB); both get scaled down. Crop or allow
   for the letterbox on JPG thumbnails.
4. **Rotation:** rotate thumbnails and previews by `/info` `orientation`, since
   the images carry no EXIF. Each visible shot therefore needs its `/info`,
   about 55 ms.
5. **Large preview:** `?size=view` (720×480, or 640×360 for MOV). For a JPG+DNG
   pair, request one of them only, as they are identical.
6. **Duplicates (name + size):** get the size from `/info` `size`, and only
   for files whose name already exists locally.
7. **Request queue:** a single worker (at most 2) for all small requests, with
   visible items first. Parallelism gains nothing, and the queue keeps running
   during downloads.
8. **Downloads:** one at a time. Write to a temporary file, check the byte
   count against `Content-Length`, then rename. Cancelling or an error
   means starting over, since there is no resume. Show progress; a full card
   takes hours.
9. **Caching:** the camera forbids HTTP caching, so the app caches thumbnails
   and `/info` itself, keyed by `dir/file` (+ size).
10. **Timeouts:** 5 s connect, 30 s read.
11. **HTTP client:** only GET is needed. Never HEAD, never Range, and never
    `/v1/device/finish`.

### Still open

- **GR IIIx:** untested (see above).
- **Long sessions:** the run lasted 15 s. It's unknown how the camera's Wi-Fi
  and auto power-off behave over a download lasting minutes or hours.
- **Large cards:** listing time was measured at 1243 files only.
- **Loading `/info`:** whether to fetch it for all shots up front (about 620 ×
  55 ms ≈ 34 s here) or lazily for visible ones only. This is a UX choice;
  lazy loading is the obvious default.
- **Folder rollover and other storage:** neither was seen (all files were on
  `sd1`, numbering below 9999).
- **Connection reuse:** whether keeping connections alive changes latency
  wasn't measured.
