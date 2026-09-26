"""Image processing using Pillow.

Provides abstraction layer for image operations (resize, identify dimensions).
"""

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps, JpegImagePlugin

from pyexpose.media.base import MediaProcessor


class ImageProcessor(MediaProcessor):
    """Pillow-based image processor.

    Per-image ``image-options`` metadata holds raw ImageMagick arguments, which Pillow can't
    interpret; those images are resized with ImageMagick ``convert`` when it's installed.
    """

    _warned_no_convert = False

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

    def resize(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        quality: int = 92,
        auto_orient: bool = True,
        additional_args: list | None = None,
    ) -> None:
        """Resize an image to fit within a width×width box.

        Matches ImageMagick: -auto-orient -resize WxW -quality Q +profile *

        Args:
            input_path: Input image path.
            output_path: Output image path.
            width: Maximum width/height (aspect ratio preserved).
            quality: JPEG quality (0-100).
            auto_orient: Apply EXIF orientation before resizing.
            additional_args: Extra ImageMagick arguments (from ``image-options``). When given,
                ImageMagick is used if available; otherwise they are ignored with a warning.
        """
        if additional_args:
            if shutil.which("convert"):
                self._resize_imagemagick(
                    input_path, output_path, width, quality, auto_orient, additional_args
                )
                return
            if not ImageProcessor._warned_no_convert:
                ImageProcessor._warned_no_convert = True
                print("image-options ignored: ImageMagick 'convert' is not installed")

        with Image.open(input_path) as img:
            subsampling = self.chroma_subsampling(img, quality)
            if auto_orient:
                img = ImageOps.exif_transpose(img)
            # Match ImageMagick -resize WxW: scale to fit within the box,
            # upscaling if necessary (thumbnail() only shrinks).
            orig_w, orig_h = img.size
            ratio = min(width / orig_w, width / orig_h)
            new_size = (round(orig_w * ratio), round(orig_h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            # Save without any metadata (+profile * equivalent)
            try:
                img.save(
                    output_path, "JPEG", quality=quality, subsampling=subsampling, optimize=True
                )
            except OSError:
                # optimize=True needs the whole JPEG to fit a buffer Pillow sizes at ~1 byte per
                # pixel; very grainy images at 4:4:4 can exceed it. Fall back to standard
                # Huffman tables (~1-2% larger).
                img.save(output_path, "JPEG", quality=quality, subsampling=subsampling)

    @staticmethod
    def chroma_subsampling(img: Image.Image, quality: int) -> int:
        """Pick the JPEG chroma subsampling ImageMagick 7 would use (Pillow's 0/1/2 codes).

        JPEG sources keep their own subsampling (camera files are usually 4:2:0). Other
        sources get 4:4:4 at quality >= 90 and 4:2:0 below. Using 4:4:4 for 4:2:0 camera
        JPEGs makes files ~25% larger with no visible gain.
        """
        if img.format == "JPEG":
            source = JpegImagePlugin.get_sampling(img)
            if source in (0, 1, 2):
                return source
        return 0 if quality >= 90 else 2

    @staticmethod
    def _resize_imagemagick(input_path, output_path, width, quality, auto_orient, extra_args):
        """Resize with ImageMagick exactly as expose.sh does (including image-options)."""
        cmd = ["convert"]
        if auto_orient:
            cmd.append("-auto-orient")
        cmd += ["-size", f"{width}x{width}", str(input_path), "-resize", f"{width}x{width}"]
        cmd += ["-quality", str(quality), "+profile", "*", *extra_args, str(output_path)]
        subprocess.run(cmd, check=True, capture_output=True)

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
