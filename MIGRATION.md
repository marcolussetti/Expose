# Migrating from expose.sh to Dorothea

Dorothea is a Python port of [expose.sh](https://github.com/Jack000/Expose). For the same
photos and settings it produces the same site: its test suite builds galleries with both and
checks that the file lists match, HTML/CSS/JS are byte-identical, and every image and video has
the same file size. This page covers what you need to change, and the places where Dorothea
deliberately behaves differently.

## Install

```sh
uvx dorothea                 # run without installing (or: pipx run dorothea)
uv tool install dorothea     # install the command (or: pipx install dorothea)
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
| Skips hidden folders only at the top level (`.foo/`). | Skips hidden folders at any depth (`gallery/.thumbs/`). |
| An image sequence mixing formats (JPEG + PNG) or extensions (`.JPG` + `.jpg`) silently loses frames. | Every frame is used; mixed formats are converted to lossless PNG first. |
| Download zips for image sequences fail (it `cp`s the folder). | The zip contains the compiled sequence video. |
| Unknown video extensions are checked with `file -ib`, using a path relative to the wrong directory, so effectively never. | Detected from the file extension's MIME type. |
| Leaves `ffmpeg2pass-*.log` in the current folder while encoding. | Keeps 2-pass logs in a temporary folder. |
| A non-text or non-UTF-8 caption file is skipped (`file` check). | Same, with a warning. Captions are always read and written as UTF-8. |
| Requires ImageMagick and `zip`; video needs ffmpeg and ffprobe. | Needs nothing beyond `pip`/`uv`; ffprobe isn't used. |

Caption Markdown is rendered by python-markdown and normalized to match expose.sh's
Markdown.pl output. One exception: Markdown.pl obfuscates email autolinks (`<me@x.com>`) with
random character entities, which by design can't be reproduced. Both versions display the same
address.

Resized JPEGs are made by Pillow rather than ImageMagick. File sizes match ImageMagick 7 (same
chroma subsampling rules) but the bytes aren't identical, so image files won't hash the same as
expose.sh's output; HTML, CSS and JS do.
