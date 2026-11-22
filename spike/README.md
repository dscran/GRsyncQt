# Camera API spike

`probe_camera.py` checks how the GR III's HTTP API behaves: thumbnails and previews
per file type, whether file sizes are available without downloading, how many
parallel requests the camera handles, and real download speed. The findings go
into `docs/camera-api.md`.

The script is read-only toward the camera: it only sends GET and HEAD, so it
deletes nothing, changes no settings and never powers the camera off.

You run it on your own: joining the camera's Wi-Fi cuts internet access. Every
result is saved on disk, so there is nothing to copy or watch during the run.

## Before you go offline

1. On the camera, shoot **at least one JPG+DNG pair** (image format set to
   RAW+JPEG) and **one short video**. The script probes the newest of each.
2. Charge the battery.
3. Set auto power-off to off or to the longest setting. If the camera sleeps,
   its Wi-Fi drops and the remaining probes fail.
4. Make sure no phone is connected to the camera (close GR Imaging Recorder),
   so the laptop is its only client.
5. Have about 100 MB free. The run downloads the DNG twice into `spike/out/`.

## Run

1. Turn on wireless LAN in the camera's menu and connect this laptop to the
   camera's network (SSID and password as shown or set on the camera). With
   NetworkManager:

   ```sh
   nmcli device wifi connect <camera-SSID> password <password>
   ```

2. From the repo root, run:

   ```sh
   ~/miniforge3/envs/general/bin/python spike/probe_camera.py
   ```

   The `01 props` line should start with `[ok]` and show
   `model='RICOH GR III'`. If the script says `not on the camera's Wi-Fi?` instead, check the connection (with
   `curl http://192.168.0.1/v1/props`, for example) and run it again.

   The run takes about 2 minutes plus the two DNG downloads. Lines marked
   `[fail]` or `[skipped]` are fine; they are findings, and the run keeps going.
   If a probe hangs, each request gives up after 30 s; Ctrl-C also stops the
   run and keeps the results written so far.

   Battery low or in a hurry? Add `--skip-downloads` to leave out the two full
   downloads (probes 9 and 10).

3. Reconnect to your normal network.

## What to bring back

Nothing to copy: the output stays in `spike/out/<timestamp>/` (gitignored,
since it holds your photos). Tell Claude the run is done and mention anything
the script can't see:

- messages on the camera's screen during the run
- whether the camera's Wi-Fi dropped or the camera went to sleep
- the last line of the console output, if the run stopped early

## Options

| Option | Use |
|---|---|
| `--jpg/--dng/--mov DIR/FILE` | probe this file instead of the newest one, e.g. `--mov 100RICOH/R0000123.MOV` |
| `--skip-downloads` | skip probes 9 and 10 |
| `--host URL` | camera address (default `http://192.168.0.1/`) |
| `--out DIR` | output root (default `spike/out/`) |

## Trial run without the camera

`fake_camera.py` stands in for the camera so the script can be tested anywhere.
Start it, then run the command above with `--host` added:

```sh
~/miniforge3/envs/general/bin/python spike/fake_camera.py &
~/miniforge3/envs/general/bin/python spike/probe_camera.py --host http://127.0.0.1:8080/
```

The switches `--no-head`, `--no-range`, `--no-mov`, `--slow` and
`--fail <path-substring>` make the fake misbehave, to exercise the script's
fail and skip paths. The fake proves only that the script works, not anything
about the camera.
