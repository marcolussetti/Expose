"""Whole-gallery zip downloads (#9)."""

import os
import zipfile

import pytest

from dorothea.album import album_zip_name, human_size
from dorothea.cli import format_plan
from dorothea.config import DEFAULT_CONFIG, Config, ConfigError
from tests.conftest import make_generator, make_test_image


def gallery(root, name, photos=("a.jpg", "b.jpg"), metadata=None):
    folder = root / name
    folder.mkdir(parents=True)
    for photo in photos:
        make_test_image(folder / photo, 64, 48, "blue")
    if metadata is not None:
        (folder / "metadata.txt").write_text(metadata, encoding="utf-8")
    return folder


def build(topdir, album=True, dry_run=False, draft=False, **overrides):
    # Not draft by default: draft mode builds no album zips
    gen = make_generator(topdir, {"download_album": album, **overrides}, draft=draft)
    gen.dry_run = gen.scanner.dry_run = dry_run
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.encode_media()
    if not dry_run:
        gen.copy_resources()
    gen.cleanup()
    return gen


def zip_of(topdir, url="iceland"):
    return topdir / "_site" / url / f"{url.rsplit('/', 1)[-1]}.zip"


class TestZip:
    def test_originals_and_readme_stored(self, tmp_path):
        folder = gallery(tmp_path, "iceland")
        build(tmp_path, download_readme="CC BY 4.0")
        with zipfile.ZipFile(zip_of(tmp_path)) as zf:
            assert zf.namelist() == ["a.jpg", "b.jpg", "readme.txt"]
            assert zf.read("a.jpg") == (folder / "a.jpg").read_bytes()
            assert zf.read("readme.txt") == b"CC BY 4.0"
            assert {i.compress_type for i in zf.infolist()} == {zipfile.ZIP_STORED}
        assert not list((tmp_path / "_site").rglob("*.part.*"))

    def test_sequence_frames_in_their_own_folder(self, tmp_path):
        folder = gallery(tmp_path, "iceland", photos=("a.jpg",))
        seq = folder / "b-imagesequence"
        seq.mkdir()
        for frame in ("001.jpg", "002.jpg"):
            make_test_image(seq / frame, 64, 48, "red")
        (seq / ".DS_Store").write_bytes(b"x")
        gen = make_generator(tmp_path)
        gen.config["download_album"] = True
        gen.scan_directories()
        gen.read_files()
        # Encode only the zip: sequences need ffmpeg
        gen._make_encoder()._create_album_zip(1, [0, 1])
        with zipfile.ZipFile(zip_of(tmp_path)) as zf:
            assert zf.namelist() == [
                "a.jpg",
                "b-imagesequence/001.jpg",
                "b-imagesequence/002.jpg",
                "readme.txt",
            ]

    def test_one_zip_per_gallery_nested(self, tmp_path):
        gallery(tmp_path / "trips", "iceland")
        gallery(tmp_path / "trips", "norway", photos=("c.jpg",))
        build(tmp_path)
        assert zipfile.ZipFile(zip_of(tmp_path, "trips/iceland")).namelist()[:2] == [
            "a.jpg",
            "b.jpg",
        ]
        assert "c.jpg" in zipfile.ZipFile(zip_of(tmp_path, "trips/norway")).namelist()

    def test_single_gallery_site_named_after_the_site(self, tmp_path):
        for photo in ("a.jpg", "b.jpg"):
            make_test_image(tmp_path / photo, 64, 48, "blue")
        build(tmp_path, site_title="My Trip")
        assert (tmp_path / "_site" / "my-trip.zip").is_file()

    def test_off_by_default(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path, album=False)
        assert not zip_of(tmp_path).exists()

    def test_draft_mode_turns_it_off(self):
        config = Config({**DEFAULT_CONFIG, "download_album": True})
        config.apply_draft_mode()
        assert config["download_album"] is False

    def test_draft_mode_ignores_opt_ins(self, tmp_path):
        gallery(tmp_path, "iceland", metadata="download: true\n")
        build(tmp_path, draft=True)
        assert not zip_of(tmp_path).exists()
        html = (tmp_path / "_site" / "iceland" / "index.html").read_text(encoding="utf-8")
        assert ".zip" not in html


class TestPerGallery:
    def _page(self, topdir, url):
        return (topdir / "_site" / url / "index.html").read_text(encoding="utf-8")

    def test_opt_out(self, tmp_path):
        gallery(tmp_path, "iceland")
        gallery(tmp_path, "private", metadata="download: false\n")
        build(tmp_path)
        assert zip_of(tmp_path).is_file()
        assert not zip_of(tmp_path, "private").exists()
        assert "private.zip" not in self._page(tmp_path, "private")
        assert 'href="iceland.zip"' in self._page(tmp_path, "iceland")

    def test_opt_in_when_off_site_wide(self, tmp_path):
        gallery(tmp_path, "iceland")
        gallery(tmp_path, "press", metadata="download: Yes\n")
        build(tmp_path, album=False)
        assert not zip_of(tmp_path).exists()
        assert zip_of(tmp_path, "press").is_file()
        assert 'href="press.zip"' in self._page(tmp_path, "press")
        assert ".zip" not in self._page(tmp_path, "iceland")

    def test_opting_out_later_removes_the_zip(self, tmp_path):
        folder = gallery(tmp_path, "iceland")
        build(tmp_path)
        (folder / "metadata.txt").write_text("download: off\n", encoding="utf-8")
        gen = build(tmp_path, dry_run=True)
        assert ("iceland/iceland.zip", "remove") in gen.planned
        assert zip_of(tmp_path).is_file()
        build(tmp_path)
        assert not zip_of(tmp_path).exists()
        assert ".zip" not in self._page(tmp_path, "iceland")
        # and it's forgotten: turning it back on builds it again
        folder.joinpath("metadata.txt").unlink()
        build(tmp_path)
        assert zip_of(tmp_path).is_file()

    def test_turning_it_off_site_wide_removes_the_zips(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path)
        build(tmp_path, album=False)
        assert not zip_of(tmp_path).exists()

    def test_a_zip_dorothea_did_not_build_is_kept(self, tmp_path):
        gallery(tmp_path, "iceland", metadata="download: false\n")
        (tmp_path / "_site" / "iceland").mkdir(parents=True)
        zip_of(tmp_path).write_bytes(b"mine")
        build(tmp_path)
        assert zip_of(tmp_path).read_bytes() == b"mine"


