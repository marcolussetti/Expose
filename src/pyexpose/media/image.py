"""Image processing using Pillow.

Provides abstraction layer for image operations (resize, identify dimensions).
"""

from pathlib import Path

from PIL import Image, ImageOps

from pyexpose.media.base import MediaProcessor


class ImageProcessor(MediaProcessor):
    """Pillow-based image processor."""

    def process(self, input_path: Path, output_path: Path, **kwargs) -> None:
        """Process an image (generic interface).

        Args:
            input_path: Input image path.
            output_path: Output image path.
            **kwargs: Additional processing parameters.
        """
        raise NotImplementedError("Use specific methods like resize(), identify(), etc.")

    def identify(self, image_path: Path, format_str: str) -> str:
        """Return image metadata matching ImageMagick identify format strings.

        Supported format strings: %w (width), %h (height),
        %[EXIF:Orientation] (EXIF orientation tag).

        Args:
            image_path: Image file path.
            format_str: Format string.

        Returns:
            String value, or "" on error.
        """
        try:
            with Image.open(image_path) as img:
                if format_str == "%w":
                    return str(img.width)
                elif format_str == "%h":
                    return str(img.height)
                elif format_str == "%[EXIF:Orientation]":
                    exif = img.getexif()
                    val = exif.get(0x0112)  # Tag 274 = Orientation
                    return str(val) if val is not None else ""
        except Exception:
            pass
        return ""

    def convert(self, args: list) -> None:
        """No-op stub kept for interface compatibility.

        Args:
            args: Ignored.
        """
        raise NotImplementedError("convert() is not supported with the Pillow backend")

    def resize(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        quality: int = 92,
        auto_orient: bool = True,
        additional_args: list = None,
    ) -> None:
        """Resize an image to fit within a width×width box.

        Matches ImageMagick: -auto-orient -resize WxW -quality Q +profile *

        Args:
            input_path: Input image path.
            output_path: Output image path.
            width: Maximum width/height (aspect ratio preserved).
            quality: JPEG quality (0-100).
            auto_orient: Apply EXIF orientation before resizing.
            additional_args: Unused; kept for interface compatibility.
        """
        with Image.open(input_path) as img:
            if auto_orient:
                img = ImageOps.exif_transpose(img)
            # Match ImageMagick -resize WxW: scale to fit within the box,
            # upscaling if necessary (thumbnail() only shrinks).
            orig_w, orig_h = img.size
            ratio = min(width / orig_w, width / orig_h)
            new_size = (round(orig_w * ratio), round(orig_h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            # Match ImageMagick chroma subsampling: 4:4:4 at quality>=90,
            # 4:2:2 at quality>=80, 4:2:0 below that.
            if quality >= 90:
                subsampling = 0  # 4:4:4
            elif quality >= 80:
                subsampling = 1  # 4:2:2
            else:
                subsampling = 2  # 4:2:0
            # Save without any metadata (+profile * equivalent)
            img.save(output_path, "JPEG", quality=quality, subsampling=subsampling, optimize=True)

    def extract_dimensions(self, image_path: Path, handle_orientation: bool = False) -> tuple:
        """Extract image dimensions, optionally handling EXIF orientation.

        Args:
            image_path: Image file path.
            handle_orientation: If True, swap dimensions for rotated images.

        Returns:
            Tuple of (width, height).
        """
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                if handle_orientation:
                    exif = img.getexif()
                    orientation = exif.get(0x0112)
                    if orientation and 5 <= orientation <= 8:
                        width, height = height, width
                return width, height
        except Exception:
            return 0, 0
