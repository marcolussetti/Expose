#!/usr/bin/env python3
"""
Expose - Static photography website generator

A Python port of expose.sh that generates static photography/video galleries.
"""

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# Default configuration
DEFAULT_CONFIG = {
    'site_title': 'My Awesome Photos',
    'theme_dir': 'theme1',
    'resolution': [3840, 2560, 1920, 1280, 1024, 640],
    'jpeg_quality': 92,
    'autorotate': True,
    'video_formats': ['h264', 'vp8'],
    'bitrate': [40, 24, 12, 7, 4, 2],
    'bitrate_maxratio': 2,
    'disable_audio': True,
    'extract_colors': True,
    'backgroundcolor': '#000000',
    'textcolor': '#ffffff',
    'default_palette': ['#000000', '#222222', '#444444', '#666666', '#999999', '#cccccc', '#ffffff'],
    'override_textcolor': True,
    'text_toggle': True,
    'social_button': True,
    'download_button': False,
    'download_readme': 'All rights reserved',
    'disqus_shortname': '',
    'sequence_keyword': 'imagesequence',
    'sequence_framerate': 24,
    'h264_encodespeed': 'veryslow',
    'vp9_encodespeed': 1,
    'ffmpeg_threads': 0
}

# Video extensions
VIDEO_EXTENSIONS = [
    '3g2', '3gp', '3gp2', 'asf', 'avi', 'dvr-ms', 'exr', 'ffindex', 'ffpreset',
    'flv', 'gxf', 'h261', 'h263', 'h264', 'h265', 'ifv', 'm2t', 'm2ts', 'mts',
    'm4v', 'mkv', 'mod', 'mov', 'mp4', 'mpg', 'mxf', 'tod', 'vob', 'webm', 'wmv', 'y4m'
]

# Video format to extension mapping
VIDEO_FORMAT_EXTENSIONS = {
    'h264': 'mp4',
    'h265': 'mp4',
    'vp9': 'webm',
    'vp8': 'webm',
    'ogv': 'ogv'
}


