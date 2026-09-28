"""``dorothea check`` (#46): find mistakes in gallery files and captions before a build.

The config itself is checked by ``Config.validate()``; this looks at every gallery's
``gallery.yml`` / ``metadata.txt`` and every caption's metadata:

- keys neither Dorothea nor the theme uses, with the key they're probably a typo of. The theme's
  keys are the ``{{placeholders}}`` in its ``post-template.html``, so custom themes are covered
  without declaring anything;
- keys in the wrong place (``sort:`` in a photo's caption only works for a whole gallery);
- values Dorothea can't use (``sort: random``, ``date: next tuesday``, ``exif: maybe``);
- caption text before the metadata block, keys set twice, captions that match no photo, and
  gallery files that are ignored (in a folder that isn't a gallery, or next to a gallery.yml).
"""

import contextlib
import difflib
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dorothea.builder import UNSAFE_CSS_VALUE
from dorothea.captions import (
    GALLERY_FILES,
    caption_file,
    gallery_file,
    is_comment,
    read_caption,
    read_text_file,
)
from dorothea.config import CAPTION_POSITIONS, Config
from dorothea.feed import parse_date
from dorothea.scanner import Scanner
from dorothea.sorting import SORT_MODES
from dorothea.themes import resolve_theme_dir
from dorothea.yamlfile import YamlError, load_mapping

_FLAGS = ("true", "false", "yes", "no", "on", "off")


def _flag(value: str) -> str:
    return "" if value.lower() in _FLAGS else "must be true or false"


def _one_of(choices: tuple[str, ...]) -> Callable[[str], str]:
    def check(value: str) -> str:
        return "" if value in choices else f"must be one of {', '.join(choices)}"

    return check


def _date(value: str) -> str:
    return "" if parse_date(value) else "isn't a date Dorothea can read; use YYYY-MM-DD"


def _css(value: str) -> str:
    return "" if not UNSAFE_CSS_VALUE & set(value) else "isn't a CSS colour"


def _exif(value: str) -> str:
    return "" if value.lower() in (*_FLAGS, "icon", "caption") else "must be false, icon or caption"


@dataclass(frozen=True)
class Key:
    """One of Dorothea's own metadata keys."""

    gallery_only: bool = False
    check: Callable[[str], str] | None = None  # the problem with a value, or ""


DOROTHEA_KEYS = {
    "title": Key(),
    "textbackground": Key(check=_css),
    "exif": Key(check=_exif),
    **{name: Key() for name in ("camera", "lens", "focal_length", "aperture")},
    **{name: Key() for name in ("shutter_speed", "iso")},
    **{name: Key() for name in ("image-options", "video-options", "video-filters")},
    "date": Key(check=_date),
    "description": Key(gallery_only=True),
    "feed": Key(gallery_only=True, check=_flag),
    "download": Key(gallery_only=True, check=_flag),
    "sort": Key(gallery_only=True, check=_one_of(SORT_MODES)),
    "caption_position": Key(check=_one_of(CAPTION_POSITIONS)),
}
# From the photo's palette, but a caption can set them too
PALETTE_KEYS = {f"color{n}" for n in range(1, 8)} | {"textcolor", "backgroundcolor"}


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int | None
    message: str

    def show(self, topdir: Path) -> str:
        try:
            where = self.path.relative_to(topdir).as_posix()
        except ValueError:
            where = str(self.path)
        return f"{where}:{self.line}: {self.message}" if self.line else f"{where}: {self.message}"


def theme_keys(theme_dir: Path) -> set[str]:
    """The keys a theme reads from metadata: the placeholders in its post template."""
    try:
        template = (theme_dir / "post-template.html").read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(re.findall(r"\{\{([\w-]+)(?::[^}]*)?\}\}", template))


