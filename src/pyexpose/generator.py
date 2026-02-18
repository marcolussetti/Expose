"""Main generator orchestrator.

Coordinates Scanner, HTMLBuilder, and MediaEncoder to generate
the complete static site. Also acts as a facade exposing all
component APIs so tests and callers don't need to know the internals.
"""

import contextlib
import shutil
from pathlib import Path

from pyexpose.builder import HTMLBuilder
from pyexpose.config import Config
from pyexpose.encoder import MediaEncoder
from pyexpose.media.image import ImageProcessor
from pyexpose.scanner import Scanner
from pyexpose.themes import resolve_theme_dir


class ExposeGenerator:
    """Main orchestrator and facade over all pipeline components.

    The generator follows a 5-stage pipeline:
    1. scan_directories() - Build navigation structure
    2. read_files() - Process images/videos, extract metadata
    3. build_html() - Generate HTML from templates
    4. encode_media() - Encode images/videos to multiple formats
    5. copy_resources() - Copy theme assets

    Also acts as a facade, delegating scanner arrays and encoder methods
    so existing code can continue to use a single generator object.
    """

    def __init__(self, topdir: Path, scriptdir: Path, config, draft: bool = False):
        """Initialize the generator.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for themes and resources).
            config: Configuration object or dict.
            draft: Whether to run in draft mode.
        """
        if isinstance(config, dict):
            config = Config(config)

        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        self.draft = draft

        self.scanner = Scanner(topdir, scriptdir, config)
        self._image_processor = ImageProcessor()
        self.output_url: str | None = None

    # --- Pipeline stages ---

    def scan_directories(self):
        """Scan working directory to populate navigation structures."""
        self.scanner.scan_directories()

    def read_files(self):
        """Read files to populate gallery structures."""
        self.scanner.read_files()

    def build_html(self):
        """Generate HTML pages for all galleries."""
        builder = HTMLBuilder(
            self.topdir,
            self.scriptdir,
            self.config,
            self.scanner.paths,
            self.scanner.nav_name,
            self.scanner.nav_depth,
            self.scanner.nav_type,
            self.scanner.nav_url,
            self.scanner.nav_count,
            self.scanner.gallery_files,
            self.scanner.gallery_nav,
            self.scanner.gallery_url,
            self.scanner.gallery_type,
            self.scanner.gallery_maxwidth,
            self.scanner.gallery_maxheight,
            self.scanner.gallery_colors,
            self.scanner.gallery_image_options,
            self.scanner.gallery_video_options,
            self.scanner.gallery_video_filters,
        )
        builder.build_html()

    def encode_media(self):
        """Encode all images and videos."""
        self._make_encoder().encode_media()

    def copy_resources(self):
        """Copy theme resources to _site directory."""
        theme_dir = resolve_theme_dir(self.config["theme_dir"], self.topdir)
        site_dir = self.topdir / "_site"
        for item in theme_dir.iterdir():
            if item.name in ["template.html", "post-template.html"]:
                continue
            dest = site_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    def run(self):
        """Run the full generation pipeline."""
        self.scan_directories()
        self.read_files()
        self.build_html()
        self.encode_media()
        self.copy_resources()
        self.cleanup()

    def cleanup(self):
        """Clean up temporary files. Removes output_url if interrupted."""
        if self.output_url:
            with contextlib.suppress(FileNotFoundError):
                Path(self.output_url).unlink()
            self.output_url = None
        if hasattr(self, "scanner"):
            self.scanner.cleanup()

    # --- ImageMagick proxy methods ---

    def identify(self, image, format_str):
        """Run ImageMagick identify."""
        return self._image_processor.identify(image, format_str)

    def convert(self, args):
        """Run ImageMagick convert."""
        return self._image_processor.convert(args)

    # --- Encoder proxy methods ---

    def _make_encoder(self) -> MediaEncoder:
        """Create a MediaEncoder from current scanner state."""
        return MediaEncoder(
            self.topdir,
            self.scriptdir,
            self.config,
            self.draft,
            self.scanner.gallery_files,
            self.scanner.gallery_nav,
            self.scanner.gallery_url,
            self.scanner.gallery_type,
            self.scanner.gallery_image_options,
            self.scanner.gallery_video_filters,
            self.scanner.nav_url,
            scratchdir=self.scanner.scratchdir,
        )

    def _encode_video(self, filepath, url, index):
        return self._make_encoder()._encode_video(filepath, url, index)

    def _encode_h264(self, *args, **kwargs):
        return self._make_encoder()._encode_h264(*args, **kwargs)

    def _encode_h265(self, *args, **kwargs):
        return self._make_encoder()._encode_h265(*args, **kwargs)

    def _encode_vp9(self, *args, **kwargs):
        return self._make_encoder()._encode_vp9(*args, **kwargs)

    def _encode_vp8(self, *args, **kwargs):
        return self._make_encoder()._encode_vp8(*args, **kwargs)

    def _encode_ogv(self, *args, **kwargs):
        return self._make_encoder()._encode_ogv(*args, **kwargs)

    def _sequence_finished(self, url):
        return self._make_encoder()._sequence_finished(url)

    def _compile_sequence(self, seq_dir):
        return self._make_encoder()._compile_sequence(seq_dir)

    def _create_download_zip(self, file_path, url, index):
        return self._make_encoder()._create_download_zip(file_path, url, index)

    # --- Scanner array properties (getters + setters for test compatibility) ---

    @property
    def paths(self):
        return self.scanner.paths

    @paths.setter
    def paths(self, v):
        self.scanner.paths = v

    @property
    def nav_name(self):
        return self.scanner.nav_name

    @nav_name.setter
    def nav_name(self, v):
        self.scanner.nav_name = v

    @property
    def nav_depth(self):
        return self.scanner.nav_depth

    @nav_depth.setter
    def nav_depth(self, v):
        self.scanner.nav_depth = v

    @property
    def nav_type(self):
        return self.scanner.nav_type

    @nav_type.setter
    def nav_type(self, v):
        self.scanner.nav_type = v

    @property
    def nav_url(self):
        return self.scanner.nav_url

    @nav_url.setter
    def nav_url(self, v):
        self.scanner.nav_url = v

    @property
    def nav_count(self):
        return self.scanner.nav_count

    @nav_count.setter
    def nav_count(self, v):
        self.scanner.nav_count = v

    @property
    def gallery_files(self):
        return self.scanner.gallery_files

    @gallery_files.setter
    def gallery_files(self, v):
        self.scanner.gallery_files = v

    @property
    def gallery_nav(self):
        return self.scanner.gallery_nav

    @gallery_nav.setter
    def gallery_nav(self, v):
        self.scanner.gallery_nav = v

    @property
    def gallery_url(self):
        return self.scanner.gallery_url

    @gallery_url.setter
    def gallery_url(self, v):
        self.scanner.gallery_url = v

    @property
    def gallery_type(self):
        return self.scanner.gallery_type

    @gallery_type.setter
    def gallery_type(self, v):
        self.scanner.gallery_type = v

    @property
    def gallery_maxwidth(self):
        return self.scanner.gallery_maxwidth

    @gallery_maxwidth.setter
    def gallery_maxwidth(self, v):
        self.scanner.gallery_maxwidth = v

    @property
    def gallery_maxheight(self):
        return self.scanner.gallery_maxheight

    @gallery_maxheight.setter
    def gallery_maxheight(self, v):
        self.scanner.gallery_maxheight = v

    @property
    def gallery_colors(self):
        return self.scanner.gallery_colors

    @gallery_colors.setter
    def gallery_colors(self, v):
        self.scanner.gallery_colors = v

    @property
    def gallery_image_options(self):
        return self.scanner.gallery_image_options

    @gallery_image_options.setter
    def gallery_image_options(self, v):
        self.scanner.gallery_image_options = v

    @property
    def gallery_video_options(self):
        return self.scanner.gallery_video_options

    @gallery_video_options.setter
    def gallery_video_options(self, v):
        self.scanner.gallery_video_options = v

    @property
    def gallery_video_filters(self):
        return self.scanner.gallery_video_filters

    @gallery_video_filters.setter
    def gallery_video_filters(self, v):
        self.scanner.gallery_video_filters = v

    @property
    def scratchdir(self):
        return self.scanner.scratchdir

    @property
    def video_enabled(self):
        return self.scanner.video_enabled

    @video_enabled.setter
    def video_enabled(self, v):
        self.scanner.video_enabled = v
