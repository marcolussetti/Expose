"""Persistent build cache.

Stored as ``.dorothea-cache.json`` in the gallery root (hidden and outside ``_site``, so it is
never scanned or published). It holds:

- **analysis**: colour palette and dimensions per source file, so unchanged photos skip
  palette extraction (the slowest part of reading a gallery).
- **outputs**: a fingerprint per generated file: the source file's stat plus a hash of every
  setting that affects the bytes (resolution, quality, per-post options...). A changed
  fingerprint means the output is rebuilt even if it already exists.
"""

import contextlib
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, NamedTuple

CACHE_NAME = ".dorothea-cache.json"
CACHE_VERSION = 1


class Fingerprint(NamedTuple):
    """What an output was built from: source stat and a hash of the relevant settings."""

    source: list[int]
    settings: str


def source_stat(path: Path) -> list[int]:
    """Identity of a source for change detection: ``[mtime_ns, size]``.

    For a directory (image sequence) this is ``[newest mtime_ns, entry count]`` over the
    directory and its files, so adding, removing or editing a frame changes it.
    """
    try:
        st = path.stat()
    except OSError:
        return [0, 0]
    if not path.is_dir():
        return [st.st_mtime_ns, st.st_size]
    newest, count = st.st_mtime_ns, 0
    for entry in os.scandir(path):
        count += 1
        with contextlib.suppress(OSError):
            newest = max(newest, entry.stat().st_mtime_ns)
    return [newest, count]


def settings_hash(**settings: Any) -> str:
    """Stable short hash of the settings that determine an output's bytes."""
    blob = json.dumps(settings, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class BuildCache:
    """Thread-safe JSON cache of analysis results and output fingerprints."""

    def __init__(self, topdir: Path):
        """Load the cache for ``topdir`` (an unreadable or old-format file starts empty)."""
        self.topdir = Path(topdir)
        self.path = self.topdir / CACHE_NAME
        self._lock = threading.Lock()
        self._dirty = False
        self._analysis: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != CACHE_VERSION:
                raise ValueError(f"unsupported version {data.get('version')!r}")
            self._analysis = dict(data.get("analysis", {}))
            self._outputs = dict(data.get("outputs", {}))
        except (OSError, ValueError, AttributeError) as e:
            print(f"Ignoring unreadable build cache {self.path.name}: {e}")
            self._analysis, self._outputs = {}, {}

    def key(self, path: Path) -> str:
        """Cache key for a path: relative to the gallery root when possible."""
        try:
            return Path(path).relative_to(self.topdir).as_posix()
        except ValueError:
            return str(path)

    # --- analysis ---

    def get_analysis(self, path: Path, stat: list[int], key: str) -> tuple[list, int, int] | None:
        """Return cached (palette, width, height) if the source and settings are unchanged."""
        with self._lock:
            entry = self._analysis.get(self.key(path))
        if not entry or entry.get("stat") != stat or entry.get("key") != key:
            return None
        return list(entry["palette"]), int(entry["width"]), int(entry["height"])

    def put_analysis(
        self, path: Path, stat: list[int], key: str, palette: list, width: int, height: int
    ) -> None:
        """Record analysis results for a source file."""
        entry = {"stat": stat, "key": key, "palette": palette, "width": width, "height": height}
        with self._lock:
            self._analysis[self.key(path)] = entry
            self._dirty = True

    # --- outputs ---

    def get_output(self, output: Path) -> Fingerprint | None:
        """Return the fingerprint an output was last built with, if known."""
        with self._lock:
            entry = self._outputs.get(self.key(output))
        if not entry:
            return None
        return Fingerprint(list(entry["source"]), entry["settings"])

    def put_output(self, output: Path, fingerprint: Fingerprint) -> None:
        """Record the fingerprint of a freshly built (or adopted) output."""
        with self._lock:
            self._outputs[self.key(output)] = {
                "source": fingerprint.source,
                "settings": fingerprint.settings,
            }
            self._dirty = True

    def drop_output(self, output: Path) -> None:
        """Forget an output that was deleted."""
        with self._lock:
            if self._outputs.pop(self.key(output), None) is not None:
                self._dirty = True

    def save(self) -> None:
        """Write the cache atomically if anything changed. Failures only warn."""
        with self._lock:
            if not self._dirty:
                return
            data = {
                "version": CACHE_VERSION,
                "analysis": self._analysis,
                "outputs": self._outputs,
            }
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
                os.replace(tmp, self.path)
                self._dirty = False
            except OSError as e:
                print(f"Could not save build cache: {e}")
