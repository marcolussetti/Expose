"""Photo details from EXIF: camera, lens, exposure (#20)."""

import io
import json
from fractions import Fraction
from pathlib import Path

import exifread
import pytest
from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

from dorothea.builder import exif_mode, exposure_summary, photo_details
from dorothea.cache import CACHE_NAME
from dorothea.config import DEFAULT_CONFIG, EXPOSE_DEFAULTS, Config, ConfigError
from dorothea.media.exif import (
    camera_name,
    format_shutter_speed,
    read_photo_info,
    shooting_details,
)
from tests.conftest import make_generator

XT4 = {
    "make": "FUJIFILM",
    "model": "X-T4",
    "lens": "XF23mmF2 R WR",
    "focal": IFDRational(23, 1),
    "fnumber": IFDRational(2, 1),
    "exposure": IFDRational(1, 250),
    "iso": 160,
}
XT4_DETAILS = {
    "camera": "Fujifilm X-T4",
    "lens": "XF23mmF2 R WR",
    "focal_length": "23mm",
    "aperture": "f/2",
    "shutter_speed": "1/250s",
    "iso": "160",
}


def exif_photo(path: Path | io.BytesIO, **tags) -> Path | io.BytesIO:
    """A small JPEG with the given EXIF (keys as in ``XT4``; missing ones aren't written)."""
    exif = Image.Exif()
    if "make" in tags:
        exif[ExifTags.Base.Make] = tags["make"]
    if "model" in tags:
        exif[ExifTags.Base.Model] = tags["model"]
    ifd = exif.get_ifd(ExifTags.IFD.Exif)
    for key, tag in (
        ("lens", ExifTags.Base.LensModel),
        ("focal", ExifTags.Base.FocalLength),
        ("fnumber", ExifTags.Base.FNumber),
        ("exposure", ExifTags.Base.ExposureTime),
        ("iso", ExifTags.Base.ISOSpeedRatings),
    ):
        if key in tags:
            ifd[tag] = tags[key]
    Image.new("RGB", (1200, 800), "teal").save(path, "JPEG", exif=exif)
    return path


def tags_of(**tags) -> dict:
    buf = io.BytesIO()
    exif_photo(buf, **tags)
    buf.seek(0)
    return exifread.process_file(buf, details=False)


class TestReading:
    def test_full_details(self, tmp_path):
        info = read_photo_info(exif_photo(tmp_path / "a.jpg", **XT4))
        assert info.details == XT4_DETAILS

    def test_no_exif(self, tmp_path):
        path = tmp_path / "plain.jpg"
        Image.new("RGB", (10, 10)).save(path)
        assert read_photo_info(path).details == {}

    def test_missing_fields_are_left_out(self):
        assert shooting_details(tags_of(model="iPhone 15 Pro", iso=50)) == {
            "camera": "iPhone 15 Pro",
            "iso": "50",
        }

    def test_zero_and_undefined_values_are_skipped(self):
        details = shooting_details(
            tags_of(fnumber=IFDRational(0, 1), exposure=IFDRational(0, 0), lens="----")
        )
        assert details == {}

    @pytest.mark.parametrize(
        "make,model,expected",
        [
            ("FUJIFILM", "X-T4", "Fujifilm X-T4"),
            ("Canon", "Canon EOS R5", "Canon EOS R5"),
            ("NIKON CORPORATION", "NIKON Z 6", "NIKON Z 6"),
            ("NIKON CORPORATION", "Z 6", "Nikon Z 6"),
            ("OLYMPUS IMAGING CORP.", "E-M5", "Olympus E-M5"),
            ("RICOH IMAGING COMPANY, LTD.", "GR III", "Ricoh GR III"),
            ("Apple", "iPhone 15 Pro", "Apple iPhone 15 Pro"),
            ("LGE", "Nexus 5", "LGE Nexus 5"),
            ("", "X100V", "X100V"),
            ("SONY", "", "Sony"),
        ],
    )
    def test_camera_name(self, make, model, expected):
        assert camera_name(make, model) == expected

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (Fraction(1, 250), "1/250s"),
            (Fraction(1, 3), "1/3s"),
            (Fraction(3, 10), "1/3s"),
            (Fraction(1), "1s"),
            (Fraction(5, 2), "2.5s"),
            (Fraction(30), "30s"),
        ],
    )
    def test_shutter_speed(self, seconds, expected):
        assert format_shutter_speed(seconds) == expected

    def test_fractional_aperture_and_focal_length(self):
        details = shooting_details(
            tags_of(fnumber=IFDRational(28, 10), focal=IFDRational(425, 100))
        )
        assert details == {"aperture": "f/2.8", "focal_length": "4.2mm"}


class TestMerging:
    def test_caption_overrides_and_hides(self):
        merged = photo_details(XT4_DETAILS, {"lens": "Helios 44-2", "iso": "-", "title": "x"})
        assert merged["lens"] == "Helios 44-2"
        assert "iso" not in merged
        assert list(merged) == ["camera", "lens", "focal_length", "aperture", "shutter_speed"]

    def test_caption_supplies_details_without_exif(self):
        assert photo_details({}, {"camera": "Zenit E", "aperture": "f/2"}) == {
            "camera": "Zenit E",
            "aperture": "f/2",
        }

    def test_summary(self):
        assert exposure_summary(XT4_DETAILS) == "23mm · f/2 · 1/250s · ISO 160"
        assert exposure_summary({"iso": "Auto"}) == "Auto"
        assert exposure_summary({}) == ""

    @pytest.mark.parametrize(
        "setting,value,expected",
        [
            ("icon", "", "icon"),
            ("icon", "false", "off"),
            ("icon", "No", "off"),
            ("icon", "caption", "caption"),
            ("caption", "true", "caption"),
            ("off", "true", "icon"),
            ("off", "caption", "caption"),
        ],
    )
    def test_mode(self, setting, value, expected):
        metadata = {"exif": value} if value else {}
        assert exif_mode(setting, metadata, Path("a.jpg")) == expected

    def test_unknown_mode_warns(self, capsys):
        assert exif_mode("icon", {"exif": "maybe"}, Path("a.jpg")) == "icon"
        assert "Ignoring 'exif: maybe' for a.jpg" in capsys.readouterr().out


