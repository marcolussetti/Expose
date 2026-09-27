# Dorothea

[![CI](https://github.com/marcolussetti/dorothea/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/marcolussetti/dorothea/actions/workflows/ci.yml?query=branch%3Amain)
[![Tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmarcolussetti%2Fdorothea%2Fbadges%2Ftests.json)](https://github.com/marcolussetti/dorothea/actions/workflows/ci.yml?query=branch%3Amain)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmarcolussetti%2Fdorothea%2Fbadges%2Fcoverage.json)](https://github.com/marcolussetti/dorothea/actions/workflows/report.yml?query=branch%3Amain)
[![Code](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmarcolussetti%2Fdorothea%2Fbadges%2Floc.json)](https://github.com/marcolussetti/dorothea/tree/main/src/dorothea)
[![Code + tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmarcolussetti%2Fdorothea%2Fbadges%2Floc-total.json)](https://github.com/marcolussetti/dorothea)
[![PyPI](https://img.shields.io/pypi/v/dorothea)](https://pypi.org/project/dorothea/)
[![Python](https://img.shields.io/pypi/pyversions/dorothea)](https://pypi.org/project/dorothea/)
[![Docs](https://readthedocs.org/projects/dorothea/badge/?version=latest)](https://dorothea.readthedocs.io/)
[![License](https://img.shields.io/pypi/l/dorothea)](https://github.com/marcolussetti/dorothea/blob/main/LICENSE.txt)

Dorothea is a [static site generator](https://en.wikipedia.org/wiki/Static_site_generator) for photography websites, primarily photo essays.

It is a port to Python of Jack Qiao's wonderful [Exposé](https://github.com/Jack000/Expose) project (originally in bash). It keeps adding fixes and features, but with `--legacy` it's output-compatible* with Exposé, and our integration tests check that on each commit.

*=Resized photos come from Pillow rather than ImageMagick, so their bytes differ slightly (their sizes match).

**Documentation: [dorothea.readthedocs.io](https://dorothea.readthedocs.io/)**, including a [configuration reference](https://dorothea.readthedocs.io/configuration/) and a guide for [migrating from expose.sh](https://dorothea.readthedocs.io/migrating/).

## What is it

If you're a photographer, you probably come back home from a trip and end up with photos that look like this:

![a bunch of images in a single folder](https://raw.githubusercontent.com/marcolussetti/dorothea/main/docs/folder.jpg)

Dorothea turns those folders into a website, resizing the photos and encoding the videos for the web. Sub-folders become galleries, and a text file next to a photo becomes its caption. Two themes are included: `photoessay`, with full-screen photos and text over them, and `medium`, with text in a column between the photos ([themes](https://dorothea.readthedocs.io/themes/)).

## Quick start

Dorothea runs on Linux, macOS and Windows with Python 3.14+; everything it needs installs with it, ffmpeg included. With [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
cd ~/my-trip-to-ecuador
uvx dorothea            # builds the site into ./_site
uvx dorothea serve      # or build, then preview it at http://localhost:8000/
```

Put the `_site` folder on any web server that serves static files. Other ways to install (`uv tool install`, pipx) are in the [getting started guide](https://dorothea.readthedocs.io/).

## Why a Python port of Exposé

I wanted to start addressing some of the pain points with the original package, branch out to new themes and tweaks, and found maintaining my own fork in Bash to be less work than porting it to Python, thanks to today's AI-assisted coding tools.