class Checker:
    """Checks one site; ``run()`` returns the problems found, in folder order."""

    def __init__(self, topdir: Path, config: Config):
        self.topdir = Path(topdir)
        self.config = config
        self.known = set(DOROTHEA_KEYS) | PALETTE_KEYS
        with contextlib.suppress(FileNotFoundError):
            self.known |= theme_keys(resolve_theme_dir(config["theme_dir"], self.topdir))
        self.problems: list[Problem] = []
        self.galleries = self.captions = 0

    def run(self) -> list[Problem]:
        scanner = Scanner(self.topdir, self.topdir, self.config, dry_run=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()):  # its progress dots
                scanner.scan_directories()
        finally:
            scanner.cleanup()
        for folder, kind in zip(scanner.paths, scanner.nav_type, strict=True):
            if kind >= 1:
                self.galleries += 1
                self._gallery(folder, scanner)
            elif (unused := gallery_file(folder)) is not None:
                self._add(unused, None, "not used: this folder only holds other galleries")
        return self.problems

    def _add(self, path: Path, line: int | None, message: str) -> None:
        self.problems.append(Problem(path, line, message))

    def _gallery(self, folder: Path, scanner: Scanner) -> None:
        source = gallery_file(folder)
        if source is not None:
            for name in GALLERY_FILES[GALLERY_FILES.index(source.name) + 1 :]:
                if (folder / name).is_file():
                    self._add(folder / name, None, f"not used: {source.name} is read instead")
            if source.suffix == ".txt":
                self._lines(source, read_text_file(source).split("\n"), 1, gallery=True)
            else:
                self._yaml(source)

        keyword = self.config.get("sequence_keyword", "")
        media = {f.stem for f in scanner._media_files(folder)}
        media |= {d.stem for d in folder.iterdir() if d.is_dir() and keyword and keyword in d.name}
        for text_file in sorted(folder.iterdir()):
            if (
                text_file.suffix.lower() not in (".txt", ".md")
                or text_file.name.startswith(("_", "."))
                or text_file.name in GALLERY_FILES
                or not text_file.is_file()
            ):
                continue
            if text_file.stem not in media:
                self._add(text_file, None, f"no photo or video named {text_file.stem}.*, so "
                          "this caption isn't shown")  # fmt: skip
                continue
            legacy = bool(self.config.get("legacy", False))
            # the photo's caption, as the build picks it (.md over .txt, the reverse with legacy)
            used = caption_file(folder / f"{text_file.stem}.photo", legacy=legacy)
            if used is not None and used != text_file:
                self._add(text_file, None, f"not used: {used.name} is read instead")
                continue
            self.captions += 1
            caption = read_caption(text_file, front_matter=not legacy)
            for line, message in caption.warnings:
                self._add(text_file, line, message)
            if caption.front_matter:
                for key, value in caption.values.items():
                    self._key(text_file, caption.lines.get(key), key, value, gallery=False)
                continue
            for line in caption.ignored:
                number = caption.head.split("\n").index(line) + 1
                self._add(text_file, number, "not shown: text before the metadata's closing "
                          "'---' is read as metadata; put the caption after it")  # fmt: skip
            self._lines(text_file, caption.head.split("\n"), 1, gallery=False)

    def _lines(self, path: Path, lines: list[str], first: int, gallery: bool) -> None:
        """``key: value`` metadata lines (a caption's head or a metadata.txt)."""
        seen: dict[str, int] = {}
        for number, line in enumerate(lines, first):
            key, sep, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if not sep or not key or not value or is_comment(line) or line.startswith("---"):
                continue
            if key in seen:
                self._add(path, number, f"{key} is set twice; line {seen[key]}'s is used")
                continue
            seen[key] = number
            self._key(path, number, key, value, gallery)

    def _yaml(self, path: Path) -> None:
        try:
            values, lines = load_mapping(read_text_file(path))
        except YamlError as e:
            self._add(path, None, f"can't be read, so it's ignored: {e}")
            return
        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, (list, dict)) and key != "polygon":
                self._add(path, lines.get(key), f"{key} should be a single value, not a list")
                continue
            text = value if isinstance(value, str) else str(value).lower()
            self._key(path, lines.get(key), key, text, gallery=True)

    def _key(self, path: Path, line: int | None, key: str, value: str, gallery: bool) -> None:
        if key not in self.known:
            close = difflib.get_close_matches(key, sorted(self.known), n=1, cutoff=0.75)
            hint = f"; did you mean {close[0]}?" if close else " (Dorothea and the theme ignore it)"
            self._add(path, line, f"unknown key {key}{hint}")
            return
        spec = DOROTHEA_KEYS.get(key)
        if spec is None:
            return
        if spec.gallery_only and not gallery:
            self._add(path, line, f"{key} only works for a whole gallery: put it in gallery.yml")
            return
        if spec.check and (problem := spec.check(value)):
            self._add(path, line, f"{key}: {value!r} {problem}")


def check_site(topdir: Path, config: Config) -> Checker:
    """Check every gallery file and caption under ``topdir``; see ``Checker.problems``."""
    checker = Checker(topdir, config)
    checker.run()
    return checker


__all__ = ["DOROTHEA_KEYS", "Checker", "Problem", "check_site", "theme_keys"]
