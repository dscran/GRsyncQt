import pytest
from fake_camera import FakeCamera, large_card
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from ui_helpers import (
    TIMEOUT_MS,
    connect,
    make_current,
    open_window,
    wait_for_preview,
)

from grsync_qt.ui.shot_model import EXPOSURE_ROLE, IMAGE_ROLE


@pytest.fixture
def camera():
    camera = FakeCamera(card=large_card(200)).start()
    yield camera
    camera.stop()


@pytest.fixture
def window(camera, qtbot):
    window = open_window(camera.url, qtbot)
    connect(window, qtbot)
    yield window
    window.close()


def wait_until_loaded(window, qtbot):
    grid = window.grid

    def is_loaded():
        assert grid.shot_model.wanted_keys(grid.wanted_rows()) == []

    qtbot.waitUntil(is_loaded, timeout=TIMEOUT_MS)


def ctrl_wheel(widget, notches: int):
    center = QPointF(widget.rect().center())
    event = QWheelEvent(
        center,
        widget.mapToGlobal(center),
        QPoint(0, 0),
        QPoint(0, 120 * notches),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def row_of_kind(window, extension) -> int:
    shots = window.model.shots
    return next(
        r for r, s in enumerate(shots) if s.thumbnail_source.endswith(extension)
    )


# Exposure line (9.6)


def test_exposure_line_under_a_thumbnail(window, qtbot):
    wait_until_loaded(window, qtbot)
    row = row_of_kind(window, ".JPG")
    index = window.model.index(row)

    assert index.data(EXPOSURE_ROLE) == "ISO 3200 · f/4.5 · 1/4 s · 0 EV"
    assert "ISO 3200" in index.data(Qt.ItemDataRole.ToolTipRole)
    assert not window.grid.grab().isNull()  # the delegate paints it


def test_video_has_no_exposure_line(window, qtbot):
    row = row_of_kind(window, ".MOV")
    window.grid.scrollTo(window.model.index(row))
    qtbot.waitUntil(
        lambda: window.model.shots[row].thumbnail_source in window.model.infos,
        timeout=TIMEOUT_MS,
    )

    assert window.model.index(row).data(EXPOSURE_ROLE) == ""


# Thumbnail size (9.7)


def test_ctrl_wheel_grows_the_thumbnails_by_one_step(window):
    position = window.size_slider.value()

    ctrl_wheel(window.grid.viewport(), 1)

    assert window.size_slider.value() == position + 1
    assert window.grid.thumbnail_side == 176


def test_slider_changes_the_size_and_it_is_remembered(window, camera, qtbot):
    window.size_slider.setValue(window.size_slider.maximum())
    assert window.grid.thumbnail_side == 320
    window.close()

    reopened = open_window(camera.url, qtbot)

    assert reopened.grid.thumbnail_side == 320
    assert reopened.size_slider.value() == reopened.size_slider.maximum()
    reopened.close()


def test_large_jpg_thumbnails_use_the_preview(window, camera, qtbot):
    wait_until_loaded(window, qtbot)
    make_current(window, 0)
    wait_for_preview(window, qtbot)
    camera.clear_log()

    window.grid.set_thumbnail_side(240)
    wait_until_loaded(window, qtbot)

    requested = camera.paths_requested()
    first_source = window.model.shots[0].thumbnail_source
    assert not [p for p in requested if p.endswith(".JPG?size=thumb")]
    assert [p for p in requested if p.endswith(".JPG?size=view")]
    assert f"/v1/photos/{first_source}?size=view" not in requested  # cached
    image = window.model.index(0).data(IMAGE_ROLE)
    assert max(image.width(), image.height()) == 320


def test_visible_rows_follow_the_size(window, qtbot):
    window.grid.set_thumbnail_side(96)
    small = len(window.grid.wanted_rows())

    window.grid.set_thumbnail_side(320)

    assert len(window.grid.wanted_rows()) < small


def test_current_shot_stays_in_view(window, qtbot):
    make_current(window, 40)
    window.grid.scrollTo(window.model.index(40))

    window.grid.set_thumbnail_side(320)

    rect = window.grid.visualRect(window.model.index(40))
    assert window.grid.viewport().rect().intersects(rect)


def test_size_slider_sits_on_top_of_the_grid(window):
    def top_of(widget) -> int:
        return widget.mapTo(window, widget.rect().topLeft()).y()

    grid_pane = window.grid.parentWidget()

    assert window.size_slider.parentWidget().parentWidget() is grid_pane
    assert top_of(window.size_slider) < top_of(window.grid)
    assert top_of(window.grid) == top_of(window.preview_pane.view)
