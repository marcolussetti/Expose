"""Video processing using FFmpeg.

Provides abstraction layer for FFmpeg commands.
"""

from pathlib import Path

from pyexpose.media.base import MediaProcessor
from pyexpose.media.ffmpeg import ffmpeg_exe, probe_dimensions, run_ffmpeg


class VideoProcessor(MediaProcessor):
    """FFmpeg wrapper for video processing.

    Uses the system ffmpeg if present, otherwise the binary bundled with imageio-ffmpeg
    (see ``pyexpose.media.ffmpeg``).
    """

    def __init__(self):
        """Initialize video processor."""
        self.available = ffmpeg_exe() is not None

    def process(self, input_path: Path, output_path: Path, **kwargs: object) -> None:
        """Process a video (generic interface).

        Args:
            input_path: Input video path.
            output_path: Output video path.
            **kwargs: Additional processing parameters.
        """
        raise NotImplementedError("Use specific methods like extract_frame(), probe(), etc.")

    def probe(self, video_path: Path) -> tuple[int, int]:
        """Return (width, height) of the first video stream, or (0, 0) if unknown."""
        return probe_dimensions(video_path)

    def extract_frame(
        self, video_path: Path, output_path: Path, frame: int = 1, quality: int = 2
    ) -> bool:
        """Extract a single frame from video.

        Args:
            video_path: Video file path.
            output_path: Output image path.
            frame: Frame number to extract.
            quality: JPEG quality (0-31, lower is better).

        Returns:
            True if ffmpeg succeeded.
        """
        return run_ffmpeg(
            [
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
            ]
        )
