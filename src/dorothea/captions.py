"""Caption and gallery files: a photo's ``.txt``/``.md`` with optional ``key: value`` metadata
(#17), and a gallery's ``gallery.yml`` or expose.sh's ``metadata.txt`` (#46).

Captions are read two ways (#52):

- a ``.md`` file starting with a ``---`` line has **YAML front matter**, read like
  ``_config.yml`` (the Jekyll/Hugo/Obsidian convention);
- anything else (``.txt`` captions, ``.md`` without front matter, and every caption with
  ``--legacy``) is read **line by line** as expose.sh reads it: everything after the first colon
  is the value. Some expose.sh lines mean something else in YAML (``textcolor: #ff9518``,
  ``polygon:[…]``, ``title: Iceland: day 1``), so a front matter YAML can't read, or would read
  with a value missing, falls back to this reading, with a warning saying what to quote.

Lines starting with ``#`` are comments in both (expose.sh ignores them too: a ``{{# …}}``
placeholder never exists).
"""

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dorothea.yamlfile import YamlError, load_mapping

_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"

# A metadata/caption separator; expose.sh only accepts "---" exactly, so "--- " (trailing
# spaces, invisible in most editors) used to leak the metadata into the caption (#17)
_SEPARATOR = re.compile(r"---[ \t]*")
# A "key: value" metadata line (keys like title, image-options, color1, polygon)
_METADATA_LINE = re.compile(r"\s*[\w-]+\s*:")

# A gallery's settings, first found wins (#46): YAML, else expose.sh's key: value lines
GALLERY_FILES = ("gallery.yml", "gallery.yaml", "metadata.txt")


def is_comment(line: str) -> bool:
    """A ``# …`` line in metadata."""
    return line.lstrip().startswith("#")


def is_separator(line: str) -> bool:
    """A ``---`` line between a caption's metadata and its text."""
    return bool(_SEPARATOR.fullmatch(line))


def caption_file(media: Path, legacy: bool = False) -> Path | None:
    """The caption file for a photo/video: same name with .md, else .txt (#52).

    With ``legacy`` the other way round, as expose.sh looks for them.
    """
    for ext in (".txt", ".md") if legacy else (".md", ".txt"):
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
        if line.strip()
        and not _SEPARATOR.fullmatch(line)
        and not _METADATA_LINE.match(line)
        and not is_comment(line)
    ]
    return "\n".join(head), "\n".join(lines[end + 1 :]), ignored


