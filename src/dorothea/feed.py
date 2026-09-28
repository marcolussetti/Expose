"""Atom feeds (#11), written when ``site_url`` is set.

- ``_site/feed.xml``: one entry per gallery, newest first. A gallery's date is, in order of
  preference: a ``date:`` in its ``metadata.txt`` (when it was published), the newest EXIF
  capture time among its photos (when they were taken), or the newest file time.
- ``_site/<gallery>/feed.xml``: one entry per photo/video of that gallery, for galleries that
  keep growing. On unless ``gallery_feeds`` is false; a gallery's ``metadata.txt`` can say
  ``feed: false`` / ``feed: true`` to override. An item's date is a ``date:`` in its caption
  metadata, else its EXIF capture time, else its file time.

Feed readers need absolute links, which is why this needs ``site_url``; the rest of the site
only uses relative paths.
"""

import functools
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dorothea import __version__
from dorothea.captions import (
    Caption,
    caption_file,
    embedded_as_caption,
    gallery_file,
    gallery_metadata,
    metadata_flag,
    read_caption,
)
from dorothea.media.exif import EmbeddedCaption, read_photo_info
from dorothea.utils import href, strip_numeric_prefix

ATOM = "http://www.w3.org/2005/Atom"
MEDIA = "http://search.yahoo.com/mrss/"  # Media RSS, for <media:thumbnail>
FEED_NAME = "feed.xml"


def feed_url_for(page_url: str) -> str:
    """The feed next to a page: the site's (``site_url``) or a gallery's."""
    return page_url.rstrip("/") + "/" + FEED_NAME


def gallery_feed_enabled(default: bool, metadata: dict[str, str]) -> bool:
    """Whether a gallery gets its own feed: ``feed:`` in its metadata.txt, else the setting."""
    return metadata_flag(metadata, "feed", default)


@dataclass(frozen=True)
class Entry:
    title: str
    id: str  # absolute URL; stable, so readers don't show an entry again
    url: str  # absolute
    image: str | None  # absolute URL of a thumbnail-sized JPEG
    summary_html: str
    updated: datetime


@dataclass
class GalleryFeed:
    """A gallery's entry in the site feed, and its own per-photo feed."""

    entry: Entry
    url: str  # the gallery page's absolute URL
    site_path: str  # nav URL, where its feed.xml goes under _site
    enabled: bool  # writes its own feed
    items: list[Entry] = field(default_factory=list)


def parse_date(value: str) -> datetime | None:
    """A ``date:`` value: ``2022-07-14``, ``2022-07-14 18:30`` or full ISO 8601. None if invalid.

    Dates without a time zone are taken as UTC.
    """
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@functools.cache
def _capture_time(path: Path) -> float | None:
    return read_photo_info(path).capture_time if path.is_file() else None


def _explicit_date(metadata: dict[str, str], where: str) -> datetime | None:
    if "date" not in metadata:
        return None
    if (parsed := parse_date(metadata["date"])) is None:
        print(f"\n\tWarning: {where}: can't read date {metadata['date']!r}; use YYYY-MM-DD")
    return parsed


def gallery_date(metadata: dict[str, str], files: Sequence[Path], where: str) -> datetime:
    """When a gallery was published, for ordering the feed (see the module docstring)."""
    if (explicit := _explicit_date(metadata, where)) is not None:
        return explicit
    captures = [t for f in files if (t := _capture_time(f)) is not None]
    if captures:
        return datetime.fromtimestamp(max(captures), UTC)
    mtimes = [f.stat().st_mtime for f in files if f.exists()]
    return datetime.fromtimestamp(max(mtimes) if mtimes else 0, UTC)


def item_date(metadata: dict[str, str], path: Path, where: str) -> datetime:
    """When a photo was taken (or a video last changed); ``date:`` in its caption wins."""
    if (explicit := _explicit_date(metadata, where)) is not None:
        return explicit
    if (capture := _capture_time(path)) is not None:
        return datetime.fromtimestamp(capture, UTC)
    return datetime.fromtimestamp(path.stat().st_mtime if path.exists() else 0, UTC)


