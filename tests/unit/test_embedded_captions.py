"""Captions from a photo's own title/description (XMP, IPTC), as Lightroom stores them (#51)."""

import json
import struct
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin, TiffImagePlugin

from dorothea.cache import CACHE_NAME
from dorothea.captions import Caption, embedded_as_caption
from dorothea.media.exif import EmbeddedCaption, embedded_caption
from tests.conftest import make_generator


def xmp(title: str = "", description: str = "", lang: str = "x-default") -> str:
    def alt(name, text):
        if not text:
            return ""
        return (
            f"<dc:{name}><rdf:Alt><rdf:li xml:lang='{lang}'>{text}</rdf:li></rdf:Alt></dc:{name}>"
        )

    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        "<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF "
        "xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'><rdf:Description "
        "xmlns:dc='http://purl.org/dc/elements/1.1/'>"
        f"{alt('title', title)}{alt('description', description)}"
        "</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end='w'?>"
    )


def iptc_jpeg(path: Path, fields: dict[int, bytes]) -> Path:
    """A JPEG with an IPTC block (Photoshop APP13), which Pillow can read but not write."""
    records = b"".join(
        b"\x1c\x02" + bytes([dataset]) + struct.pack(">H", len(value)) + value
        for dataset, value in fields.items()
    )
    resource = b"8BIM\x04\x04\x00\x00" + struct.pack(">I", len(records)) + records
    if len(records) % 2:
        resource += b"\x00"
    segment = b"Photoshop 3.0\x00" + resource
    Image.new("RGB", (64, 48), "navy").save(path, "JPEG")
    data = path.read_bytes()
    path.write_bytes(
        data[:2] + b"\xff\xed" + struct.pack(">H", len(segment) + 2) + segment + data[2:]
    )
    return path


class TestReading:
    def test_xmp_title_and_description(self, tmp_path):
        path = tmp_path / "a.jpg"
        Image.new("RGB", (8, 8)).save(
            path, xmp=xmp("Kirkjufellsfoss", "Iceland &amp; rain\r\nDay 2").encode()
        )
        assert embedded_caption(path) == EmbeddedCaption("Kirkjufellsfoss", "Iceland & rain\nDay 2")

    def test_other_languages_when_there_is_no_default(self, tmp_path):
        path = tmp_path / "a.jpg"
        Image.new("RGB", (8, 8)).save(path, xmp=xmp("Chute", lang="fr").encode())
        assert embedded_caption(path).title == "Chute"

    def test_iptc(self, tmp_path):
        path = iptc_jpeg(tmp_path / "a.jpg", {5: "Café".encode(), 120: b"Morning light"})
        assert embedded_caption(path) == EmbeddedCaption("Café", "Morning light")

    def test_iptc_latin1(self, tmp_path):
        path = iptc_jpeg(tmp_path / "a.jpg", {120: "Café".encode("latin-1")})
        assert embedded_caption(path).description == "Café"

    def test_xmp_wins_over_iptc(self, tmp_path):
        path = iptc_jpeg(tmp_path / "a.jpg", {5: b"From IPTC", 120: b"IPTC text"})
        with Image.open(path) as image:
            image.load()
            rgb = image.copy()
        rgb.save(tmp_path / "b.jpg", xmp=xmp("From XMP").encode())
        # (re-saving drops the IPTC block, so check the order on a file with both)
        both = iptc_jpeg(tmp_path / "c.jpg", {5: b"From IPTC", 120: b"IPTC text"})
        data = both.read_bytes()
        xmp_segment = b"http://ns.adobe.com/xap/1.0/\x00" + xmp("From XMP").encode()
        both.write_bytes(
            data[:2]
            + b"\xff\xe1"
            + struct.pack(">H", len(xmp_segment) + 2)
            + xmp_segment
            + data[2:]
        )
        assert embedded_caption(both) == EmbeddedCaption("From XMP", "IPTC text")

    def test_png_webp_tiff(self, tmp_path):
        info = PngImagePlugin.PngInfo()
        info.add_itxt("XML:com.adobe.xmp", xmp("PNG"))
        Image.new("RGB", (8, 8)).save(tmp_path / "a.png", pnginfo=info)
        Image.new("RGB", (8, 8)).save(tmp_path / "a.webp", xmp=xmp("WebP").encode())
        tags = TiffImagePlugin.ImageFileDirectory_v2()
        tags[700] = xmp("TIFF").encode()
        tags.tagtype[700] = 1
        Image.new("RGB", (8, 8)).save(tmp_path / "a.tif", tiffinfo=tags)
        assert [
            embedded_caption(tmp_path / f"a.{ext}").title for ext in ("png", "webp", "tif")
        ] == [
            "PNG",
            "WebP",
            "TIFF",
        ]

    @pytest.mark.parametrize(
        "content",
        [b"", b"not an image", b"\xff\xd8\xff\xe1\x00\x10http://ns.adobe.com/xap/1.0/\x00<x:"],
    )
    def test_nothing_or_broken(self, tmp_path, content):
        path = tmp_path / "a.jpg"
        path.write_bytes(content)
        assert embedded_caption(path) == EmbeddedCaption()

    def test_broken_xmp_falls_back_to_iptc(self, tmp_path):
        path = iptc_jpeg(tmp_path / "a.jpg", {120: b"IPTC text"})
        data = path.read_bytes()
        broken = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><unclosed"
        path.write_bytes(
            data[:2] + b"\xff\xe1" + struct.pack(">H", len(broken) + 2) + broken + data[2:]
        )
        assert embedded_caption(path).description == "IPTC text"

    def test_external_entities_are_not_fetched(self, tmp_path):
        """XMP comes from the photo; the XML parser mustn't read other files."""
        secret = tmp_path / "secret.txt"
        secret.write_text("SECRET")
        packet = (
            f'<!DOCTYPE x [<!ENTITY e SYSTEM "file://{secret}">]>' + xmp("&e;").split("?>", 1)[1]
        )
        path = tmp_path / "a.jpg"
        Image.new("RGB", (8, 8)).save(path, xmp=packet.encode())
        assert "SECRET" not in embedded_caption(path).title


