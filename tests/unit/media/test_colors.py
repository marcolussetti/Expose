"""Unit tests for color extraction backends and facade.

Tests ImageMagickColorExtractor, PillowColorExtractor, and the ColorExtractor
facade (fallback logic).
"""

import math
import shutil
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image
from pyexpose.media.colors import ColorExtractor
from pyexpose.media.colors_imagemagick import ImageMagickColorExtractor
from pyexpose.media.colors_pillow import PillowColorExtractor

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def blue_image(tmp_path) -> Path:
    """Solid blue 100x100 JPEG created with Pillow (no ImageMagick needed)."""
    path = tmp_path / "blue.jpg"
    Image.new("RGB", (100, 100), color=(0, 0, 255)).save(path, "JPEG")
    return path


@pytest.fixture
def gradient_image(tmp_path) -> Path:
    """Red-to-blue gradient 100x100 JPEG created with Pillow."""
    path = tmp_path / "gradient.jpg"
    img = Image.new("RGB", (100, 100))
    for x in range(100):
        r = int(255 * (1 - x / 99))
        b = int(255 * (x / 99))
        for y in range(100):
            img.putpixel((x, y), (r, 0, b))
    img.save(path, "JPEG")
    return path


# ---------------------------------------------------------------------------
# Shared contract helper
# ---------------------------------------------------------------------------


def _assert_valid_palette(palette, max_colors):
    """Check that a palette is a list of valid hex strings."""
    assert isinstance(palette, list)
    assert len(palette) <= max_colors
    for color in palette:
        assert color.startswith("#"), f"Not a hex color: {color}"
        hex_part = color[1:]
        assert len(hex_part) in (6, 12), f"Unexpected hex length: {color}"
        assert all(c in "0123456789ABCDEFabcdef" for c in hex_part)


# ---------------------------------------------------------------------------
# Pillow backend — always runs (no external deps)
# ---------------------------------------------------------------------------


class TestPillowColorExtractor:
    @pytest.fixture
    def extractor(self):
        return PillowColorExtractor()

    def test_returns_hex_colors(self, extractor, blue_image):
        _assert_valid_palette(extractor.extract_palette(blue_image), 7)

    def test_custom_num_colors(self, extractor, blue_image):
        assert len(extractor.extract_palette(blue_image, num_colors=3)) <= 3

    def test_gradient_multiple_colors(self, extractor, gradient_image):
        assert len(extractor.extract_palette(gradient_image, num_colors=5)) >= 2

    def test_nonexistent_file_returns_empty(self, extractor, tmp_path):
        assert extractor.extract_palette(tmp_path / "nonexistent.jpg") == []


# ---------------------------------------------------------------------------
# ImageMagick backend — skipped if convert not available
# ---------------------------------------------------------------------------


class TestImageMagickColorExtractor:
    @pytest.fixture
    def extractor(self):
        if not shutil.which("convert"):
            pytest.skip("ImageMagick not available")
        return ImageMagickColorExtractor()

    def test_returns_hex_colors(self, extractor, blue_image):
        _assert_valid_palette(extractor.extract_palette(blue_image), 7)

    def test_custom_num_colors(self, extractor, blue_image):
        assert len(extractor.extract_palette(blue_image, num_colors=3)) <= 3

    def test_gradient_multiple_colors(self, extractor, gradient_image):
        assert len(extractor.extract_palette(gradient_image, num_colors=5)) >= 2


# ---------------------------------------------------------------------------
# Facade — fallback logic
# ---------------------------------------------------------------------------


class TestColorExtractorFacade:
    def test_uses_imagemagick_when_available(self):
        with mock.patch("pyexpose.media.colors.shutil.which", return_value="/usr/bin/convert"):
            extractor = ColorExtractor()
        assert isinstance(extractor.backend, ImageMagickColorExtractor)

    def test_falls_back_to_pillow_when_imagemagick_missing(self):
        with mock.patch("pyexpose.media.colors.shutil.which", return_value=None):
            extractor = ColorExtractor()
        assert isinstance(extractor.backend, PillowColorExtractor)

    def test_extract_palette_delegates_to_backend(self, blue_image):
        with mock.patch("pyexpose.media.colors.shutil.which", return_value=None):
            extractor = ColorExtractor()
        _assert_valid_palette(extractor.extract_palette(blue_image), 7)


# ---------------------------------------------------------------------------
# Pillow vs ImageMagick parity — skipped if ImageMagick not available
# ---------------------------------------------------------------------------

# Real source images from the test gallery
_TEST_IMAGES = [
    Path(__file__).resolve().parents[3] / "test_run/01_Nature/02_Oceans/01_wave.jpg",
    Path(__file__).resolve().parents[3] / "test_run/01_Nature/01_Mountains/01_peak.jpg",
    Path(__file__).resolve().parents[3] / "test_run/02_Urban/01_city.jpg",
]


def _color_distance(hex_a: str, hex_b: str) -> float:
    """Euclidean distance in RGB space between two hex colors."""
    a = tuple(int(hex_a[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(hex_b[i : i + 2], 16) for i in (1, 3, 5))
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _nearest_distance(color: str, palette: list[str]) -> float:
    """Distance from color to its nearest match in palette."""
    return min(_color_distance(color, c) for c in palette)


@pytest.mark.slow
class TestPillowVsImageMagickParity:
    """Compare Pillow and ImageMagick palettes on real gallery images.

    Marked slow — skipped in fast test runs. Skipped entirely if ImageMagick
    is not available. Does not assert exact match; records mean nearest-color
    distance so we can track divergence over time.
    """

    @pytest.fixture(autouse=True)
    def require_imagemagick(self):
        if not shutil.which("convert"):
            pytest.skip("ImageMagick not available")

    @pytest.mark.parametrize("image_path", _TEST_IMAGES, ids=lambda p: p.stem)
    def test_palette_similarity(self, image_path):
        """Pillow palette should be reasonably close to ImageMagick palette."""
        if not image_path.exists():
            pytest.skip(f"Test image not found: {image_path}")

        im_palette = ImageMagickColorExtractor().extract_palette(image_path, num_colors=7)
        pil_palette = PillowColorExtractor().extract_palette(image_path, num_colors=7)

        assert len(im_palette) > 0, "ImageMagick returned empty palette"
        assert len(pil_palette) > 0, "Pillow returned empty palette"

        # For each ImageMagick color, find its nearest Pillow color.
        # Mean distance gives a single comparable number (max RGB distance = 441).
        distances = [_nearest_distance(c, pil_palette) for c in im_palette]
        mean_dist = sum(distances) / len(distances)

        # Informational output — visible with pytest -s
        print(f"\n  {image_path.name}")
        print(f"  ImageMagick: {im_palette}")
        print(f"  Pillow:      {pil_palette}")
        print(f"  Mean nearest-color distance: {mean_dist:.1f} (max possible: 441)")

        # Palettes should not be wildly different — threshold is generous
        # (one 4-bit step = 16 units per channel ≈ 27.7 Euclidean distance)
        assert mean_dist < 100, (
            f"Pillow palette diverges too much from ImageMagick for {image_path.name} "
            f"(mean distance {mean_dist:.1f})"
        )
