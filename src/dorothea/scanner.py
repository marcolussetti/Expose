"""Directory and file scanning.

Scans the working directory to build navigation structures and
process images/videos to extract metadata.
"""

import mimetypes
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from dorothea.cache import BuildCache, settings_hash, source_stat
from dorothea.config import Config
from dorothea.media.colors import ColorExtractor
from dorothea.media.exif import read_photo_info
from dorothea.media.image import ImageProcessor
from dorothea.media.video import VideoProcessor
from dorothea.progress import Reporter
from dorothea.sorting import SORT_MODES, sort_items
from dorothea.utils import (
    IMAGE_EXTENSIONS,
    sequence_frames,
    site_path,
    slug_or_fallback,
    strip_numeric_prefix,
    unique_slugs,
)

# Video extensions (from expose.py)
VIDEO_EXTENSIONS = [
    "3g2",
    "3gp",
    "3gp2",
    "asf",
    "avi",
    "dvr-ms",
    "exr",
    "ffindex",
    "ffpreset",
    "flv",
    "gxf",
    "h261",
    "h263",
    "h264",
    "h265",
    "ifv",
    "m2t",
    "m2ts",
    "mts",
    "m4v",
    "mkv",
    "mod",
    "mov",
    "mp4",
    "mpg",
    "mxf",
    "tod",
    "vob",
    "webm",
    "wmv",
    "y4m",
]


class GalleryEntry(NamedTuple):
    """One gallery item found by ``read_files`` before it's analysed."""

    nav_index: int  # index into the nav_* arrays of the directory it's in
    file_path: Path  # the image/video file, or the sequence directory
    url: str  # url-safe name
    gallery_type: int  # 0 = image, 1 = video, 2 = sequence
    image: Path  # file to take colours/dimensions from (first frame for sequences)
    is_video: bool  # a frame must be extracted from ``image`` first


