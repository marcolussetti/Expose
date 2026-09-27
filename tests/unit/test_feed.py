"""Atom feed of galleries (#11)."""

import os
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import feedparser
import pytest
from PIL import Image

from dorothea.cli import format_plan
from dorothea.config import DEFAULT_CONFIG, Config, ConfigError
from dorothea.feed import ATOM, gallery_date, gallery_feed_enabled, parse_date, thumbnail_width
from tests.conftest import make_generator, make_test_image

SITE = "https://example.com/photos/"


def photo_taken(path, when: str):
    """A JPEG whose EXIF says it was taken at ``when`` (``YYYY:MM:DD HH:MM:SS``)."""
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = when  # ExifIFD DateTimeOriginal
    Image.new("RGB", (64, 48), "green").save(path, exif=exif)


def gallery(root, name, photos=("a.jpg",), metadata=None, caption=None):
    folder = root / name
    folder.mkdir(parents=True)
    for photo in photos:
        make_test_image(folder / photo, 64, 48, "blue")
    if metadata is not None:
        (folder / "metadata.txt").write_text(metadata, encoding="utf-8")
    if caption is not None:
        (folder / f"{os.path.splitext(photos[0])[0]}.txt").write_text(caption, encoding="utf-8")
    return folder


def build(topdir, dry_run=False, encode=False, **overrides):
    gen = make_generator(topdir, overrides)
    gen.dry_run = gen.scanner.dry_run = dry_run
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    if encode:
        gen.encode_media()
        gen.copy_resources()
    return gen


def entries_of(topdir):
    return feedparser.parse((topdir / "_site" / "feed.xml").read_bytes())


class TestDates:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2022-07-14", datetime(2022, 7, 14, tzinfo=UTC)),
            ("2022-07-14 18:30", datetime(2022, 7, 14, 18, 30, tzinfo=UTC)),
            ("2022-07-14T18:30:00+02:00", datetime(2022, 7, 14, 16, 30, tzinfo=UTC)),
            ("14/07/2022", None),
            ("soon", None),
        ],
    )
    def test_parse_date(self, value, expected):
        assert parse_date(value) == expected

    def test_metadata_date_wins(self, tmp_path):
        photo = tmp_path / "a.jpg"
        photo_taken(photo, "2020:01:01 12:00:00")
        date = gallery_date({"date": "2023-03-01"}, [photo], "g")
        assert date == datetime(2023, 3, 1, tzinfo=UTC)

    def test_newest_capture_time_next(self, tmp_path):
        old, new = tmp_path / "old.jpg", tmp_path / "new.jpg"
        photo_taken(old, "2019:05:01 09:00:00")
        photo_taken(new, "2021:08:15 18:00:00")
        date = gallery_date({}, [old, new], "g")
        assert date.astimezone().replace(tzinfo=None) == datetime(2021, 8, 15, 18)

    def test_file_time_last(self, tmp_path):
        photo = tmp_path / "plain.jpg"
        Image.new("RGB", (8, 8)).save(photo)  # no EXIF
        stamp = datetime(2018, 6, 1, tzinfo=UTC).timestamp()
        os.utime(photo, (stamp, stamp))
        assert gallery_date({}, [photo], "g") == datetime(2018, 6, 1, tzinfo=UTC)

    def test_unreadable_date_warns_and_falls_back(self, tmp_path, capsys):
        photo = tmp_path / "a.jpg"
        photo_taken(photo, "2020:01:01 12:00:00")
        date = gallery_date({"date": "next tuesday"}, [photo], "iceland")
        assert date.year == 2020
        assert "iceland/metadata.txt: can't read date 'next tuesday'" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("resolutions", "max_width", "expected"),
    [
        ([3840, 2560, 1920, 1280, 1024, 640], 3840, 1280),
        ([3840, 2560, 1920, 1280, 1024, 640], 1024, 1024),
        ([3840, 2560, 1920, 1280, 1024, 640], 640, 640),
        ([1024], 1024, 1024),
        ([2560, 1920], 1920, 1920),  # nothing <= 1280 made: the smallest
    ],
)
def test_thumbnail_width(resolutions, max_width, expected):
    assert thumbnail_width(resolutions, max_width) == expected


