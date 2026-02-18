"""Image processing using ImageMagick.

Provides abstraction layer for ImageMagick commands (convert, identify).
"""

import subprocess
from pathlib import Path

from pyexpose.media.base import MediaProcessor


class ImageProcessor(MediaProcessor):
    """ImageMagick wrapper for image processing.

    Currently wraps ImageMagick subprocess calls. Can be replaced with
    Pillow or other image libraries in the future.
    """

    def process(self, input_path: Path, output_path: Path, **kwargs) -> None:
        """Process an image (generic interface).

        Args:
            input_path: Input image path.
            output_path: Output image path.
            **kwargs: Additional processing parameters.
        """
        raise NotImplementedError("Use specific methods like resize(), identify(), etc.")

    def identify(self, image_path: Path, format_str: str) -> str:
        """Run ImageMagick identify command.

        Args:
            image_path: Image file path.
            format_str: Format string for identify (e.g., "%w" for width).

        Returns:
            Identify output.
        """
        cmd = ["identify", "-format", format_str, str(image_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""

    def convert(self, args: list) -> subprocess.CompletedProcess:
        """Run ImageMagick convert command.

        Args:
            args: Arguments for convert command.

        Returns:
            CompletedProcess result.
        """
        cmd = ["convert"] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def resize(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        quality: int = 92,
        auto_orient: bool = True,
        additional_args: list = None,
    ) -> None:
        """Resize an image.

        Args:
            input_path: Input image path.
            output_path: Output image path.
            width: Target width (height calculated from aspect ratio).
            quality: JPEG quality (0-100).
            auto_orient: Apply EXIF auto-orientation.
            additional_args: Additional convert arguments.
        """
        cmd = ["convert"]
        if auto_orient:
            cmd.append("-auto-orient")
        cmd.extend(
            [
                "-size",
                f"{width}x{width}",
                str(input_path),
                "-resize",
                f"{width}x{width}",
                "-quality",
                str(quality),
                "+profile",
                "*",
            ]
        )
        if additional_args:
            cmd.extend(additional_args)
        cmd.append(str(output_path))

        subprocess.run(cmd)

    def extract_dimensions(
        self, image_path: Path, handle_orientation: bool = False
    ) -> tuple[int, int]:
        """Extract image dimensions, optionally handling EXIF orientation.

        Args:
            image_path: Image file path.
            handle_orientation: If True, swap dimensions for rotated images.

        Returns:
            Tuple of (width, height).
        """
        width_str = self.identify(image_path, "%w")
        height_str = self.identify(image_path, "%h")

        width = int(width_str) if width_str else 0
        height = int(height_str) if height_str else 0

        if handle_orientation:
            orientation = self.identify(image_path, "%[EXIF:Orientation]")
            if orientation and orientation.isdigit() and 5 <= int(orientation) <= 8:
                # Swap dimensions for rotated images
                width, height = height, width

        return width, height
