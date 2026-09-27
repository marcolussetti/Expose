"""Unit tests for dorothea.media.video module.

Tests the VideoProcessor class that wraps FFmpeg.
"""

import shutil
from unittest import mock

import pytest

from dorothea.media import ffmpeg
from dorothea.media.video import VideoProcessor


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
            mock.patch("dorothea.media.ffmpeg.shutil.which", return_value=None),
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
    """Tests for dorothea.media.ffmpeg."""

    def test_prefers_system_ffmpeg(self):
        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert ffmpeg.ffmpeg_exe() == "ffmpeg"

    def test_falls_back_to_bundled_ffmpeg(self):
        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value=None):
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


class TestFfmpegChoice:
    """The ffmpeg setting / --ffmpeg flag (issue #3)."""

    def test_auto_prefers_system(self):
        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert ffmpeg.ffmpeg_exe("auto") == "ffmpeg"

    def test_bundled_ignores_system(self):
        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            exe = ffmpeg.ffmpeg_exe("bundled")
        assert exe is not None and exe != "ffmpeg" and "ffmpeg" in exe

    def test_system_without_system_ffmpeg(self):
        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value=None):
            assert ffmpeg.ffmpeg_exe("system") is None

    def test_custom_path(self, tmp_path):
        exe = tmp_path / "my-ffmpeg"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        assert ffmpeg.ffmpeg_exe(str(exe)) == str(exe)
        assert ffmpeg.ffmpeg_kind(str(exe)) == "custom"

    def test_custom_path_must_be_executable(self, tmp_path):
        plain = tmp_path / "not-executable"
        plain.write_text("x")
        assert ffmpeg.ffmpeg_exe(str(plain)) is None
        assert ffmpeg.ffmpeg_exe(str(tmp_path / "missing")) is None

    def test_set_ffmpeg_changes_default(self):
        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            ffmpeg.set_ffmpeg("bundled")
            assert ffmpeg.ffmpeg_exe() != "ffmpeg"
            ffmpeg.set_ffmpeg(None)
            assert ffmpeg.ffmpeg_exe() == "ffmpeg"

    def test_generator_applies_config(self, tmp_path):
        from dorothea.config import DEFAULT_CONFIG, Config
        from dorothea.generator import ExposeGenerator

        ExposeGenerator(tmp_path, tmp_path, Config({**DEFAULT_CONFIG, "ffmpeg": "bundled"}))
        assert ffmpeg._choice == "bundled"

    @mock.patch("subprocess.run")
    def test_version_parsing(self, mock_run):
        mock_run.return_value = mock.MagicMock(
            stdout="ffmpeg version 7.0.2-static https://johnvansickle.com Copyright (c) 2000\n"
        )
        assert ffmpeg.ffmpeg_version("ffmpeg") == "7.0.2-static"
        mock_run.return_value = mock.MagicMock(stdout="garbage\n")
        assert ffmpeg.ffmpeg_version("ffmpeg") == "unknown"

    @mock.patch("subprocess.run")
    def test_encoder_parsing_and_missing(self, mock_run):
        mock_run.return_value = mock.MagicMock(
            stdout=(
                "Encoders:\n V..... = Video\n ------\n"
                " V....D libx264              libx264 H.264 / AVC\n"
                " V....D libvpx               libvpx VP8\n"
                " A....D aac                  AAC (Advanced Audio Coding)\n"
            )
        )
        assert ffmpeg.ffmpeg_encoders("ffmpeg") == {"libx264", "libvpx", "aac"}
        missing = ffmpeg.missing_encoders("ffmpeg", ["h264", "vp8", "vp9", "h265"])
        assert missing == {"vp9": "libvpx-vp9", "h265": "libx265"}

    @mock.patch("subprocess.run", side_effect=OSError("cannot run"))
    def test_unlistable_encoders_warn_nothing(self, _mock_run):
        assert ffmpeg.missing_encoders("ffmpeg", ["vp8"]) == {}

    def test_real_ffmpeg_has_the_default_encoders(self):
        exe = ffmpeg.ffmpeg_exe()
        assert ffmpeg.ffmpeg_version(exe) != "unknown"
        assert ffmpeg.missing_encoders(exe, ["h264", "vp8"]) == {}


class TestReportFfmpeg:
    """The 'Using ffmpeg …' line and missing-encoder warnings before video encoding."""

    def _encoder(self, tmp_path, formats):
        from dorothea.config import DEFAULT_CONFIG, Config
        from dorothea.encoder import MediaEncoder

        config = Config({**DEFAULT_CONFIG, "video_formats": formats})
        return MediaEncoder(tmp_path, tmp_path, config, False, [], [], [], [], [], [], [])

    def test_reports_ffmpeg_in_use(self, tmp_path, capsys):
        self._encoder(tmp_path, ["h264"])._report_ffmpeg()
        out = capsys.readouterr().out
        assert out.startswith("Using ffmpeg ")
        assert "Warning" not in out

    def test_warns_about_missing_encoders(self, tmp_path, capsys):
        with mock.patch("dorothea.encoder.missing_encoders", return_value={"vp9": "libvpx-vp9"}):
            self._encoder(tmp_path, ["h264", "vp9"])._report_ffmpeg()
        out = capsys.readouterr().out
        assert "no libvpx-vp9 encoder, so vp9 videos will fail" in out
        assert "--ffmpeg bundled" in out

    def test_reports_when_unavailable(self, tmp_path, capsys):
        with mock.patch("dorothea.encoder.ffmpeg_exe", return_value=None):
            self._encoder(tmp_path, ["h264"])._report_ffmpeg()
        assert "No ffmpeg available" in capsys.readouterr().out
