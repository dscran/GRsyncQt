"""Command line entry point: parse options, then start the Qt app."""

import argparse
import logging
import sys

DEFAULT_HOST = "http://192.168.0.1/"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line options."""
    parser = argparse.ArgumentParser(
        prog="grsync-qt",
        description="Browse and download photos from a Ricoh GR III / GR IIIx.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"camera base URL (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="log every camera request"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start the app and return its exit code."""
    options = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if options.verbose else logging.WARNING)

    # Imported late so that --help works without loading Qt.
    from PySide6.QtWidgets import QApplication

    from grsync_qt.settings import Settings
    from grsync_qt.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("grsync-qt")
    window = MainWindow(options.host, Settings())
    window.show()
    window.connect_camera()
    return app.exec()