class TestFeed:
    def test_off_without_site_url(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path)
        assert not (tmp_path / "_site" / "feed.xml").exists()
        html = (tmp_path / "_site" / "iceland" / "index.html").read_text(encoding="utf-8")
        assert "feed" not in html.lower()
        assert "{{" not in html

    def test_valid_atom_one_entry_per_gallery(self, tmp_path):
        gallery(tmp_path, "01 Iceland", photos=("a.jpg", "b.jpg"), metadata="date: 2022-07-14\n")
        gallery(tmp_path, "02 Ecuador", metadata="date: 2023-02-01\n")
        gallery(tmp_path, "03 Trips/Norway", metadata="date: 2021-01-01\n")
        build(tmp_path, site_url=SITE, site_title="Marco's Photos")
        feed = entries_of(tmp_path)
        assert not feed.bozo, feed.bozo_exception
        assert feed.version == "atom10"
        assert feed.feed.title == "Marco's Photos"
        assert feed.feed.link == SITE
        # newest first, absolute links, one per gallery (not per photo)
        assert [e.title for e in feed.entries] == ["Ecuador", "Iceland", "Norway"]
        assert [e.link for e in feed.entries] == [
            SITE + "ecuador/", SITE + "iceland/", SITE + "trips/norway/",
        ]  # fmt: skip
        assert feed.entries[0].updated == "2023-02-01T00:00:00Z"
        assert feed.feed.updated == "2023-02-01T00:00:00Z"

    def test_self_link_and_namespaces(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path, site_url="https://example.com")  # no trailing slash
        root = ET.fromstring((tmp_path / "_site" / "feed.xml").read_bytes())
        assert root.tag == f"{{{ATOM}}}feed"
        links = {link.get("rel"): link.get("href") for link in root.iter(f"{{{ATOM}}}link")}
        assert links["self"] == "https://example.com/feed.xml"

    def test_thumbnail_points_at_a_built_image(self, tmp_path):
        gallery(tmp_path, "iceland", caption="---\ntop: 10\n---\nGlaciers **everywhere**.\n")
        build(tmp_path, encode=True, site_url=SITE)
        entry = entries_of(tmp_path).entries[0]
        thumbnail = entry.media_thumbnail[0]["url"]
        assert thumbnail.startswith(SITE)
        assert (tmp_path / "_site" / thumbnail.removeprefix(SITE)).is_file()
        # the first caption, rendered, with the image linking to the gallery
        content = entry.content[0].value
        assert "<strong>everywhere</strong>" in content
        assert f'src="{thumbnail}"' in content
        assert f'<a href="{SITE}iceland/">' in content
        assert "top: 10" not in content

    def test_description_overrides_the_caption(self, tmp_path):
        gallery(tmp_path, "iceland", metadata="description: Two weeks *north*.\n", caption="Hi")
        build(tmp_path, site_url=SITE)
        content = entries_of(tmp_path).entries[0].content[0].value
        assert "<em>north</em>" in content and "Hi" not in content

    def test_rebuild_is_byte_identical(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path, site_url=SITE)
        first = (tmp_path / "_site" / "feed.xml").read_bytes()
        build(tmp_path, site_url=SITE)
        assert (tmp_path / "_site" / "feed.xml").read_bytes() == first

    def test_dry_run_plans_but_writes_nothing(self, tmp_path):
        gallery(tmp_path, "iceland")
        gallery(tmp_path, "norway", metadata="feed: false\n")
        gen = build(tmp_path, dry_run=True, site_url=SITE)
        assert gen.planned_feeds == 2  # the site's and iceland's
        assert not (tmp_path / "_site").exists()
        assert format_plan(2, [], feeds=2).startswith("Would write 2 HTML pages and 2 feeds;")
        assert format_plan(2, [], feeds=1).startswith("Would write 2 HTML pages and 1 feed;")


