"""Directory and file scanning.

Scans the working directory to build navigation structures and
process images/videos to extract metadata.
"""

import re
import shutil
import subprocess
import tempfile
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

        # Find all directories, sorted
        all_dirs = sorted([d for d in self.topdir.rglob("*") if d.is_dir()])
        # Include topdir itself
        all_dirs = [self.topdir] + all_dirs

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
        """Read files to populate gallery structures."""
        print("Reading files", end="", flush=True)

        sequence_keyword = self.config.get("sequence_keyword", "")

        for i, path in enumerate(self.paths):
            self.nav_count.append(-1)

            if self.nav_type[i] < 1:
                continue

            dir_path = path
            url = self.nav_url[i]

            (self.topdir / "_site" / url).mkdir(parents=True, exist_ok=True)

            index = 0

            # Get files in directory, sorted
            files = sorted([f for f in dir_path.iterdir() if not f.name.startswith("_")])

            for file_path in files:
                print(".", end="", flush=True)

                filename = file_path.name
                trimmed = re.sub(r"^[\s0-9]*", "", file_path.stem).strip()
                if not trimmed:
                    trimmed = file_path.stem

                image_url = url_safe(trimmed)

                # Check if this is a sequence directory
                if file_path.is_dir() and sequence_keyword and sequence_keyword in filename:
                    format_type = "sequence"
                    # Find first image in sequence
                    seq_images = sorted(
                        [
                            f
                            for f in file_path.iterdir()
                            if f.suffix.lower() in [".jpg", ".jpeg", ".gif", ".png"]
                        ]
                    )
                    if seq_images:
                        image = seq_images[0]
                    else:
                        continue
                elif file_path.is_file():
                    extension = file_path.suffix.lower().lstrip(".")

                    if extension in ["jpg", "jpeg", "png", "gif"]:
                        format_type = extension
                        image = file_path
                    elif extension in VIDEO_EXTENSIONS:
                        if not self.video_enabled:
                            continue
                        format_type = "video"
                        # Extract frame from video
                        temp_path = self.scratchdir / "temp.jpg"
                        self.video_processor.extract_frame(file_path, temp_path)
                        image = temp_path
                    else:
                        # Check if it's a video by mime type
                        if not self.video_enabled:
                            continue
                        result = subprocess.run(
                            ["file", "-ib", str(file_path)], capture_output=True, text=True
                        )
                        if "video" not in result.stdout:
                            continue
                        format_type = "video"
                        temp_path = self.scratchdir / "temp.jpg"
                        self.video_processor.extract_frame(file_path, temp_path)
                        image = temp_path
                else:
                    continue

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
                    if (
                        width >= res
                        and res > maxwidth
                        or maxwidth == 0
                        and count == len(resolutions)
                    ):
                        maxwidth = res
                        maxheight = res * height // width if width else 0

                index += 1

                # Store file info
                self.gallery_files.append(file_path)
                self.gallery_nav.append(i)
                self.gallery_url.append(image_url)

                if format_type == "sequence":
                    self.gallery_type.append(2)
                elif format_type == "video":
                    self.gallery_type.append(1)
                else:
                    self.gallery_type.append(0)

                self.gallery_maxwidth.append(maxwidth)
                self.gallery_maxheight.append(maxheight)
                self.gallery_colors.append(palette)
                self.gallery_image_options.append("")
                self.gallery_video_options.append("")
                self.gallery_video_filters.append("")

            self.nav_count[i] = index

        print()

    def cleanup(self):
        """Clean up temporary files."""
        if self.scratchdir.exists():
            shutil.rmtree(self.scratchdir, ignore_errors=True)
