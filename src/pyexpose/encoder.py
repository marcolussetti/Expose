"""Media encoding orchestrator.

Handles encoding of images and videos to multiple resolutions and formats.

Outputs are written to ``<name>.part.<ext>`` and renamed into place only on success, so a
failed or interrupted encode never leaves a file that later runs would skip.
"""

import os
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image

from pyexpose.cache import BuildCache, Fingerprint, settings_hash, source_stat
from pyexpose.config import VIDEO_FORMAT_EXTENSIONS, Config
from pyexpose.media.ffmpeg import run_ffmpeg
from pyexpose.media.image import ImageProcessor
from pyexpose.media.video import VideoProcessor

# Sequence frame extension -> image2 codec family (.jpg and .jpeg decode the same)
_FRAME_KIND = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".gif": "gif"}

# Arguments shared by every ffmpeg invocation (expose.sh passes these on each call)
FFMPEG_COMMON = ["-loglevel", "error", "-nostdin"]


def part_path(output: Path) -> Path:
    """Return the temporary path an output is written to before being renamed into place."""
    return output.with_name(f"{output.stem}.part{output.suffix}")


def is_current(output: Path, source: Path | None, nonempty: bool = False) -> bool:
    """Return True if ``output`` exists and is at least as new as ``source``.

    Args:
        output: Generated file.
        source: File it was generated from (None skips the freshness check).
        nonempty: Also require the output to be non-empty.
    """
    try:
        out_stat = output.stat()
    except FileNotFoundError:
        return False
    if nonempty and out_stat.st_size == 0:
        return False
    if source is None:
        return True
    try:
        return source.stat().st_mtime <= out_stat.st_mtime
    except OSError:
        return True


def _finalize(part: Path, output: Path, ok: bool) -> bool:
    """Move a finished part file into place, or discard it on failure."""
    if ok and part.exists():
        os.replace(part, output)
    elif not ok:
        part.unlink(missing_ok=True)
    return ok


