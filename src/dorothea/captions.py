"""Caption files: a photo's ``.txt``/``.md`` with optional ``key: value`` metadata (#17)."""

import re
from pathlib import Path

_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"

# A metadata/caption separator; expose.sh only accepts "---" exactly, so "--- " (trailing
# spaces, invisible in most editors) used to leak the metadata into the caption (#17)
_SEPARATOR = re.compile(r"---[ \t]*")
# A "key: value" metadata line (keys like title, image-options, color1, polygon)
_METADATA_LINE = re.compile(r"\s*[\w-]+\s*:")


def caption_file(media: Path) -> Path | None:
    """The caption file for a photo/video: same name with .txt, else .md."""
    for ext in (".txt", ".md"):
        candidate = media.parent / (media.stem + ext)
        if candidate != media and candidate.exists():
            return candidate
    return None


def read_text_file(path: Path) -> str:
    """Return a caption/metadata file's text, or "" if it's missing or not UTF-8 text.

    expose.sh only reads files that ``file`` reports as text; a binary or mis-encoded
    ``.txt`` is skipped rather than aborting the build.
    """
    try:
        # utf-8-sig drops the byte-order mark Windows editors (Notepad) often add
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError, OSError:
        print(f"\n\tSkipping {path.name}: not a UTF-8 text file")
        return ""


def split_caption(text: str) -> tuple[str, str, list[str]]:
    """Split a caption file into (metadata, Markdown caption, ignored lines), like expose.sh.

    Lines up to and including the second ``---`` (or the only one) are metadata, the rest is
    the caption. ``ignored`` lists non-blank metadata lines that aren't ``key: value``, which
    are dropped: usually caption text put before the metadata block by mistake.
    """
    text = text.removeprefix(_BOM).replace("\r", "").rstrip("\n")
    lines = text.split("\n")
    separators = [idx for idx, line in enumerate(lines) if _SEPARATOR.fullmatch(line)]
    if not separators:
        return "", text, []
    end = separators[1] if len(separators) >= 2 else separators[0]
    head = lines[: end + 1]
    ignored = [
        line
        for line in head
        if line.strip() and not _SEPARATOR.fullmatch(line) and not _METADATA_LINE.match(line)
    ]
    return "\n".join(head), "\n".join(lines[end + 1 :]), ignored


def metadata_values(text: str) -> dict[str, str]:
    """``key: value`` pairs from metadata text (a caption's head or a ``metadata.txt``)."""
    values = {}
    for line in text.split("\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip() and value.strip():
            values.setdefault(key.strip(), value.strip())
    return values