class TestGalleryFeeds:
    def test_one_entry_per_photo(self, tmp_path):
        folder = gallery(tmp_path, "log", photos=("01 dawn.jpg", "02 dusk.jpg", "0003.jpg"))
        photo_taken(folder / "01 dawn.jpg", "2024:03:01 06:00:00")
        photo_taken(folder / "02 dusk.jpg", "2024:03:02 19:00:00")
        (folder / "0003.txt").write_text("---\ntitle: Night\ndate: 2024-03-05\n---\nStars.\n")
        build(tmp_path, encode=True, site_url=SITE, site_title="Photos")

        feed = feedparser.parse((tmp_path / "_site" / "log" / "feed.xml").read_bytes())
        assert not feed.bozo, feed.bozo_exception
        assert feed.feed.title == "Photos: log"
        assert feed.feed.link == SITE + "log/"
        # newest first; caption title, else the file name without its number
        assert [e.title for e in feed.entries] == ["Night", "dusk", "dawn"]
        night = feed.entries[0]
        assert night.updated == "2024-03-05T00:00:00Z"
        assert "Stars." in night.content[0].value
        # links jump to the slide (photoessay's <a name="N">); ids use the stable slug
        assert night.link == SITE + "log/#3"
        assert night.id == SITE + "log/#0003"
        thumbnail = night.media_thumbnail[0]["url"]
        assert (tmp_path / "_site" / thumbnail.removeprefix(SITE)).is_file()

    def test_pages_announce_both_feeds(self, tmp_path):
        gallery(tmp_path, "iceland")
        build(tmp_path, encode=True, site_url=SITE, site_title="Photos")
        html = (tmp_path / "_site" / "iceland" / "index.html").read_text(encoding="utf-8")
        site = html.index(f'title="Photos" href="{SITE}feed.xml"')
        own = html.index(f'title="Photos: iceland" href="{SITE}iceland/feed.xml"')
        assert site < own  # readers usually offer the first one

    def test_opt_out_per_gallery(self, tmp_path):
        gallery(tmp_path, "iceland")
        gallery(tmp_path, "trip", metadata="feed: false\n")
        build(tmp_path, site_url=SITE)
        assert (tmp_path / "_site" / "iceland" / "feed.xml").is_file()
        assert not (tmp_path / "_site" / "trip" / "feed.xml").exists()
        html = (tmp_path / "_site" / "trip" / "index.html").read_text(encoding="utf-8")
        assert f"{SITE}feed.xml" in html and "trip/feed.xml" not in html
        # still in the site feed
        assert [e.title for e in entries_of(tmp_path).entries].count("trip") == 1

    def test_off_site_wide_with_opt_in(self, tmp_path):
        gallery(tmp_path, "iceland")
        gallery(tmp_path, "log", metadata="feed: yes\n")
        build(tmp_path, site_url=SITE, gallery_feeds=False)
        assert not (tmp_path / "_site" / "iceland" / "feed.xml").exists()
        assert (tmp_path / "_site" / "log" / "feed.xml").is_file()
        assert (tmp_path / "_site" / "feed.xml").is_file()

    @pytest.mark.parametrize(
        ("default", "value", "expected"),
        [
            (True, None, True), (False, None, False),
            (True, "false", False), (True, "No", False), (False, "true", True),
            (False, "on", True), (True, "maybe", True),
        ],
    )  # fmt: skip
    def test_gallery_feed_enabled(self, default, value, expected):
        metadata = {} if value is None else {"feed": value}
        assert gallery_feed_enabled(default, metadata) is expected


class TestThemes:
    def _page(self, tmp_path, theme, **overrides):
        gallery(tmp_path, "iceland")
        build(tmp_path, encode=True, theme_dir=theme, **overrides)
        return (tmp_path / "_site" / "iceland" / "index.html").read_text(encoding="utf-8")

    @pytest.mark.parametrize("theme", ["photoessay", "medium"])
    def test_enhanced_themes_link_the_feed(self, tmp_path, theme):
        html = self._page(tmp_path, theme, site_url=SITE, site_title='Say "cheese" <3')
        # autodiscovery for feed readers / browser extensions
        assert (
            '<link rel="alternate" type="application/atom+xml" '
            'title="Say &quot;cheese&quot; &lt;3" href="https://example.com/photos/feed.xml" />'
        ) in html
        # the visible icon/link, from the theme's feed-button.html
        assert 'href="https://example.com/photos/feed.xml" id="feed' in html
        assert not (tmp_path / "_site" / "feed-button.html").exists()
        assert (tmp_path / "_site" / "img" / "feed.png").is_file()

    @pytest.mark.parametrize("theme", ["photoessay", "medium"])
    def test_enhanced_themes_unchanged_without_site_url(self, tmp_path, theme):
        html = self._page(tmp_path, theme)
        assert "feed.xml" not in html and 'id="feed' not in html

    @pytest.mark.parametrize("theme", ["theme1", "theme2"])
    def test_original_themes_get_the_feed_file_only(self, tmp_path, theme):
        html = self._page(tmp_path, theme, site_url=SITE)
        assert "feed.xml" not in html
        assert (tmp_path / "_site" / "feed.xml").is_file()


class TestConfig:
    @pytest.mark.parametrize("url", ["", "https://example.com", "http://localhost:8000/x/"])
    def test_valid(self, url):
        Config({**DEFAULT_CONFIG, "site_url": url}).validate()

    @pytest.mark.parametrize("url", ["example.com", "ftp://x.org", "https://a b", 5])
    def test_invalid(self, url):
        with pytest.raises(ConfigError, match="site_url"):
            Config({**DEFAULT_CONFIG, "site_url": url}).validate()
