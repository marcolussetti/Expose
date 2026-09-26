"""FFmpeg binary resolution and invocation helpers.

A system ``ffmpeg`` on PATH is preferred (keeps output identical to expose.sh, which uses
whatever is on PATH). Otherwise the static binary bundled with ``imageio-ffmpeg`` is used,
so a plain ``pip``/``uv`` install works without system packages.
"""

import re
import shutil
import subprocess
from pathlib import Path

# First "WxH" after "Video:" on an ffmpeg stream line. Word boundaries keep codec tags
# such as "0x31637661" from matching.
_VIDEO_DIMENSIONS = re.compile(r"Stream #.*?: Video: .*?\b(\d{2,5})x(\d{2,5})\b")


def ffmpeg_exe() -> str | None:
    """Return the ffmpeg executable to use, or None if none is available."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError, RuntimeError:
        return None


def run_ffmpeg(args: list[str]) -> bool:
    """Run ffmpeg with the given arguments (excluding the executable).

    Stderr is captured and printed only when ffmpeg fails.

    Returns:
        True if ffmpeg exited successfully.
    """
    exe = ffmpeg_exe()
    if exe is None:
        print("ffmpeg not found; skipping video step")
        return False
    result = subprocess.run([exe, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else ""
        if stderr.strip():
            print(stderr.strip())
        return False
    return True


def probe_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream, or (0, 0) if unknown.

    Parses ``ffmpeg -i`` output instead of using ffprobe, which imageio-ffmpeg doesn't ship.
    The reported size is the coded size, matching ffprobe's ``stream=width,height``.
    """
    exe = ffmpeg_exe()
    if exe is None:
        return 0, 0
    result = subprocess.run(
        [exe, "-hide_banner", "-nostdin", "-i", str(video_path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    match = _VIDEO_DIMENSIONS.search(stderr)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))
