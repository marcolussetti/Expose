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

from pyexpose.config import Config
from pyexpose.media.colors import ColorExtractor
from pyexpose.media.image import ImageProcessor
from pyexpose.media.video import VideoProcessor
from pyexpose.utils import strip_numeric_prefix, url_safe

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


class Scanner:
    """Directory and file scanner.

    Manages the navigation structure (paths, nav_*) and gallery
    structures (gallery_files, gallery_*) that track all images/videos.
    """

    def __init__(self, topdir: Path, scriptdir: Path, config: Config):
        """Initialize the scanner.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for resources).
            config: Configuration object.
        """
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config

        # Navigation structures
        self.paths = []
        self.nav_name = []
        self.nav_depth = []
        self.nav_type = []
        self.nav_url = []
        self.nav_count = []

        # Gallery structures
        self.gallery_files = []
        self.gallery_nav = []
        self.gallery_url = []
        self.gallery_type = []
        self.gallery_maxwidth = []
        self.gallery_maxheight = []
        self.gallery_colors = []
        self.gallery_image_options = []
        self.gallery_video_options = []
        self.gallery_video_filters = []

        # Initialize media processors
        self.image_processor = ImageProcessor()
        self.video_processor = VideoProcessor()
        self.color_extractor = ColorExtractor()

        # Create scratch directory
        self.scratchdir = Path(tempfile.mkdtemp())

        # Check video support
        self.video_enabled = self.video_processor.available

    def scan_directories(self):
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

            (self.topdir / "_site" / url).mkdir(parents=True, exist_ok=True)
            self.nav_url.append(url)

        print()

    def read_files(self):
        """Read files to populate gallery structures.

        Files are discovered sequentially (ordering matters for parity), then colour
        palettes and dimensions are extracted in parallel with order preserved.
        """
        print("Reading files", end="", flush=True)

        sequence_keyword = self.config.get("sequence_keyword", "")
        entries = []  # (nav index, file path, url, gallery type, analysis source, is video)

        for i, path in enumerate(self.paths):
            self.nav_count.append(-1)

            if self.nav_type[i] < 1:
                continue

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

        counts = {}
        for (nav_index, file_path, image_url, gtype, _src, _video), result in zip(
            entries, results, strict=True
        ):
            palette, maxwidth, maxheight = result
            counts[nav_index] = counts.get(nav_index, 0) + 1

            self.gallery_files.append(file_path)
            self.gallery_nav.append(nav_index)
            self.gallery_url.append(image_url)
            self.gallery_type.append(gtype)
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

    def _classify(self, nav_index: int, file_path: Path, sequence_keyword: str):
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
            return (nav_index, file_path, image_url, 2, seq_images[0], False)

        if not file_path.is_file():
            return None

        extension = file_path.suffix.lower().lstrip(".")
        if extension in ["jpg", "jpeg", "png", "gif"]:
            return (nav_index, file_path, image_url, 0, file_path, False)

        if not self.video_enabled:
            return None
        if extension not in VIDEO_EXTENSIONS:
            # Fall back to mime type detection
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if not mime_type or "video" not in mime_type:
                return None
        return (nav_index, file_path, image_url, 1, file_path, True)

    def _analyze(self, k: int, entry) -> tuple[list, int, int]:
        """Extract (palette, maxwidth, maxheight) for one entry. Safe to run in threads."""
        _nav, _file, _url, _gtype, image, is_video = entry

        if is_video:
            # Each entry gets its own frame file so parallel extraction can't collide
            frame = self.scratchdir / f"frame-{k}.jpg"
            self.video_processor.extract_frame(image, frame)
            image = frame

        # Extract color palette
        if self.config["extract_colors"]:
            palette = self.color_extractor.extract_palette(image, num_colors=7)
        else:
            palette = list(self.config["default_palette"])

        # Get image dimensions with EXIF orientation handling
        width, height = self.image_processor.extract_dimensions(
            image, handle_orientation=self.config["autorotate"]
        )

        # Calculate max dimensions
        maxwidth = 0
        maxheight = 0
        resolutions = self.config["resolution"]

        for count, res in enumerate(resolutions, 1):
            if width >= res and res > maxwidth or maxwidth == 0 and count == len(resolutions):
                maxwidth = res
                maxheight = res * height // width if width else 0

        return palette, maxwidth, maxheight

    def cleanup(self):
        """Clean up temporary files."""
        if self.scratchdir.exists():
            shutil.rmtree(self.scratchdir, ignore_errors=True)
