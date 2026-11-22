"""The preview pane: a zoomable, upright preview of the current shot."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from grsync_qt.images import apply_orientation
from grsync_qt.request_queue import RequestQueue, info_key, view_key
from grsync_qt.shots import Shot
from grsync_qt.ui.formatting import format_bytes, format_exposure
from grsync_qt.ui.shot_model import ShotModel, file_name_of

MAX_ZOOM = 4.0  # times the image's own pixels
ZOOM_STEP = 1.25  # per wheel notch or button press
WHEEL_NOTCH = 120  # angleDelta units of one mouse wheel notch
FIT_MARGIN = 2  # pixels QGraphicsView.fitInView keeps free on each side
UNKNOWN_ORIENTATION = 0


class ZoomableImageView(QGraphicsView):
    """Shows one image, fitted by default; Ctrl+wheel zooms, dragging pans."""

    zoom_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._is_fit = True

    @property
    def has_image(self) -> bool:
        return not self._item.pixmap().isNull()

    @property
    def scale_factor(self) -> float:
        """Screen pixels per image pixel."""
        return self.transform().m11()

    @property
    def is_fit(self) -> bool:
        return self._is_fit

    def set_image(self, image: QImage | None):
        """Show image (or nothing), fitted to the view."""
        pixmap = QPixmap.fromImage(image) if image is not None else QPixmap()
        self._item.setPixmap(pixmap)
        self.scene().setSceneRect(self._item.boundingRect())
        self.fit()

    def fit(self):
        self._is_fit = True
        self.resetTransform()
        if self.has_image:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_changed.emit()

    def zoom_to_actual_size(self):
        self._is_fit = False
        self.resetTransform()
        self.zoom_changed.emit()

    def zoom_by(self, factor: float):
        """Zoom by factor, between the fitted size and MAX_ZOOM."""
        if not self.has_image:
            return
        min_scale = min(self._fit_scale(), 1.0)
        max_scale = max(self._fit_scale(), MAX_ZOOM)
        target = min(max(self.scale_factor * factor, min_scale), max_scale)
        self.scale(target / self.scale_factor, target / self.scale_factor)
        self._is_fit = False
        self.zoom_changed.emit()

    def _fit_scale(self) -> float:
        available = (
            self.viewport()
            .rect()
            .adjusted(FIT_MARGIN, FIT_MARGIN, -FIT_MARGIN, -FIT_MARGIN)
        )
        image = self._item.pixmap().size()
        return min(
            available.width() / image.width(), available.height() / image.height()
        )

    def wheelEvent(self, event):
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        notches = event.angleDelta().y() / WHEEL_NOTCH
        self.zoom_by(ZOOM_STEP**notches)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_fit:
            self.fit()


class PreviewPane(QWidget):
    """The current shot's preview with its file names, sizes, date and exposure.

    For a JPG+DNG pair only one preview is fetched, as the camera serves the
    same image for both.
    """

    def __init__(self, model: ShotModel, queue: RequestQueue, parent=None):
        super().__init__(parent)
        self.shot: Shot | None = None
        self.image: QImage | None = None  # the upright preview, once loaded
        self._model = model
        self._queue = queue
        self._failed_keys: set[str] = set()
        self.view = ZoomableImageView()
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._build_zoom_buttons())
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(self.details_label)
        queue.result_ready.connect(self._on_result)
        queue.request_failed.connect(self._on_failure)
        self.show_shot(None)

    def _build_zoom_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        buttons = [
            (
                "−",
                "Zoom out (Ctrl+wheel down)",
                lambda: self.view.zoom_by(1 / ZOOM_STEP),
            ),
            ("+", "Zoom in (Ctrl+wheel up)", lambda: self.view.zoom_by(ZOOM_STEP)),
            ("Fit", "Fit the preview into the pane", self.view.fit),
            ("100 %", "Show the preview's pixels 1:1", self.view.zoom_to_actual_size),
        ]
        self.zoom_buttons = {}
        for text, tooltip, slot in buttons:
            button = QToolButton(text=text, toolTip=tooltip)
            button.clicked.connect(slot)
            row.addWidget(button)
            self.zoom_buttons[text] = button
        row.addStretch()
        return row

    def zoom_row_height(self) -> int:
        """Height of the zoom button row, for aligning controls beside it."""
        return max(button.sizeHint().height() for button in self.zoom_buttons.values())

    @property
    def source(self) -> str | None:
        return self.shot.thumbnail_source if self.shot else None

    def show_shot(self, shot: Shot | None):
        """Show shot (or nothing), fetching what is missing."""
        if shot is not None and self.shot is not None and shot.key == self.shot.key:
            return
        self.shot = shot
        self.image = None
        self.view.set_image(None)
        self._update()
        if shot is not None:
            self._queue.request_preview(self._missing_keys())

    def _missing_keys(self) -> list[str]:
        files = self.shot.files.values()
        keys = [info_key(path) for path in files if path not in self._model.infos]
        if self.source not in self._model.previews:
            keys.append(view_key(self.source))
        return keys

    def _is_about_this_shot(self, key: str) -> bool:
        return (
            self.shot is not None and key.partition(":")[2] in self.shot.files.values()
        )

    def _on_result(self, key: str, result: object):
        # The model stores results itself; it was connected to the queue first.
        if self._is_about_this_shot(key):
            self._update()

    def _on_failure(self, key: str, reason: str):
        if self._is_about_this_shot(key):
            self._failed_keys.add(key)
            self._update()

    def _update(self):
        self.details_label.setText(self._details_text())
        if self.image is None:
            self._show_image_when_ready()

    def _show_image_when_ready(self):
        if self.shot is None:
            return
        preview = self._model.previews.get(self.source)
        info = self._model.infos.get(self.source)
        is_info_settled = info is not None or info_key(self.source) in self._failed_keys
        if preview is None or not is_info_settled:
            return
        orientation = info.orientation if info else UNKNOWN_ORIENTATION
        self.image = apply_orientation(preview, orientation)
        self.view.set_image(self.image)

    def _details_text(self) -> str:
        if self.shot is None:
            return "No shot selected."
        lines = [self._file_line(path) for path in self.shot.files.values()]
        if view_key(self.source) in self._failed_keys:
            lines.insert(0, "Preview not available.")
        info = self._model.infos.get(self.source)
        if info and info.datetime:
            lines.append("Taken " + info.datetime.replace("T", " "))
        if info and format_exposure(info):
            lines.append(format_exposure(info))
        return "\n".join(lines)

    def _file_line(self, path: str) -> str:
        info = self._model.infos.get(path)
        size = format_bytes(info.size) if info else "…"
        return f"{file_name_of(path)}  {size}"
