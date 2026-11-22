import pytest
from fake_camera import encoded_jpeg
from PySide6.QtGui import QColor, QImage

from grsync_qt.images import apply_orientation, prepare_thumbnail, trim_letterbox

RED = QColor("red")


def landscape_with_red_top_left() -> QImage:
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    image.setPixelColor(0, 0, RED)
    return image


def letterboxed(width: int, height: int, black_rows: int) -> QImage:
    picture = QImage(width, height - 2 * black_rows, QImage.Format.Format_RGB32)
    picture.fill(QColor("steelblue"))
    return picture.copy(0, -black_rows, width, height)


def test_thumbnail_with_8_black_rows_becomes_160x104():
    trimmed = trim_letterbox(letterboxed(160, 120, 8))

    assert (trimmed.width(), trimmed.height()) == (160, 104)


def test_jpeg_thumbnail_from_the_fake_is_trimmed():
    image = prepare_thumbnail(encoded_jpeg(160, 120, "steelblue", 8), True, 160)

    assert (image.width(), image.height()) == (160, 104)


def test_large_thumbnail_is_scaled_to_fit():
    image = prepare_thumbnail(encoded_jpeg(720, 480, "steelblue"), False, 160)

    assert (image.width(), image.height()) == (160, 106)


def test_trim_is_capped_at_a_quarter_per_side():
    picture = QImage(100, 60, QImage.Format.Format_RGB32)
    picture.fill(QColor("white"))
    dark_top = picture.copy(0, -40, 100, 100)  # 40 black rows on top

    trimmed = trim_letterbox(dark_top)

    assert trimmed.height() == 75


def test_picture_without_bars_is_unchanged():
    image = landscape_with_red_top_left()

    assert trim_letterbox(image).size() == image.size()


def test_orientation_6_turns_landscape_into_portrait_clockwise():
    rotated = apply_orientation(landscape_with_red_top_left(), 6)

    assert (rotated.width(), rotated.height()) == (20, 40)
    assert rotated.pixelColor(19, 0) == RED  # top-left moved to top-right


def test_orientation_8_rotates_counter_clockwise():
    rotated = apply_orientation(landscape_with_red_top_left(), 8)

    assert rotated.pixelColor(0, 39) == RED  # top-left moved to bottom-left


@pytest.mark.parametrize(
    ("orientation", "red_at"),
    [(2, (39, 0)), (3, (39, 19)), (4, (0, 19))],
)
def test_mirrors_and_half_turn(orientation, red_at):
    image = apply_orientation(landscape_with_red_top_left(), orientation)

    assert image.size() == landscape_with_red_top_left().size()
    assert image.pixelColor(*red_at) == RED


@pytest.mark.parametrize(("orientation", "red_at"), [(5, (0, 0)), (7, (19, 39))])
def test_transpose_and_transverse(orientation, red_at):
    image = apply_orientation(landscape_with_red_top_left(), orientation)

    assert (image.width(), image.height()) == (20, 40)
    assert image.pixelColor(*red_at) == RED


@pytest.mark.parametrize("orientation", [0, 1, 9, -1])
def test_unknown_orientation_is_a_no_op(orientation):
    image = landscape_with_red_top_left()

    assert apply_orientation(image, orientation) == image


def test_undecodable_data_gives_a_null_image():
    assert prepare_thumbnail(b"not a jpeg", True, 160).isNull()
