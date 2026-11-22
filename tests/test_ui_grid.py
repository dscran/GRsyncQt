import pytest
from fake_camera import FakeCamera, file_content, large_card

from grsync_qt.request_queue import RequestQueue
from grsync_qt.shots import group_shots
from grsync_qt.ui.shot_grid import ShotGrid
from grsync_qt.ui.shot_model import ShotModel

TIMEOUT_MS = 10000
NUM_FILES = 1243


@pytest.fixture
def camera():
    camera = FakeCamera(card=large_card(NUM_FILES)).start()
    yield camera
    camera.stop()


@pytest.fixture
def grid(camera, qtbot):
    queue = RequestQueue(camera.url)
    grid = ShotGrid(ShotModel(), queue)
    qtbot.addWidget(grid)
    grid.resize(800, 600)
    grid.show()
    qtbot.waitExposed(grid)
    yield grid
    queue.stop()


def show_card(grid, camera):
    grid.set_shots(group_shots([file.path for file in camera.card]))


def wait_until_loaded(grid, qtbot):
    def is_loaded():
        assert grid.shot_model.wanted_keys(grid.wanted_rows()) == []

    qtbot.waitUntil(is_loaded, timeout=TIMEOUT_MS)


def thumb_paths_requested(camera) -> list[str]:
    paths = camera.paths_requested()
    prefix, suffix = "/v1/photos/", "?size=thumb"
    return [p[len(prefix) : -len(suffix)] for p in paths if p.endswith(suffix)]


def sources(grid, rows) -> list[str]:
    return [grid.shot_model.shots[row].thumbnail_source for row in rows]


def scroll_to_row(grid, qtbot, row):
    grid.scrollTo(grid.shot_model.index(row), grid.ScrollHint.PositionAtTop)
    qtbot.wait(250)  # past the debounce


def test_only_visible_and_margin_shots_are_requested(grid, camera, qtbot):
    show_card(grid, camera)
    wait_until_loaded(grid, qtbot)
    qtbot.wait(300)

    wanted = grid.wanted_rows()
    requested = thumb_paths_requested(camera)
    assert 10 <= len(wanted) <= 60
    assert requested == sources(grid, wanted)
    assert camera.paths_requested()[0] == f"/v1/photos/{sources(grid, [0])[0]}/info"
    assert grid.shot_model.upright_thumbnail(grid.shot_model.shots[0]) is not None


def test_scrolling_moves_new_shots_to_the_front(grid, camera, qtbot):
    camera.delay = 0.03
    show_card(grid, camera)
    qtbot.waitUntil(lambda: len(camera.log) >= 2, timeout=TIMEOUT_MS)

    scroll_to_row(grid, qtbot, 300)
    num_before = len(thumb_paths_requested(camera))
    qtbot.waitUntil(
        lambda: len(thumb_paths_requested(camera)) >= num_before + 3, timeout=TIMEOUT_MS
    )

    after_scroll = thumb_paths_requested(camera)[num_before:]
    visible_now = set(sources(grid, grid.wanted_rows()))
    # One request may still have been in flight while scrolling.
    assert set(after_scroll[1:3]) <= visible_now
    assert sources(grid, [0])[0] not in after_scroll


def test_scrolling_back_makes_no_new_requests(grid, camera, qtbot):
    show_card(grid, camera)
    wait_until_loaded(grid, qtbot)
    scroll_to_row(grid, qtbot, 400)
    wait_until_loaded(grid, qtbot)
    camera.clear_log()

    scroll_to_row(grid, qtbot, 0)
    qtbot.wait(300)

    assert camera.log == []


def put_local(camera, folder, path):
    folder.mkdir(exist_ok=True)
    file = camera.file(path)
    (folder / file.name).write_bytes(file_content(file))


def badges_of(grid, row):
    return grid.shot_model.badges(grid.shot_model.shots[row])


def pair_rows(grid, count):
    return [r for r, s in enumerate(grid.shot_model.shots) if len(s.files) == 2][:count]


def test_downloaded_markers(grid, camera, qtbot, tmp_path):
    show_card(grid, camera)
    pair, jpg_only = pair_rows(grid, 2)
    for path in grid.shot_model.shots[pair].files.values():
        put_local(camera, tmp_path, path)
    put_local(camera, tmp_path, grid.shot_model.shots[jpg_only].files["JPG"])

    grid.set_destination(tmp_path)
    wait_until_loaded(grid, qtbot)

    assert badges_of(grid, pair) == [("JPG", True), ("RAW", True)]
    assert badges_of(grid, jpg_only) == [("JPG", True), ("RAW", False)]
    dng_infos = [p for p in camera.paths_requested() if p.endswith(".DNG/info")]
    assert dng_infos == [f"/v1/photos/{grid.shot_model.shots[pair].files['DNG']}/info"]


def test_markers_update_after_the_destination_changes(grid, camera, qtbot, tmp_path):
    show_card(grid, camera)
    (pair,) = pair_rows(grid, 1)
    grid.set_destination(tmp_path / "empty")
    wait_until_loaded(grid, qtbot)
    assert badges_of(grid, pair) == [("JPG", False), ("RAW", False)]

    other = tmp_path / "other"
    for path in grid.shot_model.shots[pair].files.values():
        put_local(camera, other, path)
    grid.set_destination(other)
    wait_until_loaded(grid, qtbot)

    assert badges_of(grid, pair) == [("JPG", True), ("RAW", True)]
