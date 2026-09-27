"""Command-line interface for Dorothea.

Handles argument parsing, configuration loading/validation, signal handlers,
and orchestrates the generation process.
"""

import argparse
import atexit
import json
import signal
import sys
from collections import Counter
from pathlib import Path
from types import FrameType

from dorothea import __version__
from dorothea.config import Config, ConfigError, parse_config_sh, parse_override
from dorothea.generator import ExposeGenerator


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``expose`` command."""
    parser = argparse.ArgumentParser(
        description="Dorothea - static photography website generator (a port of expose.sh). "
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
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be built without writing anything",
    )
    parser.add_argument(
        "--convert-config",
        action="store_true",
        help="Write _config.json from an expose.sh _config.sh (or --config FILE.sh) and exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def format_plan(pages: int, planned: list[tuple[str, str]]) -> str:
    """Human-readable dry-run summary."""
    reasons = Counter(reason for _path, reason in planned)
    breakdown = ", ".join(f"{n} {reason}" for reason, n in sorted(reasons.items()))
    lines = [f"Would write {pages} HTML pages; would encode {len(planned)} files"]
    if breakdown:
        lines[0] += f" ({breakdown})"
    lines += [f"  {path}  [{reason}]" for path, reason in planned]
    return "\n".join(lines)


def convert_config(topdir: Path, source: Path | None, prog: str = "dorothea") -> int:
    """Convert an expose.sh ``_config.sh`` to ``_config.json``. Returns an exit code."""
    source = source or topdir / "_config.sh"
    target = topdir / "_config.json"
    if not source.exists():
        print(f"{prog}: {source} not found", file=sys.stderr)
        return 2
    if target.exists():
        print(f"{prog}: {target} already exists; not overwriting", file=sys.stderr)
        return 2
    values, warnings = parse_config_sh(source.read_text(encoding="utf-8"))
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    text = json.dumps(values, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {target}:\n{text}", end="")
    return 0


def main() -> None:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args()

    topdir = Path.cwd()
    # scriptdir is the dorothea package directory; themes are bundled inside it
    scriptdir = Path(__file__).parent.resolve()

    if args.convert_config:
        sys.exit(convert_config(topdir, args.config, parser.prog))

    try:
        overrides = dict(parse_override(item) for item in args.set)
        if args.jobs is not None:
            overrides["jobs"] = args.jobs
        config = Config.load(topdir, scriptdir, config_path=args.config, overrides=overrides)
        for warning in config.load_warnings + config.validate(topdir):
            print(f"Warning: {warning}", file=sys.stderr)
    except ConfigError as e:
        print(f"{parser.prog}: {e}", file=sys.stderr)
        sys.exit(2)

    if args.draft:
        config.apply_draft_mode()

    generator = ExposeGenerator(topdir, scriptdir, config, draft=args.draft, dry_run=args.dry_run)

    if args.dry_run:
        generator.run()
        print(format_plan(generator.planned_pages, generator.planned))
        return

    # Set up signal handlers for cleanup
    def signal_handler(sig: int, frame: FrameType | None) -> None:
        generator.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(generator.cleanup)

    generator.run()


if __name__ == "__main__":
    main()
