"""Unit tests for pyexpose.media.image module.

Tests the ImageProcessor class that uses Pillow.
"""

import pytest
from PIL import Image
from pyexpose.media.image import ImageProcessor


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
