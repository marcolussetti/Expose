"""Whole-gallery downloads (#9).

With ``download_album``, each gallery gets ``_site/<gallery>/<gallery>.zip`` holding its
originals (an image sequence's frames in a folder of their own) plus ``readme.txt``. Pages link
it through the theme's optional ``album-download.html`` (``{{album_download}}``). A gallery's
``metadata.txt`` can opt out (``download: false``) or in (``download: true``).
"""

from pathlib import Path

from dorothea.captions import metadata_flag, metadata_values, read_text_file
from dorothea.utils import sequence_frames, slug_or_fallback


def album_enabled(default: bool, gallery_dir: Path) -> bool:
    """Whether a gallery gets a zip: ``download:`` in its metadata.txt, else the setting."""
    metadata = metadata_values(read_text_file(gallery_dir / "metadata.txt"))
    return metadata_flag(metadata, "download", default)


def album_zip_name(gallery_url: str, site_title: str) -> str:
    """File name of a gallery's zip: its folder's slug, or the site title's for a site that is
    a single gallery (whose page is ``_site`` itself)."""
    name = gallery_url.rsplit("/", 1)[-1]
    if name in ("", "."):
        name = slug_or_fallback(site_title, "album")
    return f"{name}.zip"


def album_members(files: list[Path], types: list[int]) -> list[tuple[str, Path]]:
    """``(name in the zip, source)`` for a gallery's items, in gallery order.

    Photos and videos keep their file names (unique within the gallery folder); a sequence's
    frames go in a folder named after the sequence.
    """
    members: list[tuple[str, Path]] = []
    for path, kind in zip(files, types, strict=True):
        if kind == 2:
            members += [(f"{path.name}/{frame.name}", frame) for frame in sequence_frames(path)]
        else:
            members.append((path.name, path))
    return members


def human_size(size: int) -> str:
    """Size for people, in decimal units like file managers show: ``840 KB``, ``1.2 GB``."""
    if size < 1000:
        return f"{size} bytes"
    value, unit = size / 1000, "KB"
    for bigger in ("MB", "GB"):
        if value < 1000:
            break
        value, unit = value / 1000, bigger
    return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
