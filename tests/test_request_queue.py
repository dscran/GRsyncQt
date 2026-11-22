import pytest
from fake_camera import FakeCamera, large_card
from PySide6.QtGui import QImage

from grsync_qt.camera import CameraInfo
from grsync_qt.request_queue import (
    CONNECT_KEY,
    RequestQueue,
    info_key,
    thumb_key,
    view_key,
)

TIMEOUT_MS = 5000


@pytest.fixture
def camera():
    camera = FakeCamera(card=large_card(60)).start()
    yield camera
    camera.stop()


@pytest.fixture
def queue(camera, qtbot):
    queue = RequestQueue(camera.url)
    yield queue
    queue.stop()


def served_keys(queue, qtbot, keys, count):
    """Run set_wanted(keys) and return the first count served keys in order."""
    served = []
    queue.result_ready.connect(lambda key, result: served.append(key))
    queue.set_wanted(keys)
    qtbot.waitUntil(lambda: len(served) >= count, timeout=TIMEOUT_MS)
    return served


def test_connect_returns_camera_info_and_listing(queue, qtbot):
    with qtbot.waitSignal(queue.result_ready, timeout=TIMEOUT_MS) as signal:
        queue.connect_camera()

    key, (info, paths) = signal.args
    assert key == CONNECT_KEY
    assert isinstance(info, CameraInfo)
    assert paths[0] == "100RICOH/R0000001.JPG"


def test_thumb_and_view_results_are_images(queue, qtbot):
    keys = [thumb_key("100RICOH/R0000001.JPG"), view_key("100RICOH/R0000001.JPG")]
    results = {}
    queue.result_ready.connect(lambda key, result: results.update({key: result}))

    queue.set_wanted(keys[:1])
    queue.request_preview(keys[1:])
    qtbot.waitUntil(lambda: len(results) == 2, timeout=TIMEOUT_MS)

    thumb, view = results[keys[0]], results[keys[1]]
    assert isinstance(thumb, QImage) and (thumb.width(), thumb.height()) == (160, 104)
    assert (view.width(), view.height()) == (720, 480)


def test_service_order_follows_the_wanted_order(queue, qtbot, camera):
    paths = ["100RICOH/R0000005.JPG", "100RICOH/R0000001.JPG", "100RICOH/R0000003.JPG"]
    keys = [info_key(path) for path in paths]

    served = served_keys(queue, qtbot, keys, 3)

    assert served == keys
    assert camera.paths_requested() == [f"/v1/photos/{path}/info" for path in paths]


def test_dropped_keys_are_never_requested(queue, qtbot, camera):
    camera.delay = 0.2
    first = [info_key(f"100RICOH/R00000{n:02d}.JPG") for n in range(1, 11)]
    second = [info_key(f"100RICOH/R00000{n:02d}.JPG") for n in range(20, 23)]
    served = []
    queue.result_ready.connect(lambda key, result: served.append(key))

    queue.set_wanted(first)
    qtbot.waitUntil(lambda: len(camera.log) == 1, timeout=TIMEOUT_MS)
    queue.set_wanted(second)
    qtbot.waitUntil(lambda: len(served) == 4, timeout=TIMEOUT_MS)

    assert served == first[:1] + second
    assert len(camera.log) == 4


def test_previews_go_first(queue, qtbot, camera):
    camera.delay = 0.1
    grid = [info_key(f"100RICOH/R00000{n:02d}.JPG") for n in range(1, 6)]
    preview = view_key("100RICOH/R0000020.JPG")
    served = []
    queue.result_ready.connect(lambda key, result: served.append(key))

    queue.set_wanted(grid)
    qtbot.waitUntil(lambda: len(camera.log) == 1, timeout=TIMEOUT_MS)
    queue.request_preview([preview])
    qtbot.waitUntil(lambda: len(served) == 6, timeout=TIMEOUT_MS)

    assert served[:2] == [grid[0], preview]


def test_never_more_than_one_concurrent_request(queue, qtbot, camera):
    camera.delay = 0.02
    keys = [thumb_key(f"100RICOH/R00000{n:02d}.JPG") for n in range(1, 13)]
    queue.request_preview([view_key("100RICOH/R0000001.JPG")])
    queue.connect_camera()

    served_keys(queue, qtbot, keys, len(keys) + 2)

    assert camera.max_concurrent == 1


def test_http_error_fails_only_that_key(queue, qtbot, camera):
    camera.errors["/v1/photos/100RICOH/R0000001.JPG/info"] = 500
    failed = []
    queue.request_failed.connect(lambda key, reason: failed.append((key, reason)))

    served = served_keys(
        queue,
        qtbot,
        [info_key("100RICOH/R0000001.JPG"), info_key("100RICOH/R0000002.JPG")],
        1,
    )

    assert served == [info_key("100RICOH/R0000002.JPG")]
    assert failed == [
        (
            info_key("100RICOH/R0000001.JPG"),
            "HTTP 500 for v1/photos/100RICOH/R0000001.JPG/info",
        )
    ]


def test_camera_gone_pauses_and_resume_continues(queue, qtbot, camera):
    camera.gone = True
    keys = [info_key("100RICOH/R0000001.JPG"), info_key("100RICOH/R0000002.JPG")]
    served = []
    queue.result_ready.connect(lambda key, result: served.append(key))

    with qtbot.waitSignal(queue.connection_lost, timeout=TIMEOUT_MS):
        queue.set_wanted(keys)
    qtbot.wait(200)
    assert len(camera.log) == 1  # paused: nothing more was sent

    camera.gone = False
    queue.resume()
    qtbot.waitUntil(lambda: len(served) == 2, timeout=TIMEOUT_MS)
    assert served == keys