class Scanner:
    """Directory and file scanner.

    Manages the navigation structure (paths, nav_*) and gallery
    structures (gallery_files, gallery_*) that track all images/videos.
    """

    def __init__(
        self,
        topdir: Path,
        scriptdir: Path,
        config: Config,
        cache: BuildCache | None = None,
        dry_run: bool = False,
        progress: Reporter | None = None,
    ):
        """Initialize the scanner.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for resources).
            config: Configuration object.
            cache: Build cache for palettes/dimensions (None: always analyse).
            dry_run: Create no directories and skip expensive palette extraction.
            progress: Progress display (default: none; dots are printed instead).
        """
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        self.cache = cache
        self.dry_run = dry_run
        self.progress = progress or Reporter(enabled=False)

        # Navigation structures
        self.paths: list[Path] = []
        self.nav_name: list[str] = []
        self.nav_depth: list[int] = []
        self.nav_type: list[int] = []
        self.nav_url: list[str] = []
        self.nav_count: list[int] = []

        # Gallery structures
        self.gallery_files: list[Path] = []
        self.gallery_nav: list[int] = []
        self.gallery_url: list[str] = []
        self.gallery_type: list[int] = []
        self.gallery_maxwidth: list[int] = []
        self.gallery_maxheight: list[int] = []
        self.gallery_colors: list[list[str]] = []
        self.gallery_image_options: list[str] = []
        self.gallery_video_options: list[str] = []
        self.gallery_video_filters: list[str] = []

        # Initialize media processors
        self.image_processor = ImageProcessor()
        self.video_processor = VideoProcessor()
        self.color_extractor = ColorExtractor()

        # Create scratch directory
        self.scratchdir = Path(tempfile.mkdtemp())

        # Check video support
        self.video_enabled = self.video_processor.available

    def _heading(self, text: str) -> None:
        """Start a phase: ``text`` followed by dots, or a line of its own under progress bars."""
        if self.progress.active:
            print(text.lstrip("\n"))
        else:
            print(text, end="", flush=True)

    def _dot(self) -> None:
        """One step of progress in plain output (bars show progress otherwise)."""
        if not self.progress.active:
            print(".", end="", flush=True)

    def _end_line(self) -> None:
        if not self.progress.active:
            print()

    def scan_directories(self) -> None:
        """Scan working directory to populate navigation structures."""
        self._heading("Scanning directories")

        root_depth = len(self.topdir.parts)
        sequence_keyword = self.config.get("sequence_keyword", "")

        # Find all directories, sorted. Prune _* (incl. _site) and hidden dirs while walking
        # so large output trees are never traversed; they'd be filtered out below anyway.
        found = []
        children: dict[Path, list[Path]] = {}
        for root, dirs, _files in os.walk(self.topdir):
            dirs[:] = [d for d in dirs if not d.startswith(("_", "."))]
            found.extend(Path(root) / d for d in dirs)
            children[Path(root)] = sorted(Path(root) / d for d in dirs)
        mode = self.config.get("sort", "name")
        if mode == "name":
            # Include topdir itself; plain path order, exactly as before (parity with expose.sh)
            all_dirs = [self.topdir] + sorted(found)
        else:
            all_dirs = [self.topdir] + self._ordered_dirs(self.topdir, children, mode)

        for node in all_dirs:
            self._dot()

            # Skip _site directory
            if node == self.topdir / "_site" or str(node).startswith(str(self.topdir / "_site")):
                continue

            # Skip directories under _* paths
            rel_parts = node.relative_to(self.topdir).parts if node != self.topdir else ()
            if any(part.startswith("_") for part in rel_parts):
                continue

            # Skip hidden directories (starting with .)
            if node != self.topdir and any(part.startswith(".") for part in rel_parts):
                continue

            # Calculate depth
            node_depth = len(node.parts) - root_depth

            # Skip empty directories; hidden files (e.g. a leftover .DS_Store) don't count
            try:
                if not any(not entry.name.startswith(".") for entry in node.iterdir()):
                    continue
            except PermissionError:
                continue

            # Get node name with prefix stripped
            node_name = strip_numeric_prefix(node.name)
            if not node_name:
                node_name = node.name

            # Count subdirectories, ignoring _ and hidden ones: they're skipped above, so a
            # gallery with e.g. a .thumbs folder inside must still count as a gallery (leaf)
            subdirs = [
                d for d in node.iterdir() if d.is_dir() and not d.name.startswith(("_", "."))
            ]
            dircount = len(subdirs)

            # Count subdirs excluding sequence keyword dirs
            if sequence_keyword:
                dircount_sequence = len([d for d in subdirs if sequence_keyword not in d.name])
            else:
                dircount_sequence = dircount

            # Determine node type
            if dircount > 0:
                node_type = 0 if (not sequence_keyword or dircount_sequence > 0) else 1
            elif sequence_keyword and sequence_keyword in node_name:
                continue  # Skip sequence directories
            else:
                node_type = 1  # Leaf directory

            self.paths.append(node)
            self.nav_name.append(node_name)
            self.nav_depth.append(node_depth)
            self.nav_type.append(node_type)

        # Create _site directory
        if not self.dry_run:
            (self.topdir / "_site").mkdir(exist_ok=True)

        # Gallery slugs, made unique among siblings (same parent folder) in sort order
        slugs = [slug_or_fallback(name, "gallery") for name in self.nav_name]
        siblings: dict[Path, list[int]] = {}
        for i in range(1, len(self.paths)):
            siblings.setdefault(self.paths[i].parent, []).append(i)
        for members in siblings.values():
            unique = unique_slugs([slugs[i] for i in members], list(range(len(members))))
            for i, slug in zip(members, unique, strict=True):
                if slug != slugs[i]:
                    self._warn_collision(self.paths[i], slugs[i], slug)
                    slugs[i] = slug

        # Build URL structure
        dir_stack = []
        url_rel = ""
        self.nav_url.append(".")  # First item is topdir

        self._heading("\nPopulating nav")

        for i in range(1, len(self.paths)):
            self._dot()

            if i > 1:
                if self.nav_depth[i] > self.nav_depth[i - 1]:
                    dir_stack.append(url_rel)
                elif self.nav_depth[i] < self.nav_depth[i - 1]:
                    diff = self.nav_depth[i - 1]
                    while diff > self.nav_depth[i]:
                        if dir_stack:
                            dir_stack.pop()
                        diff -= 1

            url_rel = slugs[i]

            url = "/".join(dir_stack + [url_rel]) if dir_stack else url_rel

            if not self.dry_run:
                site_path(self.topdir / "_site", url).mkdir(parents=True, exist_ok=True)
            self.nav_url.append(url)

        self._end_line()

    def read_files(self) -> None:
        """Read files to populate gallery structures.

        Files are discovered sequentially (ordering matters for parity), then colour
        palettes and dimensions are extracted in parallel with order preserved.
        """
        self._heading("Reading files")

        sequence_keyword = self.config.get("sequence_keyword", "")
        entries: list[GalleryEntry] = []

        for i, path in enumerate(self.paths):
            self.nav_count.append(-1)

            if self.nav_type[i] < 1:
                continue

            if not self.dry_run:
                site_path(self.topdir / "_site", self.nav_url[i]).mkdir(parents=True, exist_ok=True)

            # Get files in directory, sorted; skip _ and hidden files (incl. macOS ._ files)
            files = sorted(f for f in path.iterdir() if not f.name.startswith(("_", ".")))

            gallery: list[GalleryEntry] = []
            for file_path in files:
                self._dot()
                entry = self._classify(i, file_path, sequence_keyword)
                if entry:
                    gallery.append(entry)
            gallery = sort_items(
                gallery,
                self._gallery_sort(path),
                name=lambda entry: entry.file_path.name,
                taken_at=self._taken_at,
            )
            entries.extend(self._unique_urls(gallery))

        # Colours and dimensions (the slow part on a first run): a bar under progress display
        bar = self.progress.task(f"Reading {len(entries)} files", total=len(entries))

        def analyze(k: int, entry: GalleryEntry) -> tuple[list[str], int, int]:
            try:
                return self._analyze(k, entry)
            finally:
                bar.advance()

        jobs = self.config.worker_count()
        if jobs > 1 and len(entries) > 1:
            pool = ThreadPoolExecutor(max_workers=jobs)
            try:
                results = list(pool.map(analyze, range(len(entries)), entries))
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        else:
            results = [analyze(k, e) for k, e in enumerate(entries)]

        counts: dict[int, int] = {}
        for entry, (palette, maxwidth, maxheight) in zip(entries, results, strict=True):
            counts[entry.nav_index] = counts.get(entry.nav_index, 0) + 1

            self.gallery_files.append(entry.file_path)
            self.gallery_nav.append(entry.nav_index)
            self.gallery_url.append(entry.url)
            self.gallery_type.append(entry.gallery_type)
            self.gallery_maxwidth.append(maxwidth)
            self.gallery_maxheight.append(maxheight)
            self.gallery_colors.append(palette)
            self.gallery_image_options.append("")
            self.gallery_video_options.append("")
            self.gallery_video_filters.append("")

        for i in range(len(self.paths)):
            if self.nav_type[i] >= 1:
                self.nav_count[i] = counts.get(i, 0)

        self._end_line()

    def _ordered_dirs(self, top: Path, children: dict[Path, list[Path]], mode: str) -> list[Path]:
        """All directories below ``top`` in depth-first order, siblings sorted by ``mode``."""
        taken: dict[Path, float] = {}

        def earliest(directory: Path) -> float:
            # A folder's time is its earliest photo, including those in subfolders
            if directory not in taken:
                times = [self._file_taken_at(f) for f in self._media_files(directory)]
                times += [earliest(child) for child in children.get(directory, [])]
                taken[directory] = min(times, default=float("inf"))
            return taken[directory]

        result: list[Path] = []

        def visit(directory: Path) -> None:
            for child in sort_items(
                children.get(directory, []), mode, name=lambda d: d.name, taken_at=earliest
            ):
                result.append(child)
                visit(child)

        visit(top)
        return result

    @staticmethod
    def _media_files(directory: Path) -> list[Path]:
        """Photos and videos directly inside ``directory`` (hidden and ``_`` files skipped)."""
        try:
            entries = list(directory.iterdir())
        except OSError:
            return []
        media = {*IMAGE_EXTENSIONS, *VIDEO_EXTENSIONS}
        return [
            f
            for f in entries
            if f.is_file()
            and not f.name.startswith(("_", "."))
            and f.suffix.lower().lstrip(".") in media
        ]

    @staticmethod
    def _file_taken_at(path: Path) -> float:
        """EXIF capture time of a photo, else its file time."""
        capture_time = read_photo_info(path).capture_time
        if capture_time is not None:
            return capture_time
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")

    def _gallery_sort(self, gallery: Path) -> str:
        """Sort mode for a gallery's photos: ``sort:`` in its metadata.txt, else the setting."""
        mode = self.config.get("sort", "name")
        try:
            text = (gallery / "metadata.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return mode
        for line in text.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() == "sort" and value.strip():
                if value.strip() in SORT_MODES:
                    return value.strip()
                print(f"\n\tIgnoring 'sort: {value.strip()}' in {gallery.name}/metadata.txt")
        return mode

    def _unique_urls(self, gallery: list[GalleryEntry]) -> list[GalleryEntry]:
        """Give items in one gallery distinct URLs (e.g. ``01 photo.jpg`` and ``02 photo.jpg``).

        Items whose names map to the same URL would share an output folder and overwrite each
        other. The earliest one (by capture time, else file time, then name) keeps the URL;
        the others get ``-2``, ``-3``, … Galleries without collisions are unchanged.
        """
        slugs = [entry.url for entry in gallery]
        if len(set(slugs)) == len(slugs):
            return gallery
        counts: dict[str, int] = {}
        for slug in slugs:
            counts[slug] = counts.get(slug, 0) + 1
        # Only colliding items need their (EXIF) time read; the rest keep folder order
        rank = [
            (self._taken_at(entry), entry.file_path.name) if counts[entry.url] > 1 else (0.0, "")
            for entry in gallery
        ]
        result = []
        for entry, slug in zip(gallery, unique_slugs(slugs, rank), strict=True):
            if slug != entry.url:
                self._warn_collision(entry.file_path, entry.url, slug)
                entry = entry._replace(url=slug)
            result.append(entry)
        return result

    @staticmethod
    def _taken_at(entry: GalleryEntry) -> float:
        """When an item was taken: EXIF capture time for photos and sequences, else file time."""
        if not entry.is_video:
            capture_time = read_photo_info(entry.image).capture_time
            if capture_time is not None:
                return capture_time
        try:
            return entry.file_path.stat().st_mtime
        except OSError:
            return 0.0

    def _warn_collision(self, path: Path, slug: str, new_slug: str) -> None:
        """Tell the user an item was renamed because its URL was already taken."""
        rel = path.relative_to(self.topdir) if path.is_relative_to(self.topdir) else path
        print(
            f"\n\tWarning: '{rel}' has the same URL as another item ('{slug}'); using '{new_slug}'"
        )

    def _classify(
        self, nav_index: int, file_path: Path, sequence_keyword: str
    ) -> GalleryEntry | None:
        """Decide whether a gallery directory entry is an image, video or sequence.

        Returns:
            Entry tuple for ``read_files``, or None if the file isn't gallery media.
        """
        filename = file_path.name
        trimmed = re.sub(r"^[\s0-9]*", "", file_path.stem).strip()
        if not trimmed:
            trimmed = file_path.stem
        image_url = slug_or_fallback(trimmed, "item")

        if file_path.is_dir() and sequence_keyword and sequence_keyword in filename:
            # Use the first image of the sequence for colours/dimensions
            seq_images = sequence_frames(file_path)
            if not seq_images:
                return None
            return GalleryEntry(nav_index, file_path, image_url, 2, seq_images[0], False)

        if not file_path.is_file():
            return None

        extension = file_path.suffix.lower().lstrip(".")
        if extension in IMAGE_EXTENSIONS:
            return GalleryEntry(nav_index, file_path, image_url, 0, file_path, False)

        if not self.video_enabled:
            return None
        if extension not in VIDEO_EXTENSIONS:
            # Fall back to mime type detection
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if not mime_type or "video" not in mime_type:
                return None
        return GalleryEntry(nav_index, file_path, image_url, 1, file_path, True)

    def _analysis_key(self) -> str:
        """Hash of the settings palette/dimension extraction depends on."""
        return settings_hash(
            backend=type(self.color_extractor.backend).__name__,
            extract_colors=self.config["extract_colors"],
            default_palette=self.config["default_palette"],
            autorotate=self.config["autorotate"],
        )

    def _palette_and_size(self, k: int, entry: GalleryEntry) -> tuple[list[str], int, int]:
        """Colour palette and (orientation-corrected) size, from the cache when unchanged."""
        stat = source_stat(entry.file_path)
        key = self._analysis_key()
        if self.cache is not None:
            hit = self.cache.get_analysis(entry.file_path, stat, key)
            if hit is not None:
                return hit

        autorotate = self.config["autorotate"]
        if self.dry_run:
            # Skip the expensive parts; dimensions are all a dry run needs
            palette = list(self.config["default_palette"])
            if entry.is_video:
                return palette, *self.video_processor.probe(entry.image)
            return palette, *self.image_processor.extract_dimensions(entry.image, autorotate)

        image = entry.image
        if entry.is_video:
            # Each entry gets its own frame file so parallel extraction can't collide
            frame = self.scratchdir / f"frame-{k}.jpg"
            self.video_processor.extract_frame(image, frame)
            image = frame

        if self.config["extract_colors"]:
            palette = self.color_extractor.extract_palette(image, num_colors=7)
        else:
            palette = list(self.config["default_palette"])

        # Get image dimensions with EXIF orientation handling
        width, height = self.image_processor.extract_dimensions(
            image, handle_orientation=autorotate
        )
        if self.cache is not None and (width or not entry.is_video):
            self.cache.put_analysis(entry.file_path, stat, key, palette, width, height)
        return palette, width, height

    def _analyze(self, k: int, entry: GalleryEntry) -> tuple[list[str], int, int]:
        """Extract (palette, maxwidth, maxheight) for one entry. Safe to run in threads."""
        palette, width, height = self._palette_and_size(k, entry)

        # Calculate max dimensions
        maxwidth = 0
        maxheight = 0
        resolutions = self.config["resolution"]

        for count, res in enumerate(resolutions, 1):
            if width >= res and res > maxwidth or maxwidth == 0 and count == len(resolutions):
                maxwidth = res
                maxheight = res * height // width if width else 0

        return palette, maxwidth, maxheight

    def cleanup(self) -> None:
        """Clean up temporary files."""
        if self.scratchdir.exists():
            shutil.rmtree(self.scratchdir, ignore_errors=True)
