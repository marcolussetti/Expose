"""Color extraction using Pillow.

Replicates the ImageMagick pipeline:
  convert img -resize 200x200 -depth 4 +dither -colors N -unique-colors txt:-

Steps:
  1. Resize to ≤200x200
  2. Reduce to 4-bit per channel (16 levels) — normalises minor resize differences
  3. Quantize to N colors via median-cut, no dithering
  4. Return palette as hex strings
"""

from pathlib import Path

from PIL import Image


class PillowColorExtractor:
    """Extract dominant color palette using Pillow."""

    def extract_palette(self, image_path: Path, num_colors: int = 7) -> list[str]:
        """Extract dominant color palette from image.

        Args:
            image_path: Image file path.
            num_colors: Number of colors to extract.

        Returns:
            List of hex color strings (e.g., ["#ff0000", ...]).
        """
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")

                # Step 1: resize to ≤200x200 (matches -resize 200x200)
                img.thumbnail((200, 200), Image.LANCZOS)

                # Step 2: 4-bit depth reduction — 16 levels per channel
                # Matches ImageMagick -depth 4 (rounds each channel to nearest
                # multiple of 16, then clamps to 0-255)
                img = img.point(lambda x: (x >> 4) << 4)

                # Step 3: median-cut quantize, no dither (matches +dither -colors N)
                quantized = img.quantize(colors=num_colors, dither=Image.Dither.NONE)

                # Step 4: extract palette entries
                # In Pillow 12+, getpalette() returns only the colors actually
                # present — may be fewer than num_colors for simple images.
                palette_data = quantized.getpalette()
                actual_count = len(palette_data) // 3
                colors = []
                for i in range(min(num_colors, actual_count)):
                    r, g, b = palette_data[i * 3 : i * 3 + 3]
                    colors.append(f"#{r:02x}{g:02x}{b:02x}")

                return colors
        except Exception:
            return []
