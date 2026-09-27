"""Main generator orchestrator.

Coordinates Scanner, HTMLBuilder, and MediaEncoder to generate
the complete static site. Also acts as a facade exposing all
component APIs so tests and callers don't need to know the internals.
"""

import contextlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dorothea.builder import HTMLBuilder
from dorothea.cache import BuildCache
from dorothea.config import Config
from dorothea.encoder import MediaEncoder
from dorothea.feed import FEED_NAME, build_feed, collect_galleries
from dorothea.media.ffmpeg import set_ffmpeg
from dorothea.media.image import ImageProcessor
from dorothea.progress import Reporter
from dorothea.scanner import Scanner
from dorothea.themes import resolve_theme_dir
from dorothea.utils import site_path

# Theme files the builder reads markup from, which aren't copied to _site
THEME_SNIPPETS = {"template.html", "post-template.html", "feed-button.html", "album-download.html"}


class _ScannerField[T]:
    """An attribute of ``ExposeGenerator.scanner`` exposed on the generator itself."""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: ExposeGenerator, objtype: type | None = None) -> T:
        return getattr(obj.scanner, self.name)

    def __set__(self, obj: ExposeGenerator, value: T) -> None:
        setattr(obj.scanner, self.name, value)


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

    def __init__(
        self,
        topdir: Path,
        scriptdir: Path,
        config: Config | dict,
        draft: bool = False,
        dry_run: bool = False,
        use_cache: bool = True,
        progress: Reporter | None = None,
    ):
        """Initialize the generator.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for themes and resources).
            config: Configuration object or dict.
            draft: Whether to run in draft mode.
            dry_run: Work out what would be built without writing anything.
            use_cache: Use ``.dorothea-cache.json`` for palettes and output fingerprints.
            progress: Progress display for ``run()`` (default: none, plain output; the CLI
                shows bars on a terminal).
        """
        if isinstance(config, dict):
            config = Config(config)

        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        self.draft = draft
        self.dry_run = dry_run

        # Choose the ffmpeg binary before anything (Scanner's VideoProcessor) looks it up
        set_ffmpeg(config.get("ffmpeg", "auto"))

        self.progress = progress or Reporter(enabled=False)
        self.cache = BuildCache(self.topdir) if use_cache else None
        self.scanner = Scanner(
            topdir, scriptdir, config, cache=self.cache, dry_run=dry_run, progress=self.progress
        )
        self._image_processor = ImageProcessor()
        # Filled by a dry run: HTML pages and (output, reason) pairs that would be written
        self.planned_pages = 0
        self.planned: list[tuple[str, str]] = []
        self.planned_feeds = 0

    # --- Pipeline stages ---

    def scan_directories(self) -> None:
        """Scan working directory to populate navigation structures."""
        self.scanner.scan_directories()

    def read_files(self) -> None:
        """Read files to populate gallery structures."""
        self.scanner.read_files()

    def build_html(self) -> None:
        """Generate HTML pages for all galleries (a dry run only counts them)."""
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
            draft=self.draft,
            gallery_details=self.scanner.gallery_details,
        )
        self.planned_pages = builder.build_html(
            write=not self.dry_run, dots=not self.progress.active
        )
        if self.config.get("site_url"):
            self._write_feed(builder.markdown_processor.render)

    def _write_feed(self, render_markdown: Callable[[str], str]) -> None:
        """Write _site/feed.xml and the galleries' own feeds (#11).

        A dry run only counts them (``planned_feeds``).
        """
        s = self.scanner
        galleries = collect_galleries(
            self.config["site_url"], self.config["resolution"],
            self.config.get("gallery_feeds", True), s.paths, s.nav_type, s.nav_count,
            s.nav_name, s.nav_url, s.gallery_files, s.gallery_type, s.gallery_url,
            s.gallery_maxwidth, render_markdown,
        )  # fmt: skip
        own = [g for g in galleries if g.enabled]
        if self.dry_run:
            self.planned_feeds = 1 + len(own)
            return
        title = self.config["site_title"]
        site = self.topdir / "_site"
        site.mkdir(parents=True, exist_ok=True)
        entries = [g.entry for g in galleries]
        (site / FEED_NAME).write_bytes(build_feed(title, self.config["site_url"], title, entries))
        for g in own:
            feed = build_feed(f"{title}: {g.entry.title}", g.url, title, g.items)
            site_path(site, f"{g.site_path}/{FEED_NAME}").write_bytes(feed)

    def encode_media(self) -> None:
        """Encode all images and videos (a dry run records ``planned`` instead)."""
        encoder = self._make_encoder()
        try:
            encoder.encode_media()
        finally:
            self.planned = encoder.planned
            self._save_cache()

    def copy_resources(self) -> None:
        """Copy theme resources to _site directory."""
        theme_dir = resolve_theme_dir(self.config["theme_dir"], self.topdir)
        site_dir = self.topdir / "_site"
        for item in theme_dir.iterdir():
            if item.name in THEME_SNIPPETS:
                continue
            dest = site_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    def run(self) -> None:
        """Run the full generation pipeline (with progress bars, if enabled)."""
        with self.progress.live():
            self.scan_directories()
            self.read_files()
            self.build_html()
            self.encode_media()
            if not self.dry_run:
                self.copy_resources()
        self.cleanup()

    def _save_cache(self) -> None:
        if self.cache is not None and not self.dry_run:
            self.cache.save()

    def cleanup(self) -> None:
        """Clean up temporary files, including partial outputs left by an interrupted run."""
        self._save_cache()
        site = self.topdir / "_site"
        if site.is_dir():
            for part in site.rglob("*.part.*"):
                with contextlib.suppress(OSError):
                    part.unlink()
        if hasattr(self, "scanner"):
            self.scanner.cleanup()

    # --- Image helpers ---

    def identify(self, image: Path, format_str: str) -> str:
        """Return image metadata for an ImageMagick-style format string (e.g. "%w")."""
        return self._image_processor.identify(image, format_str)

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
            gallery_video_options=self.scanner.gallery_video_options,
            cache=self.cache,
            dry_run=self.dry_run,
            progress=self.progress,
        )

    def _encode_video(self, filepath: Path, url: str, index: int) -> None:
        return self._make_encoder()._encode_video(filepath, url, index)

    def _encode_h264(self, *args: Any, **kwargs: Any) -> bool:
        return self._make_encoder()._encode_h264(*args, **kwargs)

    def _encode_h265(self, *args: Any, **kwargs: Any) -> bool:
        return self._make_encoder()._encode_h265(*args, **kwargs)

    def _encode_vp9(self, *args: Any, **kwargs: Any) -> bool:
        return self._make_encoder()._encode_vp9(*args, **kwargs)

    def _encode_vp8(self, *args: Any, **kwargs: Any) -> bool:
        return self._make_encoder()._encode_vp8(*args, **kwargs)

    def _encode_ogv(self, *args: Any, **kwargs: Any) -> bool:
        return self._make_encoder()._encode_ogv(*args, **kwargs)

    def _sequence_finished(self, url: str) -> bool:
        return self._make_encoder()._sequence_finished(url)

    def _compile_sequence(self, seq_dir: Path) -> Path | None:
        return self._make_encoder()._compile_sequence(seq_dir)

    def _create_download_zip(self, file_path: Path, url: str, index: int) -> None:
        return self._make_encoder()._create_download_zip(file_path, url, index)

    # --- Scanner arrays, readable and writable through the facade (tests set them) ---

    paths = _ScannerField[list[Path]]()
    nav_name = _ScannerField[list[str]]()
    nav_depth = _ScannerField[list[int]]()
    nav_type = _ScannerField[list[int]]()
    nav_url = _ScannerField[list[str]]()
    nav_count = _ScannerField[list[int]]()
    gallery_files = _ScannerField[list[Path]]()
    gallery_nav = _ScannerField[list[int]]()
    gallery_url = _ScannerField[list[str]]()
    gallery_type = _ScannerField[list[int]]()
    gallery_maxwidth = _ScannerField[list[int]]()
    gallery_maxheight = _ScannerField[list[int]]()
    gallery_colors = _ScannerField[list[list[str]]]()
    gallery_image_options = _ScannerField[list[str]]()
    gallery_video_options = _ScannerField[list[str]]()
    gallery_video_filters = _ScannerField[list[str]]()
    gallery_details = _ScannerField[list[dict[str, str]]]()
    video_enabled = _ScannerField[bool]()

    @property
    def scratchdir(self) -> Path:
        return self.scanner.scratchdir
