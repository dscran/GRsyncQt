import pytest
from fake_camera import FakeFile
from ui_helpers import TIMEOUT_MS, connect, open_window, select_rows, selected_keys

from grsync_qt import app
from grsync_qt.ui.main_window import ConnectionState


@pytest.fixture
def window(fake_camera, qtbot):
    window = open_window(fake_camera.url, qtbot)
    yield window
    window.close()


def test_connects_at_start(window, qtbot):
    connect(window, qtbot)

    assert window.connection_label.text() == "Connected to RICOH GR III."
    assert window.model.rowCount() == 5
    assert window.model.shots[0].key == "101RICOH/R0000006"
    assert not window.retry_action.isVisible()


def test_not_reachable_then_retry_connects(window, fake_camera, qtbot):
    fake_camera.gone = True
    connect(window, qtbot, expected=ConnectionState.DISCONNECTED)
    assert "Join the camera's Wi-Fi" in window.connection_label.text()
    assert window.retry_action.isVisible() and window.retry_action.isEnabled()

    fake_camera.gone = False
    window.retry_action.trigger()
    qtbot.waitUntil(
        lambda: window.state == ConnectionState.CONNECTED, timeout=TIMEOUT_MS
    )

    assert window.model.rowCount() == 5


def test_unsupported_device_names_the_model(window, fake_camera, qtbot):
    fake_camera.props["model"] = "RICOH GR II"
    window.connect_camera()
    qtbot.waitUntil(
        lambda: "RICOH GR II" in window.connection_label.text(), timeout=TIMEOUT_MS
    )

    assert window.connection_label.text() == "Not a supported camera: RICOH GR II."
    assert window.state == ConnectionState.DISCONNECTED
    assert window.model.rowCount() == 0


def test_battery_is_shown(window, qtbot):
    connect(window, qtbot)

    assert window.battery_label.text() == "Battery 87 %"


def test_selection_count_and_select_all(window, qtbot):
    connect(window, qtbot)
    select_rows(window, [0, 2])
    assert window.selection_label.text() == "2 selected"

    window.select_all_action.trigger()
    assert window.selection_label.text() == "5 selected"

    window.clear_selection_action.trigger()
    assert window.selection_label.text() == "0 selected"


def test_refresh_shows_the_new_shot_first_and_keeps_the_selection(
    window, fake_camera, qtbot
):
    connect(window, qtbot)
    select_rows(window, [1, 3])
    before = selected_keys(window)
    fake_camera.card.append(FakeFile("101RICOH", "R0000007.JPG"))

    window.refresh_action.trigger()
    qtbot.waitUntil(lambda: window.model.rowCount() == 6, timeout=TIMEOUT_MS)

    assert window.model.shots[0].key == "101RICOH/R0000007"
    assert selected_keys(window) == before


def test_retry_after_connection_loss_keeps_the_selection(window, fake_camera, qtbot):
    connect(window, qtbot)
    select_rows(window, [0, 4])
    before = selected_keys(window)

    fake_camera.gone = True
    window.queue.request_preview(["info:100RICOH/R0000002.JPG"])
    qtbot.waitUntil(lambda: window.state == ConnectionState.LOST, timeout=TIMEOUT_MS)
    assert "lost" in window.connection_label.text()
    assert window.retry_action.isVisible()
    num_requests = len(fake_camera.log)
    qtbot.wait(300)
    assert len(fake_camera.log) == num_requests  # paused until Retry

    fake_camera.gone = False
    window.retry_action.trigger()
    qtbot.waitUntil(
        lambda: window.state == ConnectionState.CONNECTED, timeout=TIMEOUT_MS
    )

    assert selected_keys(window) == before


def test_host_option_is_used_for_every_request(fake_camera, qtbot):
    options = app.parse_args(["--host", fake_camera.url])
    window = open_window(options.host, qtbot)
    connect(window, qtbot)
    window.close()

    assert fake_camera.paths_requested()[:2] == ["/v1/props", "/v1/photos"]
