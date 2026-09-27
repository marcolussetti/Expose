"""Metadata kept in resized images, and conversion of wide-gamut photos to sRGB (#12)."""

import io

import exifread
import pytest
from PIL import Image, ImageCms
from PIL.TiffImagePlugin import IFDRational

from dorothea.config import DEFAULT_CONFIG, Config, ConfigError
from dorothea.media.image import ImageProcessor
from dorothea.media.metadata import KEEP_METADATA_LEVELS
from tests.conftest import DATADIR, HAS_IMAGEMAGICK, make_generator

P3 = (DATADIR / "icc" / "DisplayP3-v2-micro.icc").read_bytes()
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>'
COLOUR = (200, 100, 50)  # inside sRGB's gamut, but a different colour when read as Display P3


def source_photo(path, icc=P3, orientation=1, size=(1200, 900)):
    """A photo carrying every kind of metadata the levels choose between."""
    exif = Image.Exif()
    exif[0x013B] = "Jane Doe"  # Artist
    exif[0x8298] = "(c) Jane Doe"  # Copyright
    exif[0x010F] = "NIKON CORPORATION"  # Make
    exif[0x0110] = "NIKON D7500"  # Model
    exif[0x0131] = "Lightroom"  # Software
    exif[0x0112] = orientation
    exif[0x8769] = {
        0x829D: IFDRational(28, 5),  # FNumber f/5.6
        0x829A: IFDRational(1, 100),  # ExposureTime
        0x8827: 640,  # ISO
        0x9003: "2021:04:18 12:22:09",  # DateTimeOriginal
        0xA434: "18-35mm f/1.8",  # LensModel
        0xA431: "SERIAL-123",  # BodySerialNumber
        0x927C: b"maker-note",  # MakerNote
    }
    exif[0x8825] = {  # GPS: 64.14 N, 21.94 W
        1: "N",
        2: (IFDRational(64), IFDRational(8), IFDRational(24)),
        3: "W",
        4: (IFDRational(21), IFDRational(56), IFDRational(24)),
    }
    kwargs = {"exif": exif, "xmp": XMP, "quality": 95}
    if icc:
        kwargs["icc_profile"] = icc
    Image.new("RGB", size, COLOUR).save(path, **kwargs)
    return path


def resize(tmp_path, keep="none", convert=False, **source):
    src = source_photo(tmp_path / "src.jpg", **source)
    out = tmp_path / "out.jpg"
    ImageProcessor().resize(src, out, width=640, convert_to_srgb=convert, keep_metadata=keep)
    return out


def tags(path):
    with open(path, "rb") as f:
        return {k: str(v) for k, v in exifread.process_file(f, details=True).items()}


