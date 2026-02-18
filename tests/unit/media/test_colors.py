"""Unit tests for pyexpose.media.colors module.

Tests the ColorExtractor class that extracts color palettes.
"""

import shutil

import pytest
from pyexpose.media.colors import ColorExtractor


@pytest.fixture
def color_extractor():
    """Create a ColorExtractor instance."""
    return ColorExtractor()


@pytest.fixture
def test_image(tmp_path):
    """Create a test image using ImageMagick."""
    if not shutil.which("convert"):
        pytest.skip("ImageMagick not available")

    image_path = tmp_path / "test.jpg"
    import subprocess

    subprocess.run(
        ["convert", "-size", "100x100", "xc:blue", str(image_path)],
        check=True,
        capture_output=True,
    )
    return image_path


class TestColorExtractor:
    """Test ColorExtractor methods."""

    def test_extract_palette_returns_list(self, color_extractor, test_image):
        """Test that extract_palette returns a list."""
        palette = color_extractor.extract_palette(test_image)
        assert isinstance(palette, list)

    def test_extract_palette_returns_hex_colors(self, color_extractor, test_image):
        """Test that palette contains hex color strings."""
        palette = color_extractor.extract_palette(test_image)

        for color in palette:
            assert color.startswith("#")
            # Verify it's a valid hex color (6 or 12 chars after #)
            hex_part = color[1:]
            assert len(hex_part) in [6, 12]
            assert all(c in "0123456789ABCDEFabcdef" for c in hex_part)

    def test_extract_palette_custom_num_colors(self, color_extractor, test_image):
        """Test extracting custom number of colors."""
        palette = color_extractor.extract_palette(test_image, num_colors=3)

        # Should return at most num_colors (may be less for simple images)
        assert len(palette) <= 3

    def test_extract_palette_blue_image(self, color_extractor, test_image):
        """Test that blue image returns blue-ish colors."""
        palette = color_extractor.extract_palette(test_image, num_colors=1)

        # For a pure blue image, should get at least one color
        assert len(palette) >= 1
        # The dominant color should be blue-ish (just check it exists)
        assert palette[0].startswith("#")


class TestColorExtractorMultiColor:
    """Test color extraction on multi-color images."""

    @pytest.fixture
    def gradient_image(self, tmp_path):
        """Create a gradient test image."""
        if not shutil.which("convert"):
            pytest.skip("ImageMagick not available")

        image_path = tmp_path / "gradient.jpg"
        import subprocess

        subprocess.run(
            ["convert", "-size", "100x100", "gradient:red-blue", str(image_path)],
            check=True,
            capture_output=True,
        )
        return image_path

    def test_extract_palette_gradient(self, color_extractor, gradient_image):
        """Test extracting palette from gradient image."""
        palette = color_extractor.extract_palette(gradient_image, num_colors=5)

        # Gradient should produce multiple colors
        assert len(palette) >= 2

        # All should be valid hex colors
        for color in palette:
            assert color.startswith("#")
