"""Tests for download ZIP functionality."""

import zipfile

from expose import DEFAULT_CONFIG, ExposeGenerator
from tests.conftest import SCRIPTDIR, make_test_image


def make_generator_with_download(tmp_path):
    """Create a generator with download_button enabled."""
    config = dict(DEFAULT_CONFIG)
    config["download_button"] = True
    config["download_readme"] = "Test license text"
    return ExposeGenerator(tmp_path, SCRIPTDIR, config, draft=True)


class TestDownloadZip:
    """Tests for _create_download_zip method."""

    def test_create_download_zip_image(self, tmp_path):
        """Test ZIP creation for a regular image."""
        # Create test gallery with image
        gallery_dir = tmp_path / "test-gallery"
        gallery_dir.mkdir()
        image_path = gallery_dir / "photo.jpg"
        make_test_image(image_path, 800, 600, "blue")

        gen = make_generator_with_download(tmp_path)
        gen.paths = [gallery_dir]
        gen.nav_name = ["Test Gallery"]
        gen.nav_depth = [0]
        gen.nav_type = [1]  # Leaf gallery
        gen.nav_url = ["test-gallery"]
        gen.nav_count = [1]
        gen.gallery_files = [image_path]
        gen.gallery_nav = [0]
        gen.gallery_url = ["photo"]
        gen.gallery_type = [0]  # Image
        gen.gallery_maxwidth = [800]
        gen.gallery_maxheight = [600]
        gen.gallery_colors = [
            ["#000000", "#222222", "#444444", "#666666", "#999999", "#cccccc", "#ffffff"]
        ]
        gen.gallery_image_options = [""]
        gen.gallery_video_options = [""]
        gen.gallery_video_filters = [""]

        # Create output directory
        output_dir = tmp_path / "_site" / "test-gallery" / "photo"
        output_dir.mkdir(parents=True)

        # Create ZIP
        gen._create_download_zip(image_path, "test-gallery/photo", 0)

        # Verify ZIP was created
        zip_path = output_dir / "photo.zip"
        assert zip_path.exists()

        # Verify ZIP contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            files = zf.namelist()
            assert "photo.jpg" in files or "./photo.jpg" in files
            assert "readme.txt" in files or "./readme.txt" in files

            # Check readme content
            readme_content = zf.read("readme.txt").decode("utf-8")
            assert readme_content == "Test license text"

        gen.cleanup()

    def test_create_download_zip_skips_existing(self, tmp_path):
        """Test ZIP creation is skipped if file already exists."""
        gallery_dir = tmp_path / "test-gallery"
        gallery_dir.mkdir()
        image_path = gallery_dir / "photo.jpg"
        make_test_image(image_path, 800, 600, "blue")

        gen = make_generator_with_download(tmp_path)
        gen.gallery_url = ["photo"]
        gen.gallery_type = [0]

        # Create output directory and pre-existing ZIP
        output_dir = tmp_path / "_site" / "test-gallery" / "photo"
        output_dir.mkdir(parents=True)
        zip_path = output_dir / "photo.zip"
        zip_path.write_text("existing content")

        # Try to create ZIP again
        gen._create_download_zip(image_path, "test-gallery/photo", 0)

        # ZIP should not be modified
        assert zip_path.read_text() == "existing content"

        gen.cleanup()

    def test_create_download_zip_video(self, tmp_path):
        """Test ZIP creation for a video file."""
        gallery_dir = tmp_path / "test-gallery"
        gallery_dir.mkdir()
        video_path = gallery_dir / "video.mp4"
        video_path.write_text("fake video content")

        gen = make_generator_with_download(tmp_path)
        gen.gallery_url = ["video"]
        gen.gallery_type = [1]  # Video

        # Create output directory
        output_dir = tmp_path / "_site" / "test-gallery" / "video"
        output_dir.mkdir(parents=True)

        # Create ZIP
        gen._create_download_zip(video_path, "test-gallery/video", 0)

        # Verify ZIP was created
        zip_path = output_dir / "video.zip"
        assert zip_path.exists()

        with zipfile.ZipFile(zip_path, "r") as zf:
            files = zf.namelist()
            assert "video.mp4" in files or "./video.mp4" in files

        gen.cleanup()
