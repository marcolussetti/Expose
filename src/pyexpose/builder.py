"""HTML generation from templates.

Builds the HTML gallery pages by loading templates, processing markdown,
and substituting variables.
"""

import re
from pathlib import Path

from pyexpose.config import Config
from pyexpose.media.markdown import MarkdownProcessor
from pyexpose.template import TemplateEngine
from pyexpose.themes import resolve_theme_dir


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
        """
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config

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

        # Initialize processors
        self.markdown_processor = MarkdownProcessor(scriptdir)

        # Load templates
        theme_dir = resolve_theme_dir(self.config["theme_dir"], self.topdir)
        self.template_html = (theme_dir / "template.html").read_text()
        self.post_template_html = (theme_dir / "post-template.html").read_text()

    def build_html(self):
        """Build HTML pages for all galleries."""
        print("Building html", end="", flush=True)

        gallery_index = 0
        firsthtml = ""
        firstpath = ""

        for i, path in enumerate(self.paths):
            if self.nav_type[i] < 1:
                continue

            html = self.template_html

            # Read gallery metadata
            metadata_file = path / "metadata.txt"
            gallery_metadata = metadata_file.read_text() if metadata_file.exists() else ""

            nav_count = self.nav_count[i]
            for j in range(nav_count):
                print(".", end="", flush=True)

                k = j + 1
                file_path = self.gallery_files[gallery_index]
                file_type = self.gallery_type[gallery_index]
                filename = file_path.stem
                filedir = file_path.parent

                media_type = "image" if file_type == 0 else "video"

                # Look for .txt or .md file
                textfile = None
                for ext in [".txt", ".md"]:
                    candidate = filedir / (filename + ext)
                    if candidate.exists() and candidate != file_path:
                        textfile = candidate
                        break

                item_metadata = ""
                content = ""

                if textfile and textfile.exists():
                    text = textfile.read_text().replace("\r", "").rstrip("\n")
                    lines = text.split("\n")
                    dash_lines = [idx for idx, line in enumerate(lines) if line == "---"]

                    if len(dash_lines) >= 2:
                        metaline = dash_lines[1]
                        item_metadata = "\n".join(lines[: metaline + 1])
                        content = "\n".join(lines[metaline + 1 :])
                    elif len(dash_lines) == 1:
                        metaline = dash_lines[0]
                        item_metadata = "\n".join(lines[: metaline + 1])
                        content = "\n".join(lines[metaline + 1 :])
                    else:
                        content = text

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
                for line in metadata.split("\n"):
                    if ":" not in line:
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

                # Set image parameters
                post = TemplateEngine.substitute(post, "imageurl", self.gallery_url[gallery_index])
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
            output_path = self.topdir / "_site" / self.nav_url[i] / "index.html"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html)

        # Write top-level index.html (copy of first gallery with root basepath)
        if firsthtml:
            root_html = TemplateEngine.substitute(firsthtml, "basepath", "./")
            root_html = TemplateEngine.substitute(root_html, "disqus_identifier", firstpath)
            root_html = TemplateEngine.substitute(root_html, "resourcepath", firstpath + "/")
            root_html = TemplateEngine.apply_defaults(root_html)
            root_html = TemplateEngine.clean_unused(root_html)
            root_html = root_html.replace("<ul></ul>", "")
            (self.topdir / "_site").mkdir(parents=True, exist_ok=True)
            (self.topdir / "_site" / "index.html").write_text(root_html)

        print()

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
                        navigation += f'<li class="gallery {active}" data-image="{self.gallery_url[gindex]}"><a href="{{{{basepath}}}}{self.nav_url[j]}"><span>{self.nav_name[j]}</span></a><ul>{{{{marker{j}}}}}</ul></li>'
                    remaining -= 1
                elif self.nav_depth[j] == depth:
                    if self.nav_type[j] == 0:
                        substring = f'<li><span class="label">{self.nav_name[j]}</span><ul>{{{{marker{j}}}}}</ul></li>{{{{marker{parent}}}}}'
                    else:
                        gindex = self._find_gallery_index(j)
                        substring = f'<li class="gallery {active}" data-image="{self.gallery_url[gindex]}"><a href="{{{{basepath}}}}{self.nav_url[j]}"><span>{self.nav_name[j]}</span></a><ul>{{{{marker{j}}}}}</ul></li>{{{{marker{parent}}}}}'
                    navigation = TemplateEngine.substitute(navigation, f"marker{parent}", substring)
                    remaining -= 1

            prevdepth += 1
            depth += 1

        return navigation

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
