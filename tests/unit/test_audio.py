"""Videos with audio (#13): each container gets audio it can hold."""

import subprocess

import pytest

from dorothea.config import DEFAULT_CONFIG, Config
from dorothea.encoder import audio_args
from dorothea.generator import ExposeGenerator
from dorothea.media.ffmpeg import ffmpeg_exe, missing_encoders, probe_audio_codec
from tests.conftest import SCRIPTDIR


def clip(path, audio="aac", seconds=1):
    """A small clip with a sine-tone audio track (or none, audio=None)."""
    inputs = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=24"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    subprocess.run(
        [ffmpeg_exe(), "-loglevel", "error", "-y", *inputs, "-t", str(seconds),
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         *(["-c:a", {"aac": "aac", "opus": "libopus"}[audio]] if audio else []), str(path)],
        check=True,
    )  # fmt: skip
    return path


@pytest.mark.parametrize(
    ("extension", "source", "expected"),
    [
        ("mp4", "aac", ["-c:a", "copy"]),  # what expose.sh did, where it works
        ("mp4", "mp3", ["-c:a", "copy"]),
        ("mp4", "opus", ["-c:a", "aac"]),
        ("mp4", "pcm_s16le", ["-c:a", "aac"]),
        ("webm", "aac", ["-c:a", "libopus"]),  # the bug: AAC can't go in WebM
        ("webm", "opus", ["-c:a", "copy"]),
        ("webm", "vorbis", ["-c:a", "copy"]),
        ("ogv", "aac", ["-c:a", "libvorbis"]),
        ("ogv", "vorbis", ["-c:a", "copy"]),
        ("webm", None, ["-c:a", "copy"]),  # no audio track: nothing to add
    ],
)
def test_audio_args(extension, source, expected):
    assert audio_args(extension, source) == expected


def test_probe_audio_codec(tmp_path):
    assert probe_audio_codec(clip(tmp_path / "a.mp4")) == "aac"
    assert probe_audio_codec(clip(tmp_path / "b.mp4", audio=None)) is None


def build(topdir, **overrides):
    config = Config({**DEFAULT_CONFIG, "resolution": [320], "bitrate": [1],
                     "h264_encodespeed": "ultrafast", "vp9_encodespeed": 4, **overrides})  # fmt: skip
    gen = ExposeGenerator(topdir, SCRIPTDIR, config)
    gen.run()
    return topdir / "_site" / "g" / "clip"


@pytest.mark.slow
class TestEncodeWithAudio:
    def _formats(self):
        wanted = ["h264", "vp8", "vp9", "ogv"]
        missing = missing_encoders(ffmpeg_exe(), wanted)
        return [f for f in wanted if f not in missing]

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("aac", {"mp4": "aac", "webm": "opus", "ogv": "vorbis"}),
            ("opus", {"mp4": "aac", "webm": "opus", "ogv": "opus"}),  # Ogg takes Opus too
        ],
    )
    def test_every_format_is_built_with_audio(self, tmp_path, source, expected):
        (tmp_path / "g").mkdir()
        clip(tmp_path / "g" / "clip.mp4", audio=source)
        formats = self._formats()
        out = build(tmp_path, disable_audio=False, video_formats=formats)
        for fmt in formats:
            ext = {"h264": "mp4", "vp8": "webm", "vp9": "webm", "ogv": "ogv"}[fmt]
            video = out / f"320-{fmt}.{ext}"
            assert video.stat().st_size > 0, f"{fmt} not built"
            assert probe_audio_codec(video) == expected[ext], fmt

    def test_draft_keeps_audio(self, tmp_path):
        (tmp_path / "g").mkdir()
        clip(tmp_path / "g" / "clip.mp4", audio="opus")
        config = Config({**DEFAULT_CONFIG, "disable_audio": False})
        config.apply_draft_mode()
        gen = ExposeGenerator(tmp_path, SCRIPTDIR, config, draft=True)
        gen.run()
        (video,) = (tmp_path / "_site" / "g" / "clip").glob("*-h264.mp4")
        assert probe_audio_codec(video) == "aac"

    def test_audio_disabled_by_default(self, tmp_path):
        (tmp_path / "g").mkdir()
        clip(tmp_path / "g" / "clip.mp4")
        out = build(tmp_path, video_formats=["h264", "vp9"])
        assert probe_audio_codec(out / "320-h264.mp4") is None
        assert probe_audio_codec(out / "320-vp9.webm") is None

    def test_turning_audio_on_rebuilds(self, tmp_path):
        (tmp_path / "g").mkdir()
        clip(tmp_path / "g" / "clip.mp4")
        out = build(tmp_path, video_formats=["vp9"])
        assert probe_audio_codec(out / "320-vp9.webm") is None
        build(tmp_path, video_formats=["vp9"], disable_audio=False)
        assert probe_audio_codec(out / "320-vp9.webm") == "opus"

    def test_failed_format_is_reported(self, tmp_path, capsys):
        (tmp_path / "g").mkdir()
        clip(tmp_path / "g" / "clip.mp4")
        # an option ffmpeg rejects makes every encode of this video fail
        (tmp_path / "g" / "clip.txt").write_text("video-options: -nosuchoption 1\n---\n")
        build(tmp_path, video_formats=["vp9"])
        assert "vp9: skipped for g/clip" in capsys.readouterr().out
