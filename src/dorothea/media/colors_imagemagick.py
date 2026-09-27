"""Color extraction using ImageMagick."""

import re
import subprocess
from pathlib import Path

from dorothea.media import imagemagick


class ImageMagickColorExtractor:
    """Extract dominant color palette using ImageMagick's convert command."""

    def extract_palette(self, image_path: Path, num_colors: int = 7) -> list[str]:
        """Extract dominant color palette from image.

        Args:
            image_path: Image file path.
            num_colors: Number of colors to extract.

        Returns:
            List of hex color strings (e.g., ["#ff0000", ...]).
        """
        command = imagemagick.imagemagick_command()
        if command is None:
            return []  # the facade falls back to Pillow
        result = subprocess.run(
            [
                *command,
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
            encoding="utf-8",
            errors="replace",
        )

        palette = []
        for line in result.stdout.split("\n")[1:]:  # Skip header
            match = re.search(r"#[0-9A-Fa-f]+", line)
            if match:
                palette.append(match.group())

        return palette
