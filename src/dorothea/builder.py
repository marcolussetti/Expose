"""HTML generation from templates.

Builds the HTML gallery pages by loading templates, processing markdown,
and substituting variables.
"""

import contextlib
import re
from html import escape as html_escape
from pathlib import Path

from dorothea.album import album_enabled, album_members, album_zip_name, human_size
from dorothea.captions import (
    caption_file,
    gallery_metadata,
    gallery_metadata_text,
    is_comment,
    metadata_values,
    read_caption,
    read_text_file,
    split_caption,
)
from dorothea.config import Config
from dorothea.feed import feed_url_for, gallery_feed_enabled
from dorothea.media.exif import DETAIL_KEYS
from dorothea.media.markdown import MarkdownProcessor
from dorothea.template import TemplateEngine
from dorothea.themes import resolve_theme_dir
from dorothea.utils import href

__all__ = ["HTMLBuilder", "caption_file", "read_text_file", "split_caption"]


def _feed_link_tag(title: str, feed_url: str) -> str:
    """Feed autodiscovery, for browsers and feed reader extensions."""
    return (
        f'<link rel="alternate" type="application/atom+xml" '
        f'title="{html_escape(title, quote=True)}" href="{feed_url}" />'
    )


# Characters that could end the style attribute/tag or add further CSS declarations
UNSAFE_CSS_VALUE = set('"<>;{}\\')


def _textbackground_attr(value: str, source: Path) -> str:
    """Build the ``{{textbackground_attr}}`` snippet for a ``textbackground: <css colour>`` key.

    Themes put the placeholder inside the caption element's class attribute
    (``class="content{{textbackground_attr}}"``), so when the key isn't set it disappears and
    the page is byte-identical to one without the feature. When set, the snippet closes the
    class value and adds a style attribute.
    """
    if UNSAFE_CSS_VALUE & set(value):
        print(f"\n\tIgnoring textbackground for {source.name}: {value!r} is not a CSS colour")
        return ""
    return f'" style="background-color: {value}; padding: 0.5em 1em'


def exif_mode(setting: str, metadata: dict[str, str], source: Path) -> str:
    """How to show an item's details (#20): the ``exif_display`` setting, unless its caption or
    ``metadata.txt`` says ``exif: false`` (or ``icon``/``caption``, or ``true`` for the default
    style)."""
    value = metadata.get("exif", "").strip().lower()
    if not value:
        return setting
    if value in ("false", "no", "off"):
        return "off"
    if value in ("icon", "caption"):
        return value
    if value in ("true", "yes", "on"):
        return setting if setting != "off" else "icon"
    print(f"\n\tIgnoring 'exif: {value}' for {source.name}: use false, true, icon or caption")
    return setting


def photo_details(detected: dict[str, str], metadata: dict[str, str]) -> dict[str, str]:
    """Details read from EXIF, overridden by the same keys in the caption or ``metadata.txt``
    (``lens: Helios 44-2`` for a manual lens; ``lens: -`` hides it), in ``DETAIL_KEYS`` order."""
    details = dict(detected)
    for key in DETAIL_KEYS:
        if value := metadata.get(key):
            if value == "-":
                details.pop(key, None)
            else:
                details[key] = value
    return {key: details[key] for key in DETAIL_KEYS if key in details}


def exposure_summary(details: dict[str, str]) -> str:
    """``23mm · f/2 · 1/250s · ISO 160``, from the fields there are."""
    iso = details.get("iso", "")
    parts = [details.get(k, "") for k in ("focal_length", "aperture", "shutter_speed")]
    parts.append(f"ISO {iso}" if iso.isdigit() else iso)
    return " · ".join(p for p in parts if p)


# Themes style these; colours come from the photo's palette, like the post's own
_PALETTE_STYLE = 'style="color: {{textcolor}}; background-color: {{backgroundcolor}}"'


def _exif_icon(details: dict[str, str]) -> str:
    """``{{exif_icon}}``: an ⓘ button with a panel of the photo's details."""
    rows = [details.get("camera", ""), details.get("lens", ""), exposure_summary(details)]
    panel = "".join(f"<span>{html_escape(row)}</span>" for row in rows if row)
    return (
        f'<div class="photo-info"><button type="button" class="photo-info-button" '
        f'aria-label="Photo details" aria-expanded="false" {_PALETTE_STYLE}>i</button>'
        f'<div class="photo-info-panel" {_PALETTE_STYLE}>{panel}</div></div>'
    )


