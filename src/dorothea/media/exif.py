"""Photo metadata: EXIF read with ExifRead, and embedded captions read with Pillow.

``read_photo_info`` reads a photo's EXIF once into a ``PhotoInfo``: the capture time (used to
order items whose URLs collide) and the shooting details shown with ``exif_display`` (#20).
GPS (#21, #23) will be added here too.

``embedded_caption`` reads the title and description photo editors store in the file
(``embedded_captions``, #51): XMP's ``dc:title``/``dc:description`` (Lightroom, Capture One,
Apple Photos, darktable), else IPTC's ObjectName/Caption-Abstract. EXIF's own ImageDescription
is left out on purpose: many cameras fill it with "OLYMPUS DIGITAL CAMERA" or spaces.
"""

import contextlib
import logging
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import exifread
from PIL import Image, IptcImagePlugin, UnidentifiedImageError

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


_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _clean(text: str | None) -> str:
    """Line endings normalised, blank lines at the ends dropped."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _xmp_packet(image: Image.Image) -> bytes | None:
    """The XMP packet, where Pillow keeps it for each format (JPEG/WebP/HEIC, PNG, TIFF)."""
    for key in ("xmp", "XML:com.adobe.xmp"):
        if value := image.info.get(key):
            return value.encode() if isinstance(value, str) else value
    tags = getattr(image, "tag_v2", None)
    value = tags.get(700) if tags is not None else None  # TIFF's XMP tag
    return value if isinstance(value, bytes) else None


def _xmp_text(root: ElementTree.Element, name: str) -> str:
    """``dc:title``/``dc:description``: the default-language entry of its ``rdf:Alt``."""
    element = root.find(f".//{_DC}{name}")
    if element is None:
        return ""
    entries = element.findall(f".//{_RDF}li")
    for entry in entries:
        if entry.get(_LANG) == "x-default":
            return _clean(entry.text)
    return _clean(entries[0].text if entries else element.text)


def _iptc_text(info: dict, dataset: int) -> str:
    """An IPTC application record field (2:05 ObjectName, 2:120 Caption-Abstract)."""
    value = info.get((2, dataset))
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, bytes):
        return ""
    try:
        return _clean(value.decode("utf-8"))
    except UnicodeDecodeError:  # older files: Latin-1 unless they declare UTF-8
        return _clean(value.decode("latin-1"))


@dataclass(frozen=True)
class EmbeddedCaption:
    """A photo's title and description, as a photo editor stored them ("" when it has none)."""

    title: str = ""
    description: str = ""


def embedded_caption(path: Path) -> EmbeddedCaption:
    """The title and description stored in a photo (see the module docstring); XMP first."""
    try:
        with Image.open(path) as image:
            packet = _xmp_packet(image)
            iptc = IptcImagePlugin.getiptcinfo(image) or {}
    except OSError, UnidentifiedImageError, ValueError, SyntaxError:
        return EmbeddedCaption()

    title = description = ""
    if packet:
        # ElementTree (expat) refuses external entities and limits entity expansion
        with contextlib.suppress(ElementTree.ParseError):
            root = ElementTree.fromstring(packet.rstrip(b"\x00 \n\r\t"))
            title, description = _xmp_text(root, "title"), _xmp_text(root, "description")
    return EmbeddedCaption(
        title or _iptc_text(iptc, 5),
        description or _iptc_text(iptc, 120),
    )
