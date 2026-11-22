"""The thumbnail grid: shows the shot model and loads what is on screen.

After scrolling or resizing stops, the grid tells the request queue which
details it wants: the visible shots first, then one screen of margin below
and above. Shots far from the viewport are never requested.
"""

from pathlib import Path

from PySide6.QtCore import QMargins, Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QListView

from grsync_qt.request_queue import RequestQueue
from grsync_qt.shots import Shot
from grsync_qt.ui.shot_delegate import ShotDelegate
from grsync_qt.ui.shot_model import SHOT_ROLE, ShotModel

DEBOUNCE_MS = 100
GRID_SPACING = 8
WHEEL_NOTCH = 120  # angleDelta units of one mouse wheel notch


class ShotGrid(QListView):
    """A grid of shots with lazy loading and selection kept across refreshes."""

    current_shot_changed = Signal(object)  # Shot, or None
    size_steps_requested = Signal(int)  # Ctrl+wheel: + larger, - smaller

    def __init__(self, model: ShotModel, queue: RequestQueue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self.setModel(model)
        self._delegate = ShotDelegate(self)
        self.setItemDelegate(self._delegate)
        self._configure_view()
        self._wanted_timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._wanted_timer.timeout.connect(self.update_wanted)
        self.verticalScrollBar().valueChanged.connect(self.schedule_wanted_update)
        model.modelReset.connect(self.schedule_wanted_update)
        queue.result_ready.connect(model.handle_result)
        queue.request_failed.connect(model.handle_failure)
        self.selectionModel().currentChanged.connect(self._emit_current_shot)

    def _emit_current_shot(self):
        self.current_shot_changed.emit(self.current_shot())

    def current_shot(self) -> Shot | None:
        """The shot last clicked or moved to with the keyboard."""
        index = self.currentIndex()
        return index.data(SHOT_ROLE) if index.isValid() else None

    def _configure_view(self):
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self._update_grid_size()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)

    @property
    def shot_model(self) -> ShotModel:
        return self.model()

    def _update_grid_size(self):
        half_spacing = GRID_SPACING // 2
        margins = QMargins(half_spacing, half_spacing, half_spacing, half_spacing)
        self.setGridSize(self._delegate.cell_size(self.font()).grownBy(margins))

    # Thumbnail size

    @property
    def thumbnail_side(self) -> int:
        return self._delegate.thumbnail_side

    def set_thumbnail_side(self, side: int):
        """Show thumbnails of side pixels, keeping the current shot in view."""
        self._delegate.thumbnail_side = side
        self.shot_model.set_thumbnail_side(side)
        self._update_grid_size()
        self.doItemsLayout()
        if self.currentIndex().isValid():
            self.scrollTo(self.currentIndex())
        self.schedule_wanted_update()

    def wheelEvent(self, event):
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        steps = round(event.angleDelta().y() / WHEEL_NOTCH)
        if steps:
            self.size_steps_requested.emit(steps)
        event.accept()

    # Lazy loading

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_wanted_update()

    def schedule_wanted_update(self):
        self._wanted_timer.start()

    def update_wanted(self):
        """Send the request queue the keys for the rows on and near the screen."""
        self._queue.set_wanted(self.shot_model.wanted_keys(self.wanted_rows()))

    def wanted_rows(self) -> list[int]:
        """Visible rows, then a screen of margin below, then a screen above."""
        viewport = self.viewport().rect()
        below = viewport.translated(0, viewport.height())
        above = viewport.translated(0, -viewport.height())
        visible, margin_below, margin_above = [], [], []
        for row in range(self.shot_model.rowCount()):
            rect = self.visualRect(self.shot_model.index(row))
            if rect.intersects(viewport):
                visible.append(row)
            elif rect.intersects(below):
                margin_below.append(row)
            elif rect.intersects(above):
                margin_above.append(row)
        return visible + margin_below + margin_above

    def set_destination(self, folder: Path | None):
        """Re-judge the downloaded markers, fetching sizes the new folder needs."""
        self.shot_model.set_destination(folder)
        self.schedule_wanted_update()

    # Selection

    def selected_shots(self) -> list[Shot]:
        """Selected shots in grid order."""
        rows = sorted(index.row() for index in self.selectionModel().selectedIndexes())
        return [self.shot_model.shots[row] for row in rows]

    def set_shots(self, shots: list[Shot]):
        """Show new shots, keeping selection and current shot if still there."""
        selected_keys = {shot.key for shot in self.selected_shots()}
        current = self.current_shot()
        self.shot_model.set_shots(shots)
        selection = self.selectionModel()
        for row, shot in enumerate(shots):
            if shot.key in selected_keys:
                selection.select(
                    self.shot_model.index(row), selection.SelectionFlag.Select
                )
        # A model reset clears the current index without a currentChanged signal.
        current_row = self.shot_model.row_of_key(current.key) if current else None
        if current_row is None:
            self._emit_current_shot()
            return
        selection.setCurrentIndex(
            self.shot_model.index(current_row), selection.SelectionFlag.NoUpdate
        )
