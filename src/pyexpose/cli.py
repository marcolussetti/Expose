"""Command-line interface for PyExpose.

Handles argument parsing, configuration loading/validation, signal handlers,
and orchestrates the generation process.
"""

import argparse
import atexit
import signal
import sys
from pathlib import Path

from pyexpose import __version__
from pyexpose.config import Config, ConfigError, parse_override
from pyexpose.generator import ExposeGenerator


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``expose`` command."""
    parser = argparse.ArgumentParser(
        prog="expose",
        description="Expose - Static photography website generator. "
        "Run it inside a folder of images/videos; output goes to ./_site",
    )
    parser.add_argument(
        "-d",
        "--draft",
        action="store_true",
        help="Draft mode: single resolution, fast encoding",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="PATH",
        help="Config file to use (default: ./_config.json if present)",
    )
    parser.add_argument(
        "-s",
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a config value; VALUE is parsed as JSON when possible "
        "(e.g. --set jpeg_quality=85 --set 'resolution=[1920,640]'). Repeatable.",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        metavar="N",
        help="Parallel workers for image processing (default: one per CPU)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main():
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args()

    topdir = Path.cwd()
    # scriptdir is the pyexpose package directory; themes are bundled inside it
    scriptdir = Path(__file__).parent.resolve()

    try:
        overrides = dict(parse_override(item) for item in args.set)
        if args.jobs is not None:
            overrides["jobs"] = args.jobs
        config = Config.load(topdir, scriptdir, config_path=args.config, overrides=overrides)
        for warning in config.validate(topdir):
            print(f"Warning: {warning}", file=sys.stderr)
    except ConfigError as e:
        print(f"expose: {e}", file=sys.stderr)
        sys.exit(2)

    if args.draft:
        config.apply_draft_mode()

    generator = ExposeGenerator(topdir, scriptdir, config, draft=args.draft)

    # Set up signal handlers for cleanup
    def signal_handler(sig, frame):
        generator.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(generator.cleanup)

    generator.run()


if __name__ == "__main__":
    main()
