"""Regression tests for gaps found in the expose.sh parity audit."""

import subprocess
from pathlib import Path

from PIL import Image

from dorothea.media.ffmpeg import ffmpeg_exe
from tests.conftest import make_generator, make_test_image


def frame_count(video):
    """Decode a video and count its frames using ffmpeg (no ffprobe needed)."""
    result = subprocess.run(
        [ffmpeg_exe(), "-nostdin", "-i", str(video), "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    frames = [line for line in result.stderr.splitlines() if "frame=" in line]
    return int(frames[-1].split("frame=")[1].split()[0])


class TestSequenceFrames:
    def _compile(self, tmp_path, names):
        seq = tmp_path / "walk-imagesequence"
        seq.mkdir()
        for i, name in enumerate(names):
            fmt = "PNG" if name.lower().endswith(".png") else "JPEG"
            Image.new("RGB", (320, 240), (40 * i, 80, 160)).save(seq / name, format=fmt)
        # -r is an output option in expose.sh (input is read at ffmpeg's default 25 fps), so
        # 25 keeps one output frame per input frame
        gen = make_generator(tmp_path, config_overrides={"sequence_framerate": 25})
        gen.config["h264_encodespeed"] = "ultrafast"
        video = gen._compile_sequence(seq)
        count = frame_count(video)
        gen.cleanup()
        return count

    def test_mixed_formats_keep_every_frame(self, tmp_path):
        """A sequence mixing JPEG and PNG frames must not drop the odd ones out."""
        assert self._compile(tmp_path, ["01.jpg", "02.png", "03.jpg", "04.png"]) == 4

    def test_mixed_jpeg_extensions(self, tmp_path):
        """.JPG, .jpeg and .jpg are the same format and must all be used."""
        assert self._compile(tmp_path, ["01.JPG", "02.jpeg", "03.jpg"]) == 3


class TestCaptionFiles:
    def test_binary_caption_does_not_crash(self, tmp_path, capsys):
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        make_test_image(gallery / "photo.jpg", 1200, 900, "blue")
        (gallery / "photo.txt").write_bytes(b"\xff\xfe\x00binary\x80junk")

        gen = make_generator(tmp_path)
        gen.scan_directories()
        gen.read_files()
        gen.build_html()

        html = (tmp_path / "_site" / "gallery" / "index.html").read_text()
        assert "photo" in html
        assert "not a UTF-8 text file" in capsys.readouterr().out
        gen.cleanup()

    def test_utf8_caption_regardless_of_locale(self, tmp_path):
        """Captions are read and pages written as UTF-8 even under an ASCII locale."""
        import sys

        script = (
            "from tests.conftest import make_generator; from pathlib import Path; "
            f"g = make_generator(Path({str(tmp_path)!r})); "
            "g.scan_directories(); g.read_files(); g.build_html(); g.cleanup()"
        )
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        make_test_image(gallery / "photo.jpg", 1200, 900, "blue")
        (gallery / "photo.txt").write_text("Café in Reykjavík", encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONUTF8": "0"}
        result = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, cwd=Path.cwd()
        )
        assert result.returncode == 0, result.stderr
        html = (tmp_path / "_site" / "gallery" / "index.html").read_text(encoding="utf-8")
        assert "Café in Reykjavík" in html
