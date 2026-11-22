"""Human-readable sizes, speeds, durations and exposure data."""

from grsync_qt.camera import FileInfo

UNITS = ["B", "KB", "MB", "GB", "TB"]
UNIT_STEP = 1000
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600


def format_bytes(num_bytes: float) -> str:
    """Return e.g. '10.3 MB' (decimal units, like file managers)."""
    value = float(num_bytes)
    for unit in UNITS[:-1]:
        if value < UNIT_STEP:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= UNIT_STEP
    return f"{value:.1f} {UNITS[-1]}"


def format_duration(seconds: float | None) -> str:
    """Return e.g. '1 h 05 min', '3 min 20 s' or '45 s'; '…' if unknown."""
    if seconds is None:
        return "…"
    total = round(seconds)
    hours, rest = divmod(total, SECONDS_PER_HOUR)
    minutes, secs = divmod(rest, SECONDS_PER_MINUTE)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


MINUS_SIGN = "\u2212"
EXPOSURE_SEPARATOR = " · "
NO_ISO_VALUES = ("", "auto", "0")


def format_exposure(info: FileInfo) -> str:
    """Return e.g. 'ISO 3200 · f/4.5 · 1/4 s · 0 EV'; '' if there is none.

    Videos report no ISO, aperture or shutter speed, so they get ''.
    """
    parts = [
        format_iso(info.iso),
        format_aperture(info.aperture),
        format_shutter_speed(info.shutter_speed),
    ]
    if not any(parts):
        return ""
    parts.append(format_compensation(info.exposure_compensation))
    return EXPOSURE_SEPARATOR.join(part for part in parts if part)


def format_iso(iso: str) -> str:
    return "" if iso.lower() in NO_ISO_VALUES else f"ISO {iso}"


def format_aperture(aperture: str) -> str:
    try:
        f_number = float(aperture)
    except ValueError:
        return aperture
    return f"f/{f_number:g}" if f_number > 0 else ""


def format_shutter_speed(shutter_speed: str) -> str:
    """'1.4' is 1/4 s and '2.1' is 2 s: the camera sends 'numerator.denominator'."""
    numerator, _, denominator = shutter_speed.partition(".")
    if not (numerator.isdigit() and denominator.isdigit()):
        return shutter_speed
    numerator, denominator = int(numerator), int(denominator)
    if numerator == 0 or denominator == 0:
        return ""
    if numerator % denominator == 0:
        return f"{numerator // denominator} s"
    if numerator < denominator:
        return f"{numerator}/{denominator} s"
    return f"{numerator / denominator:g} s"


def format_compensation(compensation: str) -> str:
    try:
        value = float(compensation)
    except ValueError:
        return compensation
    if value == 0:
        return "0 EV"
    sign = "+" if value > 0 else MINUS_SIGN
    return f"{sign}{abs(value):g} EV"
