# Dorothea configuration

Settings are read, in increasing order of precedence, from:

1. built-in defaults: Dorothea's, or expose.sh's with `--legacy` / `"legacy": true` (below)
2. `_config.json` in the gallery folder, or `--config FILE` (`.json` or `.sh`). Without a
   `_config.json`, expose.sh's `_config.sh` is read instead (see [MIGRATION.md](MIGRATION.md))
3. `--set KEY=VALUE`, `-j N`, `--sort`, `--ffmpeg` and `--legacy` on the command line
4. draft mode (`-d`), which forces `resolution=[1024]`, `bitrate=[4]`, `video_formats=["h264"]`
   and `download_button=false`

```json
{
  "site_title": "Iceland 2022",
  "theme_dir": "theme2",
  "resolution": [2560, 1920, 1280, 640],
  "jpeg_quality": 88
}
```

Invalid values stop the build with a message naming each problem (exit code 2); unknown keys
only print a warning, since they're usually typos.

Changing a setting that affects image or video bytes (resolution, quality, bitrates, codec
speed, per-post options...) re-encodes just the affected files on the next run. There's no need
to delete `_site`.

## Legacy (expose.sh) defaults

Dorothea's defaults improve on expose.sh's in seven places. With `--legacy` (or `"legacy": true`
in `_config.json`) the defaults are exactly expose.sh's, so a gallery builds the same site as
expose.sh would. Anything you set explicitly still wins in both modes; `--no-legacy` overrides
`"legacy": true` in the config file.

| Key | Dorothea default | `--legacy` (expose.sh) |
|---|---|---|
| `theme_dir` | `"photoessay"` | `"theme1"` |
| `sort` | `"natural"` (`1, 2, 10`) | `"name"` (`1, 10, 2`) |
| `video_formats` | `["h264", "vp9"]` | `["h264", "vp8"]` |
| `h264_encodespeed` | `"slow"` | `"veryslow"` |
| `social_button` | `false` | `true` |
| `convert_to_srgb` | `true` | `false` |
| `keep_metadata` | `"camera"` | `"none"` |
| `legacy` | `false` | `true` |

Bug fixes (hidden files, non-Latin names, colliding names, …) apply in both modes; see
[MIGRATION.md](MIGRATION.md).

## Site and theme

| Key | Default | Description |
|---|---|---|
| `site_title` | `"My Awesome Photos"` | Site name shown in every page. |
| `theme_dir` | `"photoessay"` (legacy: `"theme1"`) | Theme: a bundled one, a folder of that name in the gallery, or an absolute path. Bundled: `photoessay` (full-screen photo essay) and `medium` (Medium-style column), which add keyboard navigation between photos (↓ / PageDown / → / Space / j for next, ↑ / PageUp / ← / Shift+Space / k for previous, Home / End for first / last); and expose.sh's original `theme1` and `theme2`, which they're based on and which stay unchanged. |
| `text_toggle` | `true` | Show a button to hide/show the text. |
| `social_button` | `false` (legacy: `true`) | Show the social sharing button. |
| `disqus_shortname` | `""` | Disqus forum name for comments; empty disables them. |
| `link_index_html` | `false` | Link galleries to `…/gallery/index.html` instead of `…/gallery`. Gallery links point at folders, which a web server (or `dorothea serve`) answers with the folder's `index.html`; opened straight from disk, or on a host without directory indexes, they show a folder listing instead. Turn this on for a site browsed from disk (e.g. copied onto a USB stick). Dorothea-only. |

## Images

| Key | Default | Description |
|---|---|---|
| `resolution` | `[3840, 2560, 1920, 1280, 1024, 640]` | Widths to generate (heights follow the source aspect ratio). Only sizes up to the source width are made, plus the smallest one always. |
| `jpeg_quality` | `92` | JPEG quality (1–100) for generated images. |
| `autorotate` | `true` | Apply EXIF orientation. |
| `convert_to_srgb` | `true` (legacy: `false`) | Convert photos in a wide colour space (Display P3 from phones, Adobe RGB from many cameras) to sRGB. Without it the colour profile is simply removed, as expose.sh does, and those photos look duller in browsers. Photos that are already sRGB, or have no profile, are untouched. Dorothea-only. |
| `keep_metadata` | `"camera"` (legacy: `"none"`) | Which photo metadata (EXIF) the resized images keep. See the levels below. Dorothea-only. |

