"""Color extraction facade.

Prefers ImageMagick (byte-identical output for parity tests).
Falls back to Pillow when ImageMagick is not available.
"""

from pathlib import Path

from dorothea.media import imagemagick
from dorothea.media.colors_imagemagick import ImageMagickColorExtractor
from dorothea.media.colors_pillow import PillowColorExtractor


def _make_extractor() -> ImageMagickColorExtractor | PillowColorExtractor:
    if imagemagick.imagemagick_command():
        return ImageMagickColorExtractor()
    return PillowColorExtractor()


class ColorExtractor:
    """Color palette extractor.

    Uses ImageMagick if available (maintains parity with expose.sh).
    Falls back to Pillow otherwise.
    """

    def __init__(self):
        self._backend = _make_extractor()

    @property
    def backend(self) -> ImageMagickColorExtractor | PillowColorExtractor:
        """The active backend instance."""
        return self._backend

    def extract_palette(self, image_path: Path, num_colors: int = 7) -> list[str]:
        """Extract dominant color palette from image.

        Args:
            image_path: Image file path.
            num_colors: Number of colors to extract.

        Returns:
            List of hex color strings (e.g., ["#ff0000", ...]).
        """
        palette = self._backend.extract_palette(image_path, num_colors)
        if not palette and isinstance(self._backend, ImageMagickColorExtractor):
            # This ImageMagick may lack a decoder for the format (e.g. HEIC/AVIF); Pillow has one
            palette = PillowColorExtractor().extract_palette(image_path, num_colors)
        return palette