class TestAsCaption:
    def test_title_and_description(self):
        caption = embedded_as_caption("Falls", "At dawn.")
        assert caption.body == "## Falls\n\nAt dawn."
        assert caption.values == {"title": "Falls"}
        assert caption.head == "title: Falls"

    def test_only_a_description(self):
        caption = embedded_as_caption("", "At dawn.")
        assert caption.body == "At dawn." and caption.values == {} and caption.head == ""

    def test_only_a_title(self):
        assert embedded_as_caption("Falls", "").body == "## Falls"

    def test_nothing(self):
        assert embedded_as_caption("", "") == Caption()


def build(root, embedded=True, legacy=False, files=None):
    g = root / "g"
    g.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), "teal").save(
        g / "01 falls.jpg", xmp=xmp("Kirkjufellsfoss", "Iceland, *September* 2022").encode()
    )
    for name, text in (files or {}).items():
        (g / name).write_text(text, encoding="utf-8")
    overrides = {"theme_dir": "photoessay", "embedded_captions": embedded, "legacy": legacy}
    if legacy:  # (make_generator starts from Dorothea's defaults; Config.load would switch)
        from dorothea.config import EXPOSE_DEFAULTS

        overrides["embedded_captions"] = EXPOSE_DEFAULTS["embedded_captions"]
    gen = make_generator(root, config_overrides=overrides)
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.cleanup()
    return (root / "_site" / "g" / "index.html").read_text(encoding="utf-8")


class TestPages:
    def test_shown_as_the_caption(self, tmp_path):
        html = build(tmp_path)
        assert "<h2>Kirkjufellsfoss</h2>" in html
        assert "<p>Iceland, <em>September</em> 2022</p>" in html

    def test_off(self, tmp_path):
        assert "Kirkjufellsfoss" not in build(tmp_path, embedded=False)

    def test_legacy_default_is_off(self, tmp_path):
        """expose.sh never read them, so --legacy pages don't change."""
        from dorothea.config import EXPOSE_DEFAULTS

        assert EXPOSE_DEFAULTS["embedded_captions"] is False
        assert "Kirkjufellsfoss" not in build(tmp_path, legacy=True)

    @pytest.mark.parametrize(
        "name,text,has_words",
        [
            ("01 falls.md", "My own words.", True),
            ("01 falls.txt", "My own words.", True),
            ("01 falls.md", "---\ntop: 12\n---\n", False),  # settings only: still all or nothing
            ("01 falls.txt", "", False),  # even an empty caption file
        ],
    )
    def test_a_caption_file_replaces_it_entirely(self, tmp_path, name, text, has_words):
        html = build(tmp_path, files={name: text})
        assert "Kirkjufellsfoss" not in html and "Iceland" not in html
        assert ("My own words." in html) is has_words

    def test_feed_uses_it_when_there_is_no_caption_file(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        Image.new("RGB", (800, 600), "teal").save(
            g / "01 falls.jpg", xmp=xmp("Kirkjufellsfoss", "At dawn.").encode()
        )
        Image.new("RGB", (800, 600), "teal").save(
            g / "02 road.jpg", xmp=xmp("Ring road", "Rain.").encode()
        )
        (g / "02 road.md").write_text("---\ntitle: Mine\n---\nMy words.")
        gen = make_generator(tmp_path, config_overrides={"site_url": "https://example.com/"})
        gen.run()
        feed = (tmp_path / "_site/g/feed.xml").read_text(encoding="utf-8")
        assert "<title>Kirkjufellsfoss</title>" in feed and "At dawn." in feed
        assert "<title>Mine</title>" in feed and "Ring road" not in feed

    def test_cached(self, tmp_path):
        build(tmp_path)
        cache = json.loads((tmp_path / CACHE_NAME).read_text(encoding="utf-8"))
        assert cache["captions"]["g/01 falls.jpg"]["title"] == "Kirkjufellsfoss"

    def test_videos_and_photos_without_one_are_unaffected(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        Image.new("RGB", (800, 600), "teal").save(g / "01 plain.jpg")
        gen = make_generator(tmp_path, config_overrides={"theme_dir": "photoessay"})
        gen.scan_directories()
        gen.read_files()
        gen.cleanup()
        assert gen.gallery_captions == [EmbeddedCaption()]
