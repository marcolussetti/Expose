"""EXIF metadata, read with ExifRead.

``read_photo_info`` reads a photo's EXIF once into a ``PhotoInfo``. Today that's the capture time
(used to order items whose URLs collide); camera/lens details (#20) and GPS (#21, #23) will be
added here too.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import exifread

# ExifRead logs a warning for every file without EXIF ("File format not recognized"), e.g.
# videos; missing metadata is normal here, so only let real errors through.
logging.getLogger("exifread").setLevel(logging.ERROR)


@dataclass(frozen=True)
class PhotoInfo:
    """Metadata read from a photo's EXIF. Fields are None when the photo doesn't record them."""

    capture_time: float | None = None  # POSIX timestamp of when the photo was taken


def _parse_exif_datetime(value: object) -> float | None:
    """``2022:09:23 08:17:33`` (local time, as cameras record it) → POSIX timestamp."""
    try:
        return datetime.strptime(str(value).strip(), "%Y:%m:%d %H:%M:%S").timestamp()
    except ValueError:
        return None


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

    return PhotoInfo(capture_time=capture_time)
