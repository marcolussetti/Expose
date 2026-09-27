"""Items and galleries whose names map to the same URL (#8), and EXIF capture times."""

import os
from datetime import datetime

from PIL import Image

from dorothea.media.exif import read_photo_info
from dorothea.utils import unique_slugs
from tests.conftest import make_generator, make_test_image


def photo(path, color, taken=None, digitized=None, modified=None):
    """Write a JPEG, optionally with EXIF DateTimeOriginal / DateTimeDigitized / DateTime."""
    exif = Image.Exif()
    if modified:
        exif[0x0132] = modified  # base DateTime (set by editors on export)
    sub = exif.get_ifd(0x8769)
    if taken:
        sub[0x9003] = taken  # DateTimeOriginal
    if digitized:
        sub[0x9004] = digitized  # DateTimeDigitized
    Image.new("RGB", (1200, 900), color).save(path, exif=exif)


def pixel(path):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel((10, 10))


def build(topdir):
    gen = make_generator(topdir)
    gen.run()
    return gen


class TestUniqueSlugs:
    def test_no_duplicates_unchanged(self):
        assert unique_slugs(["a", "b", "c"], [3, 2, 1]) == ["a", "b", "c"]

    def test_lowest_rank_keeps_the_slug(self):
        assert unique_slugs(["photo", "photo", "photo"], [30, 10, 20]) == [
            "photo-3",
            "photo",
            "photo-2",
        ]

    def test_ties_keep_folder_order(self):
        assert unique_slugs(["x", "x"], [0, 0]) == ["x", "x-2"]

    def test_suffixes_skip_existing_names(self):
        assert unique_slugs(["photo", "photo-2", "photo"], [1, 0, 2]) == [
            "photo",
            "photo-2",
            "photo-3",
        ]


class TestCaptureTime:
    def test_date_time_original(self, tmp_path):
        photo(tmp_path / "a.jpg", "red", taken="2022:09:23 08:17:33")
        expected = datetime(2022, 9, 23, 8, 17, 33).timestamp()
        assert read_photo_info(tmp_path / "a.jpg").capture_time == expected

    def test_falls_back_to_digitized(self, tmp_path):
        photo(tmp_path / "a.jpg", "red", digitized="2021:01:02 03:04:05")
        expected = datetime(2021, 1, 2, 3, 4, 5).timestamp()
        assert read_photo_info(tmp_path / "a.jpg").capture_time == expected

    def test_ignores_export_time(self, tmp_path):
        """The base DateTime tag is when the file was last edited, not when it was taken."""
        photo(tmp_path / "a.jpg", "red", modified="2023:02:21 20:25:14")
        assert read_photo_info(tmp_path / "a.jpg").capture_time is None

    def test_no_exif_or_not_an_image(self, tmp_path):
        make_test_image(tmp_path / "plain.jpg")
        (tmp_path / "notes.txt").write_text("hello")
        assert read_photo_info(tmp_path / "plain.jpg").capture_time is None
        assert read_photo_info(tmp_path / "notes.txt").capture_time is None
        assert read_photo_info(tmp_path / "missing.jpg").capture_time is None


class TestItemCollisions:
    def test_earlier_capture_keeps_the_url(self, tmp_path, capsys):
        g = tmp_path / "g"
        g.mkdir()
        photo(g / "01 photo.jpg", "red", taken="2021:06:01 12:00:00")
        photo(g / "02 photo.jpg", "blue", taken="2020:06:01 12:00:00")  # taken first

        gen = build(tmp_path)

        site = tmp_path / "_site" / "g"
        assert pixel(site / "photo" / "1024.jpg")[2] > 200  # blue: the earlier photo
        assert pixel(site / "photo-2" / "1024.jpg")[0] > 200  # red
        assert sorted(gen.gallery_url) == ["photo", "photo-2"]
        page = (site / "index.html").read_text()
        assert 'data-url="photo"' in page and 'data-url="photo-2"' in page
        assert "same URL as another item ('photo'); using 'photo-2'" in capsys.readouterr().out

    def test_file_time_when_no_exif(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "01 photo.jpg", 1200, 900, "red")
        make_test_image(g / "02 photo.jpg", 1200, 900, "blue")
        os.utime(g / "01 photo.jpg", (2_000_000_000, 2_000_000_000))
        os.utime(g / "02 photo.jpg", (1_000_000_000, 1_000_000_000))  # older file

        build(tmp_path)

        assert pixel(tmp_path / "_site" / "g" / "photo" / "1024.jpg")[2] > 200  # blue

    def test_case_and_extension_collisions(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        photo(g / "Photo.jpg", "red", taken="2020:01:01 00:00:00")
        Image.new("RGB", (1200, 900), "blue").save(g / "photo.png")
        os.utime(g / "photo.png", (2_000_000_000, 2_000_000_000))

        build(tmp_path)

        site = tmp_path / "_site" / "g"
        assert (site / "photo" / "1024.jpg").exists()
        assert (site / "photo-2" / "1024.jpg").exists()

    def test_real_photo_2_keeps_its_name(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        photo(g / "01 photo.jpg", "red", taken="2020:01:01 00:00:00")
        photo(g / "02 photo.jpg", "blue", taken="2021:01:01 00:00:00")
        # "photo 2" is the name that slugs to photo-2 (hyphens are stripped, like expose.sh)
        photo(g / "photo 2.jpg", "green", taken="2019:01:01 00:00:00")

        gen = build(tmp_path)

        assert sorted(gen.gallery_url) == ["photo", "photo-2", "photo-3"]
        site = tmp_path / "_site" / "g"
        assert pixel(site / "photo-2" / "1024.jpg")[1] > 100  # green: the real "photo 2.jpg"
        assert pixel(site / "photo-3" / "1024.jpg")[2] > 200  # blue

    def test_stable_across_builds(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        photo(g / "01 photo.jpg", "red", taken="2021:01:01 00:00:00")
        photo(g / "02 photo.jpg", "blue", taken="2020:01:01 00:00:00")
        first = list(build(tmp_path).gallery_url)
        gen = make_generator(tmp_path)
        gen.dry_run = gen.scanner.dry_run = True
        gen.run()
        assert list(gen.gallery_url) == first
        assert gen.planned == []  # nothing to rebuild


class TestGalleryCollisions:
    def test_sibling_galleries_get_distinct_urls(self, tmp_path, capsys):
        for folder, color in [("01 Iceland", "red"), ("02 Iceland", "blue")]:
            (tmp_path / folder).mkdir()
            make_test_image(tmp_path / folder / "shot.jpg", 1200, 900, color)

        build(tmp_path)

        site = tmp_path / "_site"
        assert pixel(site / "iceland" / "shot" / "1024.jpg")[0] > 200  # red: first in order
        assert pixel(site / "iceland-2" / "shot" / "1024.jpg")[2] > 200
        index = (site / "index.html").read_text()
        assert 'href="./iceland"' in index and 'href="./iceland-2"' in index
        assert "using 'iceland-2'" in capsys.readouterr().out

    def test_same_name_in_different_sections_is_fine(self, tmp_path, capsys):
        for section in ("2021", "2022"):
            (tmp_path / section / "Iceland").mkdir(parents=True)
            make_test_image(tmp_path / section / "Iceland" / "shot.jpg")

        build(tmp_path)

        assert (tmp_path / "_site" / "2021" / "iceland" / "shot" / "1024.jpg").exists()
        assert (tmp_path / "_site" / "2022" / "iceland" / "shot" / "1024.jpg").exists()
        assert "Warning" not in capsys.readouterr().out
