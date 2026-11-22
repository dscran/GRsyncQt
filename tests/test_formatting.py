import pytest

from grsync_qt.camera import FileInfo
from grsync_qt.ui.formatting import format_bytes, format_duration, format_exposure


def exposure(av="4.5", tv="1.4", sv="3200", xv="0.0") -> FileInfo:
    return FileInfo(1, 1, "", av, tv, sv, xv)


def test_measured_values():
    assert format_exposure(exposure()) == "ISO 3200 · f/4.5 · 1/4 s · 0 EV"


@pytest.mark.parametrize(
    ("tv", "text"),
    [("2.1", "2 s"), ("1.250", "1/250 s"), ("13.10", "1.3 s"), ("30.1", "30 s")],
)
def test_shutter_speeds(tv, text):
    assert text in format_exposure(exposure(tv=tv))


@pytest.mark.parametrize(
    ("xv", "text"), [("-1.3", "−1.3 EV"), ("0.7", "+0.7 EV"), ("-0.0", "0 EV")]
)
def test_compensation(xv, text):
    assert format_exposure(exposure(xv=xv)).endswith(text)


def test_unparseable_shutter_speed_is_shown_raw():
    assert '1/4"' in format_exposure(exposure(tv='1/4"'))


def test_whole_f_number():
    assert "f/16 " in format_exposure(exposure(av="16.0"))


def test_video_gives_no_text():
    assert format_exposure(exposure(av="0.0", tv="0.0", sv="auto", xv="0.0")) == ""


def test_missing_fields_give_no_text():
    assert format_exposure(FileInfo(1, 1, "")) == ""


def test_bytes_and_durations():
    assert format_bytes(10285531) == "10.3 MB"
    assert format_bytes(512) == "512 B"
    assert format_duration(3725) == "1 h 02 min"
    assert format_duration(200) == "3 min 20 s"
    assert format_duration(None) == "…"
