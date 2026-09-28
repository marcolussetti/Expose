"""``dorothea --convert-config`` (#46, #52): expose.sh's files → Dorothea's.

``_config.sh`` becomes ``_config.yml``, each ``metadata.txt`` a ``gallery.yml``, and each ``.txt``
caption a ``.md`` with YAML front matter. A new file is only written, and the original only
deleted, once reading the new file gives exactly the same settings (and caption); anything that
can't be converted is left as it was, with a note saying why.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dorothea.captions import (
    GALLERY_FILES,
    as_text,
    is_comment,
    is_separator,
    metadata_values,
    parse_caption,
    read_text_file,
    split_caption,
)
from dorothea.config import (
    CONFIG_FILES,
    DEFAULT_CONFIG,
    ConfigError,
    find_config_file,
    parse_config_sh,
    read_config_file,
)
from dorothea.yamlfile import SCHEMA_URL, YamlError, dump_mapping, load_mapping

# At the top of a converted _config.yml: where the settings are described, and the schema that
# gives editors (VS Code's YAML extension) completion and checks
CONFIG_HEADER = (
    "# Dorothea settings: https://dorothea.readthedocs.io/configuration/\n"
    f"# yaml-language-server: $schema={SCHEMA_URL}\n"
)

_KEY = re.compile(r"[\w-]+")


@dataclass
class Report:
    written: list[str] = field(default_factory=list)  # "Wrote … (from …)"
    notes: list[str] = field(default_factory=list)  # left as they were, and why
    errors: list[str] = field(default_factory=list)
    captions: int = 0  # .txt captions converted to .md


def _yaml_pair(key: str, value: str) -> str:
    """``key: value`` as it was written when YAML reads it back the same; quoted otherwise
    (``polygon:[…]`` JSON, text with `` #`` or a second ``: ``)."""
    try:
        loaded = load_mapping(f"{key}: {value}\n")[0].get(key)
    except YamlError:
        loaded = None
    if as_text(loaded) == value:
        return f"{key}: {value}"
    return dump_mapping({key: value}).rstrip("\n")


def metadata_to_yaml(text: str) -> str:
    """A ``metadata.txt``'s ``key: value`` lines as a ``gallery.yml`` with the same settings.

    Comments and blank lines are kept; lines that aren't settings, and keys set again (Dorothea
    reads the first), become comments rather than being lost.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in text.replace("\r", "").split("\n"):
        stripped = line.strip()
        if not stripped or is_comment(line):
            out.append(stripped)
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.fullmatch(key) or not value or key in seen:
            out.append(f"# {stripped}")
            continue
        seen.add(key)
        out.append(_yaml_pair(key, value))
    return "\n".join(out).strip("\n") + "\n"


def _yaml_settings(text: str) -> dict[str, str]:
    """What Dorothea reads from a gallery.yml: its values as text (as captions.gallery_metadata)."""
    values, _lines = load_mapping(text)
    return {key: as_text(value) for key, value in values.items() if as_text(value)}


def convert_gallery_file(source: Path, report: Report, topdir: Path) -> None:
    """``metadata.txt`` → ``gallery.yml`` next to it, deleting the original."""
    where = source.parent.relative_to(topdir).as_posix()
    if any((source.parent / name).exists() for name in GALLERY_FILES if name != source.name):
        report.notes.append(
            f"{where}/metadata.txt: left as it is; the folder already has a gallery.yml"
        )
        return
    text = read_text_file(source)
    converted = metadata_to_yaml(text)
    try:
        same = _yaml_settings(converted) == metadata_values(text)
    except YamlError:
        same = False
    if not same:
        report.notes.append(
            f"{where}/metadata.txt: left as it is; it couldn't be converted without changing it"
        )
        return
    (source.parent / "gallery.yml").write_text(converted, encoding="utf-8")
    source.unlink()
    report.written.append(f"{where}/gallery.yml (from metadata.txt, now deleted)")


def convert_config_file(topdir: Path, source: Path, report: Report) -> None:
    """``_config.sh`` → ``_config.yml``, deleting the original if every line converted."""
    target = topdir / "_config.yml"
    if any((topdir / name).exists() for name in CONFIG_FILES if not name.endswith(".sh")):
        report.notes.append(f"{source.name}: left as it is; {target.name} already exists")
        return
    values, warnings = parse_config_sh(source.read_text(encoding="utf-8"))
    text = dump_mapping(values, header=CONFIG_HEADER)
    if load_mapping(text)[0] != values:  # pragma: no cover - dump_mapping round-trips (tested)
        report.errors.append(f"{source.name}: couldn't be converted without changing it")
        return
    target.write_text(text, encoding="utf-8")
    if warnings:
        report.written.append(f"{target.name} (from {source.name})")
        report.notes.extend(f"{source.name}: {warning}" for warning in warnings)
        report.notes.append(
            f"{source.name}: kept, since the lines above couldn't be converted; "
            f"{target.name} is used from now on"
        )
    else:
        source.unlink()
        report.written.append(f"{target.name} (from {source.name}, now deleted)")


def caption_to_markdown(text: str) -> str:
    """A ``.txt`` caption as a ``.md``: its metadata as YAML front matter, then the caption.

    A caption without metadata stays as it is. Caption text put before the metadata (which
    wasn't shown) becomes a comment, like other lines that aren't settings.
    """
    text = text.replace("\r", "").rstrip("\n")
    head, body, _ignored = split_caption(text)
    if not head:
        return text + "\n"
    settings = "\n".join(line for line in head.split("\n") if not is_separator(line))
    front = metadata_to_yaml(settings) if settings.strip() else ""
    return "---\n" + front + "---\n" + (body + "\n" if body else "")


def convert_caption(source: Path, report: Report, topdir: Path) -> None:
    """``NN photo.txt`` → ``NN photo.md`` with front matter, deleting the original."""
    where = source.relative_to(topdir).as_posix()
    target = source.with_suffix(".md")
    if target.exists():
        report.notes.append(
            f"{where}: left as it is; {target.name} already exists (and is the caption shown)"
        )
        return
    text = read_text_file(source)
    converted = caption_to_markdown(text)
    old = parse_caption(text, source.name)
    new = parse_caption(converted, target.name)
    if new.warnings or new.values != old.values or new.body != old.body:
        report.notes.append(f"{where}: left as it is; it couldn't be converted without changing it")
        return
    target.write_text(converted, encoding="utf-8")
    source.unlink()
    report.captions += 1


def _legacy(topdir: Path, config_source: Path | None) -> bool:
    """Whether the site's config (after converting it) asks for expose.sh's reading."""
    source = config_source if config_source and config_source.exists() else None
    try:
        source = source or find_config_file(topdir)
        return source is not None and read_config_file(source)[0].get("legacy") is True
    except ConfigError, OSError:  # an unreadable config is reported by the build, not here
        return False


def _caption_files(folder: Path, files: list[str], keyword: str) -> list[Path]:
    """The ``.txt`` captions in ``folder``: named after one of its photos, videos or sequences."""
    from dorothea.scanner import Scanner

    media = {f.stem for f in Scanner._media_files(folder)}
    media |= {Path(d).stem for d in os.listdir(folder) if keyword and keyword in d}
    return [
        folder / name
        for name in sorted(files)
        if name.endswith(".txt")
        and not name.startswith(("_", "."))
        and name not in GALLERY_FILES
        and Path(name).stem in media
    ]


def convert_site(topdir: Path, config_source: Path | None = None) -> Report:
    """Convert ``topdir``'s ``_config.sh`` (or ``config_source``), every ``metadata.txt``, and
    every ``.txt`` caption (unless the site uses ``legacy: true``)."""
    report = Report()
    source = config_source or topdir / "_config.sh"
    if source.exists():
        convert_config_file(topdir, source, report)
    elif config_source is not None:
        report.errors.append(f"{config_source} not found")

    captions = not _legacy(topdir, config_source)
    keyword = str(DEFAULT_CONFIG["sequence_keyword"])
    skipped = False
    for root, dirs, files in os.walk(topdir):
        dirs[:] = sorted(d for d in dirs if not d.startswith(("_", ".")))
        folder = Path(root)
        if "metadata.txt" in files:
            convert_gallery_file(folder / "metadata.txt", report, topdir)
        for caption in _caption_files(folder, files, keyword):
            if captions:
                convert_caption(caption, report, topdir)
            else:
                skipped = True
    if report.captions:
        report.written.append(f"{report.captions} .md caption(s) (from .txt, now deleted)")
    if skipped:
        report.notes.append(
            ".txt captions: left as they are, since the site uses legacy: true (expose.sh's "
            "reading, which doesn't understand .md front matter)"
        )
    return report
