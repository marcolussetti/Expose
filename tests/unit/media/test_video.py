"""Unit tests for pyexpose.media.video module.

Tests the VideoProcessor class that wraps FFmpeg.
"""

import shutil
from unittest import mock

import pytest

from pyexpose.media import ffmpeg
from pyexpose.media.video import VideoProcessor


@pytest.fixture
def video_processor():
    """Create a VideoProcessor instance."""
    return VideoProcessor()


class TestVideoProcessor:
    """Test VideoProcessor methods."""

    def test_availability_check(self, video_processor):
        """Video is available via system ffmpeg or the bundled imageio-ffmpeg binary."""
        assert video_processor.available is True

    def test_unavailable_without_any_ffmpeg(self):
        """No system ffmpeg and no bundled binary → video disabled."""
        with (
            mock.patch("pyexpose.media.ffmpeg.shutil.which", return_value=None),
            mock.patch("imageio_ffmpeg.get_ffmpeg_exe", side_effect=RuntimeError),
        ):
            assert VideoProcessor().available is False

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


class TestFfmpegHelpers:
    """Tests for pyexpose.media.ffmpeg."""

    def test_prefers_system_ffmpeg(self):
        with mock.patch("pyexpose.media.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert ffmpeg.ffmpeg_exe() == "ffmpeg"

    def test_falls_back_to_bundled_ffmpeg(self):
        with mock.patch("pyexpose.media.ffmpeg.shutil.which", return_value=None):
            exe = ffmpeg.ffmpeg_exe()
        assert exe is not None
        assert "ffmpeg" in exe

    @mock.patch("subprocess.run")
    def test_run_ffmpeg_reports_failure(self, mock_run, capsys):
        mock_run.return_value = mock.MagicMock(returncode=1, stderr="boom\n")
        assert ffmpeg.run_ffmpeg(["-i", "x"]) is False
        assert "boom" in capsys.readouterr().out

    @mock.patch("subprocess.run")
    def test_run_ffmpeg_success(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
        assert ffmpeg.run_ffmpeg(["-i", "x"]) is True
        assert "ffmpeg" in mock_run.call_args[0][0][0]

    @pytest.mark.parametrize(
        "stderr,expected",
        [
            (
                "  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), "
                "yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 24 fps\n",
                (1920, 1080),
            ),
            (
                "  Stream #0:0: Video: vp8, yuv420p(tv, progressive), 720x1280, SAR 1:1\n",
                (720, 1280),
            ),
            ("  Stream #0:0: Audio: aac, 48000 Hz, stereo\n", (0, 0)),
            ("", (0, 0)),
        ],
    )
    @mock.patch("subprocess.run")
    def test_probe_dimensions_parsing(self, mock_run, stderr, expected):
        mock_run.return_value = mock.MagicMock(returncode=1, stderr=stderr)
        assert ffmpeg.probe_dimensions("clip.mp4") == expected

    @pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not available")
    def test_probe_matches_ffprobe(self, tmp_path):
        """probe_dimensions agrees with ffprobe on a real clip."""
        import subprocess

        video = tmp_path / "clip.mp4"
        subprocess.run(
            [
                ffmpeg.ffmpeg_exe(),
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x176:rate=5",
                "-t",
                "1",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ],
            check=True,
            capture_output=True,
        )
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-of",
                "csv=p=0",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                str(video),
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        w, h = (int(x) for x in out.split(","))
        assert ffmpeg.probe_dimensions(video) == (w, h)