class TestConfig:
    def test_defaults(self):
        assert DEFAULT_CONFIG["exif_display"] == "icon"
        assert EXPOSE_DEFAULTS["exif_display"] == "off"

    def test_invalid_value(self):
        with pytest.raises(ConfigError, match="exif_display must be one of off, icon, caption"):
            Config({**DEFAULT_CONFIG, "exif_display": "yes"}).validate()


def build(topdir, mode="icon", theme="photoessay", captions=None, gallery_metadata=None):
    """A one-gallery site with an X-T4 photo (``a``) and one without EXIF (``b``)."""
    g = topdir / "g"
    g.mkdir(parents=True)
    exif_photo(g / "01 a.jpg", **XT4)
    Image.new("RGB", (1200, 800), "navy").save(g / "02 b.jpg")
    for stem, text in (captions or {}).items():
        (g / f"{stem}.txt").write_text(text, encoding="utf-8")
    if gallery_metadata:
        (g / "metadata.txt").write_text(gallery_metadata, encoding="utf-8")
    gen = make_generator(topdir, config_overrides={"theme_dir": theme, "exif_display": mode})
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.cleanup()
    return (topdir / "_site" / "g" / "index.html").read_text(encoding="utf-8")


PANEL = (
    "<span>Fujifilm X-T4</span><span>XF23mmF2 R WR</span><span>23mm · f/2 · 1/250s · ISO 160</span>"
)
LINE = '<p class="photo-info-line">Fujifilm X-T4 · 23mm · f/2 · 1/250s · ISO 160</p>'


class TestPages:
    @pytest.mark.parametrize("theme", ["photoessay", "medium", "contactsheet"])
    def test_icon(self, tmp_path, theme):
        html = build(tmp_path, theme=theme)
        assert html.count('<div class="photo-info">') == 1  # not for the photo without EXIF
        assert PANEL in html
        assert 'aria-label="Photo details"' in html
        assert "photo-info-line" not in html
        assert '<script src="../photo-info.js"></script>' in html

    @pytest.mark.parametrize("theme", ["photoessay", "medium", "contactsheet"])
    def test_caption(self, tmp_path, theme):
        html = build(tmp_path, mode="caption", theme=theme)
        assert html.count(LINE) == 1
        assert 'class="photo-info"' not in html

    def test_icon_takes_the_photos_colours(self, tmp_path):
        html = build(tmp_path)
        button = html.split('class="photo-info-button"')[1].split(">")[0]
        # A solid test photo's palette has one colour, so no background (the stylesheet's applies)
        assert 'style="color: #ffffff; background-color: "' in button
        assert "{{" not in html

    @pytest.mark.parametrize("mode", ["icon", "caption"])
    def test_contactsheet_keeps_the_details_for_its_lightbox(self, tmp_path, mode):
        """The grid doesn't show them: they're in a hidden holder the lightbox copies from."""
        html = build(tmp_path, mode=mode, theme="contactsheet")
        tile = html.split('<figure class="tile')[1]
        holder = tile.split('<div class="lightbox-only" hidden>')[1].split("<figcaption")[0]
        assert ("photo-info-button" if mode == "icon" else LINE) in holder
        assert "Fujifilm" not in tile.split("<figcaption")[1]

    @pytest.mark.parametrize("theme", ["photoessay", "medium", "contactsheet"])
    def test_off(self, tmp_path, theme):
        html = build(tmp_path, mode="off", theme=theme)
        assert 'photo-info"' not in html and "photo-info-line" not in html
        assert "Fujifilm" not in html

    @pytest.mark.parametrize("theme", ["theme1", "theme2"])
    def test_expose_themes_are_unchanged(self, tmp_path, theme):
        """theme1/theme2 have no placeholders, so their pages are the same either way (#5)."""
        on = build(tmp_path / "on", theme=theme)
        off = build(tmp_path / "off", mode="off", theme=theme)
        assert on == off
        assert "Fujifilm" not in on

    def test_caption_overrides(self, tmp_path):
        html = build(
            tmp_path,
            captions={
                "01 a": "lens: Helios <44-2>\niso: -\n---\nHello",
                "02 b": "camera: Zenit E\n---\n",
            },
        )
        assert "<span>Helios &lt;44-2&gt;</span>" in html
        assert "ISO" not in html
        assert "<span>Zenit E</span>" in html  # a photo without EXIF, described by its caption

    def test_post_opt_out(self, tmp_path):
        html = build(tmp_path, captions={"01 a": "exif: false\n---\nHello"})
        assert 'class="photo-info"' not in html

    def test_gallery_style(self, tmp_path):
        html = build(tmp_path, gallery_metadata="exif: caption\n")
        assert LINE in html
        assert 'class="photo-info"' not in html

    def test_details_are_cached(self, tmp_path):
        build(tmp_path)
        cache = json.loads((tmp_path / CACHE_NAME).read_text(encoding="utf-8"))
        assert cache["details"]["g/01 a.jpg"]["details"] == XT4_DETAILS
        assert cache["details"]["g/02 b.jpg"]["details"] == {}