def centre(path):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel((img.width // 2, img.height // 2))


COPYRIGHT = {"Image Artist", "Image Copyright"}
CAMERA = {"Image Make", "Image Model", "EXIF LensModel", "EXIF FNumber", "EXIF ISOSpeedRatings",
          "EXIF DateTimeOriginal"}  # fmt: skip
LOCATION = {"GPS GPSLatitude", "GPS GPSLongitude"}
EXTRAS = {"Image Software", "EXIF BodySerialNumber"}


class TestKeepMetadata:
    @pytest.mark.parametrize(
        "level,kept",
        [
            ("none", set()),
            ("copyright", COPYRIGHT),
            ("camera", COPYRIGHT | CAMERA),
            ("location", COPYRIGHT | LOCATION),
            ("cameralocation", COPYRIGHT | CAMERA | LOCATION),
            ("all", COPYRIGHT | CAMERA | LOCATION | EXTRAS),
        ],
    )
    def test_levels(self, tmp_path, level, kept):
        found = set(tags(resize(tmp_path, keep=level)))
        everything = COPYRIGHT | CAMERA | LOCATION | EXTRAS
        assert kept <= found, kept - found
        assert not (everything - kept) & found, (everything - kept) & found

    def test_camera_values_survive(self, tmp_path):
        found = tags(resize(tmp_path, keep="camera"))
        assert found["Image Model"] == "NIKON D7500"
        assert found["EXIF FNumber"] == "28/5"
        assert found["EXIF DateTimeOriginal"] == "2021:04:18 12:22:09"

    def test_only_all_keeps_xmp_and_maker_notes(self, tmp_path):
        with Image.open(resize(tmp_path, keep="all")) as img:
            assert img.info.get("xmp") == XMP
        with Image.open(resize(tmp_path, keep="cameralocation")) as img:
            assert "xmp" not in img.info
        assert "EXIF MakerNote" not in tags(resize(tmp_path, keep="cameralocation"))

    @pytest.mark.parametrize("level", ["camera", "all"])
    def test_orientation_reset_after_autorotate(self, tmp_path, level):
        """The pixels are already upright; keeping orientation 6 would rotate them twice."""
        out = resize(tmp_path, keep=level, orientation=6)
        with Image.open(out) as img:
            assert img.height > img.width  # rotated to portrait
            assert img.getexif().get(0x0112, 1) == 1

    def test_none_writes_no_metadata(self, tmp_path):
        """expose.sh's behaviour (--legacy): no EXIF, XMP or ICC profile."""
        out = resize(tmp_path, keep="none")
        with Image.open(out) as img:
            assert not img.getexif()
            assert "xmp" not in img.info and "icc_profile" not in img.info


class TestColourConversion:
    def test_p3_is_converted_to_srgb(self, tmp_path):
        out = resize(tmp_path, convert=True)
        with Image.open(out) as img:
            assert "icc_profile" not in img.info  # untagged means sRGB
        r, g, b = centre(out)
        # P3 (200, 100, 50) is a more saturated orange in sRGB: red up, blue down
        assert r > COLOUR[0] + 5 and b < COLOUR[2] - 5

    def test_legacy_strips_without_converting(self, tmp_path):
        out = resize(tmp_path, convert=False, keep="none")
        with Image.open(out) as img:
            assert "icc_profile" not in img.info
        assert all(abs(a - b) <= 3 for a, b in zip(centre(out), COLOUR, strict=True))

    def test_unconverted_profile_is_kept_with_metadata(self, tmp_path):
        """Not converting but keeping metadata: the profile stays so colours are still right."""
        with Image.open(resize(tmp_path, convert=False, keep="camera")) as img:
            assert img.info.get("icc_profile") == P3

    def test_srgb_photos_are_left_alone(self, tmp_path):
        out = resize(tmp_path, convert=True, icc=SRGB)
        assert all(abs(a - b) <= 3 for a, b in zip(centre(out), COLOUR, strict=True))

    @pytest.mark.skipif(not HAS_IMAGEMAGICK, reason="ImageMagick not installed")
    def test_image_options_path_converts_too(self, tmp_path):
        """Photos with image-options go through ImageMagick, which converts via -profile."""
        src = source_photo(tmp_path / "src.jpg")
        out = tmp_path / "out.jpg"
        ImageProcessor().resize(
            src, out, width=640, additional_args=["-sharpen", "0x0.5"], convert_to_srgb=True
        )
        r, _g, b = centre(out)
        assert r > COLOUR[0] + 5 and b < COLOUR[2] - 5

    def test_untagged_photos_are_left_alone(self, tmp_path):
        out = resize(tmp_path, convert=True, icc=None)
        assert all(abs(a - b) <= 3 for a, b in zip(centre(out), COLOUR, strict=True))


class TestBuild:
    def _gallery(self, tmp_path):
        (tmp_path / "g").mkdir()
        source_photo(tmp_path / "g" / "photo.jpg")

    def test_defaults_keep_camera_info_but_not_location(self, tmp_path):
        self._gallery(tmp_path)
        make_generator(tmp_path).run()
        found = tags(tmp_path / "_site" / "g" / "photo" / "1024.jpg")
        assert set(found) >= CAMERA
        assert not LOCATION & set(found)

    def test_legacy_keeps_nothing(self, tmp_path):
        self._gallery(tmp_path)
        make_generator(tmp_path, config_overrides={"legacy": True, "keep_metadata": "none",
                                                   "convert_to_srgb": False}).run()  # fmt: skip
        with Image.open(tmp_path / "_site" / "g" / "photo" / "1024.jpg") as img:
            assert not img.getexif() and "icc_profile" not in img.info

    def test_changing_the_level_rebuilds_images(self, tmp_path):
        self._gallery(tmp_path)
        make_generator(tmp_path).run()
        gen = make_generator(tmp_path, config_overrides={"keep_metadata": "all"})
        gen.dry_run = gen.scanner.dry_run = True
        gen.run()
        assert gen.planned == [("g/photo/1024.jpg", "settings changed")]


class TestSettings:
    @pytest.mark.parametrize("level", KEEP_METADATA_LEVELS)
    def test_valid_levels(self, tmp_path, level):
        Config({**DEFAULT_CONFIG, "keep_metadata": level}).validate(tmp_path)

    def test_invalid_level(self, tmp_path):
        with pytest.raises(ConfigError, match="keep_metadata must be one of"):
            Config({**DEFAULT_CONFIG, "keep_metadata": "everything"}).validate(tmp_path)

    def test_convert_must_be_boolean(self, tmp_path):
        with pytest.raises(ConfigError, match="convert_to_srgb must be true or false"):
            Config({**DEFAULT_CONFIG, "convert_to_srgb": "yes"}).validate(tmp_path)


def test_p3_fixture_is_really_p3():
    profile = ImageCms.ImageCmsProfile(io.BytesIO(P3))
    assert "P3" in ImageCms.getProfileDescription(profile)
