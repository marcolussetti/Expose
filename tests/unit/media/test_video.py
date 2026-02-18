"""Unit tests for pyexpose.media.video module.

Tests the VideoProcessor class that wraps FFmpeg.
"""

import shutil

import pytest
from pyexpose.media.video import VideoProcessor


@pytest.fixture
def video_processor():
    """Create a VideoProcessor instance."""
    return VideoProcessor()


class TestVideoProcessor:
    """Test VideoProcessor methods."""

    def test_availability_check(self, video_processor):
        """Test that availability is correctly detected."""
        has_ffmpeg = shutil.which("ffmpeg") is not None
        has_ffprobe = shutil.which("ffprobe") is not None

        assert video_processor.available == (has_ffmpeg and has_ffprobe)

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not available")
    def test_extract_frame_creates_image(self, video_processor, tmp_path):
        """Test extracting a frame from video creates an image file."""
        # Create a simple test video using ffmpeg
        video_path = tmp_path / "test.mp4"
        import subprocess

        subprocess.run(
            [
                "ffmpeg",
                "-f",
                "lavfi",
                "-i",
                "color=blue:s=320x240:d=1",
                "-pix_fmt",
                "yuv420p",
                str(video_path),
            ],
            check=True,
            capture_output=True,
        )

        output_path = tmp_path / "frame.jpg"
        video_processor.extract_frame(video_path, output_path)

        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestVideoProcessorMethods:
    """Test individual video processing methods."""

    def test_process_not_implemented(self, video_processor, tmp_path):
        """Test that generic process() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            video_processor.process(tmp_path / "in.mp4", tmp_path / "out.mp4")
