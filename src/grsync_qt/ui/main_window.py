"""The main window: connection state, the shot grid and downloads."""

import logging
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from grsync_qt.camera import CameraInfo
from grsync_qt.destination import is_writable
from grsync_qt.downloader import Downloader, DownloadSummary
from grsync_qt.request_queue import CONNECT_KEY, RequestQueue
from grsync_qt.settings import Settings
from grsync_qt.shots import DownloadFormat, group_shots, plan_download
from grsync_qt.ui.download_panel import DownloadPanel
from grsync_qt.ui.preview_pane import PreviewPane
from grsync_qt.ui.shot_grid import ShotGrid
from grsync_qt.ui.shot_model import ShotModel

LOW_BATTERY_PERCENT = 15
WINDOW_TITLE = "GRsync"
DEFAULT_WINDOW_SIZE = (1200, 750)
GRID_STRETCH = 3  # the grid gets 3/5 of the width when the window grows
PREVIEW_STRETCH = 2
THUMBNAIL_SIZES = list(range(96, 321, 16))  # pixels; slider positions
SIZE_SLIDER_WIDTH = 120

log = logging.getLogger(__name__)


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    LOST = "lost"


class MainWindow(QMainWindow):
    """Connects to the camera at start, shows its shots and downloads them."""

    def __init__(self, base_url: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state = ConnectionState.DISCONNECTED
        self.camera_info: CameraInfo | None = None
        self.queue = RequestQueue(base_url, self)
        self.downloader = Downloader(base_url, self)
        self.model = ShotModel(self)
        self.grid = ShotGrid(self.model, self.queue)
        self.download_panel = DownloadPanel()
        self.preview_pane = PreviewPane(self.model, self.queue)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setWindowTitle(WINDOW_TITLE)
        self._build_toolbar()
        self._build_status_bar()
        self._build_central_widget()
        self._connect_signals()
        self._restore_settings()

    # Building

    def _build_toolbar(self):
        toolbar = QToolBar("Main", movable=False)
        self.addToolBar(toolbar)
        self.retry_action = toolbar.addAction("Retry", self.connect_camera)
        self.refresh_action = toolbar.addAction("Refresh", self.refresh)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        toolbar.addSeparator()
        self.select_all_action = toolbar.addAction("Select all", self.grid.selectAll)
        self.clear_selection_action = toolbar.addAction(
            "Clear selection", self.grid.clearSelection
        )
        toolbar.addSeparator()
        self.format_combo = QComboBox()
        for download_format in DownloadFormat:
            self.format_combo.addItem(download_format.value, download_format)
        toolbar.addWidget(self.format_combo)
        self.destination_action = toolbar.addAction(
            "Destination…", self.choose_destination
        )
        self.download_action = toolbar.addAction("Download", self.start_download)

    def _build_status_bar(self):
        self.connection_label = QLabel()
        self.battery_label = QLabel()
        self.selection_label = QLabel()
        self.statusBar().addWidget(self.connection_label, stretch=1)
        self.statusBar().addPermanentWidget(self.selection_label)
        self.statusBar().addPermanentWidget(self.battery_label)

    def _build_grid_pane(self) -> QWidget:
        """The grid with its size slider on top, like the preview's zoom buttons."""
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(0, len(THUMBNAIL_SIZES) - 1)
        self.size_slider.setPageStep(1)
        self.size_slider.setFixedWidth(SIZE_SLIDER_WIDTH)
        self.size_slider.setToolTip("Thumbnail size (Ctrl+mouse wheel over the grid)")
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(QLabel("Size"))
        controls_layout.addWidget(self.size_slider)
        controls_layout.addStretch()
        # Same height as the zoom buttons, so both panes start at the same line.
        controls.setFixedHeight(self.preview_pane.zoom_row_height())
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(controls)
        layout.addWidget(self.grid, stretch=1)
        return pane

    def _build_central_widget(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(self._build_grid_pane())
        self.splitter.addWidget(self.preview_pane)
        self.splitter.setStretchFactor(0, GRID_STRETCH)
        self.splitter.setStretchFactor(1, PREVIEW_STRETCH)
        layout.addWidget(self.splitter, stretch=1)
        layout.addWidget(self.download_panel)
        self.setCentralWidget(central)

    def _connect_signals(self):
        self.queue.result_ready.connect(self._on_result)
        self.queue.request_failed.connect(self._on_request_failed)
        self.queue.connection_lost.connect(self._on_connection_lost)
        self.downloader.progress.connect(self.download_panel.show_progress)
        self.downloader.file_done.connect(self._on_file_done)
        self.downloader.finished.connect(self._on_download_finished)
        self.downloader.connection_lost.connect(self._on_connection_lost)
        self.download_panel.cancel_requested.connect(self._cancel_download)
        self.grid.selectionModel().selectionChanged.connect(self._update_selection)
        self.grid.current_shot_changed.connect(self.preview_pane.show_shot)
        self.grid.size_steps_requested.connect(self._step_thumbnail_size)
        self.size_slider.valueChanged.connect(self._apply_thumbnail_size)
        self.format_combo.currentIndexChanged.connect(self._save_format)

    def _restore_settings(self):
        index = self.format_combo.findData(self.settings.download_format)
        self.format_combo.setCurrentIndex(index)
        self._show_destination(self.settings.destination)
        geometry = self.settings.geometry
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(*DEFAULT_WINDOW_SIZE)
        self._restore_thumbnail_size()
        splitter_state = self.settings.splitter_state
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)
        self._update_selection()
        self._set_state(ConnectionState.DISCONNECTED, "Not connected.")

    # Connection

    def connect_camera(self):
        """Connect (or reconnect) and load the shot list."""
        self._set_state(ConnectionState.CONNECTING, "Connecting to the camera…")
        self.queue.connect_camera()

    def refresh(self):
        """Reload the shot list, keeping the selection."""
        self.model.refresh_destination()
        self.connect_camera()

    def _on_result(self, key: str, result: object):
        if key != CONNECT_KEY:
            return
        self.camera_info, paths = result
        self.grid.set_shots(group_shots(paths))
        self._set_state(
            ConnectionState.CONNECTED, f"Connected to {self.camera_info.model}."
        )

    def _on_request_failed(self, key: str, reason: str):
        if key == CONNECT_KEY:
            self._set_state(ConnectionState.DISCONNECTED, f"{reason}.")

    def _on_connection_lost(self, reason: str):
        self.queue.pause()
        if self.state == ConnectionState.CONNECTED:
            message = "Connection to the camera lost. Choose Retry when it is back."
            self._set_state(ConnectionState.LOST, message)
            return
        message = "Camera not reachable. Join the camera's Wi-Fi, then choose Retry."
        self._set_state(ConnectionState.DISCONNECTED, message)

    def _set_state(self, state: ConnectionState, message: str):
        self.state = state
        self.connection_label.setText(message)
        is_connected = state == ConnectionState.CONNECTED
        self.retry_action.setEnabled(state != ConnectionState.CONNECTING)
        self.retry_action.setVisible(not is_connected)
        self.refresh_action.setEnabled(is_connected)
        self._update_download_action()
        self._update_battery()

    def _update_battery(self):
        battery = self.camera_info.battery if self.camera_info else None
        is_shown = self.state == ConnectionState.CONNECTED and battery is not None
        self.battery_label.setText(f"Battery {battery} %" if is_shown else "")

    # Thumbnail size

    def _restore_thumbnail_size(self):
        saved = self.settings.thumbnail_size
        position = min(
            range(len(THUMBNAIL_SIZES)), key=lambda i: abs(THUMBNAIL_SIZES[i] - saved)
        )
        self.size_slider.setValue(position)
        self._apply_thumbnail_size(position)

    def _step_thumbnail_size(self, steps: int):
        self.size_slider.setValue(self.size_slider.value() + steps)

    def _apply_thumbnail_size(self, position: int):
        side = THUMBNAIL_SIZES[position]
        self.settings.thumbnail_size = side
        self.grid.set_thumbnail_side(side)

    # Selection

    def _update_selection(self):
        count = len(self.grid.selectionModel().selectedIndexes())
        self.selection_label.setText(f"{count} selected")
        self._update_download_action()

    # Destination and format

    def choose_destination(self) -> Path | None:
        """Ask for the destination folder; None if the user cancels."""
        start = str(self.settings.destination or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Destination folder", start)
        if not folder:
            return None
        self.settings.destination = Path(folder)
        self._show_destination(Path(folder))
        return Path(folder)

    def _show_destination(self, folder: Path | None):
        # Only the folder name: a long path would push Download off the toolbar.
        self.destination_action.setText(
            f"Folder: {folder.name or folder}" if folder else "Destination…"
        )
        self.destination_action.setToolTip(
            f"Destination folder: {folder}" if folder else "Choose the destination"
        )
        self.grid.set_destination(folder)

    def _save_format(self):
        self.settings.download_format = self.format_combo.currentData()

    # Downloading

    def _update_download_action(self):
        has_selection = self.grid.selectionModel().hasSelection()
        can_download = self.state == ConnectionState.CONNECTED and has_selection
        self.download_action.setEnabled(can_download and not self.downloader.is_running)

    def start_download(self):
        """Download the selected shots after checking folder and battery."""
        shots = self.grid.selected_shots()
        if not shots or self.downloader.is_running:
            return
        folder = self._writable_destination()
        if folder is None or not self._confirm_battery():
            return
        plan = plan_download(shots, self.format_combo.currentData())
        known_sizes = {path: info.size for path, info in self.model.infos.items()}
        self.downloader.start(
            plan.files, folder, known_sizes, len(plan.shots_not_in_format)
        )
        self.download_panel.show_started(len(plan.files))
        self._update_download_action()

    def _writable_destination(self) -> Path | None:
        """The remembered folder if usable, else one the user picks."""
        folder = self.settings.destination
        if folder is None or not folder.is_dir():
            folder = self.choose_destination()
        while folder is not None and not is_writable(folder):
            QMessageBox.warning(
                self,
                "Folder not writable",
                f"Can't write to {folder}. Please choose another folder.",
            )
            folder = self.choose_destination()
        return folder

    def _confirm_battery(self) -> bool:
        battery = self.camera_info.battery if self.camera_info else None
        if battery is None or battery >= LOW_BATTERY_PERCENT:
            return True
        answer = QMessageBox.question(
            self,
            "Low battery",
            f"The camera's battery is at {battery} %. A long download may "
            "drain it. Download anyway?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _cancel_download(self):
        self.downloader.cancel()
        self.download_panel.show_cancelling()

    def _on_file_done(self, path: str):
        self.model.refresh_destination()

    def _on_download_finished(self, summary: DownloadSummary):
        self.download_panel.show_summary(summary)
        self.model.refresh_destination()
        self.grid.schedule_wanted_update()
        self._update_download_action()

    # Closing

    def closeEvent(self, event):
        self.settings.geometry = self.saveGeometry()
        self.settings.splitter_state = self.splitter.saveState()
        self.settings.sync()
        self.downloader.cancel()
        self.queue.stop()
        super().closeEvent(event)
