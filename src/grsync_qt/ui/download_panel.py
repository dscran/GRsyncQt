"""Progress, cancel and summary of a download, below the grid."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from grsync_qt.downloader import DownloadProgress, DownloadSummary
from grsync_qt.ui.formatting import format_bytes, format_duration
from grsync_qt.ui.shot_model import file_name_of


class DownloadPanel(QWidget):
    """Shows a running download and, when it ends, its summary."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.hide)
        layout = QHBoxLayout(self)
        layout.addWidget(self.status_label, stretch=1)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.close_button)
        self.hide()

    def show_started(self, num_files: int):
        self.progress_bar.setRange(0, max(num_files, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_button.show()
        self.cancel_button.setEnabled(True)
        self.close_button.hide()
        self.status_label.setText(f"Starting download of {num_files} files…")
        self.show()

    def show_progress(self, progress: DownloadProgress):
        self.progress_bar.setValue(progress.file_number - 1)
        self.status_label.setText(progress_text(progress))

    def show_cancelling(self):
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Cancelling…")

    def show_summary(self, summary: DownloadSummary):
        self.progress_bar.hide()
        self.cancel_button.hide()
        self.close_button.show()
        self.status_label.setText(summary_text(summary))
        self.show()


def progress_text(progress: DownloadProgress) -> str:
    return (
        f"Downloading {progress.file_name} ({progress.position_text}) · "
        f"{format_bytes(progress.bytes_done)} done · "
        f"{format_bytes(progress.bytes_per_second)}/s · "
        f"{format_duration(progress.seconds_remaining)} left"
    )


def summary_text(summary: DownloadSummary) -> str:
    if summary.was_cancelled:
        heading = "Download cancelled."
    elif summary.lost_connection:
        heading = "Download stopped: the camera stopped answering."
    else:
        heading = "Download finished."
    counts = (
        f"{len(summary.downloaded)} downloaded, "
        f"{len(summary.already_present)} already present, "
        f"{summary.not_in_format} not in the chosen format, "
        f"{len(summary.failed)} failed, "
        f"{len(summary.not_attempted)} not attempted."
    )
    failures = [f"{file_name_of(path)}: {reason}" for path, reason in summary.failed]
    return "\n".join([f"{heading} {counts}", *failures])
