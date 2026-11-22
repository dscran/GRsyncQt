"""Emitting Qt signals from worker threads."""

from PySide6.QtCore import SignalInstance


def emit_from_worker(signal: SignalInstance, *args):
    """Emit signal, unless its QObject was deleted meanwhile (e.g. on quit).

    Worker threads are daemons that may finish a request after the window
    and its objects are gone; there is nobody left to tell then.
    """
    try:
        signal.emit(*args)
    except RuntimeError:
        pass
