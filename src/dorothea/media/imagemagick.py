"""Finding ImageMagick (optional: colour extraction and ``image-options``).

ImageMagick 7 installs ``magick``, which produces the same bytes as expose.sh's ``convert``
without IM7's "convert is deprecated" warning (which ``magick convert`` prints too). It's
stricter about order: operators such as ``-auto-orient`` must come after the input image.
ImageMagick 6 only has ``convert``, but so does Windows (``System32\\convert.exe``, a disk
format tool), so a ``convert`` is only used after ``convert -version`` says it's ImageMagick
(#19, upstream Jack000/Expose#50).
"""

import functools
import shutil
import subprocess


@functools.cache
def imagemagick_command() -> tuple[str, ...] | None:
    """The command that runs ImageMagick's ``convert``, or None if it isn't installed."""
    magick = shutil.which("magick")
    if magick:
        return (magick,)
    convert = shutil.which("convert")
    if convert and _is_imagemagick(convert):
        return (convert,)
    return None


def _is_imagemagick(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return "ImageMagick" in (result.stdout if isinstance(result.stdout, str) else "")