def thumbnail_width(resolutions: Sequence[int], max_width: int) -> int:
    """The output width to show in feed readers: the largest made that's at most 1280px.

    Sizes up to the item's own width are made, and the smallest one always.
    """
    made = [r for r in resolutions if r <= max_width] or [min(resolutions)]
    small = [r for r in made if r <= 1280]
    return max(small) if small else min(made)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_feed(title: str, page_url: str, author: str, entries: Sequence[Entry]) -> bytes:
    """The Atom document for a page (the site or a gallery), with ``feed.xml`` next to it.

    Deterministic: rebuilding an unchanged site gives the same bytes.
    """
    ET.register_namespace("", ATOM)
    ET.register_namespace("media", MEDIA)
    page_url = page_url.rstrip("/") + "/"
    entries = sorted(entries, key=lambda e: (e.updated, e.id), reverse=True)

    def sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
        element = ET.SubElement(parent, f"{{{ATOM}}}{tag}", attrs)
        element.text = text
        return element

    feed = ET.Element(f"{{{ATOM}}}feed")
    sub(feed, "title", title)
    sub(feed, "id", page_url)
    sub(feed, "link", rel="self", type="application/atom+xml", href=feed_url_for(page_url))
    sub(feed, "link", rel="alternate", type="text/html", href=page_url)
    updated = max((e.updated for e in entries), default=datetime.fromtimestamp(0, UTC))
    sub(feed, "updated", _timestamp(updated))
    sub(sub(feed, "author"), "name", author)
    sub(feed, "generator", "Dorothea", uri="https://github.com/marcolussetti/dorothea",
        version=__version__)  # fmt: skip

    for e in entries:
        entry = sub(feed, "entry")
        sub(entry, "title", e.title)
        sub(entry, "id", e.id)
        sub(entry, "link", rel="alternate", type="text/html", href=e.url)
        sub(entry, "updated", _timestamp(e.updated))
        content = e.summary_html
        if e.image:
            ET.SubElement(entry, f"{{{MEDIA}}}thumbnail", url=e.image)
            content = f'<p><a href="{e.url}"><img src="{e.image}" alt="" /></a></p>{content}'
        sub(entry, "content", content, type="html")

    ET.indent(feed)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True) + b"\n"


def collect_galleries(
    site_url: str,
    resolutions: Sequence[int],
    gallery_feeds: bool,
    paths: Sequence[Path],
    nav_type: Sequence[int],
    nav_count: Sequence[int],
    nav_name: Sequence[str],
    nav_url: Sequence[str],
    gallery_files: Sequence[Path],
    gallery_type: Sequence[int],
    gallery_url: Sequence[str],
    gallery_maxwidth: Sequence[int],
    render_markdown: Callable[[str], str],
    front_matter: bool = True,
    gallery_captions: Sequence[EmbeddedCaption] = (),
) -> list[GalleryFeed]:
    """Every gallery's feed data, from the scanner's arrays (galleries' items are consecutive).

    ``front_matter``: read ``.md`` captions' YAML front matter (off with ``--legacy``).
    ``gallery_captions``: photos' own titles/descriptions, where caption files leave them out.
    """
    _capture_time.cache_clear()  # shared by the gallery and item dates of this build only
    base = site_url.rstrip("/") + "/"
    galleries = []
    index = 0
    for i, path in enumerate(paths):
        if nav_type[i] < 1:
            continue
        positions = range(index, index + nav_count[i])
        index += nav_count[i]
        if not positions:
            continue
        metadata = gallery_metadata(path)
        page = base + href(nav_url[i]) + "/"
        enabled = gallery_feed_enabled(gallery_feeds, metadata)

        items = []
        captions = []
        for number, k in enumerate(positions, 1):
            caption = Caption()
            if (textfile := caption_file(gallery_files[k], legacy=not front_matter)) is not None:
                caption = read_caption(textfile, front_matter)  # (the builder prints warnings)
            elif k < len(gallery_captions):  # the photo's own, when it has no caption file
                own = gallery_captions[k]
                caption = embedded_as_caption(own.title, own.description)
            item_meta = caption.values
            caption_html = render_markdown(caption.body) if caption.body.strip() else ""
            captions.append(caption_html)
            width = thumbnail_width(resolutions, gallery_maxwidth[k])
            # item URLs are relative to their gallery's page
            image = f"{page}{href(gallery_url[k])}/{width}.jpg"
            if enabled:
                where = f"{nav_url[i]}/{gallery_files[k].name}"
                items.append(
                    Entry(
                        title=item_meta.get("title")
                        or strip_numeric_prefix(gallery_files[k].stem) or gallery_url[k],
                        id=f"{page}#{href(gallery_url[k])}",
                        # photoessay has an <a name="N"> per slide; elsewhere, the gallery
                        url=f"{page}#{number}",
                        image=image,
                        summary_html=caption_html,
                        updated=item_date(item_meta, gallery_files[k], where),
                    )
                )  # fmt: skip

        # The gallery's text: a `description:` in metadata.txt, else the first caption
        summary = metadata.get("description", "")
        summary = render_markdown(summary) if summary else captions[0]
        first = positions[0]
        photos = [gallery_files[k] for k in positions if gallery_type[k] == 0]
        entry = Entry(
            title=nav_name[i],
            id=page,
            url=page,
            image=f"{page}{href(gallery_url[first])}/"
            f"{thumbnail_width(resolutions, gallery_maxwidth[first])}.jpg",
            summary_html=summary,
            updated=gallery_date(
                metadata,
                photos or [gallery_files[k] for k in positions],
                f"{nav_url[i]}/{source.name}" if (source := gallery_file(path)) else nav_url[i],
            ),
        )
        galleries.append(GalleryFeed(entry, page, nav_url[i], enabled, items))
    return galleries
