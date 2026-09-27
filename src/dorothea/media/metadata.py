"""What metadata and colour profile resized images keep (#12).

expose.sh strips everything (``convert … +profile '*'``). Dorothea can instead keep chosen groups
of EXIF tags (``keep_metadata``) and convert wide-gamut photos to sRGB (``convert_to_srgb``), so
they don't look dull once their ICC profile is gone.
"""

import io
import tempfile
from pathlib import Path

from PIL import Image, ImageCms

KEEP_METADATA_LEVELS = ("none", "copyright", "camera", "location", "cameralocation", "all")

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
ORIENTATION = 0x0112

# Tag groups, by EXIF tag number
COPYRIGHT_TAGS = {0x013B, 0x8298}  # Artist, Copyright
CAMERA_TAGS = {0x010F, 0x0110}  # Make, Model
CAMERA_EXIF_TAGS = {
    0x829A,  # ExposureTime
    0x829D,  # FNumber
    0x8822,  # ExposureProgram
    0x8827,  # ISOSpeedRatings
    0x9003,  # DateTimeOriginal
    0x9004,  # DateTimeDigitized
    0x9010,  # OffsetTime
    0x9011,  # OffsetTimeOriginal
    0x9012,  # OffsetTimeDigitized
    0x9201,  # ShutterSpeedValue
    0x9202,  # ApertureValue
    0x9204,  # ExposureBiasValue
    0x9205,  # MaxApertureValue
    0x9207,  # MeteringMode
    0x9209,  # Flash
    0x920A,  # FocalLength
    0xA402,  # ExposureMode
    0xA403,  # WhiteBalance
    0xA405,  # FocalLengthIn35mmFilm
    0xA406,  # SceneCaptureType
    0xA432,  # LensSpecification
    0xA433,  # LensMake
    0xA434,  # LensModel
}
# Dropped even by "all": they describe the original file, not the resized one
STALE_EXIF_TAGS = {0xA002, 0xA003, 0xA005}  # PixelXDimension, PixelYDimension, Interop pointer

LEVEL_GROUPS = {
    "none": set(),
    "copyright": {"copyright"},
    "camera": {"copyright", "camera"},
    "location": {"copyright", "location"},
    "cameralocation": {"copyright", "camera", "location"},
}


def filtered_exif(source: Image.Exif, level: str, oriented: bool) -> Image.Exif | None:
    """The EXIF to write into a resized image for a ``keep_metadata`` level (None: no EXIF).

    Args:
        source: The original photo's EXIF.
        level: One of ``KEEP_METADATA_LEVELS``.
        oriented: The pixels were already rotated upright (autorotate), so the orientation tag
            must say "normal" or viewers would rotate the photo a second time.
    """
    if level == "none" or not source:
        return None
    exif_ifd = dict(source.get_ifd(EXIF_IFD))
    gps_ifd = dict(source.get_ifd(GPS_IFD))
    out = Image.Exif()

    if level == "all":
        for tag, value in source.items():
            if tag not in (EXIF_IFD, GPS_IFD):
                out[tag] = value
        exif_keep = {t: v for t, v in exif_ifd.items() if t not in STALE_EXIF_TAGS}
        gps_keep = gps_ifd
    else:
        groups = LEVEL_GROUPS[level]
        tags = (COPYRIGHT_TAGS if "copyright" in groups else set()) | (
            CAMERA_TAGS if "camera" in groups else set()
        )
        for tag in tags & set(source):
            out[tag] = source[tag]
        exif_keep = (
            {t: v for t, v in exif_ifd.items() if t in CAMERA_EXIF_TAGS}
            if "camera" in groups
            else {}
        )
        gps_keep = gps_ifd if "location" in groups else {}

    if exif_keep:
        out[EXIF_IFD] = exif_keep
    if gps_keep:
        out[GPS_IFD] = gps_keep
    if oriented and ORIENTATION in out:
        out[ORIENTATION] = 1
    return out if len(out) else None


def is_srgb(icc_profile: bytes) -> bool:
    """True for profiles that describe themselves as sRGB (no conversion needed)."""
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
        return "srgb" in ImageCms.getProfileDescription(profile).lower()
    except OSError, ImageCms.PyCMSError:
        return False


def to_srgb(img: Image.Image, icc_profile: bytes) -> Image.Image:
    """Convert an image from its embedded ICC profile to sRGB.

    Raises:
        ImageCms.PyCMSError: If the profile or image mode can't be converted.
    """
    source = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
    converted = ImageCms.profileToProfile(
        img, source, ImageCms.createProfile("sRGB"), outputMode="RGB"
    )
    if converted is None:  # only returned when converting in place
        raise ImageCms.PyCMSError("conversion returned no image")
    return converted


_srgb_profile_path: Path | None = None


def srgb_profile_file() -> Path:
    """An sRGB ICC profile on disk, for ImageMagick's ``-profile`` (created once per run)."""
    global _srgb_profile_path
    if _srgb_profile_path is None or not _srgb_profile_path.exists():
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        with tempfile.NamedTemporaryFile(suffix=".icc", delete=False) as f:
            f.write(profile.tobytes())
        _srgb_profile_path = Path(f.name)
    return _srgb_profile_path