class MediaEncoder:
    """Media encoder.

    Orchestrates image and video encoding to multiple resolutions
    and formats using the media processing modules.
    """

    def __init__(
        self,
        topdir: Path,
        scriptdir: Path,
        config: Config,
        draft: bool,
        gallery_files: list[Path],
        gallery_nav: list[int],
        gallery_url: list[str],
        gallery_type: list[int],
        gallery_image_options: list[str],
        gallery_video_filters: list[str],
        nav_url: list[str],
        scratchdir: Path | None = None,
        gallery_video_options: list[str] | None = None,
        cache: BuildCache | None = None,
        dry_run: bool = False,
    ):
        """Initialize the media encoder.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for resources).
            config: Configuration object.
            draft: Whether to run in draft mode.
            gallery_files: List of gallery file paths.
            gallery_nav: Navigation index for each gallery.
            gallery_url: Gallery URLs.
            gallery_type: Gallery types (0=image, 1=video, 2=sequence).
            gallery_image_options: ImageMagick options per gallery item.
            gallery_video_filters: FFmpeg filters per gallery item.
            nav_url: Navigation URLs.
            scratchdir: Optional existing scratch directory to reuse.
            gallery_video_options: FFmpeg options per gallery item.
            cache: Build cache for output fingerprints (None: rebuild on missing/stale only).
            dry_run: Record what would be encoded in ``planned`` instead of encoding.
        """
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        self.draft = draft

        # Gallery structures
        self.gallery_files = gallery_files
        self.gallery_nav = gallery_nav
        self.gallery_url = gallery_url
        self.gallery_type = gallery_type
        self.gallery_image_options = gallery_image_options
        self.gallery_video_options = gallery_video_options or []
        self.gallery_video_filters = gallery_video_filters
        self.nav_url = nav_url

        # Initialize processors
        self.image_processor = ImageProcessor()
        self.video_processor = VideoProcessor()

        # Use provided scratch directory or create a new one
        self.scratchdir = Path(scratchdir) if scratchdir else Path(tempfile.mkdtemp())

        self.autorotate = config["autorotate"]

        self.cache = cache
        self.dry_run = dry_run
        # (output path relative to _site, reason) for every file a dry run would build
        self.planned: list[tuple[str, str]] = []

    # --- helpers ---

    @staticmethod
    def _item(values: list, index: int, default: Any = "") -> Any:
        """Return values[index], or default when the per-item array is short."""
        return values[index] if index < len(values) and values[index] else default

    def _source(self, index: int, fallback: Path | None = None) -> Path | None:
        """Return the source file for gallery item ``index`` (for freshness checks)."""
        return self._item(self.gallery_files, index, fallback)

    @staticmethod
    def _fingerprint(source: Path | None, **settings: Any) -> Fingerprint:
        """Fingerprint of an output: its source's stat plus the settings that shape it."""
        stat = source_stat(source) if source is not None else [0, 0]
        return Fingerprint(stat, settings_hash(**settings))

    def _needs(
        self, output: Path, fingerprint: Fingerprint, source: Path | None, nonempty: bool = False
    ) -> str | None:
        """Why ``output`` must be (re)built, or None if it's up to date.

        With a cache, an output is rebuilt when its recorded fingerprint differs (source edited,
        settings or per-post metadata changed). Outputs with no record (e.g. built by
        expose.sh or an older PyExpose) are adopted if they're newer than their source.
        """
        try:
            stat = output.stat()
        except FileNotFoundError:
            return "new"
        if nonempty and stat.st_size == 0:
            return "new"
        if self.cache is None:
            return None if is_current(output, source) else "source changed"

        recorded = self.cache.get_output(output)
        if recorded == fingerprint:
            return None
        if recorded is not None:
            return "source changed" if recorded.source != fingerprint.source else "settings changed"
        if is_current(output, source):
            if not self.dry_run:
                self.cache.put_output(output, fingerprint)
            return None
        return "source changed"

    def _plan(self, output: Path, reason: str) -> None:
        """Record an output a dry run would build."""
        self.planned.append((output.relative_to(self.topdir / "_site").as_posix(), reason))

    def _built(self, output: Path, fingerprint: Fingerprint, ok: bool = True) -> None:
        """Record a successfully built output's fingerprint."""
        if ok and self.cache is not None and output.exists():
            self.cache.put_output(output, fingerprint)

    def _video_settings(self, index: int, vformat: str, res: int, j: int) -> dict[str, Any]:
        """Settings that determine the bytes of one encoded video file."""
        bitrates = self.config["bitrate"]
        mbit = bitrates[j] if j < len(bitrates) else bitrates[-1]
        speed = None
        if vformat in ("h264", "h265"):
            speed = self.config["h264_encodespeed"]
        elif vformat == "vp9":
            speed = self.config["vp9_encodespeed"]
        return {
            "kind": "video-draft" if self.draft else "video",
            "format": vformat,
            "res": res,
            "mbit": None if self.draft else mbit,
            "maxratio": None if self.draft else self.config["bitrate_maxratio"],
            "speed": None if self.draft else speed,
            "filters": self._item(self.gallery_video_filters, index),
            "options": self._item(self.gallery_video_options, index),
            "audio": not self.config["disable_audio"],
        }

    # --- pipeline ---

    def encode_media(self) -> None:
        """Encode all images and videos.

        Images are encoded in parallel (``jobs`` config key, 0 = one per CPU). Videos and
        sequences run one at a time since each ffmpeg process already uses every core.
        """
        if not self.dry_run:
            print("Starting encode")

        total = len(self.gallery_files)
        images = [i for i in range(total) if self.gallery_type[i] == 0]
        videos = [i for i in range(total) if self.gallery_type[i] != 0]

        jobs = self.config.worker_count()
        # A dry run only stats files; keep it sequential so the plan lists in gallery order
        if jobs > 1 and len(images) > 1 and not self.dry_run:
            pool = ThreadPoolExecutor(max_workers=jobs)
            try:
                # list() re-raises any worker exception here
                list(pool.map(self._encode_item, images))
            finally:
                # On Ctrl-C/errors, drop queued items instead of waiting for all of them
                pool.shutdown(wait=True, cancel_futures=True)
        else:
            for i in images:
                self._encode_item(i)

        for i in videos:
            self._encode_item(i)

    def _encode_item(self, i: int) -> None:
        """Encode one gallery item in its own scratch directory."""
        file_path = self.gallery_files[i]
        url = f"{self.nav_url[self.gallery_nav[i]]}/{self.gallery_url[i]}"
        if not self.dry_run:
            print(f"[{i + 1}/{len(self.gallery_files)}] {self.gallery_url[i]}")
            (self.topdir / "_site" / url).mkdir(parents=True, exist_ok=True)

        scratch = self.scratchdir / f"item-{i}"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            if self.gallery_type[i] == 0:
                image = file_path
            else:
                filepath = file_path

                if self.gallery_type[i] == 2:
                    # Compile image sequence to video
                    if self._sequence_finished(url, i):
                        return

                    print("Compiling sequence images")
                    filepath = self._compile_sequence(file_path, scratch=scratch)
                    if not filepath:
                        return

                if self.dry_run:
                    # Plan from the source's dimensions without compiling or extracting
                    width, height = self._planning_dims(i, file_path)
                    self._encode_video(file_path, url, i, dims=(width, height))
                    self._encode_images(file_path, url, i, width=width)
                    if self.config["download_button"]:
                        self._create_download_zip(file_path, url, i)
                    return

                self._encode_video(filepath, url, i, scratch=scratch)

                # Extract frame for thumbnail
                image = scratch / "temp.jpg"
                filters = self._item(self.gallery_video_filters, i)
                filter_arg = f",{filters}" if filters else ""
                options = shlex.split(self._item(self.gallery_video_options, i))
                run_ffmpeg(
                    FFMPEG_COMMON
                    + ["-y", "-i", str(filepath), *options]
                    + ["-vf", f"select=gte(n\\,1){filter_arg}", "-vframes", "1"]
                    + ["-qscale:v", "2", str(image)]
                )
                if not image.exists():
                    print(f"\tCould not extract a frame from {file_path.name}; skipping images")
                    return

            self._encode_images(image, url, i)

            if self.config["download_button"]:
                self._create_download_zip(file_path, url, i, scratch=scratch)
        except (OSError, subprocess.CalledProcessError) as e:
            # Unreadable/corrupt source or failed convert: report and continue with the rest
            print(f"\tError encoding {file_path}: {e}")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _planning_dims(self, index: int, file_path: Path) -> tuple[int, int]:
        """Source dimensions for a dry run: probe videos, read a sequence's first frame."""
        if self.gallery_type[index] == 2:
            frames = sorted(f for f in file_path.iterdir() if f.suffix.lower() in _FRAME_KIND)
            if not frames:
                return 0, 0
            return self.image_processor.extract_dimensions(frames[0])
        return self.video_processor.probe(file_path)

    def _sequence_finished(self, url: str, index: int | None = None) -> bool:
        """Check if sequence encoding is already complete.

        Args:
            url: URL path for the sequence.
            index: Gallery index, to also check fingerprints (None: existence only).

        Returns:
            True if all sequence video files exist, are non-empty and up to date.
        """
        for vformat in self.config["video_formats"]:
            for j, res in enumerate(self.config["resolution"]):
                ext = VIDEO_FORMAT_EXTENSIONS.get(vformat, "mp4")
                videofile = self.topdir / "_site" / url / f"{res}-{vformat}.{ext}"
                if index is None:
                    if not is_current(videofile, None, nonempty=True):
                        return False
                    continue
                source = self._source(index)
                fp = self._fingerprint(source, **self._video_settings(index, vformat, res, j))
                if self._needs(videofile, fp, source, nonempty=True):
                    return False
        return True

    def _compile_sequence(self, seq_dir: Path, scratch: Path | None = None) -> Path | None:
        """Compile image sequence to video.

        Args:
            seq_dir: Directory containing sequence images.
            scratch: Scratch directory to use (defaults to the shared scratchdir).

        Returns:
            Path to compiled video, or None if compilation failed.
        """
        scratch = scratch or self.scratchdir
        images = sorted(
            [f for f in seq_dir.iterdir() if f.suffix.lower() in [".jpg", ".jpeg", ".gif", ".png"]]
        )

        if not images:
            return None

        # ffmpeg's image2 demuxer needs sequentially named frames with one extension, and
        # decodes every frame with the codec of the first. Frames that are all one format are
        # copied under a uniform extension (so .JPG/.jpeg/.jpg mix fine); mixed formats are
        # converted to lossless PNG first (expose.sh silently drops the odd frames out).
        kinds = {_FRAME_KIND[img.suffix.lower()] for img in images}
        if len(kinds) == 1:
            ext = f".{kinds.pop()}"
            for j, img in enumerate(images):
                shutil.copy(img, scratch / f"{j:04d}{ext}")
        else:
            ext = ".png"
            for j, img in enumerate(images):
                with Image.open(img) as frame:
                    frame.convert("RGB").save(scratch / f"{j:04d}{ext}")

        sequence_video = scratch / "sequencevideo.mp4"
        maxres = max(self.config["resolution"])

        run_ffmpeg(
            FFMPEG_COMMON
            + ["-f", "image2", "-y", "-i", str(scratch / f"%04d{ext}")]
            + ["-c:v", "libx264", "-threads", str(self.config["ffmpeg_threads"])]
            + ["-vf", f"scale={maxres}:trunc(ow/a/2)*2", "-profile:v", "high"]
            + ["-pix_fmt", "yuv420p", "-preset", self.config["h264_encodespeed"]]
            + ["-crf", "15", "-r", str(self.config["sequence_framerate"])]
            + ["-f", "mp4", str(sequence_video)]
        )

        return sequence_video if sequence_video.exists() else None

    def _encode_video(
        self,
        filepath: Path,
        url: str,
        index: int,
        scratch: Path | None = None,
        dims: tuple[int, int] | None = None,
    ) -> None:
        """Encode video to multiple formats and resolutions.

        Args:
            filepath: Path to source video file.
            url: URL path for output files.
            index: Index into gallery arrays.
            scratch: Scratch directory for 2-pass logs (defaults to the shared scratchdir).
            dims: Known (width, height); probed from ``filepath`` when None.
        """
        scratch = scratch or self.scratchdir
        width, height = dims if dims is not None else self.video_processor.probe(filepath)

        filters = self._item(self.gallery_video_filters, index)
        filters_arg = f",{filters}" if filters else ""
        filters_full = ["-vf", filters] if filters else []
        options = shlex.split(self._item(self.gallery_video_options, index))
        source = self._source(index, filepath)

        audio_args = ["-an"] if self.config["disable_audio"] else ["-c:a", "copy"]

        if self.draft:
            # Draft mode: single pass CRF with ultrafast preset
            res = self.config["resolution"][0]
            output_path = self.topdir / "_site" / url / f"{res}-h264.mp4"

            fp = self._fingerprint(source, **self._video_settings(index, "h264", res, 0))
            reason = self._needs(output_path, fp, source, nonempty=True)
            if reason is None:
                return
            if self.dry_run:
                self._plan(output_path, reason)
                return

            part = part_path(output_path)
            ok = run_ffmpeg(
                FFMPEG_COMMON
                + ["-y", "-i", str(filepath), "-c:v", "libx264"]
                + ["-threads", str(self.config["ffmpeg_threads"]), *options]
                + ["-vf", f"scale={res}:trunc(ow/a/2)*2{filters_arg}"]
                + ["-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
                + ["-crf", "26", *audio_args]
                + ["-movflags", "+faststart", "-f", "mp4", str(part)]
            )
            self._built(output_path, fp, _finalize(part, output_path, ok))
            return

        # Full encode: 2-pass VBR
        encoders = {
            "h264": self._encode_h264,
            "h265": self._encode_h265,
            "vp9": self._encode_vp9,
            "vp8": self._encode_vp8,
        }
        for vformat in self.config["video_formats"]:
            firstpass = False
            passlog = scratch / f"pass-{vformat}"

            for j, res in enumerate(self.config["resolution"]):
                if width < res:
                    continue

                bitrates = self.config["bitrate"]
                mbit = bitrates[j] if j < len(bitrates) else bitrates[-1]
                mbitmax = mbit * self.config["bitrate_maxratio"]
                scaled_height = height * res // width if width else 0

                ext = VIDEO_FORMAT_EXTENSIONS.get(vformat, "mp4")
                output_path = self.topdir / "_site" / url / f"{res}-{vformat}.{ext}"

                fp = self._fingerprint(source, **self._video_settings(index, vformat, res, j))
                reason = self._needs(output_path, fp, source, nonempty=True)
                if reason is None:
                    continue
                if self.dry_run:
                    self._plan(output_path, reason)
                    continue

                print(f"\tEncoding {vformat} {res} x {scaled_height}")

                if vformat in encoders:
                    success = encoders[vformat](
                        filepath,
                        output_path,
                        res,
                        mbit,
                        mbitmax,
                        filters_arg,
                        filters_full,
                        audio_args,
                        firstpass,
                        options=options,
                        passlog=passlog,
                    )
                elif vformat == "ogv":
                    success = self._encode_ogv(
                        filepath,
                        output_path,
                        res,
                        mbit,
                        mbitmax,
                        filters_arg,
                        audio_args,
                        options=options,
                    )
                else:
                    success = True

                if not success:
                    break  # Skip this format entirely

                self._built(output_path, fp)
                firstpass = True

    def _two_pass(
        self,
        filepath: Path,
        output: Path,
        codec: str,
        quality_pass1: list[str],
        quality_pass2: list[str],
        container: str,
        faststart: bool,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        filters_full: list[str],
        audio_args: list[str],
        firstpass: bool,
        options: list[str],
        passlog: Path | None,
    ) -> bool:
        """Run a 2-pass VBR encode, mirroring the expose.sh ffmpeg calls.

        Pass 1 is skipped when ``firstpass`` is True (its stats are reused from the first
        resolution of the same format). Both passes share ``passlog`` so ffmpeg's stats
        files land in the scratch dir instead of the current directory.

        Returns:
            False if either pass failed (the caller skips the remaining resolutions).
        """
        threads = ["-threads", str(self.config["ffmpeg_threads"])]
        rate = ["-b:v", f"{mbit}M", "-maxrate", f"{mbitmax}M", "-bufsize", f"{mbitmax}M"]
        passlog_args = ["-passlogfile", str(passlog or self.scratchdir / "ffmpeg2pass")]

        if not firstpass:
            ok = run_ffmpeg(
                FFMPEG_COMMON
                + ["-y", "-i", str(filepath), "-c:v", codec, *threads, *options, *filters_full]
                + [*quality_pass1, *rate, "-pass", "1", *passlog_args]
                + ["-an", "-f", container, "/dev/null"]
            )
            if not ok:
                return False

        part = part_path(output)
        ok = run_ffmpeg(
            FFMPEG_COMMON
            + ["-y", "-i", str(filepath), "-c:v", codec, *threads, *options]
            + ["-vf", f"scale={res}:trunc(ow/a/2)*2{filters_arg}"]
            + [*quality_pass2, *rate, "-pass", "2", *passlog_args, *audio_args]
            + (["-movflags", "+faststart"] if faststart else [])
            + ["-f", container, str(part)]
        )
        return _finalize(part, output, ok)

    def _encode_h264(
        self,
        filepath: Path,
        output: Path,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        filters_full: list[str],
        audio_args: list[str],
        firstpass: bool,
        options: Sequence[str] = (),
        passlog: Path | None = None,
    ) -> bool:
        """Encode h264 video with 2-pass. See ``_two_pass`` for arguments."""
        quality = ["-profile:v", "high", "-pix_fmt", "yuv420p"]
        quality += ["-preset", self.config["h264_encodespeed"]]
        return self._two_pass(
            filepath, output, "libx264", quality, quality, "mp4", True, res, mbit, mbitmax,
            filters_arg, filters_full, audio_args, firstpass, list(options), passlog,
        )  # fmt: skip

    def _encode_h265(
        self,
        filepath: Path,
        output: Path,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        filters_full: list[str],
        audio_args: list[str],
        firstpass: bool,
        options: Sequence[str] = (),
        passlog: Path | None = None,
    ) -> bool:
        """Encode h265 video with 2-pass. See ``_two_pass`` for arguments."""
        quality = ["-pix_fmt", "yuv420p", "-preset", self.config["h264_encodespeed"]]
        return self._two_pass(
            filepath, output, "libx265", quality, quality, "mp4", True, res, mbit, mbitmax,
            filters_arg, filters_full, audio_args, firstpass, list(options), passlog,
        )  # fmt: skip

    def _encode_vp9(
        self,
        filepath: Path,
        output: Path,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        filters_full: list[str],
        audio_args: list[str],
        firstpass: bool,
        options: Sequence[str] = (),
        passlog: Path | None = None,
    ) -> bool:
        """Encode VP9 video with 2-pass. See ``_two_pass`` for arguments."""
        pass1 = ["-pix_fmt", "yuv420p", "-speed", "4"]
        pass2 = ["-pix_fmt", "yuv420p", "-speed", str(self.config["vp9_encodespeed"])]
        return self._two_pass(
            filepath, output, "libvpx-vp9", pass1, pass2, "webm", False, res, mbit, mbitmax,
            filters_arg, filters_full, audio_args, firstpass, list(options), passlog,
        )  # fmt: skip

    def _encode_vp8(
        self,
        filepath: Path,
        output: Path,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        filters_full: list[str],
        audio_args: list[str],
        firstpass: bool,
        options: Sequence[str] = (),
        passlog: Path | None = None,
    ) -> bool:
        """Encode VP8 video with 2-pass. See ``_two_pass`` for arguments."""
        quality = ["-pix_fmt", "yuv420p"]
        return self._two_pass(
            filepath, output, "libvpx", quality, quality, "webm", False, res, mbit, mbitmax,
            filters_arg, filters_full, audio_args, firstpass, list(options), passlog,
        )  # fmt: skip

    def _encode_ogv(
        self,
        filepath: Path,
        output: Path,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        audio_args: list[str],
        options: Sequence[str] = (),
    ) -> bool:
        """Encode Theora video (1-pass).

        Args:
            filepath: Source video path.
            output: Output video path.
            res: Target resolution.
            mbit: Target bitrate in Mbps.
            mbitmax: Maximum bitrate in Mbps.
            filters_arg: Filter arguments string.
            audio_args: Audio encoding args.
            options: Extra ffmpeg options from ``video-options`` metadata.

        Returns:
            True if encoding succeeded.
        """
        part = part_path(output)
        ok = run_ffmpeg(
            FFMPEG_COMMON
            + ["-y", "-i", str(filepath), "-c:v", "libtheora"]
            + ["-threads", str(self.config["ffmpeg_threads"]), *options]
            + ["-vf", f"scale={res}:trunc(ow/a/2)*2{filters_arg}", "-pix_fmt", "yuv420p"]
            + ["-b:v", f"{mbit}M", "-maxrate", f"{mbitmax}M", "-bufsize", f"{mbitmax}M"]
            + [*audio_args, str(part)]
        )
        return _finalize(part, output, ok)

    def _encode_images(self, image: Path, url: str, index: int, width: int | None = None) -> None:
        """Generate static images for each resolution.

        Args:
            image: Source image path.
            url: URL path for output files.
            index: Index into gallery arrays.
            width: Known source width (read from ``image`` when None).
        """
        if width is None:
            width_str = self.image_processor.identify(image, "%w")
            width = int(width_str) if width_str else 0

        gtype = self._item(self.gallery_type, index, 0)
        # Image options are ImageMagick arguments; never applied to video thumbnails
        options = self._item(self.gallery_image_options, index) if gtype != 1 else ""
        extra_args = shlex.split(options)

        source = self._source(index, image)
        resolutions = self.config["resolution"]
        settings = {
            "kind": "image",
            "quality": self.config["jpeg_quality"],
            "autorotate": self.autorotate,
            "options": options,
            "backend": "imagemagick" if extra_args and shutil.which("convert") else "pillow",
        }
        if gtype != 0:
            # Thumbnails are grabbed from the (filtered) video
            settings["video_filters"] = self._item(self.gallery_video_filters, index)
            settings["video_options"] = self._item(self.gallery_video_options, index)

        for count, res in enumerate(resolutions, 1):
            output_path = self.topdir / "_site" / url / f"{res}.jpg"

            fp = self._fingerprint(source, res=res, **settings)
            reason = self._needs(output_path, fp, source)
            if reason is None:
                continue

            # Only downscale or use smallest resolution
            if width >= res or count == len(resolutions):
                if self.dry_run:
                    self._plan(output_path, reason)
                    continue
                part = part_path(output_path)
                try:
                    self.image_processor.resize(
                        image,
                        part,
                        width=res,
                        quality=self.config["jpeg_quality"],
                        auto_orient=self.autorotate,
                        additional_args=extra_args,
                    )
                except BaseException:
                    part.unlink(missing_ok=True)
                    raise
                self._built(output_path, fp, _finalize(part, output_path, True))

    def _create_download_zip(
        self, file_path: Path, url: str, index: int, scratch: Path | None = None
    ) -> None:
        """Create ZIP file for download.

        Args:
            file_path: Source file path.
            url: URL path for output.
            index: Index into gallery arrays.
            scratch: Scratch directory (defaults to the shared scratchdir).
        """
        scratch = scratch or self.scratchdir
        zip_path = self.topdir / "_site" / url / f"{self.gallery_url[index]}.zip"

        fp = self._fingerprint(file_path, kind="zip", readme=self.config["download_readme"])
        reason = self._needs(zip_path, fp, file_path)
        if reason is None:
            return
        if self.dry_run:
            self._plan(zip_path, reason)
            return

        zip_dir = scratch / "zip"
        zip_dir.mkdir(exist_ok=True)

        if self.gallery_type[index] == 2:
            # For sequences, use the compiled video
            filezip = scratch / "sequencevideo.mp4"
            if not filezip.exists():
                filezip = file_path
        else:
            filezip = file_path

        shutil.copy(filezip, zip_dir / filezip.name)

        # Write readme
        (zip_dir / "readme.txt").write_text(self.config["download_readme"], encoding="utf-8")

        # Create zip using stdlib (flat structure, no ./ prefix)
        part = part_path(zip_path)
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in zip_dir.iterdir():
                zf.write(f, f.name)
        self._built(zip_path, fp, _finalize(part, zip_path, True))

    def cleanup(self) -> None:
        """Clean up temporary files."""
        if self.scratchdir.exists():
            shutil.rmtree(self.scratchdir, ignore_errors=True)
