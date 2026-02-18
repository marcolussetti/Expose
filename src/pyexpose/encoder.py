"""Media encoding orchestrator.

Handles encoding of images and videos to multiple resolutions and formats.
"""

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from pyexpose.config import Config
from pyexpose.media.image import ImageProcessor
from pyexpose.media.video import VideoProcessor

# Video format extensions
VIDEO_FORMAT_EXTENSIONS = {"h264": "mp4", "h265": "mp4", "vp9": "webm", "vp8": "webm", "ogv": "ogv"}


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
            gallery_image_options: ImageMagick options per gallery.
            gallery_video_filters: FFmpeg filters per gallery.
            nav_url: Navigation URLs.
            scratchdir: Optional existing scratch directory to reuse.
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
        self.gallery_video_filters = gallery_video_filters
        self.nav_url = nav_url

        # Initialize processors
        self.image_processor = ImageProcessor()
        self.video_processor = VideoProcessor()

        # Use provided scratch directory or create a new one
        self.scratchdir = Path(scratchdir) if scratchdir else Path(tempfile.mkdtemp())

        # Track current output URL for display
        self.output_url = None

        # Setup autorotate option
        self.autorotate_option = "-auto-orient" if config["autorotate"] else ""

    def encode_media(self):
        """Encode all images and videos."""
        print("Starting encode")

        for i, file_path in enumerate(self.gallery_files):
            print(self.gallery_url[i])

            navindex = self.gallery_nav[i]
            url = f"{self.nav_url[navindex]}/{self.gallery_url[i]}"

            output_dir = self.topdir / "_site" / url
            output_dir.mkdir(parents=True, exist_ok=True)

            if self.gallery_type[i] == 0:
                # Regular image
                image = file_path
            else:
                # Video or sequence
                filepath = file_path

                if self.gallery_type[i] == 2:
                    # Compile image sequence to video
                    if self._sequence_finished(url):
                        continue

                    print("Compiling sequence images")
                    filepath = self._compile_sequence(file_path)
                    if not filepath:
                        continue

                # Encode video
                self._encode_video(filepath, url, i)

                # Extract frame for thumbnail
                temp_path = self.scratchdir / "temp.jpg"
                filters = self.gallery_video_filters[i]
                filter_arg = f",{filters}" if filters else ""

                subprocess.run(
                    [
                        "ffmpeg",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-y",
                        "-i",
                        str(filepath),
                        "-vf",
                        f"select=gte(n\\,1){filter_arg}",
                        "-vframes",
                        "1",
                        "-qscale:v",
                        "2",
                        str(temp_path),
                    ],
                    stdin=subprocess.DEVNULL,
                )
                image = temp_path

            # Generate static images for each resolution
            self._encode_images(image, url, i)

            # Write zip file if download enabled
            if self.config["download_button"]:
                self._create_download_zip(file_path, url, i)

            # Clean scratch directory
            for f in self.scratchdir.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f)

    def _sequence_finished(self, url: str) -> bool:
        """Check if sequence encoding is already complete.

        Args:
            url: URL path for the sequence.

        Returns:
            True if all sequence video files exist and are non-empty.
        """
        for res in self.config["resolution"]:
            for vformat in self.config["video_formats"]:
                ext = VIDEO_FORMAT_EXTENSIONS.get(vformat, "mp4")
                videofile = self.topdir / "_site" / url / f"{res}-{vformat}.{ext}"
                if not videofile.exists() or videofile.stat().st_size == 0:
                    return False
        return True

    def _compile_sequence(self, seq_dir: Path) -> Path | None:
        """Compile image sequence to video.

        Args:
            seq_dir: Directory containing sequence images.

        Returns:
            Path to compiled video, or None if compilation failed.
        """
        # Copy files to scratch with sequential names
        images = sorted(
            [f for f in seq_dir.iterdir() if f.suffix.lower() in [".jpg", ".jpeg", ".gif", ".png"]]
        )

        if not images:
            return None

        for j, img in enumerate(images):
            shutil.copy(img, self.scratchdir / f"{j:04d}{img.suffix}")

        sequence_video = self.scratchdir / "sequencevideo.mp4"
        maxres = max(self.config["resolution"])

        # Get extension of first image for input pattern
        first_ext = images[0].suffix

        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-f",
                "image2",
                "-y",
                "-i",
                str(self.scratchdir / f"%04d{first_ext}"),
                "-c:v",
                "libx264",
                "-threads",
                str(self.config["ffmpeg_threads"]),
                "-vf",
                f"scale={maxres}:trunc(ow/a/2)*2",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                self.config["h264_encodespeed"],
                "-crf",
                "15",
                "-r",
                str(self.config["sequence_framerate"]),
                "-f",
                "mp4",
                str(sequence_video),
            ]
        )

        return sequence_video if sequence_video.exists() else None

    def _encode_video(self, filepath: Path, url: str, index: int):
        """Encode video to multiple formats and resolutions.

        Args:
            filepath: Path to source video file.
            url: URL path for output files.
            index: Index into gallery arrays.
        """
        # Get video dimensions
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-of",
                "flat=s=_",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                str(filepath),
            ],
            capture_output=True,
            text=True,
        )

        dimensions = {}
        for line in result.stdout.split("\n"):
            if "width" in line:
                dimensions["width"] = int(line.split("=")[1])
            elif "height" in line:
                dimensions["height"] = int(line.split("=")[1])

        width = dimensions.get("width", 0)
        height = dimensions.get("height", 0)

        filters = self.gallery_video_filters[index]
        filters_arg = f",{filters}" if filters else ""
        filters_full = ["-vf", filters] if filters else []

        audio_args = ["-an"] if self.config["disable_audio"] else ["-c:a", "copy"]

        if self.draft:
            # Draft mode: single pass CRF with ultrafast preset
            res = self.config["resolution"][0]
            output_path = self.topdir / "_site" / url / f"{res}-h264.mp4"

            if output_path.exists() and output_path.stat().st_size > 0:
                return

            self.output_url = str(output_path)

            cmd = (
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-i",
                    str(filepath),
                    "-c:v",
                    "libx264",
                    "-threads",
                    str(self.config["ffmpeg_threads"]),
                    "-vf",
                    f"scale={res}:trunc(ow/a/2)*2{filters_arg}",
                    "-profile:v",
                    "high",
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "26",
                ]
                + audio_args
                + ["-movflags", "+faststart", "-f", "mp4", str(output_path)]
            )
            subprocess.run(cmd)
            self.output_url = None
        else:
            # Full encode: 2-pass VBR
            for vformat in self.config["video_formats"]:
                firstpass = False

                for j, res in enumerate(self.config["resolution"]):
                    if width < res:
                        continue

                    mbit = (
                        self.config["bitrate"][j]
                        if j < len(self.config["bitrate"])
                        else self.config["bitrate"][-1]
                    )
                    mbitmax = mbit * self.config["bitrate_maxratio"]
                    scaled_height = height * res // width if width else 0

                    ext = VIDEO_FORMAT_EXTENSIONS.get(vformat, "mp4")
                    videofile = f"{res}-{vformat}.{ext}"
                    output_path = self.topdir / "_site" / url / videofile

                    if output_path.exists() and output_path.stat().st_size > 0:
                        continue

                    self.output_url = str(output_path)
                    print(f"\tEncoding {vformat} {res} x {scaled_height}")

                    if vformat == "h265":
                        success = self._encode_h265(
                            filepath,
                            output_path,
                            res,
                            mbit,
                            mbitmax,
                            filters_arg,
                            filters_full,
                            audio_args,
                            firstpass,
                        )
                    elif vformat == "h264":
                        success = self._encode_h264(
                            filepath,
                            output_path,
                            res,
                            mbit,
                            mbitmax,
                            filters_arg,
                            filters_full,
                            audio_args,
                            firstpass,
                        )
                    elif vformat == "vp9":
                        success = self._encode_vp9(
                            filepath,
                            output_path,
                            res,
                            mbit,
                            mbitmax,
                            filters_arg,
                            filters_full,
                            audio_args,
                            firstpass,
                        )
                    elif vformat == "vp8":
                        success = self._encode_vp8(
                            filepath,
                            output_path,
                            res,
                            mbit,
                            mbitmax,
                            filters_arg,
                            filters_full,
                            audio_args,
                            firstpass,
                        )
                    elif vformat == "ogv":
                        self._encode_ogv(
                            filepath, output_path, res, mbit, mbitmax, filters_arg, audio_args
                        )
                        success = True
                    else:
                        success = True

                    if not success:
                        break  # Skip this format entirely

                    if not firstpass:
                        firstpass = True

                    self.output_url = None

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
    ) -> bool:
        """Encode h264 video with 2-pass.

        Args:
            filepath: Source video path.
            output: Output video path.
            res: Target resolution.
            mbit: Target bitrate in Mbps.
            mbitmax: Maximum bitrate in Mbps.
            filters_arg: Filter arguments string.
            filters_full: Full filter command args.
            audio_args: Audio encoding args.
            firstpass: Whether this is the first pass.

        Returns:
            True if encoding succeeded, False otherwise.
        """
        if not firstpass:
            cmd = (
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(filepath),
                    "-c:v",
                    "libx264",
                    "-threads",
                    str(self.config["ffmpeg_threads"]),
                ]
                + filters_full
                + [
                    "-profile:v",
                    "high",
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    self.config["h264_encodespeed"],
                    "-b:v",
                    f"{mbit}M",
                    "-maxrate",
                    f"{mbitmax}M",
                    "-bufsize",
                    f"{mbitmax}M",
                    "-pass",
                    "1",
                    "-an",
                    "-f",
                    "mp4",
                    "/dev/null",
                ]
            )
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = (
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(filepath),
                "-c:v",
                "libx264",
                "-threads",
                str(self.config["ffmpeg_threads"]),
                "-vf",
                f"scale={res}:trunc(ow/a/2)*2{filters_arg}",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                self.config["h264_encodespeed"],
                "-b:v",
                f"{mbit}M",
                "-maxrate",
                f"{mbitmax}M",
                "-bufsize",
                f"{mbitmax}M",
                "-pass",
                "2",
            ]
            + audio_args
            + ["-movflags", "+faststart", "-f", "mp4", str(output)]
        )
        subprocess.run(cmd)
        return True

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
    ) -> bool:
        """Encode h265 video with 2-pass.

        Args:
            filepath: Source video path.
            output: Output video path.
            res: Target resolution.
            mbit: Target bitrate in Mbps.
            mbitmax: Maximum bitrate in Mbps.
            filters_arg: Filter arguments string.
            filters_full: Full filter command args.
            audio_args: Audio encoding args.
            firstpass: Whether this is the first pass.

        Returns:
            True if encoding succeeded, False otherwise.
        """
        if not firstpass:
            cmd = (
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(filepath),
                    "-c:v",
                    "libx265",
                    "-threads",
                    str(self.config["ffmpeg_threads"]),
                ]
                + filters_full
                + [
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    self.config["h264_encodespeed"],
                    "-b:v",
                    f"{mbit}M",
                    "-maxrate",
                    f"{mbitmax}M",
                    "-bufsize",
                    f"{mbitmax}M",
                    "-pass",
                    "1",
                    "-an",
                    "-f",
                    "mp4",
                    "/dev/null",
                ]
            )
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = (
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(filepath),
                "-c:v",
                "libx265",
                "-threads",
                str(self.config["ffmpeg_threads"]),
                "-vf",
                f"scale={res}:trunc(ow/a/2)*2{filters_arg}",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                self.config["h264_encodespeed"],
                "-b:v",
                f"{mbit}M",
                "-maxrate",
                f"{mbitmax}M",
                "-bufsize",
                f"{mbitmax}M",
                "-pass",
                "2",
            ]
            + audio_args
            + ["-movflags", "+faststart", "-f", "mp4", str(output)]
        )
        subprocess.run(cmd)
        return True

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
    ) -> bool:
        """Encode VP9 video with 2-pass.

        Args:
            filepath: Source video path.
            output: Output video path.
            res: Target resolution.
            mbit: Target bitrate in Mbps.
            mbitmax: Maximum bitrate in Mbps.
            filters_arg: Filter arguments string.
            filters_full: Full filter command args.
            audio_args: Audio encoding args.
            firstpass: Whether this is the first pass.

        Returns:
            True if encoding succeeded, False otherwise.
        """
        if not firstpass:
            cmd = (
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(filepath),
                    "-c:v",
                    "libvpx-vp9",
                    "-threads",
                    str(self.config["ffmpeg_threads"]),
                ]
                + filters_full
                + [
                    "-pix_fmt",
                    "yuv420p",
                    "-speed",
                    "4",
                    "-b:v",
                    f"{mbit}M",
                    "-maxrate",
                    f"{mbitmax}M",
                    "-bufsize",
                    f"{mbitmax}M",
                    "-pass",
                    "1",
                    "-an",
                    "-f",
                    "webm",
                    "/dev/null",
                ]
            )
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = (
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(filepath),
                "-c:v",
                "libvpx-vp9",
                "-threads",
                str(self.config["ffmpeg_threads"]),
                "-vf",
                f"scale={res}:trunc(ow/a/2)*2{filters_arg}",
                "-pix_fmt",
                "yuv420p",
                "-speed",
                str(self.config["vp9_encodespeed"]),
                "-b:v",
                f"{mbit}M",
                "-maxrate",
                f"{mbitmax}M",
                "-bufsize",
                f"{mbitmax}M",
                "-pass",
                "2",
            ]
            + audio_args
            + ["-f", "webm", str(output)]
        )
        subprocess.run(cmd)
        return True

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
    ) -> bool:
        """Encode VP8 video with 2-pass.

        Args:
            filepath: Source video path.
            output: Output video path.
            res: Target resolution.
            mbit: Target bitrate in Mbps.
            mbitmax: Maximum bitrate in Mbps.
            filters_arg: Filter arguments string.
            filters_full: Full filter command args.
            audio_args: Audio encoding args.
            firstpass: Whether this is the first pass.

        Returns:
            True if encoding succeeded, False otherwise.
        """
        if not firstpass:
            cmd = (
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(filepath),
                    "-c:v",
                    "libvpx",
                    "-threads",
                    str(self.config["ffmpeg_threads"]),
                ]
                + filters_full
                + [
                    "-pix_fmt",
                    "yuv420p",
                    "-b:v",
                    f"{mbit}M",
                    "-maxrate",
                    f"{mbitmax}M",
                    "-bufsize",
                    f"{mbitmax}M",
                    "-pass",
                    "1",
                    "-an",
                    "-f",
                    "webm",
                    "/dev/null",
                ]
            )
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = (
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(filepath),
                "-c:v",
                "libvpx",
                "-threads",
                str(self.config["ffmpeg_threads"]),
                "-vf",
                f"scale={res}:trunc(ow/a/2)*2{filters_arg}",
                "-pix_fmt",
                "yuv420p",
                "-b:v",
                f"{mbit}M",
                "-maxrate",
                f"{mbitmax}M",
                "-bufsize",
                f"{mbitmax}M",
                "-pass",
                "2",
            ]
            + audio_args
            + ["-f", "webm", str(output)]
        )
        subprocess.run(cmd)
        return True

    def _encode_ogv(
        self,
        filepath: Path,
        output: Path,
        res: int,
        mbit: float,
        mbitmax: float,
        filters_arg: str,
        audio_args: list[str],
    ):
        """Encode Theora video (1-pass).

        Args:
            filepath: Source video path.
            output: Output video path.
            res: Target resolution.
            mbit: Target bitrate in Mbps.
            mbitmax: Maximum bitrate in Mbps.
            filters_arg: Filter arguments string.
            audio_args: Audio encoding args.
        """
        cmd = (
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(filepath),
                "-c:v",
                "libtheora",
                "-threads",
                str(self.config["ffmpeg_threads"]),
                "-vf",
                f"scale={res}:trunc(ow/a/2)*2{filters_arg}",
                "-pix_fmt",
                "yuv420p",
                "-b:v",
                f"{mbit}M",
                "-maxrate",
                f"{mbitmax}M",
                "-bufsize",
                f"{mbitmax}M",
            ]
            + audio_args
            + [str(output)]
        )
        subprocess.run(cmd)

    def _encode_images(self, image: Path, url: str, index: int):
        """Generate static images for each resolution.

        Args:
            image: Source image path.
            url: URL path for output files.
            index: Index into gallery arrays.
        """
        width_str = self.image_processor.identify(image, "%w")
        width = int(width_str) if width_str else 0

        options = self.gallery_image_options[index]

        # Don't apply image options to videos
        if self.gallery_type[index] == 1:
            options = ""

        resolutions = self.config["resolution"]

        for count, res in enumerate(resolutions, 1):
            output_path = self.topdir / "_site" / url / f"{res}.jpg"

            if output_path.exists():
                continue

            # Only downscale or use smallest resolution
            if width >= res or count == len(resolutions):
                cmd = ["convert"]
                if self.autorotate_option.strip():
                    cmd.append("-auto-orient")
                cmd.extend(
                    [
                        "-size",
                        f"{res}x{res}",
                        str(image),
                        "-resize",
                        f"{res}x{res}",
                        "-quality",
                        str(self.config["jpeg_quality"]),
                        "+profile",
                        "*",
                    ]
                )
                if options:
                    cmd.extend(options.split())
                cmd.append(str(output_path))

                subprocess.run(cmd)

    def _create_download_zip(self, file_path: Path, url: str, index: int):
        """Create ZIP file for download.

        Args:
            file_path: Source file path.
            url: URL path for output.
            index: Index into gallery arrays.
        """
        zip_path = self.topdir / "_site" / url / f"{self.gallery_url[index]}.zip"

        if zip_path.exists():
            return

        zip_dir = self.scratchdir / "zip"
        zip_dir.mkdir(exist_ok=True)

        if self.gallery_type[index] == 2:
            # For sequences, use the compiled video
            filezip = self.scratchdir / "sequencevideo.mp4"
            if not filezip.exists():
                filezip = file_path
        else:
            filezip = file_path

        filename = filezip.name
        shutil.copy(filezip, zip_dir / filename)

        # Write readme
        (zip_dir / "readme.txt").write_text(self.config["download_readme"])

        # Create zip using stdlib (flat structure, no ./ prefix)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in zip_dir.iterdir():
                zf.write(f, f.name)

    def cleanup(self):
        """Clean up temporary files."""
        if self.scratchdir.exists():
            shutil.rmtree(self.scratchdir, ignore_errors=True)
