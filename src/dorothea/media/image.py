"""Image processing using Pillow.

Provides abstraction layer for image operations (resize, identify dimensions).
"""

import subprocess
from pathlib import Path

import pillow_heif
from PIL import Image, ImageCms, ImageOps, JpegImagePlugin

from dorothea.media import imagemagick
from dorothea.media.base import MediaProcessor
from dorothea.media.metadata import filtered_exif, is_srgb, srgb_profile_file, to_srgb

# HEIC/HEIF (iPhone photos) through Pillow's Image.open; WebP, AVIF and TIFF are built in (#2)
pillow_heif.register_heif_opener()

_SIXTEEN_BIT_MODES = {"I", "I;16", "I;16B", "I;16L", "I;16N"}


def jpeg_compatible(img: Image.Image) -> Image.Image:
    """Convert an image to a mode JPEG can store (RGB, L or CMYK).

    Like ImageMagick when it writes a JPEG, transparency is dropped rather than blended: pixels
    keep the colour stored under them. Palette images (GIF, 8-bit PNG) become RGB, greyscale with
    alpha becomes greyscale, and 16-bit greyscale is scaled down to 8 bits. Animated GIF/WebP
    images are already on their first frame when opened.
    """
    if img.mode in ("RGB", "L", "CMYK"):
        return img
    if img.mode in ("LA", "La", "1"):
        return img.convert("L")
    if img.mode in _SIXTEEN_BIT_MODES:
        return img.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    return img.convert("RGB")


class ImageProcessor(MediaProcessor):
    """Pillow-based image processor.

    Per-image ``image-options`` metadata holds raw ImageMagick arguments, which Pillow can't
    interpret; those images are resized with ImageMagick ``convert`` when it's installed.
    """

    _warned_no_convert = False

    def process(self, input_path: Path, output_path: Path, **kwargs: object) -> None:
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
        convert_to_srgb: bool = False,
        keep_metadata: str = "none",
    ) -> None:
        """Resize an image to fit within a width×width box.

        With the defaults this matches expose.sh's
        ``convert -auto-orient -resize WxW -quality Q +profile '*'``: no metadata or ICC profile.

        Args:
            input_path: Input image path.
            output_path: Output image path.
            width: Maximum width/height (aspect ratio preserved).
            quality: JPEG quality (0-100).
            auto_orient: Apply EXIF orientation before resizing.
            additional_args: Extra ImageMagick arguments (from ``image-options``). When given,
                ImageMagick is used if available; otherwise they are ignored with a warning.
            convert_to_srgb: Convert photos with a non-sRGB ICC profile (Display P3, Adobe RGB…)
                to sRGB, so they don't look dull once the profile is gone.
            keep_metadata: Which EXIF to keep, one of ``KEEP_METADATA_LEVELS``. With anything but
                ``none``, an unconverted non-sRGB ICC profile is kept too.
        """
        if additional_args:
            if imagemagick.imagemagick_command():
                self._resize_imagemagick(
                    input_path,
                    output_path,
                    width,
                    quality,
                    auto_orient,
                    additional_args,
                    convert_to_srgb,
                )
                return
            if not ImageProcessor._warned_no_convert:
                ImageProcessor._warned_no_convert = True
                print("image-options ignored: ImageMagick is not installed")

        with Image.open(input_path) as img:
            subsampling = self.chroma_subsampling(img, quality)
            icc_profile = img.info.get("icc_profile")
            source_exif = img.getexif() if keep_metadata != "none" else None
            xmp = img.info.get("xmp") if keep_metadata == "all" else None
            if auto_orient:
                img = ImageOps.exif_transpose(img)
            # Before resizing: palette images only resize with nearest-neighbour
            img = jpeg_compatible(img)
            # Match ImageMagick -resize WxW: scale to fit within the box,
            # upscaling if necessary (thumbnail() only shrinks).
            orig_w, orig_h = img.size
            ratio = min(width / orig_w, width / orig_h)
            new_size = (round(orig_w * ratio), round(orig_h * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

            # Nothing extra by default (+profile * equivalent)
            extra: dict = {}
            if icc_profile and not is_srgb(icc_profile):
                converted = False
                if convert_to_srgb:
                    try:
                        img = to_srgb(img, icc_profile)
                        converted = True
                    except ImageCms.PyCMSError as e:
                        print(f"\n\tCould not convert {input_path.name} to sRGB: {e}")
                if not converted and keep_metadata != "none":
                    extra["icc_profile"] = icc_profile
            if source_exif is not None:
                exif = filtered_exif(source_exif, keep_metadata, oriented=auto_orient)
                if exif is not None:
                    extra["exif"] = exif
            if xmp:
                extra["xmp"] = xmp

            try:
                img.save(
                    output_path,
                    "JPEG",
                    quality=quality,
                    subsampling=subsampling,
                    optimize=True,
                    **extra,
                )
            except OSError:
                # optimize=True needs the whole JPEG to fit a buffer Pillow sizes at ~1 byte per
                # pixel; very grainy images at 4:4:4 can exceed it. Fall back to standard
                # Huffman tables (~1-2% larger).
                img.save(output_path, "JPEG", quality=quality, subsampling=subsampling, **extra)

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
    def _resize_imagemagick(
        input_path: Path,
        output_path: Path,
        width: int,
        quality: int,
        auto_orient: bool,
        extra_args: list[str],
        convert_to_srgb: bool = False,
    ) -> None:
        """Resize with ImageMagick exactly as expose.sh does (including image-options).

        With ``convert_to_srgb``, ``-profile <sRGB>`` converts from the embedded profile first
        (it only assigns one when the image has none, so untagged images are unchanged).
        Metadata is always stripped on this path.
        """
        cmd = list(imagemagick.imagemagick_command() or ("convert",))
        cmd += ["-size", f"{width}x{width}", str(input_path)]
        # expose.sh puts -auto-orient first, which IM6/IM7 `convert` apply once the image is
        # read; `magick` needs it after the input. Same bytes either way.
        if auto_orient:
            cmd.append("-auto-orient")
        if convert_to_srgb:
            cmd += ["-profile", str(srgb_profile_file())]
        cmd += ["-resize", f"{width}x{width}"]
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
