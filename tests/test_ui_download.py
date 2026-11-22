import os

import pytest
from fake_camera import FakeCamera, FakeFile
from PySide6.QtWidgets import QFileDialog, QMessageBox
from ui_helpers import TIMEOUT_MS, connect, open_window, select_rows

from grsync_qt import downloader as downloader_module
from grsync_qt.downloader import DownloadSummary
from grsync_qt.shots import DownloadFormat
from grsync_qt.ui.download_panel import summary_text

TEN_JPGS = [FakeFile("100RICOH", f"R00000{n:02d}.JPG") for n in range(1, 11)]


@pytest.fixture
def camera():
    camera = FakeCamera(card=list(TEN_JPGS)).start()
    yield camera
    camera.stop()


@pytest.fixture
def window(camera, qtbot):
    window = open_window(camera.url, qtbot)
    connect(window, qtbot)
    window.format_combo.setCurrentIndex(
        window.format_combo.findData(DownloadFormat.JPG)
    )
    yield window
    window.close()


@pytest.fixture
def folder_dialog(monkeypatch, tmp_path):
    """Answers the folder dialog with the folders in answers, in turn."""
    answers = [str(tmp_path / "photos")]
    asked = []

    def get_existing_directory(*args, **kwargs):
        asked.append(args)
        return answers.pop(0) if answers else ""

    os.mkdir(answers[0])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", get_existing_directory)
    return answers, asked


def download_requests(camera):
    return [p for p in camera.paths_requested() if p.endswith(".JPG")]


def wait_for_summary(window, qtbot):
    qtbot.waitUntil(
        lambda: window.download_panel.close_button.isVisible(), timeout=TIMEOUT_MS
    )
    return window.download_panel.status_label.text()


def test_first_download_asks_for_a_folder(window, camera, qtbot, folder_dialog):
    answers, asked = folder_dialog
    folder = answers[0]
    select_rows(window, [0, 1])

    window.download_action.trigger()
    text = wait_for_summary(window, qtbot)

    assert len(asked) == 1
    assert sorted(os.listdir(folder)) == ["R0000009.JPG", "R0000010.JPG"]
    assert window.settings.destination is not None
    assert text.startswith("Download finished. 2 downloaded")


def test_unwritable_folder_is_refused_before_downloading(
    window, camera, qtbot, folder_dialog, monkeypatch, tmp_path
):
    answers, asked = folder_dialog
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o500)
    answers.insert(0, str(read_only))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    answers.pop()  # the user cancels the second folder dialog
    select_rows(window, [0])

    try:
        window.download_action.trigger()
    finally:
        read_only.chmod(0o700)

    assert len(warnings) == 1 and "Can't write to" in warnings[0][2]
    assert len(asked) == 2
    assert download_requests(camera) == []
    assert not window.download_panel.isVisible()


def test_low_battery_warns_and_cancel_sends_nothing(
    window, camera, qtbot, folder_dialog, monkeypatch
):
    camera.props["battery"] = 10
    connect(window, qtbot)
    questions = []

    def answer_no(*args, **kwargs):
        questions.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer_no)
    select_rows(window, [0])

    window.download_action.trigger()
    qtbot.wait(200)

    assert len(questions) == 1 and "10 %" in questions[0][2]
    assert download_requests(camera) == []


def test_low_battery_continue_downloads(
    window, camera, qtbot, folder_dialog, monkeypatch
):
    camera.props["battery"] = 10
    connect(window, qtbot)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    select_rows(window, [0])

    window.download_action.trigger()

    assert "1 downloaded" in wait_for_summary(window, qtbot)


def test_progress_text_shows_3_of_10(window, camera, qtbot, folder_dialog, monkeypatch):
    monkeypatch.setattr(downloader_module, "PROGRESS_INTERVAL_SECONDS", 0)
    camera.chunk_delay = 0.01
    texts = []
    window.downloader.progress.connect(
        lambda progress: texts.append(window.download_panel.status_label.text())
    )
    window.select_all_action.trigger()

    window.download_action.trigger()
    wait_for_summary(window, qtbot)

    third = [text for text in texts if "R0000008.JPG" in text]
    assert third and "(3 of 10)" in third[-1]
    assert " done · " in third[-1] and "/s · " in third[-1] and " left" in third[-1]


def test_summary_shows_counts_and_the_failed_files_reason(
    window, camera, qtbot, folder_dialog
):
    answers, _ = folder_dialog
    folder = answers[0]
    for name in ("R0000010.JPG", "R0000009.JPG", "R0000008.JPG"):
        size = camera.file(f"100RICOH/{name}").size
        with open(os.path.join(folder, name), "wb") as file:
            file.write(b"\0" * size)  # presence is judged by name and size
    camera.errors["/v1/photos/100RICOH/R0000005.JPG"] = 500
    window.select_all_action.trigger()

    window.download_action.trigger()
    text = wait_for_summary(window, qtbot)

    assert text.splitlines() == [
        "Download finished. 6 downloaded, 3 already present, "
        "0 not in the chosen format, 1 failed, 0 not attempted.",
        "R0000005.JPG: camera answered HTTP 500",
    ]


def test_cancel_button_stops_the_download(window, camera, qtbot, folder_dialog):
    camera.chunk_delay = 0.05
    window.select_all_action.trigger()

    window.download_action.trigger()
    qtbot.waitUntil(lambda: len(download_requests(camera)) >= 1, timeout=TIMEOUT_MS)
    window.download_panel.cancel_button.click()
    text = wait_for_summary(window, qtbot)

    assert text.startswith("Download cancelled.")
    assert len(download_requests(camera)) == 1


def test_summary_text_for_a_lost_connection():
    summary = DownloadSummary(
        downloaded=["1/A.JPG"],
        failed=[("1/B.JPG", "connection to the camera lost")],
        not_attempted=["1/C.JPG"],
        lost_connection=True,
    )

    assert summary_text(summary).splitlines() == [
        "Download stopped: the camera stopped answering. 1 downloaded, "
        "0 already present, 0 not in the chosen format, 1 failed, 1 not attempted.",
        "B.JPG: connection to the camera lost",
    ]