def metadata_values(text: str) -> dict[str, str]:
    """``key: value`` pairs from metadata text (a caption's head or a ``metadata.txt``)."""
    values = {}
    for line in text.split("\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip() and value.strip() and not is_comment(line):
            values.setdefault(key.strip(), value.strip())
    return values


def gallery_file(directory: Path) -> Path | None:
    """The gallery's settings file: the first of ``GALLERY_FILES`` that exists."""
    for name in GALLERY_FILES:
        if (candidate := directory / name).is_file():
            return candidate
    return None


def as_text(value: Any) -> str:
    """A YAML value as metadata text: ``true``, ``32.5``, and lists/mappings (theme1's
    ``polygon``) as the JSON themes read."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


@functools.cache
def _read_yaml_gallery(path: Path, _mtime_ns: int) -> dict[str, str]:
    """A ``gallery.yml``'s values as text (cached per version, so a broken file warns once)."""
    try:
        values, _lines = load_mapping(read_text_file(path))
    except YamlError as e:
        print(f"\n\tWarning: ignoring {path.parent.name}/{path.name}: {e}")
        return {}
    return {key: text for key, value in values.items() if (text := as_text(value))}


def gallery_metadata(directory: Path) -> dict[str, str]:
    """A gallery's settings (from ``gallery.yml``, else ``metadata.txt``), key → value text."""
    path = gallery_file(directory)
    if path is None:
        return {}
    if path.suffix == ".txt":
        return metadata_values(read_text_file(path))
    return dict(_read_yaml_gallery(path, path.stat().st_mtime_ns))


def gallery_metadata_text(directory: Path) -> str:
    """A gallery's settings as ``key: value`` lines, for reading like a caption's metadata.

    ``metadata.txt`` is returned as it is, so pages are built exactly as before; a
    ``gallery.yml`` is written out as one line per key (template values are one line anyway).
    """
    path = gallery_file(directory)
    if path is None or path.suffix == ".txt":
        return read_text_file(path) if path else ""
    return "\n".join(
        f"{key}: {' '.join(value.split())}" for key, value in gallery_metadata(directory).items()
    )


def metadata_flag(metadata: dict[str, str], key: str, default: bool) -> bool:
    """A yes/no ``key:`` from metadata (``true``/``yes``/``on``, ``false``/``no``/``off``,
    any case), else ``default``."""
    value = metadata.get(key, "").strip().lower()
    if value in ("true", "yes", "on"):
        return True
    if value in ("false", "no", "off"):
        return False
    return default


@dataclass
class Caption:
    """A caption file, read (see the module docstring for the two ways)."""

    head: str = ""  # its metadata as `key: value` lines, as templates read them
    values: dict[str, str] = field(default_factory=dict)  # key -> value text
    body: str = ""  # the Markdown caption
    front_matter: bool = False  # read as YAML front matter
    lines: dict[str, int] = field(default_factory=dict)  # key -> line in the file (front matter)
    ignored: list[str] = field(default_factory=list)  # text before the metadata (line by line)
    # Why front matter was read the old way: (line in the file or None, message)
    warnings: list[tuple[int | None, str]] = field(default_factory=list)

    def warning_lines(self, name: str) -> list[str]:
        """The warnings as ``01 falls.md line 3: …``."""
        return [f"{name}{f' line {line}' if line else ''}: {text}" for line, text in self.warnings]


def _front_matter(lines: list[str]) -> int | None:
    """The index of the line closing a front matter block that opens on the first line."""
    if not lines or not _SEPARATOR.fullmatch(lines[0]):
        return None
    return next((i for i in range(1, len(lines)) if _SEPARATOR.fullmatch(lines[i])), None)


def parse_caption(text: str, name: str = "", front_matter: bool = True) -> Caption:
    """Read a caption file's text; ``name`` (e.g. ``01 falls.md``) decides whether it can have
    YAML front matter (``.md`` only, and not with ``--legacy``: ``front_matter=False``)."""
    text = text.removeprefix(_BOM).replace("\r", "").rstrip("\n")
    lines = text.split("\n")
    close = _front_matter(lines) if front_matter and name.lower().endswith(".md") else None
    if close is None:
        head, body, ignored = split_caption(text)
        return Caption(head, metadata_values(head), body, ignored=ignored)

    block = "\n".join(lines[1:close])
    body = "\n".join(lines[close + 1 :])
    warnings: list[tuple[int | None, str]] = []
    try:
        loaded, key_lines = load_mapping(block)
    except YamlError as e:
        # the block starts on the file's second line
        warnings.append((e.line + 1 if e.line else None, f"not valid YAML ({e.problem})"))
        loaded, key_lines = {}, {}
    values = {key: shown for key, value in loaded.items() if (shown := as_text(value))}

    # What the old reading makes of the same lines: a value it has and YAML drops (`#…` read as
    # a comment) is almost certainly a mistake, not an intention
    if not warnings:
        for key, value in metadata_values(block).items():
            if key not in values:
                warnings.append((key_lines.get(key, 0) + 1, (
                    f"'{key}: {value}' reads as empty in YAML; quote the value: "
                    f'{key}: "{value}"'
                )))  # fmt: skip
    if warnings:
        warnings.append((None, "read line by line (as a .txt caption) until that's fixed"))
        head, body, ignored = split_caption(text)
        return Caption(head, metadata_values(head), body, ignored=ignored, warnings=warnings)

    head = "\n".join(f"{key}: {' '.join(value.split())}" for key, value in values.items())
    lines_in_file = {key: line + 1 for key, line in key_lines.items()}
    return Caption(head, values, body, front_matter=True, lines=lines_in_file)


def embedded_as_caption(title: str, description: str) -> Caption:
    """The caption for a photo with no caption file, from its own title/description (#51).

    All or nothing: a caption file, if there is one, is used instead, title included. The title
    is the photo's ``title`` (feeds, themes' ``{{title}}``) and a heading above the description,
    so both show in every theme.
    """
    if not (title or description):
        return Caption()
    title = " ".join(title.split())
    parts = [f"## {title}"] if title else []
    body = "\n\n".join([*parts, description] if description else parts)
    values = {"title": title} if title else {}
    return Caption(f"title: {title}" if title else "", values, body)


def read_caption(path: Path, front_matter: bool = True) -> Caption:
    """``parse_caption`` for a file (empty if it's missing or not UTF-8 text)."""
    return parse_caption(read_text_file(path), path.name, front_matter)
