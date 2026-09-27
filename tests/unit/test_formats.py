"""Image modes JPEG can't store, and newer photo formats (#2)."""

import subprocess
from unittest import mock

import pytest
from PIL import Image

from dorothea.media.colors import ColorExtractor
from dorothea.media.colors_imagemagick import ImageMagickColorExtractor
from dorothea.media.ffmpeg import ffmpeg_exe
from dorothea.media.image import jpeg_compatible
from dorothea.utils import IMAGE_EXTENSIONS
from tests.conftest import make_generator


def pixel(path):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel((10, 10))


def close(a, b, tolerance=4):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


class TestJpegCompatible:
    def test_rgb_is_unchanged(self):
        img = Image.new("RGB", (4, 4), "red")
        assert jpeg_compatible(img) is img

    def test_transparency_is_dropped_like_imagemagick(self):
        """Pixels keep the colour stored under them (ImageMagick doesn't blend onto a background)."""
        img = Image.new("RGBA", (2, 1))
        img.putdata([(0, 0, 255, 128), (255, 0, 0, 0)])
        out = jpeg_compatible(img)
        assert out.mode == "RGB"
        assert [out.getpixel((0, 0)), out.getpixel((1, 0))] == [(0, 0, 255), (255, 0, 0)]

    def test_palette_becomes_rgb(self):
        img = Image.new("RGB", (4, 4), (10, 200, 30)).convert("P", palette=Image.Palette.ADAPTIVE)
        out = jpeg_compatible(img)
        assert out.mode == "RGB" and close(out.getpixel((0, 0)), (10, 200, 30))

    @pytest.mark.parametrize("mode,expected", [("LA", "L"), ("1", "L"), ("CMYK", "CMYK")])
    def test_other_modes(self, mode, expected):
        assert jpeg_compatible(Image.new(mode, (4, 4))).mode == expected

    def test_sixteen_bit_is_scaled(self):
        out = jpeg_compatible(Image.new("I;16", (4, 4), 40000))
        assert out.mode == "L" and out.getpixel((0, 0)) == 40000 // 256


def gallery(tmp_path):
    """One photo per format/mode that used to fail or wasn't read at all."""
    g = tmp_path / "g"
    g.mkdir()
    Image.new("RGB", (800, 600), (255, 0, 0)).convert("P").save(g / "01 static.gif")
    frames = [Image.new("RGB", (800, 600), (0, 80, 160 + 20 * i)) for i in range(3)]
    frames[0].save(g / "02 animated.gif", save_all=True, append_images=frames[1:])
    Image.new("RGBA", (800, 600), (0, 0, 255, 128)).save(g / "03 transparent.png")
    # Adaptive palette: the default web palette would dither this colour
    Image.new("RGB", (800, 600), (0, 200, 0)).convert("P", palette=Image.Palette.ADAPTIVE).save(
        g / "04 palette.png"
    )
    Image.new("LA", (800, 600), (128, 200)).save(g / "05 grey alpha.png")
    Image.new("I;16", (800, 600), 40000).save(g / "06 sixteen bit.png")
    Image.new("RGB", (800, 600), (0, 128, 0)).save(g / "07 phone.webp")
    Image.new("RGB", (800, 600), (255, 255, 0)).save(g / "08 modern.avif")
    Image.new("RGB", (800, 600), (128, 0, 128)).save(g / "09 iphone.heic")
    Image.new("RGB", (800, 600), (255, 165, 0)).save(g / "10 scan.tiff")
    return g


EXPECTED = {
    "static": (255, 0, 0),
    "animated": (0, 80, 160),  # first frame
    "transparent": (0, 0, 255),
    "palette": (0, 200, 0),
    "grey-alpha": (128, 128, 128),
    "sixteen-bit": (156, 156, 156),
    "phone": (0, 128, 0),
    "modern": (255, 255, 0),
    "iphone": (128, 0, 128),
    "scan": (255, 165, 0),
}


class TestBuild:
    @pytest.mark.parametrize("legacy", [False, True])
    def test_every_format_and_mode_is_published(self, tmp_path, capsys, legacy):
        gallery(tmp_path)
        overrides = {"legacy": True, "theme_dir": "theme1"} if legacy else None
        make_generator(tmp_path, config_overrides=overrides).run()
        assert "Error encoding" not in capsys.readouterr().out
        for name, colour in EXPECTED.items():
            out = tmp_path / "_site" / "g" / name / "1024.jpg"
            assert out.exists(), name
            assert close(pixel(out), colour, tolerance=6), (name, pixel(out))

    def test_image_extensions(self):
        assert {"webp", "avif", "heic", "heif", "tif", "tiff"} <= set(IMAGE_EXTENSIONS)


class TestHeic:
    def test_orientation_is_already_applied_when_opened(self, tmp_path):
        """pillow-heif applies HEIC's own rotation and reports EXIF orientation 1, so our
        autorotate step can't rotate a second time."""
        exif = Image.Exif()
        exif[0x0112] = 6
        path = tmp_path / "sideways.heic"
        Image.new("RGB", (800, 600), "purple").save(path, exif=exif)
        with Image.open(path) as img:
            assert img.getexif().get(0x0112, 1) == 1


class TestSequences:
    def test_heic_and_webp_frames_are_converted(self, tmp_path):
        seq = tmp_path / "walk-imagesequence"
        seq.mkdir()
        Image.new("RGB", (320, 240), "red").save(seq / "01.heic")
        Image.new("RGB", (320, 240), "blue").save(seq / "02.webp")
        Image.new("RGB", (320, 240), "green").save(seq / "03.heic")
        gen = make_generator(tmp_path, config_overrides={"sequence_framerate": 25})
        gen.config["h264_encodespeed"] = "ultrafast"
        video = gen._compile_sequence(seq)
        result = subprocess.run(
            [ffmpeg_exe(), "-nostdin", "-i", str(video), "-map", "0:v:0", "-f", "null", "-"],
            capture_output=True,
            text=True,
        )
        frames = [line for line in result.stderr.splitlines() if "frame=" in line]
        assert int(frames[-1].split("frame=")[1].split()[0]) == 3
        gen.cleanup()


class TestPalette:
    def test_falls_back_to_pillow_when_imagemagick_cannot_read(self, tmp_path):
        path = tmp_path / "iphone.heic"
        Image.new("RGB", (100, 100), (128, 0, 128)).save(path)
        extractor = ColorExtractor()
        extractor._backend = ImageMagickColorExtractor()
        with mock.patch.object(ImageMagickColorExtractor, "extract_palette", return_value=[]):
            palette = extractor.extract_palette(path)
        assert palette and palette[0].lower().startswith("#8")
