"""FFmpeg binary resolution and invocation helpers.

Which ffmpeg is used is set by the ``ffmpeg`` setting (``--ffmpeg``):

- ``auto`` (default): a system ``ffmpeg`` on PATH (keeps output identical to expose.sh, which
  uses whatever is on PATH), otherwise the static binary bundled with ``imageio-ffmpeg``, so a
  plain ``pip``/``uv`` install works without system packages
- ``system``: only the one on PATH
- ``bundled``: only imageio-ffmpeg's
- a path to an ffmpeg binary
"""

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

FFMPEG_CHOICES = ("auto", "bundled", "system")

# Encoder each video format needs (see MediaEncoder._encode_* for the arguments)
FORMAT_ENCODERS = {
    "h264": "libx264",
    "h265": "libx265",
    "vp9": "libvpx-vp9",
    "vp8": "libvpx",
    "ogv": "libtheora",
}

# Current choice; set once per build by ExposeGenerator from the config
_choice = "auto"

# First "WxH" after "Video:" on an ffmpeg stream line. Word boundaries keep codec tags
# such as "0x31637661" from matching.
_VIDEO_DIMENSIONS = re.compile(r"Stream #.*?: Video: .*?\b(\d{2,5})x(\d{2,5})\b")
_DURATION = re.compile(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_AUDIO_CODEC = re.compile(r"Stream #.*?: Audio: (\w+)")


def set_ffmpeg(choice: str | None) -> None:
    """Select which ffmpeg later calls use: ``auto``, ``bundled``, ``system`` or a path."""
    global _choice
    _choice = choice or "auto"


def _system_ffmpeg() -> str | None:
    return "ffmpeg" if shutil.which("ffmpeg") else None


def _bundled_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError, RuntimeError:
        return None


def ffmpeg_exe(choice: str | None = None) -> str | None:
    """Return the ffmpeg executable to use, or None if the chosen one isn't available.

    Args:
        choice: ``auto``, ``bundled``, ``system`` or a path; defaults to the current setting.
    """
    choice = choice or _choice
    if choice == "auto":
        return _system_ffmpeg() or _bundled_ffmpeg()
    if choice == "system":
        return _system_ffmpeg()
    if choice == "bundled":
        return _bundled_ffmpeg()
    path = Path(choice).expanduser()
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def ffmpeg_kind(exe: str) -> str:
    """Where an executable returned by ``ffmpeg_exe`` comes from: system, bundled or custom."""
    if exe == "ffmpeg":
        return "system"
    if exe == _bundled_ffmpeg():
        return "bundled"
    return "custom"


def _run_text(args: list[str]) -> str:
    """Run a command and return its stdout ("" if it can't run)."""
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace"
        )
    except OSError:
        return ""
    return result.stdout if isinstance(result.stdout, str) else ""


def ffmpeg_version(exe: str) -> str:
    """Version string from ``ffmpeg -version`` (e.g. ``7.0.2-static``), or ``unknown``."""
    first = _run_text([exe, "-version"]).split("\n", 1)[0].split()
    return first[2] if len(first) > 2 and first[:2] == ["ffmpeg", "version"] else "unknown"


def ffmpeg_encoders(exe: str) -> set[str]:
    """Names of the encoders an ffmpeg binary was built with (``ffmpeg -encoders``)."""
    # A legend ("V..... = Video"), a "------" line, then " V....D libx264   H.264 / AVC ..."
    _legend, _sep, listing = _run_text([exe, "-hide_banner", "-encoders"]).partition("------")
    encoders = set()
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            encoders.add(parts[1])
    return encoders


def describe_ffmpeg(exe: str) -> str:
    """One-line description, e.g. ``ffmpeg 7.0.2-static (bundled: /path/to/ffmpeg)``."""
    kind = ffmpeg_kind(exe)
    location = shutil.which(exe) if kind == "system" else exe
    return f"ffmpeg {ffmpeg_version(exe)} ({kind}: {location})"


def missing_encoders(exe: str, formats: Iterable[str]) -> dict[str, str]:
    """Video formats (``{format: encoder}``) that this ffmpeg can't encode."""
    available = ffmpeg_encoders(exe)
    if not available:
        return {}  # couldn't list encoders; don't guess
    return {
        fmt: FORMAT_ENCODERS[fmt]
        for fmt in formats
        if fmt in FORMAT_ENCODERS and FORMAT_ENCODERS[fmt] not in available
    }


def run_ffmpeg(args: list[str], progress: Callable[[float], None] | None = None) -> bool:
    """Run ffmpeg with the given arguments (excluding the executable).

    Stderr is captured and printed only when ffmpeg fails.

    Args:
        args: ffmpeg arguments.
        progress: Called with the seconds of output written so far, from ffmpeg's
            ``-progress`` reports (which only affect reporting, not the output). Without it,
            ffmpeg runs exactly as before.

    Returns:
        True if ffmpeg exited successfully.
    """
    exe = ffmpeg_exe()
    if exe is None:
        print(f"ffmpeg not available (ffmpeg setting: {_choice}); skipping video step")
        return False
    if progress is not None:
        return _run_with_progress(exe, args, progress)
    # ffmpeg writes UTF-8 (file names), whatever the locale; Windows' default codec is cp1252
    result = subprocess.run(
        [exe, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else ""
        if stderr.strip():
            print(stderr.strip())
        return False
    return True


def _run_with_progress(exe: str, args: list[str], progress: Callable[[float], None]) -> bool:
    """``run_ffmpeg`` with ``-progress pipe:1``: stream stdout, report ``out_time_us``."""
    # stderr goes to a file so a chatty ffmpeg can't block on a full pipe while we read stdout
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr:
        process = subprocess.Popen(
            [exe, "-progress", "pipe:1", "-nostats", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit():
                progress(int(value) / 1_000_000)
        returncode = process.wait()
        if returncode != 0:
            stderr.seek(0)
            message = stderr.read().strip()
            if message:
                print(message)
            return False
    return True


def _probe(video_path: Path) -> str:
    """``ffmpeg -i``'s description of a file (its stderr), or "" without ffmpeg.

    Used instead of ffprobe, which imageio-ffmpeg doesn't ship.
    """
    exe = ffmpeg_exe()
    if exe is None:
        return ""
    result = subprocess.run(
        [exe, "-hide_banner", "-nostdin", "-i", str(video_path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stderr if isinstance(result.stderr, str) else ""


def probe_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream, or (0, 0) if unknown.

    The reported size is the coded size, matching ffprobe's ``stream=width,height``.
    """
    match = _VIDEO_DIMENSIONS.search(_probe(video_path))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def probe_audio_codec(video_path: Path) -> str | None:
    """Codec of the first audio stream (e.g. ``aac``, ``opus``), or None if there's none."""
    match = _AUDIO_CODEC.search(_probe(video_path))
    return match.group(1) if match else None


def probe_duration(video_path: Path) -> float:
    """Length of a video in seconds from ``ffmpeg -i``'s ``Duration:`` line, or 0 if unknown."""
    match = _DURATION.search(_probe(video_path))
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
