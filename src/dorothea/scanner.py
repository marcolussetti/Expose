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
from dorothea.media.image import ImageProcessor
from dorothea.media.video import VideoProcessor
from dorothea.utils import strip_numeric_prefix, url_safe

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
    ):
        """Initialize the scanner.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for resources).
            config: Configuration object.
            cache: Build cache for palettes/dimensions (None: always analyse).
            dry_run: Create no directories and skip expensive palette extraction.
        """
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        self.cache = cache
        self.dry_run = dry_run

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

    def scan_directories(self) -> None:
        """Scan working directory to populate navigation structures."""
        print("Scanning directories", end="", flush=True)

        root_depth = len(self.topdir.parts)
        sequence_keyword = self.config.get("sequence_keyword", "")

        # Find all directories, sorted. Prune _* (incl. _site) and hidden dirs while walking
        # so large output trees are never traversed; they'd be filtered out below anyway.
        found = []
        for root, dirs, _files in os.walk(self.topdir):
            dirs[:] = [d for d in dirs if not d.startswith(("_", "."))]
            found.extend(Path(root) / d for d in dirs)
        # Include topdir itself
        all_dirs = [self.topdir] + sorted(found)

        for node in all_dirs:
            print(".", end="", flush=True)

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

            # Skip empty directories
            try:
                if not any(node.iterdir()):
                    continue
            except PermissionError:
                continue

            # Get node name with prefix stripped
            node_name = strip_numeric_prefix(node.name)
            if not node_name:
                node_name = node.name

            # Count subdirectories (excluding _ prefixed)
            subdirs = [d for d in node.iterdir() if d.is_dir() and not d.name.startswith("_")]
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

        # Build URL structure
        dir_stack = []
        url_rel = ""
        self.nav_url.append(".")  # First item is topdir

        print("\nPopulating nav", end="", flush=True)

        for i in range(1, len(self.paths)):
            print(".", end="", flush=True)

            if i > 1:
                if self.nav_depth[i] > self.nav_depth[i - 1]:
                    dir_stack.append(url_rel)
                elif self.nav_depth[i] < self.nav_depth[i - 1]:
                    diff = self.nav_depth[i - 1]
                    while diff > self.nav_depth[i]:
                        if dir_stack:
                            dir_stack.pop()
                        diff -= 1

            url_rel = url_safe(self.nav_name[i])

            url = "/".join(dir_stack + [url_rel]) if dir_stack else url_rel

            if not self.dry_run:
                (self.topdir / "_site" / url).mkdir(parents=True, exist_ok=True)
            self.nav_url.append(url)

        print()

    def read_files(self) -> None:
        """Read files to populate gallery structures.

        Files are discovered sequentially (ordering matters for parity), then colour
        palettes and dimensions are extracted in parallel with order preserved.
        """
        print("Reading files", end="", flush=True)

        sequence_keyword = self.config.get("sequence_keyword", "")
        entries: list[GalleryEntry] = []

        for i, path in enumerate(self.paths):
            self.nav_count.append(-1)

            if self.nav_type[i] < 1:
                continue

            if not self.dry_run:
                (self.topdir / "_site" / self.nav_url[i]).mkdir(parents=True, exist_ok=True)

            # Get files in directory, sorted
            files = sorted([f for f in path.iterdir() if not f.name.startswith("_")])

            for file_path in files:
                print(".", end="", flush=True)
                entry = self._classify(i, file_path, sequence_keyword)
                if entry:
                    entries.append(entry)

        jobs = self.config.worker_count()
        if jobs > 1 and len(entries) > 1:
            pool = ThreadPoolExecutor(max_workers=jobs)
            try:
                results = list(pool.map(self._analyze, range(len(entries)), entries))
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        else:
            results = [self._analyze(k, e) for k, e in enumerate(entries)]

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

        print()

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
        image_url = url_safe(trimmed)

        if file_path.is_dir() and sequence_keyword and sequence_keyword in filename:
            # Use the first image of the sequence for colours/dimensions
            seq_images = sorted(
                f
                for f in file_path.iterdir()
                if f.suffix.lower() in [".jpg", ".jpeg", ".gif", ".png"]
            )
            if not seq_images:
                return None
            return GalleryEntry(nav_index, file_path, image_url, 2, seq_images[0], False)

        if not file_path.is_file():
            return None

        extension = file_path.suffix.lower().lstrip(".")
        if extension in ["jpg", "jpeg", "png", "gif"]:
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
