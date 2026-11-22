"""Paints one shot: thumbnail (or placeholder), name, exposure and badges."""

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from grsync_qt.ui.shot_model import (
    BADGES_ROLE,
    EXPOSURE_ROLE,
    IMAGE_ROLE,
    JPG_THUMBNAIL_SIDE,
)

PADDING = 6
LINE_SPACING = 4
BADGE_SPACING = 4
BADGE_PADDING = 4
SMALL_FONT_FACTOR = 0.85  # the exposure line is set smaller than the name
DOWNLOADED_COLOR = QColor("#2e8b57")
PLACEHOLDER_COLOR = QColor(128, 128, 128, 60)


class ShotDelegate(QStyledItemDelegate):
    """Draws a grid cell for a shot, with thumbnails of thumbnail_side pixels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbnail_side = JPG_THUMBNAIL_SIDE

    def cell_size(self, font: QFont) -> QSize:
        """Thumbnail plus name, exposure and badge lines."""
        line_height = QFontMetrics(font).height()
        text_height = 3 * line_height + 3 * LINE_SPACING
        side = self.thumbnail_side
        return QSize(side + 2 * PADDING, side + PADDING + text_height + PADDING)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return self.cell_size(option.font)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_background(painter, option)
        thumbnail_rect = QRect(
            option.rect.x() + PADDING,
            option.rect.y() + PADDING,
            self.thumbnail_side,
            self.thumbnail_side,
        )
        self._paint_thumbnail(painter, thumbnail_rect, index.data(IMAGE_ROLE))
        line_height = QFontMetrics(option.font).height() + LINE_SPACING
        top = thumbnail_rect.bottom() + LINE_SPACING
        self._paint_text(painter, option, index.data(), top, option.font)
        exposure_font = small_font(option.font)
        exposure = index.data(EXPOSURE_ROLE)
        self._paint_text(painter, option, exposure, top + line_height, exposure_font)
        badges = index.data(BADGES_ROLE)
        self._paint_badges(painter, option, badges, top + 2 * line_height)
        painter.restore()

    def _paint_background(self, painter: QPainter, option: QStyleOptionViewItem):
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

    def _paint_thumbnail(self, painter: QPainter, rect: QRect, image):
        if image is None or image.isNull():
            painter.fillRect(rect, PLACEHOLDER_COLOR)
            return
        size = image.size().scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(rect.center())
        painter.drawImage(target, image)

    def _paint_text(self, painter, option, text: str, top: int, font: QFont):
        """One centered line, elided if the cell is too narrow (tooltip has it all)."""
        metrics = QFontMetrics(font)
        width = option.rect.width() - 2 * PADDING
        rect = QRect(option.rect.x() + PADDING, top, width, metrics.height())
        elided = metrics.elidedText(text or "", Qt.TextElideMode.ElideRight, width)
        painter.setFont(font)
        painter.setPen(self._text_color(option))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)
        painter.setFont(option.font)

    def _paint_badges(self, painter, option, badges, top: int):
        metrics = QFontMetrics(option.font)
        widths = [
            metrics.horizontalAdvance(label) + 2 * BADGE_PADDING for label, _ in badges
        ]
        total_width = sum(widths) + BADGE_SPACING * (len(badges) - 1)
        left = option.rect.x() + (option.rect.width() - total_width) // 2
        for (label, is_downloaded), width in zip(badges, widths, strict=True):
            rect = QRect(left, top, width, metrics.height())
            self._paint_badge(painter, option, rect, label, is_downloaded)
            left += width + BADGE_SPACING

    def _paint_badge(self, painter, option, rect: QRect, label, is_downloaded):
        """A filled badge means the file is in the destination folder."""
        if is_downloaded:
            painter.setBrush(DOWNLOADED_COLOR)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor("white"))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self._text_color(option))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 3, 3)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _text_color(self, option: QStyleOptionViewItem) -> QColor:
        if option.state & QStyle.StateFlag.State_Selected:
            return option.palette.color(QPalette.ColorRole.HighlightedText)
        return option.palette.color(QPalette.ColorRole.Text)


def small_font(font: QFont) -> QFont:
    smaller = QFont(font)
    if font.pointSizeF() > 0:
        smaller.setPointSizeF(font.pointSizeF() * SMALL_FONT_FACTOR)
    else:
        smaller.setPixelSize(round(font.pixelSize() * SMALL_FONT_FACTOR))
    return smaller
