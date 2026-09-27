# Migrating from expose.sh to Dorothea

Dorothea is a Python port of [expose.sh](https://github.com/Jack000/Expose). With `--legacy`
(expose.sh's default settings) it produces the same site: its test suite builds galleries with
both and checks that the file lists match, HTML/CSS/JS are byte-identical, and every image and
video has the same file size. This page covers what you need to change, and the places where
Dorothea deliberately behaves differently.

## Keeping expose.sh's output: `--legacy`

A few of Dorothea's default settings differ from expose.sh's: the `photoessay` theme (theme1
plus keyboard navigation; `theme1` and `theme2` are still bundled, unchanged), natural sort
order (`1, 2, 10`), vp9 instead of vp8 video, a faster h264 preset, no share menu, wide-gamut
photos converted to sRGB, and camera information (but never location) kept in the resized
photos. To keep exactly what expose.sh
made, run `dorothea --legacy`, or add `"legacy": true` to `_config.json`. Settings you set
explicitly win either way. The full list is in
[CONFIG.md](CONFIG.md#legacy-exposesh-defaults).

## Install

```sh
uvx dorothea                 # run without installing
uv tool install dorothea     # install the command

# with pipx, ask for Python 3.14 explicitly (pipx doesn't pick it from the package):
pipx install --python 3.14 --fetch-python=missing dorothea
```

No system packages are required: Pillow resizes images and an ffmpeg binary is bundled.
Optional:

- a system **ffmpeg** on `PATH` is preferred over the bundled one
- **ImageMagick** is used for colour extraction (identical palettes to expose.sh) and for
  per-post `image-options`

Run it the same way as before, inside the gallery folder: `dorothea` or `dorothea -d`. The
command is also installed as `expose`, so `expose -d` keeps working.

## Configuration

Your `_config.sh` keeps working: without a `_config.json`, Dorothea reads it. It's parsed,
never executed, so only plain assignments are supported:

```sh
site_title="Iceland 2022"        # quoted or unquoted values, comments
resolution=(2560 1920 1280 640)  # arrays on one line
autorotate=false                 # true/false become booleans, numbers become numbers
```

Anything else (`$(...)`, `${VAR}`, `export`, `if`) is skipped with a warning naming the line.
To switch to JSON, the recommended format:

```sh
dorothea --convert-config        # writes _config.json from _config.sh
```

If both files exist, `_config.json` wins. Every setting is described in
[CONFIG.md](CONFIG.md).

> **Note:** expose.sh ignores `resolution`, `bitrate`, `video_formats` and `default_palette` set
> in `_config.sh` (it reassigns them after reading the file). Dorothea honours them, so a
> gallery that set them will now actually use those values.

## New in Dorothea

- **Sort orders**: `sort` / `--sort` can order galleries and photos naturally (`1, 2, 10`, the
  default), by name (expose.sh's order, the `--legacy` default), by capture time (the site
  follows the trip), or in reverse.
- **Incremental builds that notice changes.** expose.sh skips any output that already exists,
  so edits needed a manual `rm -rf _site`. Dorothea rebuilds exactly the files whose source,
  settings or per-post metadata changed. State lives in `.dorothea-cache.json` in the gallery
  folder, which also caches colour palettes so re-runs are fast. An existing `_site` from
  expose.sh is adopted as-is, and files newer than their source aren't re-encoded.
- `-n` / `--dry-run` lists what would be built and why.
- `--set KEY=VALUE` overrides a setting for one run; `--config FILE` picks a config file.
- `-j N` resizes images in parallel (default: one worker per CPU).
- Config values are validated, with a clear error instead of a broken build.
- A failed or interrupted encode never leaves a truncated file behind; it's retried next run.
- A corrupt photo is reported and skipped instead of aborting the build.

## Intentional differences

These are places where expose.sh has a bug or a platform quirk that Dorothea doesn't copy:

| expose.sh | Dorothea |
|---|---|
| Skips hidden folders only at the top level (`.foo/`); a hidden folder inside a gallery (`gallery/.thumbs/`) is published as a gallery and the photos around it disappear. | Skips hidden folders at any depth without affecting the gallery around them. |
| Publishes hidden files (`.hidden.jpg`) and macOS `._` helper files as photos. | Ignores every name starting with `.` (as well as `_`). |
| Drops non-ASCII letters from URLs: `Москва` and `北京` become empty, `Café` becomes `caf`. | Keeps letters from any script (`москва`, `北京`, `café`); names with no letters or digits (e.g. only emoji) get a stable `gallery-…`/`item-…` name. ASCII names produce the same URLs as expose.sh. |
| Files or galleries whose names map to the same URL (`01 photo.jpg` / `02 photo.jpg`) share one output folder and overwrite each other. | The earliest photo (EXIF capture time, else file time) keeps the URL; the others get `-2`, `-3`, … with a warning. |
| An image sequence mixing formats (JPEG + PNG) or extensions (`.JPG` + `.jpg`) silently loses frames. | Every frame is used; mixed formats are converted to lossless PNG first. |
| Download zips for image sequences fail (it `cp`s the folder). | The zip contains the compiled sequence video. |
| Unknown video extensions are checked with `file -ib`, using a path relative to the wrong directory, so effectively never. | Detected from the file extension's MIME type. |
| With `disable_audio=false`, always copies the audio track, so AAC audio (most phone/camera videos) makes every WebM and Ogg encode fail. | Copies audio where the format allows it and re-encodes otherwise (Opus for WebM, Vorbis for Ogg, AAC for MP4). |
| Leaves `ffmpeg2pass-*.log` in the current folder while encoding. | Keeps 2-pass logs in a temporary folder. |
| A caption separator must be exactly `---`: with trailing spaces, the metadata shows up in the caption. Text before the metadata block silently disappears. | `---` with trailing whitespace is a separator too. Text before the metadata block is still dropped, but with a warning naming the file. |
| A non-text or non-UTF-8 caption file is skipped (`file` check). | Same, with a warning. Captions are always read and written as UTF-8. |
| Requires ImageMagick and `zip`; video needs ffmpeg and ffprobe. | Needs nothing beyond `pip`/`uv`; ffprobe isn't used. |
| Reads JPEG, PNG and GIF photos only. | Also reads WebP, AVIF, HEIC/HEIF (iPhone) and TIFF, with or without `--legacy`. |

Caption Markdown is rendered by python-markdown and normalized to match expose.sh's
Markdown.pl output. One exception: Markdown.pl obfuscates email autolinks (`<me@x.com>`) with
random character entities, which by design can't be reproduced. Both versions display the same
address.

Resized JPEGs are made by Pillow rather than ImageMagick. File sizes match ImageMagick 7 (same
chroma subsampling rules) but the bytes aren't identical, so image files won't hash the same as
expose.sh's output; HTML, CSS and JS do.