`keep_metadata` levels:

| Level | Keeps |
|---|---|
| `"none"` | nothing (expose.sh's behaviour) |
| `"copyright"` | artist and copyright |
| `"camera"` | copyright, plus camera and lens, focal length, aperture, shutter speed, ISO, exposure settings and when the photo was taken |
| `"location"` | copyright, plus GPS location |
| `"cameralocation"` | copyright, camera settings and GPS location |
| `"all"` | everything, including GPS location, the editing software, camera serial numbers, maker notes and XMP |

> **Privacy:** `"location"`, `"cameralocation"` and `"all"` publish **where each photo was taken**:
> anyone can download a photo and read its GPS coordinates. The default (`"camera"`) never does.

The orientation tag is always reset, since the resized images are already rotated upright. Photos
that use `image-options` are processed by ImageMagick, which keeps no metadata (they are still
converted to sRGB). If `convert_to_srgb` is off and metadata is kept, a wide-gamut photo keeps its
colour profile, so its colours stay right.

## Colours

| Key | Default | Description |
|---|---|---|
| `extract_colors` | `true` | Extract a 7-colour palette from each photo/video for the theme (`color1`…`color7`, background, text). |
| `default_palette` | `["#000000", "#222222", "#444444", "#666666", "#999999", "#cccccc", "#ffffff"]` | Palette (background to foreground) used when `extract_colors` is false. |
| `backgroundcolor` | `"#000000"` | Slide background, visible before the image loads. |
| `textcolor` | `"#ffffff"` | Default text colour. |
| `override_textcolor` | `true` | Use `textcolor` for body text instead of the palette's last colour. |

## Video

Video needs ffmpeg: by default a system `ffmpeg` on `PATH` is used if present, otherwise the one
bundled with Dorothea (imageio-ffmpeg); the `ffmpeg` setting below picks explicitly. Builds with
videos print which ffmpeg they use.

| Key | Default | Description |
|---|---|---|
| `video_formats` | `["h264", "vp9"]` (legacy: `["h264", "vp8"]`) | Formats to encode, in order of preference: `h264`, `h265`, `vp9`, `vp8`, `ogv`. |
| `bitrate` | `[40, 24, 12, 7, 4, 2]` | Target bitrate in Mbit/s for each entry in `resolution` (the last value repeats if the list is shorter). |
| `bitrate_maxratio` | `2` | Max bitrate as a multiple of the target (VBR). Must be ≥ 1; 1 means constant bitrate. |
| `disable_audio` | `true` | Strip audio. When `false`, audio is copied where the format allows it and re-encoded otherwise: MP4 keeps AAC/MP3 (anything else becomes AAC), WebM keeps Opus/Vorbis (else Opus), Ogg keeps Vorbis/Opus (else Vorbis). |
| `h264_encodespeed` | `"slow"` (legacy: `"veryslow"`) | x264/x265 preset: `ultrafast` … `veryslow`. Slower compresses better. |
| `vp9_encodespeed` | `1` | VP9 speed, 0 (best, very slow) to 4 (fastest). |
| `ffmpeg_threads` | `0` | ffmpeg `-threads` (0 = auto). Lower it to throttle CPU use. |
| `ffmpeg` | `"auto"` | Which ffmpeg to use: `"auto"` (the system one if installed, else the bundled one), `"bundled"`, `"system"`, or a path to an ffmpeg binary. Same as `--ffmpeg`. A system ffmpeg built without an encoder you need (e.g. libvpx for `vp8`) is reported at build time; switch to `"bundled"`. Dorothea-only. |
| `sequence_keyword` | `"imagesequence"` | A folder whose name contains this is compiled into a video from its images. |
| `sequence_framerate` | `24` | Frame rate of compiled image sequences. |

## Downloads

| Key | Default | Description |
|---|---|---|
| `download_button` | `false` | Offer each original in a zip with a readme. |
| `download_readme` | `"All rights reserved"` | Text of the `readme.txt` in each zip. |

## Dorothea-only

| Key | Default | Description |
|---|---|---|
| `jobs` | `0` | Parallel workers for reading and resizing images (0 = one per CPU). Same as `-j N`. Videos always encode one at a time, since ffmpeg already uses every core. |
| `sort` | `"natural"` (legacy: `"name"`) | Order of galleries and photos. `"natural"`: numbers compare as numbers (`1, 2, 10`), ignoring case. `"name"`: by name, like expose.sh (so `10` comes before `2` unless you zero-pad). `"capture"`: when photos were taken (EXIF capture time, else file time); galleries follow their earliest photo, so the site reads like the trip. Add `-desc` to reverse any of them (`"capture-desc"` for newest first). Same as `--sort`. A gallery's `metadata.txt` can set `sort:` for its own photos. |
| `legacy` | `false` | Use expose.sh's defaults instead of Dorothea's (see [Legacy defaults](#legacy-exposesh-defaults)). Same as `--legacy`. |

## Command line

| Flag | Description |
|---|---|
| `-d`, `--draft` | Draft mode: one 1024px size, fast h264 only. |
| `-n`, `--dry-run` | List what would be built (and why) without writing anything. |
| `-c FILE`, `--config FILE` | Use this config file (`.json` or expose.sh `.sh`). |
| `-s KEY=VALUE`, `--set KEY=VALUE` | Override a setting; VALUE is JSON if it parses (`--set 'resolution=[1920,640]'`), else a string. Repeatable. |
| `-j N`, `--jobs N` | Parallel workers (see `jobs`). |
| `--ffmpeg auto\|bundled\|system\|PATH` | Which ffmpeg to use (see `ffmpeg`). |
| `--sort MODE` | Order of galleries and photos (see `sort`). |
| `--legacy`, `--no-legacy` | Use expose.sh's defaults (or not, overriding the config file); see `legacy`. |
| `--convert-config` | Write `_config.json` from `_config.sh` and exit. |
| `--version` | Print the version. |
| `-h`, `--help` | Show all options. |

## Per-post metadata

A text file next to a photo or video with the same name holds its caption: `01 Glacier.txt` or
`01 Glacier.md` (if both exist, the `.txt` is used). Lines before a `---` line are `key: value`
metadata; the rest is Markdown either way. A `metadata.txt` in a gallery folder applies to every
post in it, and a post's own metadata wins.

```
image-options: -modulate 100,120
top: 30
left: 5
---
Caption in *Markdown*.
```

| Key | Description |
|---|---|
| `image-options` | Extra ImageMagick `convert` arguments for this photo (needs ImageMagick installed; otherwise ignored with a warning). Not applied to video thumbnails. |
| `video-options` | Extra ffmpeg arguments, e.g. `-ss 10 -t 5` to cut a clip. |
| `video-filters` | ffmpeg filters appended after scaling, e.g. `hflip`. |
| `textbackground` | A CSS colour drawn behind the caption text (with a little padding), e.g. `rgba(0,0,0,.5)` to keep white text readable over a bright photo. Works in both bundled themes; put it in `metadata.txt` to apply it to a whole gallery. Values containing `"`, `<`, `>`, `;`, `{`, `}` or `\` are ignored with a warning. Dorothea-only. |
| `sort` | Only in a gallery's `metadata.txt`: the order of that gallery's photos (any `sort` mode, e.g. `natural-desc` for a newest-first log), overriding the site setting. Dorothea-only. |
| anything else | Available to the theme as `{{key}}`. theme1 uses `top`, `left`, `width`, `height` (percent), `polygon` and `textcolor`; theme2 uses `width` and `class`. `color1`…`color7` come from the extracted palette. |

## Build cache

Dorothea keeps `.dorothea-cache.json` in the gallery folder. It holds extracted palettes, so
unchanged photos aren't re-analysed, and a fingerprint for every generated file, so changed
sources, settings or metadata rebuild exactly what they affect. It's safe to delete: the next
run re-analyses the photos and keeps any existing output that's newer than its source.