class TestRebuild:
    def test_unchanged_gallery_is_not_rezipped(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path)
        before = zip_of(tmp_path).stat().st_mtime_ns
        os.utime(zip_of(tmp_path), ns=(before - 10**9, before - 10**9))
        build(tmp_path)
        assert zip_of(tmp_path).stat().st_mtime_ns == before - 10**9

    def test_added_photo_rebuilds(self, tmp_path):
        folder = gallery(tmp_path, "iceland")
        build(tmp_path)
        make_test_image(folder / "c.jpg", 64, 48, "green")
        build(tmp_path)
        assert "c.jpg" in zipfile.ZipFile(zip_of(tmp_path)).namelist()

    def test_removed_photo_rebuilds(self, tmp_path):
        folder = gallery(tmp_path, "iceland")
        build(tmp_path)
        (folder / "b.jpg").unlink()
        build(tmp_path)
        assert zipfile.ZipFile(zip_of(tmp_path)).namelist() == ["a.jpg", "readme.txt"]

    def test_edited_photo_rebuilds(self, tmp_path):
        folder = gallery(tmp_path, "iceland")
        build(tmp_path)
        make_test_image(folder / "a.jpg", 80, 60, "green")
        build(tmp_path)
        assert zipfile.ZipFile(zip_of(tmp_path)).read("a.jpg") == (folder / "a.jpg").read_bytes()

    def test_readme_change_rebuilds(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path)
        build(tmp_path, download_readme="CC0")
        assert zipfile.ZipFile(zip_of(tmp_path)).read("readme.txt") == b"CC0"

    def test_rebuild_is_byte_identical(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path)
        first = zip_of(tmp_path).read_bytes()
        zip_of(tmp_path).unlink()
        build(tmp_path)
        assert zip_of(tmp_path).read_bytes() == first

    def test_dry_run_plans_it(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path)
        zip_of(tmp_path).unlink()
        gen = build(tmp_path, dry_run=True)
        assert ("iceland/iceland.zip", "new") in gen.planned
        assert not zip_of(tmp_path).exists()
        assert "iceland/iceland.zip  [new]" in format_plan(2, gen.planned)


class TestThemes:
    def _pages(self, tmp_path, theme, album=True):
        gallery(tmp_path, "iceland")
        build(tmp_path, album=album, theme_dir=theme)
        site = tmp_path / "_site"
        return (
            (site / "iceland" / "index.html").read_text(encoding="utf-8"),
            (site / "index.html").read_text(encoding="utf-8"),
        )

    @pytest.mark.parametrize("theme", ["photoessay", "medium"])
    def test_enhanced_themes_link_the_zip(self, tmp_path, theme):
        page, root = self._pages(tmp_path, theme)
        assert 'href="iceland.zip" id="album' in page
        # the top-level index.html is the first gallery's page, one folder up
        assert 'href="iceland/iceland.zip" id="album' in root
        size = sum(f.stat().st_size for f in (tmp_path / "iceland").iterdir())
        assert f"({human_size(size)})" in page
        assert not (tmp_path / "_site" / "album-download.html").exists()

    @pytest.mark.parametrize("theme", ["photoessay", "medium"])
    def test_enhanced_themes_unchanged_when_off(self, tmp_path, theme):
        page, root = self._pages(tmp_path, theme, album=False)
        for html in (page, root):
            assert ".zip" not in html and "album" not in html and "{{" not in html

    @pytest.mark.parametrize("theme", ["theme1", "theme2"])
    def test_original_themes_get_the_zip_only(self, tmp_path, theme):
        page, _root = self._pages(tmp_path, theme)
        assert "iceland.zip" not in page
        assert zip_of(tmp_path).is_file()


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0 bytes"), (999, "999 bytes"), (1500, "1.5 KB"), (48_000_000, "48 MB"),
     (1_234_000_000, "1.2 GB"), (3_000_000_000_000, "3000 GB")],
)  # fmt: skip
def test_human_size(size, expected):
    assert human_size(size) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [("iceland", "iceland.zip"), ("trips/iceland", "iceland.zip"), (".", "my-trip.zip")],
)
def test_album_zip_name(url, expected):
    assert album_zip_name(url, "My Trip") == expected


def test_config_must_be_bool():
    with pytest.raises(ConfigError, match="download_album"):
        Config({**DEFAULT_CONFIG, "download_album": "yes"}).validate()
