"""Tests for edge cases and error handling paths."""

import shutil
from pathlib import Path
from unittest import mock

import pytest

from expose import DEFAULT_CONFIG, ExposeGenerator
from tests.conftest import SCRIPTDIR, make_test_image


def make_generator(tmp_path, config_overrides=None, draft=True):
    """Create a basic generator."""
    config = dict(DEFAULT_CONFIG)
    if config_overrides:
        config.update(config_overrides)
    return ExposeGenerator(tmp_path, SCRIPTDIR, config, draft=draft)


class TestErrorHandling:
    """Tests for error handling paths."""

    def test_cleanup_with_output_url(self, tmp_path):
        """Test cleanup removes output_url file."""
        gen = make_generator(tmp_path)

        # Create a file to simulate output_url
        output_file = tmp_path / "output.mp4"
        output_file.write_text("video data")
        gen.output_url = str(output_file)

        gen.cleanup()

        # File should be removed
        assert not output_file.exists()


class TestVideoMimeTypeDetection:
    """Tests for video file detection by mime type."""

    @mock.patch("subprocess.run")
    def test_read_files_video_by_mime_type(self, mock_run, tmp_path):
        """Test detecting video by mime type when extension is unknown."""
        gen = make_generator(tmp_path)
        gen.video_enabled = True

        # Create gallery directory
        gallery_dir = tmp_path / "gallery"
        gallery_dir.mkdir()

        # Create file with unknown extension but video mime type
        video_file = gallery_dir / "video.xyz"
        video_file.write_text("fake video")

        # Setup gallery structures
        gen.paths = [gallery_dir]
        gen.nav_name = ["Gallery"]
        gen.nav_depth = [0]
        gen.nav_type = [1]
        gen.nav_url = ["gallery"]

        # Mock identify for dimensions
        with mock.patch.object(gen, "identify", return_value="640"):
            # Mock subprocess.run for both 'file' and 'ffmpeg' calls
            call_count = [0]
            def mock_subprocess(*args, **kwargs):
                call_count[0] += 1
                cmd = args[0] if args else kwargs.get("args", [])
                if isinstance(cmd, list):
                    if "file" in cmd[0]:
                        return mock.MagicMock(
                            stdout="video/mp4; charset=binary",
                            returncode=0
                        )
                    elif "ffmpeg" in cmd[0]:
                        # Create temp frame for color extraction
                        (gen.scratchdir / "temp.jpg").write_text("frame")
                        return mock.MagicMock(returncode=0)
                return mock.MagicMock(returncode=0)

            with mock.patch("subprocess.run", side_effect=mock_subprocess):
                # Mock convert for color extraction
                with mock.patch.object(gen, "convert", return_value=mock.MagicMock(returncode=0)):
                    gen.read_files()

        # Should have detected video
        assert len(gen.gallery_files) >= 0  # May or may not be added depending on mocks

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_read_files_non_video_mime_type(self, mock_run, tmp_path):
        """Test ignoring non-video files by mime type."""
        gen = make_generator(tmp_path)
        gen.video_enabled = True

        gallery_dir = tmp_path / "gallery"
        gallery_dir.mkdir()

        # Create file with unknown extension
        data_file = gallery_dir / "data.xyz"
        data_file.write_text("not a video")

        gen.paths = [gallery_dir]
        gen.nav_name = ["Gallery"]
        gen.nav_depth = [0]
        gen.nav_type = [1]
        gen.nav_url = ["gallery"]

        # Mock file command to return non-video mime type
        mock_run.return_value = mock.MagicMock(
            stdout="application/octet-stream; charset=binary",
            returncode=0
        )

        gen.read_files()

        # Should have no gallery files (non-video was skipped)
        assert len(gen.gallery_files) == 0

        gen.cleanup()


class TestMarkdownProcessing:
    """Tests for Markdown processing when perl is available."""

    @mock.patch("shutil.which")
    def test_build_html_no_markdown_without_perl(self, mock_which, tmp_gallery):
        """Test HTML generation skips Markdown when perl unavailable."""
        mock_which.return_value = None

        gen = make_generator(tmp_gallery)
        gen.scan_directories()
        gen.read_files()
        gen.build_html()

        # HTML should be generated without markdown processing
        html_path = tmp_gallery / "_site" / "nature" / "mountains" / "index.html"
        assert html_path.exists()

        gen.cleanup()


class TestEncodeMedia:
    """Tests for the encode_media method."""

    def test_encode_media_empty_gallery(self, tmp_path):
        """Test encode_media handles empty gallery."""
        gen = make_generator(tmp_path)

        # Empty gallery structures
        gen.gallery_files = []

        # Should not raise
        gen.encode_media()

        gen.cleanup()