def _exif_caption(details: dict[str, str]) -> str:
    """``{{exif_caption}}``: the details on one line, for under the caption."""
    parts = [details.get("camera", ""), exposure_summary(details)]
    line = " · ".join(p for p in parts if p)
    return f'<p class="photo-info-line">{html_escape(line)}</p>'


class HTMLBuilder:
    """HTML page builder.

    Generates HTML gallery pages by:
    1. Loading template.html and post-template.html from theme
    2. Reading metadata from text files
    3. Processing markdown content
    4. Building navigation structure
    5. Substituting template variables
    6. Writing index.html files
    """

    def __init__(
        self,
        topdir: Path,
        scriptdir: Path,
        config: Config,
        paths: list[Path],
        nav_name: list[str],
        nav_depth: list[int],
        nav_type: list[int],
        nav_url: list[str],
        nav_count: list[int],
        gallery_files: list[Path],
        gallery_nav: list[int],
        gallery_url: list[str],
        gallery_type: list[int],
        gallery_maxwidth: list[int],
        gallery_maxheight: list[int],
        gallery_colors: list[list[str]],
        gallery_image_options: list[str],
        gallery_video_options: list[str],
        gallery_video_filters: list[str],
        draft: bool = False,
        gallery_details: list[dict[str, str]] | None = None,
    ):
        """Initialize the HTML builder.

        Args:
            topdir: Top-level working directory (gallery root).
            scriptdir: Script directory (for themes).
            config: Configuration object.
            paths: List of directory paths.
            nav_name: Navigation names (parallel to paths).
            nav_depth: Navigation depths (parallel to paths).
            nav_type: Navigation types (0=branch, 1=leaf) (parallel to paths).
            nav_url: Navigation URLs (parallel to paths).
            nav_count: Gallery counts per nav item (parallel to paths).
            gallery_files: List of gallery file paths.
            gallery_nav: Navigation index for each gallery (parallel to gallery_files).
            gallery_url: Gallery URLs (parallel to gallery_files).
            gallery_type: Gallery types (0=image, 1=video, 2=sequence).
            gallery_maxwidth: Max widths (parallel to gallery_files).
            gallery_maxheight: Max heights (parallel to gallery_files).
            gallery_colors: Color palettes (parallel to gallery_files).
            gallery_image_options: Image options (updated as side effect of text file parsing).
            gallery_video_options: Video options (updated as side effect of text file parsing).
            gallery_video_filters: Video filters (updated as side effect of text file parsing).
            draft: Draft mode, which builds no album zips, so pages don't link them.
            gallery_details: Shooting details read from EXIF (parallel to gallery_files; #20).
        """
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        # .md captions' YAML front matter (#52); --legacy reads every caption as expose.sh does
        self.front_matter = not config.get("legacy", False)

        # Navigation structures
        self.paths = paths
        self.nav_name = nav_name
        self.nav_depth = nav_depth
        self.nav_type = nav_type
        self.nav_url = nav_url
        self.nav_count = nav_count

        # Gallery structures
        self.gallery_files = gallery_files
        self.gallery_nav = gallery_nav
        self.gallery_url = gallery_url
        self.gallery_type = gallery_type
        self.gallery_maxwidth = gallery_maxwidth
        self.gallery_maxheight = gallery_maxheight
        self.gallery_colors = gallery_colors
        self.gallery_image_options = gallery_image_options
        self.gallery_video_options = gallery_video_options
        self.gallery_video_filters = gallery_video_filters
        self.gallery_details = gallery_details or []

        # Initialize processors
        self.markdown_processor = MarkdownProcessor(scriptdir)

        # Load templates
        theme_dir = resolve_theme_dir(self.config["theme_dir"], self.topdir)
        self.template_html = (theme_dir / "template.html").read_text(encoding="utf-8")
        self.post_template_html = (theme_dir / "post-template.html").read_text(encoding="utf-8")

        # Feed (#11): with site_url, {{feed_link}} (autodiscovery for feed readers) and, in themes
        # that provide feed-button.html, {{feed_button}}. Both vanish without site_url.
        self.feed_link = self.feed_button = ""
        if site_url := self.config.get("site_url", ""):
            feed_url = feed_url_for(site_url)
            self.feed_link = _feed_link_tag(self.config["site_title"], feed_url)
            button = theme_dir / "feed-button.html"
            if button.is_file():
                self.feed_button = TemplateEngine.substitute(
                    button.read_text(encoding="utf-8").strip(), "feedurl", feed_url
                )

        # Whole-gallery zip (#9): {{album_download}}, from the theme's album-download.html, on
        # pages of galleries that get one (download_album, or their own ``download:``)
        self.album_button = ""
        album = theme_dir / "album-download.html"
        if not draft and album.is_file():
            self.album_button = album.read_text(encoding="utf-8").strip()

    def build_html(self, write: bool = True, dots: bool = True) -> int:
        """Build HTML pages for all galleries.

        Args:
            write: Write the pages. With False (dry run) metadata is still parsed, which
                fills the per-item image/video options, but nothing is written.
            dots: Print a dot per post (off while progress bars are drawn).

        Returns:
            Number of pages (including the top-level index.html).
        """
        dots = dots and write
        if write:
            print("Building html", end="" if dots else "\n", flush=True)
        pages = 0

        gallery_index = 0
        firsthtml = ""
        firstpath = ""

        for i, path in enumerate(self.paths):
            if self.nav_type[i] < 1:
                continue

            html = self.template_html

            # Read gallery metadata
            gallery_metadata = gallery_metadata_text(path)

            nav_count = self.nav_count[i]
            first_item = gallery_index
            for j in range(nav_count):
                if dots:
                    print(".", end="", flush=True)

                k = j + 1
                file_path = self.gallery_files[gallery_index]
                file_type = self.gallery_type[gallery_index]

                media_type = "image" if file_type == 0 else "video"

                textfile = caption_file(file_path, legacy=not self.front_matter)

                item_metadata = ""
                content = ""

                if textfile is not None:
                    caption = read_caption(textfile, front_matter=self.front_matter)
                    item_metadata, content = caption.head, caption.body
                    for warning in caption.warning_lines(textfile.name):
                        print(f"\n\tWarning: {warning}")
                    if caption.ignored:
                        print(
                            f"\n\tWarning: {textfile.name}: ignoring {len(caption.ignored)} "
                            "line(s) in the metadata section that aren't 'key: value' (first: "
                            f"{caption.ignored[0]!r}); put the caption after the second '---'"
                        )

                # Combine metadata: item + gallery + colors
                metadata = item_metadata + "\n" + gallery_metadata + "\n"

                # Add color palette to metadata
                colors = self.gallery_colors[gallery_index]
                for z, color in enumerate(colors, 1):
                    metadata += f"color{z}:{color}\n"

                # Set background and text colors
                backgroundcolor = colors[1] if len(colors) > 1 else ""
                if self.config["override_textcolor"]:
                    textcolor = self.config["textcolor"]
                else:
                    textcolor = colors[-1] if colors else self.config["textcolor"]

                # Process markdown
                content = self.markdown_processor.render(content)

                # Apply post template
                post = TemplateEngine.substitute(self.post_template_html, "index", str(k))
                post = TemplateEngine.substitute(post, "post", content)

                # Parse and apply metadata to post
                textbackground = None
                for line in metadata.split("\n"):
                    if ":" not in line or is_comment(line):
                        continue
                    parts = line.split(":", 1)
                    key = parts[0].strip()
                    value = parts[1].strip() if len(parts) > 1 else ""

                    if key and value:
                        post = TemplateEngine.substitute(post, key, value)

                        if key == "image-options":
                            self.gallery_image_options[gallery_index] = value
                        elif key == "video-options":
                            self.gallery_video_options[gallery_index] = value
                        elif key == "video-filters":
                            self.gallery_video_filters[gallery_index] = value
                        elif key == "textbackground" and textbackground is None:
                            # Post metadata comes before metadata.txt, so a post's own value wins
                            textbackground = value

                if textbackground is not None:
                    post = TemplateEngine.substitute(
                        post, "textbackground_attr", _textbackground_attr(textbackground, file_path)
                    )

                post = self._apply_details(post, gallery_index, metadata, file_path)

                # Set image parameters
                post = TemplateEngine.substitute(
                    post, "imageurl", href(self.gallery_url[gallery_index])
                )
                post = TemplateEngine.substitute(
                    post, "imagewidth", str(self.gallery_maxwidth[gallery_index])
                )
                post = TemplateEngine.substitute(
                    post, "imageheight", str(self.gallery_maxheight[gallery_index])
                )

                # Set colors
                post = TemplateEngine.substitute(post, "textcolor", textcolor)
                post = TemplateEngine.substitute(post, "backgroundcolor", backgroundcolor)
                post = TemplateEngine.substitute(post, "type", media_type)

                # Append to main template (iterative accumulation)
                html = TemplateEngine.substitute(html, "content", post + " {{content}}")

                gallery_index += 1

            # Substitute page-level variables
            html = TemplateEngine.substitute(html, "sitetitle", self.config["site_title"])
            html = TemplateEngine.substitute(html, "gallerytitle", self.nav_name[i])
            html = TemplateEngine.substitute(
                html, "disqus_shortname", self.config["disqus_shortname"]
            )

            resolution_str = " ".join(str(r) for r in self.config["resolution"])
            html = TemplateEngine.substitute(html, "resolution", resolution_str)

            format_str = " ".join(self.config["video_formats"])
            html = TemplateEngine.substitute(html, "videoformats", format_str)

            html = TemplateEngine.substitute(
                html, "text_toggle", "block" if self.config["text_toggle"] else "none"
            )
            html = TemplateEngine.substitute(
                html, "social_button", "block" if self.config["social_button"] else "none"
            )
            html = TemplateEngine.substitute(
                html, "download_button", "block" if self.config["download_button"] else "none"
            )
            if self.feed_link:
                html = TemplateEngine.substitute(html, "feed_link", self._page_feed_links(i, path))
                html = TemplateEngine.substitute(html, "feed_button", self.feed_button)
            if self.album_button and album_enabled(self.config.get("download_album", False), path):
                items = range(first_item, first_item + nav_count)
                html = TemplateEngine.substitute(
                    html, "album_download", self._album_button(i, items)
                )

            # Build navigation
            navigation_html = self._build_navigation(i)
            navigation_html = re.sub(r"\{\{marker\d+\}\}", "", navigation_html)
            html = TemplateEngine.substitute(html, "navigation", navigation_html)

            # Store first gallery HTML for top-level index
            if not firsthtml:
                firsthtml = html
                firstpath = self.nav_url[i]

            # Set basepath, disqus_identifier
            basepath = "./" if self.nav_depth[i] == 0 else "../" * self.nav_depth[i]
            html = TemplateEngine.substitute(html, "basepath", basepath)
            html = TemplateEngine.substitute(html, "disqus_identifier", self.nav_url[i])

            # Apply defaults and clean unused variables
            html = TemplateEngine.apply_defaults(html)
            html = TemplateEngine.clean_unused(html)
            html = html.replace("<ul></ul>", "")

            # Write output
            pages += 1
            if write:
                output_path = self.topdir / "_site" / self.nav_url[i] / "index.html"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(html, encoding="utf-8")

        # Write top-level index.html (copy of first gallery with root basepath)
        if firsthtml:
            root_html = TemplateEngine.substitute(firsthtml, "basepath", "./")
            root_html = TemplateEngine.substitute(root_html, "disqus_identifier", firstpath)
            root_html = TemplateEngine.substitute(root_html, "resourcepath", href(firstpath) + "/")
            root_html = TemplateEngine.apply_defaults(root_html)
            root_html = TemplateEngine.clean_unused(root_html)
            root_html = root_html.replace("<ul></ul>", "")
            pages += 1
            if write:
                (self.topdir / "_site").mkdir(parents=True, exist_ok=True)
                (self.topdir / "_site" / "index.html").write_text(root_html, encoding="utf-8")

        if dots:
            print()
        return pages

    def _build_navigation(self, current_idx: int) -> str:
        """Build navigation menu HTML.

        Args:
            current_idx: Index of current page in nav structures.

        Returns:
            Navigation HTML with hierarchical structure.
        """
        navigation = ""
        depth = 1
        prevdepth = 0
        remaining = len(self.paths)
        parent = -1

        while remaining > 1:
            for j, _path in enumerate(self.paths):
                if depth > 1 and self.nav_depth[j] == prevdepth:
                    parent = j

                active = "active" if current_idx == j else ""

                if parent < 0 and self.nav_depth[j] == 1:
                    if self.nav_type[j] == 0:
                        navigation += f'<li><span class="label">{self.nav_name[j]}</span><ul>{{{{marker{j}}}}}</ul></li>'
                    else:
                        gindex = self._find_gallery_index(j)
                        navigation += f'<li class="gallery {active}" data-image="{href(self.gallery_url[gindex])}"><a href="{{{{basepath}}}}{self._nav_link(j)}"><span>{self.nav_name[j]}</span></a><ul>{{{{marker{j}}}}}</ul></li>'
                    remaining -= 1
                elif self.nav_depth[j] == depth:
                    if self.nav_type[j] == 0:
                        substring = f'<li><span class="label">{self.nav_name[j]}</span><ul>{{{{marker{j}}}}}</ul></li>{{{{marker{parent}}}}}'
                    else:
                        gindex = self._find_gallery_index(j)
                        substring = f'<li class="gallery {active}" data-image="{href(self.gallery_url[gindex])}"><a href="{{{{basepath}}}}{self._nav_link(j)}"><span>{self.nav_name[j]}</span></a><ul>{{{{marker{j}}}}}</ul></li>{{{{marker{parent}}}}}'
                    navigation = TemplateEngine.substitute(navigation, f"marker{parent}", substring)
                    remaining -= 1

            prevdepth += 1
            depth += 1

        return navigation

    def _apply_details(self, post: str, index: int, metadata: str, source: Path) -> str:
        """Fill an item's shooting details (#20): ``{{exif_icon}}`` or ``{{exif_caption}}`` per
        ``exif_display``, and ``{{camera}}``, ``{{lens}}``, … ``{{exif_summary}}`` for custom
        themes. With the setting off (or ``exif: false``) they're all left empty."""
        values = metadata_values(metadata)
        mode = exif_mode(self.config.get("exif_display", "off"), values, source)
        detected = self.gallery_details[index] if index < len(self.gallery_details) else {}
        details = photo_details(detected, values)
        if mode == "off" or not details:
            return post
        post = TemplateEngine.substitute(
            post, f"exif_{mode}", _exif_icon(details) if mode == "icon" else _exif_caption(details)
        )
        for key, value in details.items():
            post = TemplateEngine.substitute(post, key, html_escape(value))
        return TemplateEngine.substitute(
            post, "exif_summary", html_escape(exposure_summary(details))
        )

    def _page_feed_links(self, nav_idx: int, path: Path) -> str:
        """``{{feed_link}}`` for a gallery page: the site feed, then the gallery's own feed."""
        metadata = gallery_metadata(path)
        if not gallery_feed_enabled(self.config.get("gallery_feeds", True), metadata):
            return self.feed_link
        page = self.config["site_url"].rstrip("/") + "/" + href(self.nav_url[nav_idx]) + "/"
        title = f"{self.config['site_title']}: {self.nav_name[nav_idx]}"
        return self.feed_link + " " + _feed_link_tag(title, feed_url_for(page))

    def _album_button(self, nav_idx: int, items: range) -> str:
        """``{{album_download}}`` for a gallery page: the theme's markup with the zip's URL
        (under ``{{resourcepath}}``, so the top-level copy of the first page links into its
        folder) and its size, which is about the originals' (the zip stores them as they are)."""
        members = album_members(
            [self.gallery_files[k] for k in items], [self.gallery_type[k] for k in items]
        )
        size = 0
        for _name, path in members:
            with contextlib.suppress(OSError):
                size += path.stat().st_size
        name = album_zip_name(self.nav_url[nav_idx], self.config["site_title"])
        button = TemplateEngine.substitute(
            self.album_button, "albumurl", "{{resourcepath}}" + href(name)
        )
        return TemplateEngine.substitute(button, "albumsize", human_size(size))

    def _nav_link(self, nav_idx: int) -> str:
        """A gallery's link: its directory (like expose.sh), or its index.html with
        ``link_index_html``, which also works opened from disk (#6)."""
        link = href(self.nav_url[nav_idx])
        return f"{link}/index.html" if self.config.get("link_index_html", False) else link

    def _find_gallery_index(self, nav_idx: int) -> int:
        """Find first gallery index for a navigation item.

        Args:
            nav_idx: Navigation index to find gallery for.

        Returns:
            Index into gallery arrays for first gallery in this nav item.
        """
        for k, nav in enumerate(self.gallery_nav):
            if nav == nav_idx:
                return k
        return 0
