"""Tests for video encoding functionality with mocked ffmpeg."""

from pathlib import Path
from unittest import mock

from dorothea.config import DEFAULT_CONFIG, Config
from dorothea.generator import ExposeGenerator
from tests.conftest import SCRIPTDIR, make_test_image

PROBE_640x480 = "  Stream #0:0: Video: h264 (High), yuv420p(progressive), 640x480, 24 fps\n"


def make_video_enabled_generator(tmp_path):
    """Create a generator with video support enabled (mocked)."""
    config_dict = dict(DEFAULT_CONFIG)
    config_dict["video_formats"] = ["h264"]
    config_dict["resolution"] = [640, 320]
    config_dict["bitrate"] = [4, 2]
    config = Config(config_dict)
    gen = ExposeGenerator(tmp_path, SCRIPTDIR, config, draft=True)
    gen.video_enabled = True  # Force enable even without ffmpeg
    return gen


class TestVideoEncoding:
    """Tests for video encoding methods."""

    @mock.patch("subprocess.run")
    def test_encode_video_draft_mode(self, mock_run, tmp_path):
        """Test video encoding in draft mode (single pass)."""
        gen = make_video_enabled_generator(tmp_path)
        gen.draft = True
        # Set single resolution for draft mode
        gen.config["resolution"] = [640]

        # Create fake video file
        video_path = tmp_path / "test.mp4"
        video_path.write_text("fake video")

        # Setup gallery structures
        gen.gallery_video_options = [""]
        gen.gallery_video_filters = [""]

        # Mock `ffmpeg -i` probe output for dimensions
        mock_run.side_effect = [
            mock.MagicMock(stderr=PROBE_640x480, returncode=1),  # probe
            mock.MagicMock(returncode=0),  # ffmpeg
        ]

        gen._encode_video(video_path, "test-video", 0)

        # Should probe then encode
        assert mock_run.call_count == 2

        # Check ffmpeg was called with draft mode settings
        ffmpeg_call = mock_run.call_args_list[1]
        cmd = ffmpeg_call[0][0]
        assert "ultrafast" in cmd  # Draft mode uses ultrafast preset
        assert "-crf" in cmd  # Draft mode uses CRF

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_video_skips_existing(self, mock_run, tmp_path):
        """Test video encoding skips if output already exists."""
        gen = make_video_enabled_generator(tmp_path)
        gen.draft = True
        # Set single resolution for draft mode
        gen.config["resolution"] = [640]

        video_path = tmp_path / "test.mp4"
        video_path.write_text("fake video")

        gen.gallery_video_options = [""]
        gen.gallery_video_filters = [""]

        # Create existing output file
        output_dir = tmp_path / "_site" / "test-video"
        output_dir.mkdir(parents=True)
        (output_dir / "640-h264.mp4").write_text("existing")

        mock_run.return_value = mock.MagicMock(stderr=PROBE_640x480, returncode=1)

        gen._encode_video(video_path, "test-video", 0)

        # Should only probe, not encode (early return)
        assert mock_run.call_count == 1

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_h264_two_pass(self, mock_run, tmp_path):
        """Test H.264 two-pass encoding."""
        gen = make_video_enabled_generator(tmp_path)
        gen.draft = False

        video_path = tmp_path / "test.mp4"
        video_path.write_text("fake video")

        output_path = tmp_path / "output.mp4"

        mock_run.return_value = mock.MagicMock(returncode=0)

        success = gen._encode_h264(
            video_path, output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )

        assert success is True
        # Should call ffmpeg twice (2 passes)
        assert mock_run.call_count == 2

        # First pass should output to /dev/null
        first_call = mock_run.call_args_list[0][0][0]
        assert "/dev/null" in first_call

        # Second pass writes a .part file that is renamed into place on success
        second_call = mock_run.call_args_list[1][0][0]
        assert str(tmp_path / "output.part.mp4") in second_call

        # Both passes share a pass log in the scratch dir, not the current directory
        for call in (first_call, second_call):
            logfile = call[call.index("-passlogfile") + 1]
            assert logfile.startswith(str(gen.scratchdir))

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_h264_first_pass_failure(self, mock_run, tmp_path):
        """Test H.264 encoding handles first pass failure."""
        gen = make_video_enabled_generator(tmp_path)

        video_path = tmp_path / "test.mp4"
        output_path = tmp_path / "output.mp4"

        # First pass fails
        mock_run.return_value = mock.MagicMock(returncode=1)

        success = gen._encode_h264(
            video_path, output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )

        assert success is False

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_h265(self, mock_run, tmp_path):
        """Test H.265 encoding."""
        gen = make_video_enabled_generator(tmp_path)
        gen.config["video_formats"] = ["h265"]

        video_path = tmp_path / "test.mp4"
        output_path = tmp_path / "output.mp4"

        mock_run.return_value = mock.MagicMock(returncode=0)

        success = gen._encode_h265(
            video_path, output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )

        assert success is True
        # Check libx265 codec was used
        call_args = mock_run.call_args_list[0][0][0]
        assert "libx265" in call_args

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_vp9(self, mock_run, tmp_path):
        """Test VP9 encoding."""
        gen = make_video_enabled_generator(tmp_path)
        gen.config["video_formats"] = ["vp9"]

        video_path = tmp_path / "test.mp4"
        output_path = tmp_path / "output.webm"

        mock_run.return_value = mock.MagicMock(returncode=0)

        success = gen._encode_vp9(
            video_path, output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )

        assert success is True
        call_args = mock_run.call_args_list[0][0][0]
        assert "libvpx-vp9" in call_args

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_vp8(self, mock_run, tmp_path):
        """Test VP8 encoding."""
        gen = make_video_enabled_generator(tmp_path)
        gen.config["video_formats"] = ["vp8"]

        video_path = tmp_path / "test.mp4"
        output_path = tmp_path / "output.webm"

        mock_run.return_value = mock.MagicMock(returncode=0)

        success = gen._encode_vp8(
            video_path, output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )

        assert success is True
        call_args = mock_run.call_args_list[0][0][0]
        assert "libvpx" in call_args

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_encode_ogv(self, mock_run, tmp_path):
        """Test OGV (Theora) encoding."""
        gen = make_video_enabled_generator(tmp_path)

        video_path = tmp_path / "test.mp4"
        output_path = tmp_path / "output.ogv"

        mock_run.return_value = mock.MagicMock(returncode=0)

        gen._encode_ogv(video_path, output_path, 640, 4, 8, "", ["-an"])

        call_args = mock_run.call_args[0][0]
        assert "libtheora" in call_args

        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_second_pass_failure_leaves_no_output(self, mock_run, tmp_path):
        """A failed pass 2 must not leave an output (or .part) file behind."""
        gen = make_video_enabled_generator(tmp_path)
        video_path = tmp_path / "test.mp4"
        output_path = tmp_path / "output.mp4"

        def fake_run(cmd, **kwargs):
            if "2" in cmd and cmd[cmd.index("-pass") + 1] == "2":
                Path(cmd[-1]).write_text("partial")  # ffmpeg dies mid-write
                return mock.MagicMock(returncode=1, stderr="encode failed")
            return mock.MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run
        success = gen._encode_h264(
            video_path, output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )

        assert success is False
        assert not output_path.exists()
        assert not (tmp_path / "output.part.mp4").exists()
        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_second_pass_success_renames_part(self, mock_run, tmp_path):
        """A successful pass 2 moves the .part file into place."""
        gen = make_video_enabled_generator(tmp_path)
        output_path = tmp_path / "output.mp4"

        def fake_run(cmd, **kwargs):
            if cmd[-1].endswith(".part.mp4"):
                Path(cmd[-1]).write_text("video")
            return mock.MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run
        assert gen._encode_h264(
            tmp_path / "in.mp4", output_path, 640, 4, 8, "", [], ["-an"], firstpass=False
        )
        assert output_path.read_text() == "video"
        assert not (tmp_path / "output.part.mp4").exists()
        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_video_options_passed_to_ffmpeg(self, mock_run, tmp_path):
        """video-options metadata is inserted after -threads, as in expose.sh."""
        gen = make_video_enabled_generator(tmp_path)
        gen.config["resolution"] = [640]
        video_path = tmp_path / "test.mp4"
        video_path.write_text("fake video")
        gen.gallery_video_options = ["-ss 00:00:02 -t 5"]
        gen.gallery_video_filters = [""]

        mock_run.side_effect = [
            mock.MagicMock(stderr=PROBE_640x480, returncode=1),
            mock.MagicMock(returncode=0, stderr=""),
        ]
        gen._encode_video(video_path, "test-video", 0)

        cmd = mock_run.call_args_list[1][0][0]
        t = cmd.index("-threads")
        assert cmd[t + 2 : t + 6] == ["-ss", "00:00:02", "-t", "5"]
        gen.cleanup()

    @mock.patch("subprocess.run")
    def test_stale_output_is_reencoded(self, mock_run, tmp_path):
        """An output older than its source is re-encoded; a newer one is skipped."""
        import os

        gen = make_video_enabled_generator(tmp_path)
        gen.draft = True
        gen.config["resolution"] = [640]
        video_path = tmp_path / "test.mp4"
        video_path.write_text("fake video")
        gen.gallery_files = [video_path]
        gen.gallery_video_options = [""]
        gen.gallery_video_filters = [""]

        out = tmp_path / "_site" / "test-video" / "640-h264.mp4"
        out.parent.mkdir(parents=True)
        out.write_text("old encode")
        os.utime(out, (1, 1))  # older than the source

        mock_run.return_value = mock.MagicMock(stderr=PROBE_640x480, returncode=0)
        gen._encode_video(video_path, "test-video", 0)
        assert mock_run.call_count == 2  # probe + re-encode
        gen.cleanup()


