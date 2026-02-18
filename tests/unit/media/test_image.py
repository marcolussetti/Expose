"""Unit tests for pyexpose.media.image module.

Tests the ImageProcessor class that wraps ImageMagick.
"""

import shutil

import pytest
from pyexpose.media.image import ImageProcessor


@pytest.fixture
def image_processor():
    """Create an ImageProcessor instance."""
    return ImageProcessor()


@pytest.fixture
def test_image(tmp_path):
    """Create a test image using ImageMagick."""
    if not shutil.which("convert"):
        pytest.skip("ImageMagick not available")

    image_path = tmp_path / "test.jpg"
    import subprocess

    subprocess.run(
        ["convert", "-size", "640x480", "xc:blue", str(image_path)],
        check=True,
        capture_output=True,
    )
    return image_path


class TestImageProcessor:
    """Test ImageProcessor methods."""

    def test_identify_width(self, image_processor, test_image):
        """Test identifying image width."""
        width = image_processor.identify(test_image, "%w")
        assert width == "640"

    def test_identify_height(self, image_processor, test_image):
        """Test identifying image height."""
        height = image_processor.identify(test_image, "%h")
        assert height == "480"

    def test_extract_dimensions(self, image_processor, test_image):
        """Test extracting image dimensions."""
        width, height = image_processor.extract_dimensions(test_image)
        assert width == 640
        assert height == 480

    def test_resize_image(self, image_processor, test_image, tmp_path):
        """Test resizing an image."""
        output_path = tmp_path / "resized.jpg"
        image_processor.resize(
            test_image,
            output_path,
            width=320,
            quality=90,
            auto_orient=False,
        )

        assert output_path.exists()

        # Verify new dimensions
        width, height = image_processor.extract_dimensions(output_path)
        assert width == 320
        assert height == 240  # Aspect ratio maintained

    def test_convert_basic(self, image_processor, test_image, tmp_path):
        """Test basic convert operation."""
        output_path = tmp_path / "converted.jpg"
        result = image_processor.convert([str(test_image), str(output_path)])
        assert result.returncode == 0
        assert output_path.exists()


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
