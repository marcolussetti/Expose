"""Color extraction from images.

Extracts dominant color palettes from images for use in themes.
"""

import re
import subprocess
from pathlib import Path


class ColorExtractor:
    """Color palette extractor.

    Currently uses ImageMagick for color extraction. Can be replaced with
    Pillow + color quantization libraries later.
    """

    def extract_palette(self, image_path: Path, num_colors: int = 7) -> list[str]:
        """Extract dominant color palette from image.

        Args:
            image_path: Image file path.
            num_colors: Number of colors to extract.

        Returns:
            List of hex color strings (e.g., ["#ff0000", "#00ff00", ...]).
        """
        result = subprocess.run(
            [
                "convert",
                str(image_path),
                "-resize",
                "200x200",
                "-depth",
                "4",
                "+dither",
                "-colors",
                str(num_colors),
                "-unique-colors",
                "txt:-",
            ],
            capture_output=True,
            text=True,
        )

        # Parse colors from output
        palette = []
        for line in result.stdout.split("\n")[1:]:  # Skip header
            match = re.search(r"#[0-9A-Fa-f]+", line)
            if match:
                palette.append(match.group())

        return palette
