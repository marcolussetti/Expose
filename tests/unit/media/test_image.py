"""Unit tests for dorothea.media.image module.

Tests the ImageProcessor class that uses Pillow.
"""

import shutil
import subprocess

import pytest
from PIL import Image, JpegImagePlugin

from dorothea.media.image import ImageProcessor


@pytest.fixture
def image_processor():
    """Create an ImageProcessor instance."""
    return ImageProcessor()


@pytest.fixture
def test_image(tmp_path):
    """Create a 640x480 blue test image using Pillow."""
    image_path = tmp_path / "test.jpg"
    img = Image.new("RGB", (640, 480), color=(0, 0, 255))
    img.save(image_path, "JPEG")
    return image_path


class TestImageProcessor:
    """Test ImageProcessor methods."""

    def test_identify_width(self, image_processor, test_image):
        """Test identifying image width."""
        assert image_processor.identify(test_image, "%w") == "640"

    def test_identify_height(self, image_processor, test_image):
        """Test identifying image height."""
        assert image_processor.identify(test_image, "%h") == "480"

    def test_extract_dimensions(self, image_processor, test_image):
        """Test extracting image dimensions."""
        width, height = image_processor.extract_dimensions(test_image)
        assert width == 640
        assert height == 480

    def test_resize_image(self, image_processor, test_image, tmp_path):
        """Test resizing an image."""
        output_path = tmp_path / "resized.jpg"
        image_processor.resize(test_image, output_path, width=320, quality=90, auto_orient=False)

        assert output_path.exists()
        width, height = image_processor.extract_dimensions(output_path)
        assert width == 320
        assert height == 240  # Aspect ratio maintained


class TestImageProcessorEdgeCases:
    """Test edge cases and error handling."""

    def test_identify_nonexistent_file(self, image_processor, tmp_path):
        """Test identify on nonexistent file."""
        result = image_processor.identify(tmp_path / "nonexistent.jpg", "%w")
        assert result == ""

    def test_extract_dimensions_invalid_file(self, image_processor, tmp_path):
        """Test extract_dimensions on invalid file."""
        width, height = image_processor.extract_dimensions(tmp_path / "invalid.jpg")
        assert width == 0
        assert height == 0


def _noisy_source(path, **save_kwargs):
    """A detailed 800x600 image so subsampling actually affects the output."""
    # Independent noise per channel: grey noise would be saved as a 1-channel JPEG by ImageMagick
    bands = [Image.effect_noise((800, 600), 80 + 10 * i) for i in range(3)]
    Image.merge("RGB", bands).save(path, **save_kwargs)


def _sampling(path):
    with Image.open(path) as img:
        return JpegImagePlugin.get_sampling(img)


class TestChromaSubsampling:
    """Resized JPEGs use the chroma subsampling ImageMagick 7 would pick."""

    @pytest.mark.parametrize("source_sub", [0, 2])
    def test_jpeg_source_keeps_its_subsampling(self, image_processor, tmp_path, source_sub):
        src = tmp_path / "src.jpg"
        _noisy_source(src, quality=95, subsampling=source_sub)
        out = tmp_path / "out.jpg"
        image_processor.resize(src, out, width=400, quality=92)
        assert _sampling(out) == source_sub

    @pytest.mark.parametrize("quality,expected", [(92, 0), (90, 0), (89, 2), (60, 2)])
    def test_non_jpeg_source_depends_on_quality(self, image_processor, tmp_path, quality, expected):
        src = tmp_path / "src.png"
        _noisy_source(src)
        out = tmp_path / "out.jpg"
        image_processor.resize(src, out, width=400, quality=quality)
        assert _sampling(out) == expected

    def test_camera_style_jpeg_not_inflated(self, image_processor, tmp_path):
        """A 4:2:0 source must not be re-encoded as 4:4:4 (the old ~25% size penalty)."""
        src = tmp_path / "src.jpg"
        _noisy_source(src, quality=95, subsampling=2)
        out = tmp_path / "out.jpg"
        forced_444 = tmp_path / "444.jpg"
        image_processor.resize(src, out, width=400, quality=92)
        with Image.open(out) as img:
            img.save(forced_444, "JPEG", quality=92, subsampling=0, optimize=True)
        assert out.stat().st_size < forced_444.stat().st_size

    @pytest.mark.skipif(shutil.which("convert") is None, reason="ImageMagick not installed")
    @pytest.mark.parametrize(
        "name,save_kwargs,quality",
        [
            ("src.jpg", {"quality": 95, "subsampling": 2}, 92),
            ("src.jpg", {"quality": 95, "subsampling": 0}, 92),
            ("src.png", {}, 92),
            ("src.png", {}, 80),
        ],
    )
    def test_matches_imagemagick(self, image_processor, tmp_path, name, save_kwargs, quality):
        src = tmp_path / name
        _noisy_source(src, **save_kwargs)
        ours, theirs = tmp_path / "ours.jpg", tmp_path / "im.jpg"
        image_processor.resize(src, ours, width=400, quality=quality)
        subprocess.run(
            ["convert", str(src), "-resize", "400x400", "-quality", str(quality), str(theirs)],
            check=True,
            capture_output=True,
        )
        assert _sampling(ours) == _sampling(theirs)


def test_resize_survives_optimize_buffer_overflow(image_processor, tmp_path):
    """Grainy 4:4:4 output can overflow Pillow's optimize buffer; resize must still succeed."""
    src = tmp_path / "grain.png"
    _noisy_source(src)
    out = tmp_path / "out.jpg"
    image_processor.resize(src, out, width=800, quality=92)
    assert _sampling(out) == 0
    with Image.open(out) as img:
        assert img.size == (800, 600)
