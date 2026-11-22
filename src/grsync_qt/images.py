"""Fixes for camera images: upright orientation and letterbox removal.

The camera sends images without EXIF and unrotated, so the orientation comes
from the file's /info. JPG thumbnails put a 3:2 picture into a 4:3 frame with
black bars, which are trimmed.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QTransform

DARK_THRESHOLD = 24  # a pixel is near-black if every channel is below this
MAX_TRIM_FRACTION = 0.25  # never trim more than this per side
BYTES_PER_PIXEL = 3  # Format_RGB888

# QTransform(m11, m12, m21, m22, dx, dy) maps x' = m11*x + m21*y, y' = m12*x + m22*y.
ORIENTATION_TRANSFORMS = {
    2: QTransform(-1, 0, 0, 1, 0, 0),  # mirrored horizontally
    3: QTransform(-1, 0, 0, -1, 0, 0),  # rotated 180°
    4: QTransform(1, 0, 0, -1, 0, 0),  # mirrored vertically
    5: QTransform(0, 1, 1, 0, 0, 0),  # transposed
    6: QTransform(0, 1, -1, 0, 0, 0),  # rotated 90° clockwise
    7: QTransform(0, -1, -1, 0, 0, 0),  # transversed
    8: QTransform(0, -1, 1, 0, 0, 0),  # rotated 90° counter-clockwise
}


def apply_orientation(image: QImage, orientation: int) -> QImage:
    """Return image turned upright for an EXIF orientation value (1-8).

    Unknown values, including 0 for videos, leave the image unchanged.
    """
    transform = ORIENTATION_TRANSFORMS.get(orientation)
    if transform is None:
        return image
    return image.transformed(transform)


def trim_letterbox(image: QImage) -> QImage:
    """Return image without near-black bars, trimming at most 25 % per side."""
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = rgb.width(), rgb.height()
    rows = [_row_bytes(rgb, y) for y in range(height)]
    top = _count_dark(rows, int(height * MAX_TRIM_FRACTION))
    bottom = _count_dark(rows[::-1], int(height * MAX_TRIM_FRACTION))
    picture_rows = rows[top : height - bottom]
    columns = [_column_bytes(picture_rows, x) for x in range(width)]
    left = _count_dark(columns, int(width * MAX_TRIM_FRACTION))
    right = _count_dark(columns[::-1], int(width * MAX_TRIM_FRACTION))
    return image.copy(left, top, width - left - right, height - top - bottom)


def decode(data: bytes) -> QImage:
    """Decode JPEG bytes; a null image if they can't be decoded."""
    image = QImage()
    image.loadFromData(data)
    return image


def prepare_thumbnail(data: bytes, has_letterbox: bool, max_side: int) -> QImage:
    """Decode a camera thumbnail, trim its letterbox and fit it into max_side.

    The orientation is applied later, once the file's /info has arrived.
    """
    image = decode(data)
    if image.isNull():
        return image
    if has_letterbox:
        image = trim_letterbox(image)
    return fit_within(image, max_side)


def fit_within(image: QImage, max_side: int) -> QImage:
    """Scale image down to fit a max_side square; smaller images stay as they are."""
    if image.width() <= max_side and image.height() <= max_side:
        return image
    return image.scaled(
        max_side,
        max_side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _row_bytes(image: QImage, y: int) -> bytes:
    start = y * image.bytesPerLine()
    return bytes(image.constBits()[start : start + image.width() * BYTES_PER_PIXEL])


def _column_bytes(rows: list[bytes], x: int) -> bytes:
    start = x * BYTES_PER_PIXEL
    return b"".join(row[start : start + BYTES_PER_PIXEL] for row in rows)


def _count_dark(lines: list[bytes], max_count: int) -> int:
    """Count leading lines whose pixels are all near-black, up to max_count."""
    count = 0
    while count < max_count and _is_dark(lines[count]):
        count += 1
    return count


def _is_dark(line: bytes) -> bool:
    return not line or max(line) < DARK_THRESHOLD
