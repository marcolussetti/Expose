"""EXIF metadata, read with ExifRead.

``read_photo_info`` reads a photo's EXIF once into a ``PhotoInfo``: the capture time (used to
order items whose URLs collide) and the shooting details shown with ``exif_display`` (#20).
GPS (#21, #23) will be added here too.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import exifread

# ExifRead logs a warning for every file without EXIF ("File format not recognized"), e.g.
# videos; missing metadata is normal here, so only let real errors through.
logging.getLogger("exifread").setLevel(logging.ERROR)

# Shooting details, in display order: the template variables and caption keys (#20)
DETAIL_KEYS = ("camera", "lens", "focal_length", "aperture", "shutter_speed", "iso")

# Company suffixes that makers put in the Make tag ("NIKON CORPORATION")
_MAKE_SUFFIX = re.compile(
    r"[\s,]+(corporation|corp\.?|co\.?,?\s*ltd\.?|company|camera\s+ag|imaging\b.*|optical\b.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PhotoInfo:
    """Metadata read from a photo's EXIF. Fields are None when the photo doesn't record them."""

    capture_time: float | None = None  # POSIX timestamp of when the photo was taken
    # Shooting details, formatted for display (``DETAIL_KEYS`` → "23mm", "f/2", "1/250s", "160")
    details: dict[str, str] = field(default_factory=dict, hash=False)


def _parse_exif_datetime(value: object) -> float | None:
    """``2022:09:23 08:17:33`` (local time, as cameras record it) → POSIX timestamp."""
    try:
        return datetime.strptime(str(value).strip(), "%Y:%m:%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def _text(tags: dict[str, Any], key: str) -> str:
    """A string tag, stripped of padding (some cameras fill unused bytes with spaces/NULs)."""
    tag = tags.get(key)
    if tag is None:
        return ""
    value = " ".join(str(tag.values).replace("\x00", " ").split())
    # Placeholders some cameras write when there's no value
    return "" if not value.strip("-") or value.lower() in ("unknown", "none") else value


def _number(tags: dict[str, Any], key: str) -> Fraction | None:
    """A numeric tag's first value; None when missing, zero or undefined (``0/0``)."""
    tag = tags.get(key)
    values = getattr(tag, "values", None)
    if not isinstance(values, list) or not values:
        return None
    try:
        value = Fraction(values[0])
    except TypeError, ValueError, ZeroDivisionError:
        return None
    return value if value > 0 else None


def _decimal(value: Fraction) -> str:
    """At most one decimal, no trailing zero: 2 → "2", 2.8 → "2.8", 4.25 → "4.2"."""
    return f"{round(float(value), 1):g}"


def camera_name(make: str, model: str) -> str:
    """ "FUJIFILM" + "X-T4" → "Fujifilm X-T4"; "Canon" + "Canon EOS R5" → "Canon EOS R5"."""
    make = _MAKE_SUFFIX.sub("", make).strip()
    if make.isupper() and len(make) > 3:  # SONY, NIKON, FUJIFILM; keep acronyms like LGE, HTC
        make = make.title()
    if not make or model.lower().startswith(make.lower()):
        return model
    return f"{make} {model}".strip()


def format_shutter_speed(seconds: Fraction) -> str:
    """1/250 → "1/250s"; 0.3 → "1/3s"; 2.5 → "2.5s"."""
    if seconds < 1:
        return f"1/{round(1 / seconds)}s"
    return f"{_decimal(seconds)}s"


def shooting_details(tags: dict[str, Any]) -> dict[str, str]:
    """The ``DETAIL_KEYS`` a photo records, formatted for display. Missing ones are left out."""
    details = {}
    if camera := camera_name(_text(tags, "Image Make"), _text(tags, "Image Model")):
        details["camera"] = camera
    if lens := _text(tags, "EXIF LensModel"):
        details["lens"] = lens
    if focal := _number(tags, "EXIF FocalLength"):
        details["focal_length"] = f"{_decimal(focal)}mm"
    if aperture := _number(tags, "EXIF FNumber"):
        details["aperture"] = f"f/{_decimal(aperture)}"
    if exposure := _number(tags, "EXIF ExposureTime"):
        details["shutter_speed"] = format_shutter_speed(exposure)
    if iso := _number(tags, "EXIF ISOSpeedRatings"):
        details["iso"] = str(int(iso))
    return details


def read_photo_info(path: Path) -> PhotoInfo:
    """Read a photo's EXIF. Files without EXIF, or that can't be read, give an empty PhotoInfo."""
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except OSError:
        return PhotoInfo()

    # DateTimeOriginal, else DateTimeDigitized. The base "Image DateTime" tag is ignored: editors
    # set it on export, so it's the last-modified time rather than the capture time.
    capture_time = None
    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized"):
        if key in tags:
            capture_time = _parse_exif_datetime(tags[key])
            if capture_time is not None:
                break

    return PhotoInfo(capture_time=capture_time, details=shooting_details(tags))
