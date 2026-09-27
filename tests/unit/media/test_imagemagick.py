"""Finding ImageMagick without mistaking Windows' convert.exe for it (#19)."""

import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from dorothea.encoder import MediaEncoder
from dorothea.media.image import ImageProcessor
from dorothea.media.imagemagick import imagemagick_command
from tests.conftest import DATADIR, HAS_IMAGEMAGICK, make_generator


def lookup(found: dict[str, str], version_output: str | Exception = ""):
    """imagemagick_command() with ``shutil.which`` finding only ``found``."""
    imagemagick_command.cache_clear()
    result = mock.Mock(returncode=0, stdout=version_output, stderr="")
    run = mock.Mock(side_effect=version_output) if isinstance(version_output, Exception) else None
    with (
        mock.patch("dorothea.media.imagemagick.shutil.which", side_effect=found.get),
        mock.patch("subprocess.run", run or mock.Mock(return_value=result)) as ran,
    ):
        return imagemagick_command(), ran


def test_prefers_magick():
    """IM7's `magick` makes expose.sh's bytes without the deprecation warning."""
    command, ran = lookup({"magick": "/usr/bin/magick", "convert": "/usr/bin/convert"})
    assert command == ("/usr/bin/magick",)
    ran.assert_not_called()


def test_imagemagick_6_convert():
    command, _ = lookup(
        {"convert": "/usr/bin/convert"}, "Version: ImageMagick 6.9.11-60 Q16 x86_64\n"
    )
    assert command == ("/usr/bin/convert",)


def test_ignores_windows_convert_exe():
    """C:\\Windows\\System32\\convert.exe converts FAT volumes to NTFS (upstream #50)."""
    command, ran = lookup(
        {"convert": r"C:\Windows\System32\convert.exe"}, "Invalid Parameter - -version\n"
    )
    assert command is None
    assert ran.call_args.args[0] == [r"C:\Windows\System32\convert.exe", "-version"]


def test_convert_that_cannot_run():
    command, _ = lookup({"convert": "/usr/bin/convert"}, PermissionError("denied"))
    assert command is None


def test_not_installed():
    command, _ = lookup({})
    assert command is None


def test_result_is_cached():
    lookup({"magick": "/usr/bin/magick"})
    with mock.patch("dorothea.media.imagemagick.shutil.which", return_value=None):
        assert imagemagick_command() == ("/usr/bin/magick",)


@pytest.mark.skipif(
    not (shutil.which("magick") and shutil.which("convert")), reason="needs ImageMagick 7"
)
def test_magick_resize_matches_expose_sh_convert(tmp_path):
    """`magick` needs -auto-orient after the input; the bytes match expose.sh's `convert`."""
    src = DATADIR / "test_run" / "01_Nature" / "01_Mountains" / "01_peak.jpg"
    ours, theirs = tmp_path / "ours.jpg", tmp_path / "theirs.jpg"
    ImageProcessor._resize_imagemagick(src, ours, 640, 92, True, ["-negate"])
    subprocess.run(
        ["convert", "-auto-orient", "-size", "640x640", str(src), "-resize", "640x640",
         "-quality", "92", "+profile", "*", "-negate", str(theirs)],
        check=True, capture_output=True,
    )  # fmt: skip
    assert ours.read_bytes() == theirs.read_bytes()


@pytest.mark.skipif(not HAS_IMAGEMAGICK, reason="ImageMagick not installed")
def test_real_imagemagick_runs_quietly(tmp_path):
    out = tmp_path / "x.png"
    result = subprocess.run(
        [*imagemagick_command(), "-size", "4x4", "xc:red", str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stat().st_size > 0
    assert "deprecated" not in result.stderr


def test_first_pass_writes_to_os_devnull(tmp_path):
    """/dev/null doesn't exist on Windows; os.devnull is NUL there."""
    gen = make_generator(tmp_path)
    encoder = gen._make_encoder()
    calls = []
    with mock.patch.object(
        MediaEncoder, "_ffmpeg", side_effect=lambda args, **kw: calls.append(args) or False
    ):
        encoder._encode_h264(
            Path("in.mp4"), tmp_path / "640-h264.mp4", 640, 4, 8, "", [], ["-an"], False
        )
    assert calls[0][-3:] == ["-f", "mp4", os.devnull]