class TestSequenceHandling:
    """Tests for image sequence compilation."""

    def test_sequence_finished_false(self, tmp_path):
        """Test _sequence_finished returns False when files missing."""
        gen = make_video_enabled_generator(tmp_path)
        # Use single resolution and format for simpler testing
        gen.config["resolution"] = [640]
        gen.config["video_formats"] = ["h264"]

        # No files exist
        result = gen._sequence_finished("test-sequence")
        assert result is False

        gen.cleanup()

    def test_sequence_finished_true(self, tmp_path):
        """Test _sequence_finished returns True when all files exist."""
        gen = make_video_enabled_generator(tmp_path)
        # Use single resolution and format for simpler testing
        gen.config["resolution"] = [640]
        gen.config["video_formats"] = ["h264"]

        # Create output directory with encoded files
        output_dir = tmp_path / "_site" / "test-sequence"
        output_dir.mkdir(parents=True)
        (output_dir / "640-h264.mp4").write_text("video data")

        result = gen._sequence_finished("test-sequence")
        assert result is True

        gen.cleanup()

    def test_compile_sequence(self, tmp_path):
        """Test image sequence compilation."""
        gen = make_video_enabled_generator(tmp_path)
        gen.config["resolution"] = [640]  # Use single resolution

        # Create sequence directory with images
        seq_dir = tmp_path / "sequence-imagesequence"
        seq_dir.mkdir()
        make_test_image(seq_dir / "001.jpg", 640, 480, "red")
        make_test_image(seq_dir / "002.jpg", 640, 480, "blue")

        expected_output = gen.scratchdir / "sequencevideo.mp4"

        # Create a custom mock that creates the output file when called
        def mock_subprocess_run(*args, **kwargs):
            # Simulate ffmpeg creating the output file
            expected_output.write_text("compiled video")
            return mock.MagicMock(returncode=0)

        with mock.patch("subprocess.run", side_effect=mock_subprocess_run):
            result = gen._compile_sequence(seq_dir)

        assert result is not None
        assert result.exists()
        assert result == expected_output

        gen.cleanup()

    def test_compile_sequence_empty(self, tmp_path):
        """Test _compile_sequence returns None for empty directory."""
        gen = make_video_enabled_generator(tmp_path)

        seq_dir = tmp_path / "empty-sequence"
        seq_dir.mkdir()

        result = gen._compile_sequence(seq_dir)

        assert result is None

        gen.cleanup()
