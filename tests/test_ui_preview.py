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

from grsync_qt.ui.preview_pane import MAX_ZOOM


@pytest.fixture
def window(fake_camera, qtbot):
    window = open_window(fake_camera.url, qtbot)
    connect(window, qtbot)
    yield window
    window.close()


def view_requests(camera) -> list[str]:
    return [p for p in camera.paths_requested() if p.endswith("?size=view")]


def click_row(window, qtbot, row):
    rect = window.grid.visualRect(window.model.index(row))
    qtbot.mouseClick(
        window.grid.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )


def test_clicking_a_portrait_pair_shows_it_upright(window, fake_camera, qtbot):
    row = window.model.row_of_key("101RICOH/R0000006")

    click_row(window, qtbot, row)
    pane = wait_for_preview(window, qtbot)

    assert (pane.image.width(), pane.image.height()) == (480, 720)
    qtbot.waitUntil(lambda: "614.4 KB" in pane.details_label.text(), timeout=TIMEOUT_MS)
    assert pane.details_label.text().splitlines() == [
        "R0000006.JPG  307.2 KB",
        "R0000006.DNG  614.4 KB",
        "Taken 2026-11-22 12:00:00",
        "ISO 3200 · f/4.5 · 1/4 s · 0 EV",
    ]
    assert view_requests(fake_camera) == ["/v1/photos/101RICOH/R0000006.JPG?size=view"]


def test_video_shows_its_preview_frame(window, qtbot):
    make_current(window, window.model.row_of_key("100RICOH/R0000003.MOV"))

    pane = wait_for_preview(window, qtbot)

    assert (pane.image.width(), pane.image.height()) == (640, 360)
    assert "ISO" not in pane.details_label.text()


def test_empty_card_shows_an_empty_pane(qtbot):
    camera = FakeCamera(card=[]).start()
    window = open_window(camera.url, qtbot)
    try:
        connect(window, qtbot)
        assert window.preview_pane.shot is None
        assert not window.preview_pane.view.has_image
        assert window.preview_pane.details_label.text() == "No shot selected."
    finally:
        window.close()
        camera.stop()


def test_stepping_quickly_fetches_few_previews(qtbot):
    camera = FakeCamera(card=large_card(60)).start()
    window = open_window(camera.url, qtbot)
    try:
        connect(window, qtbot)
        qtbot.wait(500)  # let the grid's first requests settle
        camera.delay = 0.1
        make_current(window, 0)
        window.grid.setFocus()
        for _ in range(10):
            qtbot.keyClick(window.grid, Qt.Key.Key_Right)
        pane = wait_for_preview(window, qtbot)
        last_source = window.model.shots[10].thumbnail_source

        assert pane.shot == window.model.shots[10]
        assert len(view_requests(camera)) <= 3
        assert view_requests(camera)[-1] == f"/v1/photos/{last_source}?size=view"
    finally:
        window.close()
        camera.stop()


def test_refresh_keeps_the_current_shot(window, qtbot):
    make_current(window, 2)
    shot = window.preview_pane.shot

    connect(window, qtbot)

    assert window.grid.current_shot() == shot
    assert window.preview_pane.shot == shot


def test_splitter_state_survives_a_new_window(fake_camera, window, qtbot):
    window.splitter.setSizes([700, 200])
    sizes = window.splitter.sizes()
    window.close()

    reopened = open_window(fake_camera.url, qtbot)

    assert reopened.splitter.sizes() == sizes
    reopened.close()


# Zoom


def ctrl_wheel(view, notches: int):
    center = QPointF(view.viewport().rect().center())
    event = QWheelEvent(
        center,
        view.viewport().mapToGlobal(center),
        QPoint(0, 0),
        QPoint(0, 120 * notches),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view.viewport(), event)


@pytest.fixture
def pane(window, qtbot):
    make_current(window, 0)
    return wait_for_preview(window, qtbot)


def image_fits_view(view) -> bool:
    shown = view.mapFromScene(view.sceneRect()).boundingRect()
    return view.viewport().rect().contains(shown)


def test_preview_fits_by_default(pane):
    assert pane.view.is_fit
    assert image_fits_view(pane.view)


def test_ctrl_wheel_zooms_in(pane):
    before = pane.view.scale_factor

    ctrl_wheel(pane.view, 2)

    assert pane.view.scale_factor == pytest.approx(before * 1.25**2)
    assert not pane.view.is_fit


def test_zoom_is_capped(pane):
    ctrl_wheel(pane.view, 40)

    assert pane.view.scale_factor == pytest.approx(MAX_ZOOM)


def test_fit_and_actual_size_buttons(pane):
    ctrl_wheel(pane.view, 3)

    pane.zoom_buttons["100 %"].click()
    assert pane.view.scale_factor == 1.0

    pane.zoom_buttons["Fit"].click()
    assert pane.view.is_fit and image_fits_view(pane.view)


def test_another_shot_resets_to_fit(window, pane, qtbot):
    ctrl_wheel(pane.view, 3)

    make_current(window, 1)
    wait_for_preview(window, qtbot)

    assert pane.view.is_fit and image_fits_view(pane.view)


def test_drag_pans_a_zoomed_image(pane, qtbot):
    ctrl_wheel(pane.view, 6)
    scroll_bar = pane.view.horizontalScrollBar()
    before = scroll_bar.value()

    viewport = pane.view.viewport()
    center = viewport.rect().center()
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseMove(viewport, pos=center + QPoint(-60, 0))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=center + QPoint(-60, 0))

    assert scroll_bar.value() > before
