import os

import pytest
from fake_camera import FakeCamera, FakeFile, file_content

from grsync_qt import downloader as downloader_module
from grsync_qt.downloader import Downloader, SpeedMeter

TIMEOUT_MS = 10000
TEN_JPGS = [f"100RICOH/R00000{n:02d}.JPG" for n in range(1, 11)]


@pytest.fixture
def camera():
    card = [FakeFile("100RICOH", path.split("/")[1]) for path in TEN_JPGS]
    camera = FakeCamera(card=card).start()
    yield camera
    camera.stop()


@pytest.fixture
def downloader(camera, qtbot):
    return Downloader(camera.url)


def run_plan(downloader, qtbot, files, folder, **kwargs):
    with qtbot.waitSignal(downloader.finished, timeout=TIMEOUT_MS) as signal:
        downloader.start(files, folder, **kwargs)
    return signal.args[0]


def local_copy(camera, folder, path):
    file_name = path.split("/")[1]
    (folder / file_name).write_bytes(file_content(camera.file(path)))


def test_downloads_a_file_with_its_camera_name(camera, downloader, qtbot, tmp_path):
    summary = run_plan(downloader, qtbot, TEN_JPGS[:1], tmp_path)

    assert summary.downloaded == TEN_JPGS[:1]
    content = (tmp_path / "R0000001.JPG").read_bytes()
    assert content == file_content(camera.file(TEN_JPGS[0]))


def test_mixed_result(camera, downloader, qtbot, tmp_path):
    for path in TEN_JPGS[:3]:
        local_copy(camera, tmp_path, path)
    camera.errors["/v1/photos/" + TEN_JPGS[5]] = 500

    summary = run_plan(downloader, qtbot, TEN_JPGS, tmp_path, not_in_format=2)

    assert len(summary.downloaded) == 6
    assert summary.already_present == TEN_JPGS[:3]
    assert summary.failed == [(TEN_JPGS[5], "camera answered HTTP 500")]
    assert summary.not_in_format == 2
    assert summary.not_attempted == []


def test_presence_uses_info_only_on_a_name_match(camera, downloader, qtbot, tmp_path):
    local_copy(camera, tmp_path, TEN_JPGS[0])

    run_plan(downloader, qtbot, TEN_JPGS[:2], tmp_path)

    info_requests = [p for p in camera.paths_requested() if p.endswith("/info")]
    assert info_requests == [f"/v1/photos/{TEN_JPGS[0]}/info"]


def test_different_local_file_gets_a_collision_name(
    camera, downloader, qtbot, tmp_path
):
    (tmp_path / "R0000001.JPG").write_bytes(b"other")

    summary = run_plan(downloader, qtbot, TEN_JPGS[:1], tmp_path)

    assert summary.downloaded == TEN_JPGS[:1]
    assert (tmp_path / "R0000001.JPG").read_bytes() == b"other"
    assert (tmp_path / "R0000001_2.JPG").stat().st_size == 300 * 1024


def test_interrupted_transfer_leaves_no_file(camera, downloader, qtbot, tmp_path):
    camera.drops.add("/v1/photos/" + TEN_JPGS[1])
    lost = []
    downloader.connection_lost.connect(lost.append)

    summary = run_plan(downloader, qtbot, TEN_JPGS[:4], tmp_path)

    assert os.listdir(tmp_path) == ["R0000001.JPG"]
    assert summary.failed == [(TEN_JPGS[1], "connection to the camera lost")]
    assert summary.not_attempted == TEN_JPGS[2:4]
    assert summary.lost_connection and lost


def test_size_mismatch_is_reported(camera, downloader, qtbot, tmp_path):
    known_sizes = {TEN_JPGS[0]: 999}

    summary = run_plan(
        downloader, qtbot, TEN_JPGS[:2], tmp_path, known_sizes=known_sizes
    )

    assert summary.failed == [
        (TEN_JPGS[0], "size mismatch: 307200 of 999 bytes arrived")
    ]
    assert summary.downloaded == TEN_JPGS[1:2]
    assert os.listdir(tmp_path) == ["R0000002.JPG"]


def test_cancel_mid_file_keeps_finished_files(camera, downloader, qtbot, tmp_path):
    camera.chunk_delay = 0.02

    def cancel_in_fifth_file(path):
        if path == TEN_JPGS[3]:
            downloader.cancel()

    downloader.file_done.connect(cancel_in_fifth_file)
    summary = run_plan(downloader, qtbot, TEN_JPGS, tmp_path)

    assert sorted(os.listdir(tmp_path)) == [p.split("/")[1] for p in TEN_JPGS[:4]]
    assert summary.was_cancelled
    assert summary.downloaded == TEN_JPGS[:4]
    assert summary.not_attempted == TEN_JPGS[4:]


def test_camera_gone_leaves_the_rest_not_attempted(camera, downloader, qtbot, tmp_path):
    def gone_after_second_file(path):
        if path == TEN_JPGS[1]:
            camera.gone = True

    downloader.file_done.connect(gone_after_second_file)
    summary = run_plan(downloader, qtbot, TEN_JPGS, tmp_path)

    assert summary.downloaded == TEN_JPGS[:2]
    assert summary.failed == [(TEN_JPGS[2], "connection to the camera lost")]
    assert summary.not_attempted == TEN_JPGS[3:]
    assert summary.lost_connection


def test_progress_carries_file_position(downloader, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module, "PROGRESS_INTERVAL_SECONDS", 0)
    updates = []
    downloader.progress.connect(updates.append)

    run_plan(downloader, qtbot, TEN_JPGS, tmp_path)

    third = [u for u in updates if u.file_name == "R0000003.JPG"]
    assert third and third[0].position_text == "3 of 10"
    assert updates[-1].bytes_done == 10 * 300 * 1024
    assert updates[-1].bytes_per_second > 0


def test_progress_is_throttled(camera, downloader, qtbot, tmp_path):
    camera.chunk_delay = 0.01
    updates = []
    downloader.progress.connect(updates.append)

    run_plan(downloader, qtbot, TEN_JPGS[:4], tmp_path)  # 20 chunks, ~0.2 s

    assert 1 <= len(updates) <= 2


def test_leftover_temp_files_are_removed(downloader, qtbot, tmp_path):
    (tmp_path / ".grsync-qt-abc.part").write_bytes(b"old")

    run_plan(downloader, qtbot, TEN_JPGS[:1], tmp_path)

    assert os.listdir(tmp_path) == ["R0000001.JPG"]


def test_write_error_fails_the_file(downloader, qtbot, tmp_path):
    summary = run_plan(downloader, qtbot, TEN_JPGS[:1], tmp_path / "missing")

    ((path, reason),) = summary.failed
    assert path == TEN_JPGS[0] and reason.startswith("write error")


def test_speed_meter_moving_average():
    meter = SpeedMeter(window_seconds=5)
    for second in range(10):
        meter.add(float(second), second * 1000)

    assert meter.bytes_per_second() == 1000
