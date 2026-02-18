"""Video processing using FFmpeg.

Provides abstraction layer for FFmpeg commands.
"""

import shutil
import subprocess
from pathlib import Path

from pyexpose.media.base import MediaProcessor


class VideoProcessor(MediaProcessor):
    """FFmpeg wrapper for video processing.

    Currently wraps FFmpeg subprocess calls. Can be replaced with
    python-ffmpeg or other video libraries in the future.
    """

    def __init__(self):
        """Initialize video processor."""
        self.available = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

    def process(self, input_path: Path, output_path: Path, **kwargs) -> None:
        """Process a video (generic interface).

        Args:
            input_path: Input video path.
            output_path: Output video path.
            **kwargs: Additional processing parameters.
        """
        raise NotImplementedError("Use specific methods like encode_h264(), extract_frame(), etc.")

    def probe(self, video_path: Path) -> dict:
        """Probe video metadata using ffprobe.

        Args:
            video_path: Video file path.

        Returns:
            Dictionary with video metadata.
        """
        # Placeholder - will be implemented when extracting from expose.py
        return {}

    def extract_frame(
        self, video_path: Path, output_path: Path, frame: int = 1, quality: int = 2
    ) -> None:
        """Extract a single frame from video.

        Args:
            video_path: Video file path.
            output_path: Output image path.
            frame: Frame number to extract.
            quality: JPEG quality (0-31, lower is better).
        """
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"select=gte(n\\,{frame})",
                "-vframes",
                "1",
                "-qscale:v",
                str(quality),
                str(output_path),
            ],
            stdin=subprocess.DEVNULL,
        )

    def encode_h264(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        bitrate: int,
        max_bitrate: int,
        **kwargs,
    ) -> None:
        """Encode video to H.264/MP4.

        Args:
            input_path: Input video path.
            output_path: Output video path.
            width: Target width.
            bitrate: Target bitrate in Mbps.
            max_bitrate: Maximum bitrate in Mbps.
            **kwargs: Additional encoding parameters.

        Placeholder - will be implemented when extracting from expose.py.
        """
        pass

    def encode_vp9(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        bitrate: int,
        max_bitrate: int,
        **kwargs,
    ) -> None:
        """Encode video to VP9/WebM.

        Args:
            input_path: Input video path.
            output_path: Output video path.
            width: Target width.
            bitrate: Target bitrate in Mbps.
            max_bitrate: Maximum bitrate in Mbps.
            **kwargs: Additional encoding parameters.

        Placeholder - will be implemented when extracting from expose.py.
        """
        pass
