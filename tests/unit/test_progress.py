"""Progress display (#4): overall counts and per-ffmpeg-pass progress."""

import io
import subprocess
from unittest import mock

import pytest
from rich.console import Console

from dorothea.config import DEFAULT_CONFIG, Config
from dorothea.generator import ExposeGenerator
from dorothea.media.ffmpeg import ffmpeg_exe, probe_duration, run_ffmpeg
from dorothea.progress import Reporter
from tests.conftest import SCRIPTDIR, make_test_image


def clip(path, seconds=2, size="320x240"):
    subprocess.run(
        [ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc=size={size}:rate=24", "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path


def terminal():
    """A Reporter drawing to a string, as if on a terminal."""
    out = io.StringIO()
    return Reporter(enabled=True, console=Console(file=out, force_terminal=True, width=120)), out


class TestReporter:
    def test_disabled_does_nothing(self):
        reporter = Reporter(enabled=False)
        with reporter.live():
            assert not reporter.active
            reporter.task("x", total=3).advance()
            with reporter.ffmpeg("pass", 10.0) as callback:
                assert callback is None

    def test_off_outside_a_terminal_by_default(self):
        with mock.patch("sys.stdout.isatty", return_value=False):
            assert Reporter().enabled is False

    def test_live_bars(self):
        reporter, out = terminal()
        with reporter.live():
            assert reporter.active
            task = reporter.task("Encoding 0/2", total=2)
            task.describe("Encoding 1/2 photo")
            task.advance()
            with reporter.ffmpeg("h264 1280px pass 2/2", 10.0) as callback:
                assert callback is not None
                callback(5.0)
                callback(99.0)  # clamped to the duration
        assert not reporter.active
        assert "Encoding 1/2 photo" in out.getvalue()

    def test_unknown_duration_means_no_bar(self):
        reporter, _ = terminal()
        with reporter.live(), reporter.ffmpeg("pass", 0.0) as callback:
            assert callback is None


class TestFfmpegProgress:
    def test_reports_seconds_written(self, tmp_path):
        source = clip(tmp_path / "in.mp4", seconds=3)
        seen: list[float] = []
        ok = run_ffmpeg(
            ["-loglevel", "error", "-nostdin", "-y", "-i", str(source), "-c:v", "libx264",
             "-preset", "ultrafast", str(tmp_path / "out.mp4")],
            progress=seen.append,
        )  # fmt: skip
        assert ok
        assert seen and seen == sorted(seen)
        assert seen[-1] == pytest.approx(3.0, abs=0.2)

    def test_failure_is_reported(self, tmp_path, capsys):
        ok = run_ffmpeg(
            ["-loglevel", "error", "-nostdin", "-i", str(tmp_path / "missing.mp4"), "x.mp4"],
            progress=lambda _seconds: None,
        )
        assert ok is False
        assert "missing.mp4" in capsys.readouterr().out

    def test_probe_duration(self, tmp_path):
        assert probe_duration(clip(tmp_path / "in.mp4", seconds=2)) == pytest.approx(2.0, abs=0.1)

    @mock.patch("subprocess.run")
    def test_probe_duration_parsing(self, mock_run):
        mock_run.return_value = mock.MagicMock(stderr="  Duration: 01:02:03.50, start: 0.0\n")
        assert probe_duration("x.mp4") == pytest.approx(3723.5)
        mock_run.return_value = mock.MagicMock(stderr="  Duration: N/A, bitrate: N/A\n")
        assert probe_duration("x.mp4") == 0.0


@pytest.mark.slow
class TestBuildWithProgress:
    def _gallery(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "photo.jpg", 1200, 900, "red")
        clip(g / "clip.mp4", seconds=2, size="640x360")

    def _build(self, topdir, progress):
        config = Config({**DEFAULT_CONFIG, "resolution": [640], "bitrate": [1],
                         "video_formats": ["h264"], "h264_encodespeed": "ultrafast"})  # fmt: skip
        gen = ExposeGenerator(topdir, SCRIPTDIR, config, progress=progress)
        gen.run()
        return gen

    def test_bars_are_drawn(self, tmp_path):
        self._gallery(tmp_path)
        reporter, out = terminal()
        self._build(tmp_path, reporter)
        text = out.getvalue()
        assert "Reading 2 files" in text
        assert "Encoding" in text
        assert (tmp_path / "_site" / "g" / "clip" / "640-h264.mp4").stat().st_size > 0

    def test_progress_only_adds_reporting_flags(self, tmp_path):
        """With bars, ffmpeg gets the usual arguments behind ``-progress pipe:1 -nostats``.

        (The encoded bytes can't be compared: threaded x264 2-pass isn't deterministic.)
        """
        commands = {}
        for name, reporter in [("plain", Reporter(enabled=False)), ("bars", terminal()[0])]:
            top = tmp_path / name
            top.mkdir()
            self._gallery(top)
            # subprocess.run goes through Popen too, so this sees both paths
            with mock.patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                gen = self._build(top, reporter)
            calls = [c.args[0] for c in popen.call_args_list]
            commands[name] = [
                [
                    str(a).replace(str(gen.scratchdir), "TMP").replace(str(top), "TOP")
                    for a in cmd[1:]
                ]
                for cmd in calls
                if "ffmpeg" in str(cmd[0]) and "-pass" in cmd
            ]
        assert commands["plain"]
        assert commands["bars"] == [
            ["-progress", "pipe:1", "-nostats", *c] for c in commands["plain"]
        ]