class ExposeGenerator:
    def __init__(self, topdir, scriptdir, config, draft=False):
        self.topdir = Path(topdir)
        self.scriptdir = Path(scriptdir)
        self.config = config
        self.draft = draft

        # Navigation structures
        self.paths = []
        self.nav_name = []
        self.nav_depth = []
        self.nav_type = []
        self.nav_url = []
        self.nav_count = []

        # Gallery structures
        self.gallery_files = []
        self.gallery_nav = []
        self.gallery_url = []
        self.gallery_type = []
        self.gallery_maxwidth = []
        self.gallery_maxheight = []
        self.gallery_colors = []
        self.gallery_image_options = []
        self.gallery_video_options = []
        self.gallery_video_filters = []

        # Create scratch directory
        self.scratchdir = Path(tempfile.mkdtemp())
        os.chmod(self.scratchdir, 0o740)

        # Track output files for cleanup
        self.output_url = None

        # Check for video support
        self.video_enabled = (
            shutil.which('ffmpeg') is not None and
            shutil.which('ffprobe') is not None
        )
        if not self.video_enabled:
            print("FFmpeg not found, videos will not be processed")

        # Set autorotate option
        self.autorotate_option = " -auto-orient " if config['autorotate'] else ""

        # Apply draft mode settings
        if draft:
            print("Draft mode On")
            self.config['resolution'] = [1024]
            self.config['bitrate'] = [4]
            self.config['video_formats'] = ['h264']
            self.config['download_button'] = False

    def cleanup(self):
        """Clean up temporary files and directories."""
        # Remove ffmpeg log/temp files
        for pattern in ['ffmpeg*.log', 'ffmpeg*.mbtree', 'ffmpeg*.temp']:
            for f in Path('.').glob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass

        # Remove scratch directory
        if self.scratchdir.exists():
            shutil.rmtree(self.scratchdir, ignore_errors=True)

        # Remove output file if exists
        if self.output_url and Path(self.output_url).exists():
            try:
                Path(self.output_url).unlink()
            except OSError:
                pass

    def template(self, text, key, value):
        """
        Template substitution matching exact sed behavior.

        Replaces {{key}} and {{key:default}} with value.

        Note: The shell version uses `echo $value` (unquoted) which collapses
        whitespace. We replicate this behavior.
        """
        key = key.strip()
        # Collapse whitespace like shell's unquoted echo $value
        collapsed_value = ' '.join(value.split())
        # Escape for regex replacement (matching sed escaping)
        escaped_value = collapsed_value.replace('\\', '\\\\').replace('/', '\\/').replace('&', '\\&')
        # Now unescape for Python's re.sub (we need the literal replacement)
        replacement = escaped_value.replace('\\/', '/').replace('\\&', '&').replace('\\\\', '\\')

        # Replace {{key}} and {{key:default}}
        text = re.sub(r'\{\{' + re.escape(key) + r'\}\}', replacement, text)
        text = re.sub(r'\{\{' + re.escape(key) + r':[^}]*\}\}', replacement, text)
        return text

    def url_safe(self, name):
        """
        Convert name to URL-safe format.

        Matches: sed 's/[^ a-zA-Z0-9]//g;s/ /-/g' | tr '[:upper:]' '[:lower:]'
        """
        # Remove non-alphanumeric chars except space
        result = re.sub(r'[^ a-zA-Z0-9]', '', name)
        # Replace spaces with hyphens
        result = result.replace(' ', '-')
        # Convert to lowercase
        return result.lower()

    def strip_numeric_prefix(self, name):
        """
        Strip numeric prefix from name.

        Matches: sed -e 's/^[0-9]*//' | sed -e 's/^[[:space:]]*//;s/[[:space:]]*$//'
        """
        result = re.sub(r'^[0-9]*', '', name).strip()
        return result if result else name

    def run_command(self, cmd, capture=True, check=False):
        """Run a shell command and return output."""
        try:
            result = subprocess.run(
                cmd,
                shell=isinstance(cmd, str),
                capture_output=capture,
                text=True,
                check=check
            )
            return result.stdout if capture else None
        except subprocess.CalledProcessError:
            return None

    def identify(self, image_path, format_str):
        """Run ImageMagick identify command."""
        cmd = ['identify', '-format', format_str, str(image_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ''

    def convert(self, args):
        """Run ImageMagick convert command."""
        cmd = ['convert'] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def scan_directories(self):
        """Scan working directory to populate navigation structures."""
        print("Scanning directories", end='', flush=True)

        root_depth = len(self.topdir.parts)
        sequence_keyword = self.config.get('sequence_keyword', '')

        # Find all directories, sorted
        all_dirs = sorted([
            d for d in self.topdir.rglob('*')
            if d.is_dir()
        ])
        # Include topdir itself
        all_dirs = [self.topdir] + all_dirs

        for node in all_dirs:
            print('.', end='', flush=True)

            # Skip _site directory
            if node == self.topdir / '_site' or str(node).startswith(str(self.topdir / '_site')):
                continue

            # Skip directories under _* paths
            rel_parts = node.relative_to(self.topdir).parts if node != self.topdir else ()
            if any(part.startswith('_') for part in rel_parts):
                continue

            # Skip hidden directories (starting with .)
            if node != self.topdir and any(part.startswith('.') for part in rel_parts):
                continue

            # Calculate depth
            node_depth = len(node.parts) - root_depth

            # Skip empty directories
            try:
                if not any(node.iterdir()):
                    continue
            except PermissionError:
                continue

            # Get node name with prefix stripped
            node_name = self.strip_numeric_prefix(node.name)
            if not node_name:
                node_name = node.name

            # Count subdirectories (excluding _ prefixed)
            subdirs = [
                d for d in node.iterdir()
                if d.is_dir() and not d.name.startswith('_')
            ]
            dircount = len(subdirs)

            # Count subdirs excluding sequence keyword dirs
            if sequence_keyword:
                dircount_sequence = len([
                    d for d in subdirs
                    if sequence_keyword not in d.name
                ])
            else:
                dircount_sequence = dircount

            # Determine node type
            if dircount > 0:
                if not sequence_keyword or dircount_sequence > 0:
                    node_type = 0  # Contains other dirs, not a leaf
                else:
                    node_type = 1  # Contains only sequence dirs
            else:
                if sequence_keyword and sequence_keyword in node_name:
                    continue  # Skip sequence directories
                else:
                    node_type = 1  # Leaf directory

            self.paths.append(node)
            self.nav_name.append(node_name)
            self.nav_depth.append(node_depth)
            self.nav_type.append(node_type)

        # Create _site directory
        (self.topdir / '_site').mkdir(exist_ok=True)

        # Build URL structure
        dir_stack = []
        url_rel = ''
        self.nav_url.append('.')  # First item is topdir

        print("\nPopulating nav", end='', flush=True)

        for i in range(1, len(self.paths)):
            print('.', end='', flush=True)

            if i > 1:
                if self.nav_depth[i] > self.nav_depth[i-1]:
                    dir_stack.append(url_rel)
                elif self.nav_depth[i] < self.nav_depth[i-1]:
                    diff = self.nav_depth[i-1]
                    while diff > self.nav_depth[i]:
                        if dir_stack:
                            dir_stack.pop()
                        diff -= 1

            url_rel = self.url_safe(self.nav_name[i])

            url = '/'.join(dir_stack + [url_rel]) if dir_stack else url_rel

            (self.topdir / '_site' / url).mkdir(parents=True, exist_ok=True)
            self.nav_url.append(url)

        print()

    def read_files(self):
        """Read files to populate gallery structures."""
        print("Reading files", end='', flush=True)

        sequence_keyword = self.config.get('sequence_keyword', '')

        for i, path in enumerate(self.paths):
            self.nav_count.append(-1)

            if self.nav_type[i] < 1:
                continue

            dir_path = path
            url = self.nav_url[i]

            (self.topdir / '_site' / url).mkdir(parents=True, exist_ok=True)

            index = 0

            # Get files in directory, sorted
            files = sorted([
                f for f in dir_path.iterdir()
                if not f.name.startswith('_')
            ])

            for file_path in files:
                print('.', end='', flush=True)

                filename = file_path.name
                trimmed = re.sub(r'^[\s0-9]*', '', file_path.stem).strip()
                if not trimmed:
                    trimmed = file_path.stem

                image_url = self.url_safe(trimmed)

                # Check if this is a sequence directory
                if file_path.is_dir() and sequence_keyword and sequence_keyword in filename:
                    format_type = 'sequence'
                    # Find first image in sequence
                    seq_images = sorted([
                        f for f in file_path.iterdir()
                        if f.suffix.lower() in ['.jpg', '.jpeg', '.gif', '.png']
                    ])
                    if seq_images:
                        image = seq_images[0]
                    else:
                        continue
                elif file_path.is_file():
                    extension = file_path.suffix.lower().lstrip('.')

                    if extension in ['jpg', 'jpeg', 'png', 'gif']:
                        format_type = extension
                        image = file_path
                    elif extension in VIDEO_EXTENSIONS:
                        if not self.video_enabled:
                            continue
                        format_type = 'video'
                        # Extract frame from video
                        temp_path = self.scratchdir / 'temp.jpg'
                        subprocess.run([
                            'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                            '-i', str(file_path),
                            '-vf', 'select=gte(n\\,1)',
                            '-vframes', '1', '-qscale:v', '2',
                            str(temp_path)
                        ], stdin=subprocess.DEVNULL)
                        image = temp_path
                    else:
                        # Check if it's a video by mime type
                        if not self.video_enabled:
                            continue
                        result = subprocess.run(
                            ['file', '-ib', str(file_path)],
                            capture_output=True, text=True
                        )
                        if 'video' not in result.stdout:
                            continue
                        format_type = 'video'
                        temp_path = self.scratchdir / 'temp.jpg'
                        subprocess.run([
                            'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                            '-i', str(file_path),
                            '-vf', 'select=gte(n\\,1)',
                            '-vframes', '1', '-qscale:v', '2',
                            str(temp_path)
                        ], stdin=subprocess.DEVNULL)
                        image = temp_path
                else:
                    continue

                # Extract color palette
                if self.config['extract_colors']:
                    result = subprocess.run([
                        'convert', str(image),
                        '-resize', '200x200',
                        '-depth', '4',
                        '+dither',
                        '-colors', '7',
                        '-unique-colors',
                        'txt:-'
                    ], capture_output=True, text=True)

                    # Parse colors from output
                    palette = []
                    for line in result.stdout.split('\n')[1:]:  # Skip header
                        match = re.search(r'#[0-9A-Fa-f]+', line)
                        if match:
                            palette.append(match.group())
                else:
                    palette = list(self.config['default_palette'])

                # Get image dimensions with EXIF orientation handling
                orientation = self.identify(image, '%[EXIF:Orientation]')

                if (self.config['autorotate'] and orientation and
                    orientation.isdigit() and 5 <= int(orientation) <= 8):
                    # Rotated image - swap dimensions
                    width = int(self.identify(image, '%h') or '0')
                    height = int(self.identify(image, '%w') or '0')
                else:
                    width = int(self.identify(image, '%w') or '0')
                    height = int(self.identify(image, '%h') or '0')

                # Calculate max dimensions
                maxwidth = 0
                maxheight = 0
                resolutions = self.config['resolution']

                for count, res in enumerate(resolutions, 1):
                    if width >= res and res > maxwidth:
                        maxwidth = res
                        maxheight = res * height // width if width else 0
                    elif maxwidth == 0 and count == len(resolutions):
                        maxwidth = res
                        maxheight = res * height // width if width else 0

                index += 1

                # Store file info
                self.gallery_files.append(file_path)
                self.gallery_nav.append(i)
                self.gallery_url.append(image_url)

                if format_type == 'sequence':
                    self.gallery_type.append(2)
                elif format_type == 'video':
                    self.gallery_type.append(1)
                else:
                    self.gallery_type.append(0)

                self.gallery_maxwidth.append(maxwidth)
                self.gallery_maxheight.append(maxheight)
                self.gallery_colors.append(palette)
                self.gallery_image_options.append('')
                self.gallery_video_options.append('')
                self.gallery_video_filters.append('')

            self.nav_count[i] = index

        print()

    def build_html(self):
        """Build HTML files for each gallery."""
        print("Building HTML", end='', flush=True)

        theme_dir = self.scriptdir / self.config['theme_dir']
        template_html = (theme_dir / 'template.html').read_text()
        post_template_html = (theme_dir / 'post-template.html').read_text()

        gallery_index = 0
        firsthtml = ''
        firstpath = ''

        for i, path in enumerate(self.paths):
            if self.nav_type[i] < 1:
                continue

            html = template_html

            # Read gallery metadata
            metadata_file = path / 'metadata.txt'
            gallery_metadata = metadata_file.read_text() if metadata_file.exists() else ''

            nav_count = self.nav_count[i]
            for j in range(nav_count):
                print('.', end='', flush=True)

                k = j + 1
                file_path = self.gallery_files[gallery_index]
                file_type = self.gallery_type[gallery_index]

                # Find text file with same name
                filename = file_path.stem
                filedir = file_path.parent

                media_type = 'image' if file_type == 0 else 'video'

                # Look for .txt or .md file
                textfile = None
                for ext in ['.txt', '.md']:
                    candidate = filedir / (filename + ext)
                    if candidate.exists() and candidate != file_path:
                        textfile = candidate
                        break

                metadata = ''
                content = ''

                if textfile and textfile.exists():
                    text = textfile.read_text().replace('\r', '').rstrip('\n')

                    # Find metadata section (before second ---)
                    lines = text.split('\n')
                    dash_lines = [idx for idx, line in enumerate(lines) if line == '---']

                    if len(dash_lines) >= 2:
                        metaline = dash_lines[1]
                        metadata = '\n'.join(lines[:metaline + 1])
                        content = '\n'.join(lines[metaline + 1:])
                    elif len(dash_lines) == 1:
                        metaline = dash_lines[0]
                        metadata = '\n'.join(lines[:metaline + 1])
                        content = '\n'.join(lines[metaline + 1:])
                    else:
                        content = text

                # Add gallery metadata
                metadata += '\n' + gallery_metadata + '\n'

                # Add color palette to metadata
                colors = self.gallery_colors[gallery_index]
                for z, color in enumerate(colors, 1):
                    metadata += f'color{z}:{color}\n'

                # Set background and text colors (match shell: use color2 or empty)
                backgroundcolor = colors[1] if len(colors) > 1 else ''
                if self.config['override_textcolor']:
                    textcolor = self.config['textcolor']
                else:
                    textcolor = colors[-1] if colors else self.config['textcolor']

                # Process markdown if perl available
                if shutil.which('perl'):
                    markdown_script = self.scriptdir / 'Markdown_1.0.1' / 'Markdown.pl'
                    if markdown_script.exists():
                        result = subprocess.run(
                            ['perl', str(markdown_script), '--html4tags'],
                            input=content,
                            capture_output=True,
                            text=True
                        )
                        content = result.stdout

                # Apply post template
                post = self.template(post_template_html, 'index', str(k))
                post = self.template(post, 'post', content)

                # Parse and apply metadata
                for line in metadata.split('\n'):
                    if ':' not in line:
                        continue
                    key = line.split(':')[0].strip()
                    value = ':'.join(line.split(':')[1:]).strip()

                    if key and value:
                        post = self.template(post, key, value)

                        if key == 'image-options':
                            self.gallery_image_options[gallery_index] = value
                        elif key == 'video-options':
                            self.gallery_video_options[gallery_index] = value
                        elif key == 'video-filters':
                            self.gallery_video_filters[gallery_index] = value

                # Set image parameters
                post = self.template(post, 'imageurl', self.gallery_url[gallery_index])
                post = self.template(post, 'imagewidth', str(self.gallery_maxwidth[gallery_index]))
                post = self.template(post, 'imageheight', str(self.gallery_maxheight[gallery_index]))

                # Set colors
                post = self.template(post, 'textcolor', textcolor)
                post = self.template(post, 'backgroundcolor', backgroundcolor)
                post = self.template(post, 'type', media_type)

                # Append to main template
                html = self.template(html, 'content', post + ' {{content}}')

                gallery_index += 1

            # Write HTML file variables
            html = self.template(html, 'sitetitle', self.config['site_title'])
            html = self.template(html, 'gallerytitle', self.nav_name[i])
            html = self.template(html, 'disqus_shortname', self.config['disqus_shortname'])

            resolution_str = ' '.join(str(r) for r in self.config['resolution'])
            html = self.template(html, 'resolution', resolution_str)

            format_str = ' '.join(self.config['video_formats'])
            html = self.template(html, 'videoformats', format_str)

            # Toggle displays
            html = self.template(html, 'text_toggle', 'block' if self.config['text_toggle'] else 'none')
            html = self.template(html, 'social_button', 'block' if self.config['social_button'] else 'none')
            html = self.template(html, 'download_button', 'block' if self.config['download_button'] else 'none')

            # Build navigation
            navigation = self._build_navigation(i)
            html = self.template(html, 'navigation', navigation)

            # Store first HTML for index
            if not firsthtml:
                firsthtml = html
                firstpath = self.nav_url[i]

            # Set basepath
            if self.nav_depth[i] == 0:
                basepath = './'
            else:
                basepath = '../' * self.nav_depth[i]

            html = self.template(html, 'basepath', basepath)
            html = self.template(html, 'disqus_identifier', self.nav_url[i])

            # Set default values for {{XXX:default}} strings
            html = re.sub(r'\{\{[^{}]*:([^}]*)\}\}', r'\1', html)

            # Remove unused template variables and empty <ul>s
            html = re.sub(r'\{\{[^}]*\}\}', '', html)
            html = html.replace('<ul></ul>', '')

            # Write HTML file
            output_path = self.topdir / '_site' / self.nav_url[i] / 'index.html'
            output_path.write_text(html)

        # Write top-level index.html
        if firsthtml:
            firsthtml = self.template(firsthtml, 'basepath', './')
            firsthtml = self.template(firsthtml, 'disqus_identifier', firstpath)
            firsthtml = self.template(firsthtml, 'resourcepath', firstpath + '/')
            firsthtml = re.sub(r'\{\{[^{}]*:([^}]*)\}\}', r'\1', firsthtml)
            firsthtml = re.sub(r'\{\{[^}]*\}\}', '', firsthtml)
            firsthtml = firsthtml.replace('<ul></ul>', '')

            (self.topdir / '_site' / 'index.html').write_text(firsthtml)

        print()

    def _build_navigation(self, current_idx):
        """Build navigation menu HTML."""
        navigation = ''
        depth = 1
        prevdepth = 0
        remaining = len(self.paths)
        parent = -1

        while remaining > 1:
            for j, path in enumerate(self.paths):
                if depth > 1 and self.nav_depth[j] == prevdepth:
                    parent = j

                active = 'active' if current_idx == j else ''

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
                    navigation = self.template(navigation, f'marker{parent}', substring)
                    remaining -= 1

            prevdepth += 1
            depth += 1

        return navigation

    def _find_gallery_index(self, nav_idx):
        """Find first gallery index for a navigation item."""
        for k, nav in enumerate(self.gallery_nav):
            if nav == nav_idx:
                return k
        return 0

    def encode_media(self):
        """Resize images and encode videos."""
        print("Starting encode")

        for i, file_path in enumerate(self.gallery_files):
            print(self.gallery_url[i])

            navindex = self.gallery_nav[i]
            url = f"{self.nav_url[navindex]}/{self.gallery_url[i]}"

            output_dir = self.topdir / '_site' / url
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
                temp_path = self.scratchdir / 'temp.jpg'
                filters = self.gallery_video_filters[i]
                filter_arg = f',{filters}' if filters else ''

                subprocess.run([
                    'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                    '-i', str(filepath),
                    '-vf', f'select=gte(n\\,1){filter_arg}',
                    '-vframes', '1', '-qscale:v', '2',
                    str(temp_path)
                ], stdin=subprocess.DEVNULL)
                image = temp_path

            # Generate static images for each resolution
            self._encode_images(image, url, i)

            # Write zip file if download enabled
            if self.config['download_button']:
                self._create_download_zip(file_path, url, i)

            # Clean scratch directory
            for f in self.scratchdir.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f)

    def _sequence_finished(self, url):
        """Check if sequence encoding is already complete."""
        for res in self.config['resolution']:
            for vformat in self.config['video_formats']:
                ext = VIDEO_FORMAT_EXTENSIONS.get(vformat, 'mp4')
                videofile = self.topdir / '_site' / url / f'{res}-{vformat}.{ext}'
                if not videofile.exists() or videofile.stat().st_size == 0:
                    return False
        return True

    def _compile_sequence(self, seq_dir):
        """Compile image sequence to video."""
        # Copy files to scratch with sequential names
        images = sorted([
            f for f in seq_dir.iterdir()
            if f.suffix.lower() in ['.jpg', '.jpeg', '.gif', '.png']
        ])

        if not images:
            return None

        for j, img in enumerate(images):
            shutil.copy(img, self.scratchdir / f'{j:04d}{img.suffix}')

        sequence_video = self.scratchdir / 'sequencevideo.mp4'
        maxres = max(self.config['resolution'])

        # Get extension of first image for input pattern
        first_ext = images[0].suffix

        subprocess.run([
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-f', 'image2', '-y',
            '-i', str(self.scratchdir / f'%04d{first_ext}'),
            '-c:v', 'libx264',
            '-threads', str(self.config['ffmpeg_threads']),
            '-vf', f'scale={maxres}:trunc(ow/a/2)*2',
            '-profile:v', 'high',
            '-pix_fmt', 'yuv420p',
            '-preset', self.config['h264_encodespeed'],
            '-crf', '15',
            '-r', str(self.config['sequence_framerate']),
            '-f', 'mp4',
            str(sequence_video)
        ])

        return sequence_video if sequence_video.exists() else None

    def _encode_video(self, filepath, url, index):
        """Encode video to multiple formats and resolutions."""
        # Get video dimensions
        result = subprocess.run([
            'ffprobe', '-v', 'error',
            '-of', 'flat=s=_',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            str(filepath)
        ], capture_output=True, text=True)

        dimensions = {}
        for line in result.stdout.split('\n'):
            if 'width' in line:
                dimensions['width'] = int(line.split('=')[1])
            elif 'height' in line:
                dimensions['height'] = int(line.split('=')[1])

        width = dimensions.get('width', 0)
        height = dimensions.get('height', 0)

        options = self.gallery_video_options[index]
        filters = self.gallery_video_filters[index]
        filters_arg = f',{filters}' if filters else ''
        filters_full = ['-vf', filters] if filters else []

        audio_args = ['-an'] if self.config['disable_audio'] else ['-c:a', 'copy']

        if self.draft:
            # Draft mode: single pass CRF with ultrafast preset
            res = self.config['resolution'][0]
            output_path = self.topdir / '_site' / url / f'{res}-h264.mp4'

            if output_path.exists() and output_path.stat().st_size > 0:
                return

            self.output_url = str(output_path)

            cmd = [
                'ffmpeg', '-loglevel', 'error', '-nostdin',
                '-i', str(filepath),
                '-c:v', 'libx264',
                '-threads', str(self.config['ffmpeg_threads']),
                '-vf', f'scale={res}:trunc(ow/a/2)*2{filters_arg}',
                '-profile:v', 'high',
                '-pix_fmt', 'yuv420p',
                '-preset', 'ultrafast',
                '-crf', '26'
            ] + audio_args + [
                '-movflags', '+faststart',
                '-f', 'mp4',
                str(output_path)
            ]
            subprocess.run(cmd)
            self.output_url = None
        else:
            # Full encode: 2-pass VBR
            for vformat in self.config['video_formats']:
                firstpass = False

                for j, res in enumerate(self.config['resolution']):
                    if width < res:
                        continue

                    mbit = self.config['bitrate'][j] if j < len(self.config['bitrate']) else self.config['bitrate'][-1]
                    mbitmax = mbit * self.config['bitrate_maxratio']
                    scaled_height = height * res // width if width else 0

                    ext = VIDEO_FORMAT_EXTENSIONS.get(vformat, 'mp4')
                    videofile = f'{res}-{vformat}.{ext}'
                    output_path = self.topdir / '_site' / url / videofile

                    if output_path.exists() and output_path.stat().st_size > 0:
                        continue

                    self.output_url = str(output_path)
                    print(f'\tEncoding {vformat} {res} x {scaled_height}')

                    if vformat == 'h265':
                        success = self._encode_h265(filepath, output_path, res, mbit, mbitmax,
                                                    filters_arg, filters_full, audio_args, firstpass)
                    elif vformat == 'h264':
                        success = self._encode_h264(filepath, output_path, res, mbit, mbitmax,
                                                    filters_arg, filters_full, audio_args, firstpass)
                    elif vformat == 'vp9':
                        success = self._encode_vp9(filepath, output_path, res, mbit, mbitmax,
                                                   filters_arg, filters_full, audio_args, firstpass)
                    elif vformat == 'vp8':
                        success = self._encode_vp8(filepath, output_path, res, mbit, mbitmax,
                                                   filters_arg, filters_full, audio_args, firstpass)
                    elif vformat == 'ogv':
                        self._encode_ogv(filepath, output_path, res, mbit, mbitmax,
                                        filters_arg, audio_args)
                        success = True
                    else:
                        success = True

                    if not success:
                        break  # Skip this format entirely

                    if not firstpass:
                        firstpass = True

                    self.output_url = None

    def _encode_h264(self, filepath, output, res, mbit, mbitmax, filters_arg, filters_full, audio_args, firstpass):
        """Encode h264 video with 2-pass."""
        if not firstpass:
            cmd = [
                'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                '-i', str(filepath),
                '-c:v', 'libx264',
                '-threads', str(self.config['ffmpeg_threads'])
            ] + filters_full + [
                '-profile:v', 'high',
                '-pix_fmt', 'yuv420p',
                '-preset', self.config['h264_encodespeed'],
                '-b:v', f'{mbit}M',
                '-maxrate', f'{mbitmax}M',
                '-bufsize', f'{mbitmax}M',
                '-pass', '1',
                '-an',
                '-f', 'mp4',
                '/dev/null'
            ]
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = [
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', str(filepath),
            '-c:v', 'libx264',
            '-threads', str(self.config['ffmpeg_threads']),
            '-vf', f'scale={res}:trunc(ow/a/2)*2{filters_arg}',
            '-profile:v', 'high',
            '-pix_fmt', 'yuv420p',
            '-preset', self.config['h264_encodespeed'],
            '-b:v', f'{mbit}M',
            '-maxrate', f'{mbitmax}M',
            '-bufsize', f'{mbitmax}M',
            '-pass', '2'
        ] + audio_args + [
            '-movflags', '+faststart',
            '-f', 'mp4',
            str(output)
        ]
        subprocess.run(cmd)
        return True

    def _encode_h265(self, filepath, output, res, mbit, mbitmax, filters_arg, filters_full, audio_args, firstpass):
        """Encode h265 video with 2-pass."""
        if not firstpass:
            cmd = [
                'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                '-i', str(filepath),
                '-c:v', 'libx265',
                '-threads', str(self.config['ffmpeg_threads'])
            ] + filters_full + [
                '-pix_fmt', 'yuv420p',
                '-preset', self.config['h264_encodespeed'],
                '-b:v', f'{mbit}M',
                '-maxrate', f'{mbitmax}M',
                '-bufsize', f'{mbitmax}M',
                '-pass', '1',
                '-an',
                '-f', 'mp4',
                '/dev/null'
            ]
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = [
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', str(filepath),
            '-c:v', 'libx265',
            '-threads', str(self.config['ffmpeg_threads']),
            '-vf', f'scale={res}:trunc(ow/a/2)*2{filters_arg}',
            '-pix_fmt', 'yuv420p',
            '-preset', self.config['h264_encodespeed'],
            '-b:v', f'{mbit}M',
            '-maxrate', f'{mbitmax}M',
            '-bufsize', f'{mbitmax}M',
            '-pass', '2'
        ] + audio_args + [
            '-movflags', '+faststart',
            '-f', 'mp4',
            str(output)
        ]
        subprocess.run(cmd)
        return True

    def _encode_vp9(self, filepath, output, res, mbit, mbitmax, filters_arg, filters_full, audio_args, firstpass):
        """Encode VP9 video with 2-pass."""
        if not firstpass:
            cmd = [
                'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                '-i', str(filepath),
                '-c:v', 'libvpx-vp9',
                '-threads', str(self.config['ffmpeg_threads'])
            ] + filters_full + [
                '-pix_fmt', 'yuv420p',
                '-speed', '4',
                '-b:v', f'{mbit}M',
                '-maxrate', f'{mbitmax}M',
                '-bufsize', f'{mbitmax}M',
                '-pass', '1',
                '-an',
                '-f', 'webm',
                '/dev/null'
            ]
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = [
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', str(filepath),
            '-c:v', 'libvpx-vp9',
            '-threads', str(self.config['ffmpeg_threads']),
            '-vf', f'scale={res}:trunc(ow/a/2)*2{filters_arg}',
            '-pix_fmt', 'yuv420p',
            '-speed', str(self.config['vp9_encodespeed']),
            '-b:v', f'{mbit}M',
            '-maxrate', f'{mbitmax}M',
            '-bufsize', f'{mbitmax}M',
            '-pass', '2'
        ] + audio_args + [
            '-f', 'webm',
            str(output)
        ]
        subprocess.run(cmd)
        return True

    def _encode_vp8(self, filepath, output, res, mbit, mbitmax, filters_arg, filters_full, audio_args, firstpass):
        """Encode VP8 video with 2-pass."""
        if not firstpass:
            cmd = [
                'ffmpeg', '-loglevel', 'error', '-nostdin', '-y',
                '-i', str(filepath),
                '-c:v', 'libvpx',
                '-threads', str(self.config['ffmpeg_threads'])
            ] + filters_full + [
                '-pix_fmt', 'yuv420p',
                '-b:v', f'{mbit}M',
                '-maxrate', f'{mbitmax}M',
                '-bufsize', f'{mbitmax}M',
                '-pass', '1',
                '-an',
                '-f', 'webm',
                '/dev/null'
            ]
            result = subprocess.run(cmd)
            if result.returncode != 0:
                return False

        cmd = [
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', str(filepath),
            '-c:v', 'libvpx',
            '-threads', str(self.config['ffmpeg_threads']),
            '-vf', f'scale={res}:trunc(ow/a/2)*2{filters_arg}',
            '-pix_fmt', 'yuv420p',
            '-b:v', f'{mbit}M',
            '-maxrate', f'{mbitmax}M',
            '-bufsize', f'{mbitmax}M',
            '-pass', '2'
        ] + audio_args + [
            '-f', 'webm',
            str(output)
        ]
        subprocess.run(cmd)
        return True

    def _encode_ogv(self, filepath, output, res, mbit, mbitmax, filters_arg, audio_args):
        """Encode Theora video (1-pass)."""
        cmd = [
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', str(filepath),
            '-c:v', 'libtheora',
            '-threads', str(self.config['ffmpeg_threads']),
            '-vf', f'scale={res}:trunc(ow/a/2)*2{filters_arg}',
            '-pix_fmt', 'yuv420p',
            '-b:v', f'{mbit}M',
            '-maxrate', f'{mbitmax}M',
            '-bufsize', f'{mbitmax}M'
        ] + audio_args + [
            str(output)
        ]
        subprocess.run(cmd)

    def _encode_images(self, image, url, index):
        """Generate static images for each resolution."""
        width_str = self.identify(image, '%w')
        width = int(width_str) if width_str else 0

        options = self.gallery_image_options[index]

        # Don't apply image options to videos
        if self.gallery_type[index] == 1:
            options = ''

        resolutions = self.config['resolution']

        for count, res in enumerate(resolutions, 1):
            output_path = self.topdir / '_site' / url / f'{res}.jpg'

            if output_path.exists():
                continue

            # Only downscale or use smallest resolution
            if width >= res or count == len(resolutions):
                cmd = ['convert']
                if self.autorotate_option.strip():
                    cmd.append('-auto-orient')
                cmd.extend([
                    '-size', f'{res}x{res}',
                    str(image),
                    '-resize', f'{res}x{res}',
                    '-quality', str(self.config['jpeg_quality']),
                    '+profile', '*'
                ])
                if options:
                    cmd.extend(options.split())
                cmd.append(str(output_path))

                subprocess.run(cmd)

    def _create_download_zip(self, file_path, url, index):
        """Create ZIP file for download."""
        zip_path = self.topdir / '_site' / url / f'{self.gallery_url[index]}.zip'

        if zip_path.exists():
            return

        zip_dir = self.scratchdir / 'zip'
        zip_dir.mkdir(exist_ok=True)

        if self.gallery_type[index] == 2:
            # For sequences, use the compiled video
            filezip = self.scratchdir / 'sequencevideo.mp4'
            if not filezip.exists():
                filezip = file_path
        else:
            filezip = file_path

        filename = filezip.name
        shutil.copy(filezip, zip_dir / filename)

        # Write readme
        (zip_dir / 'readme.txt').write_text(self.config['download_readme'])

        os.chmod(zip_dir, 0o740)

        # Create zip
        original_dir = os.getcwd()
        os.chdir(zip_dir)
        subprocess.run(['zip', '-r', str(zip_path), './'], capture_output=True)
        os.chdir(original_dir)

    def copy_resources(self):
        """Copy theme resources to _site."""
        theme_dir = self.scriptdir / self.config['theme_dir']
        site_dir = self.topdir / '_site'

        for item in theme_dir.iterdir():
            if item.name in ['template.html', 'post-template.html']:
                continue

            dest = site_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    def run(self):
        """Run the full generation process."""
        self.scan_directories()
        self.read_files()
        self.build_html()
        self.encode_media()
        self.copy_resources()
        self.cleanup()


def check_dependencies():
    """Check required dependencies are available."""
    if not shutil.which('convert'):
        print("ImageMagick is a required dependency, aborting...", file=sys.stderr)
        sys.exit(1)
    if not shutil.which('identify'):
        print("ImageMagick is a required dependency, aborting...", file=sys.stderr)
        sys.exit(1)


def load_config(topdir, scriptdir):
    """Load configuration from _config.json or use defaults."""
    config = dict(DEFAULT_CONFIG)

    config_path = Path(topdir) / '_config.json'
    if config_path.exists():
        with open(config_path) as f:
            user_config = json.load(f)
            config.update(user_config)

    return config


def main():
    parser = argparse.ArgumentParser(description='Expose - Static photography website generator')
    parser.add_argument('-d', '--draft', action='store_true',
                        help='Draft mode: single resolution, fast encoding')
    args = parser.parse_args()

    check_dependencies()

    topdir = Path.cwd()
    scriptdir = Path(__file__).parent.resolve()

    config = load_config(topdir, scriptdir)

    generator = ExposeGenerator(topdir, scriptdir, config, draft=args.draft)

    # Set up signal handlers for cleanup
    def signal_handler(sig, frame):
        generator.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(generator.cleanup)

    generator.run()


if __name__ == '__main__':
    main()
