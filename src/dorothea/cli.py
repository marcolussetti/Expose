"""Command-line interface for Dorothea.

Handles option parsing (click), configuration loading/validation, signal handlers,
and orchestrates the generation process.
"""

import atexit
import io
import signal
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

import click

from dorothea import __version__
from dorothea.config import Config, ConfigError, parse_override
from dorothea.convert import convert_site
from dorothea.generator import ExposeGenerator
from dorothea.progress import Reporter


def format_plan(pages: int, planned: list[tuple[str, str]], feeds: int = 0) -> str:
    """Human-readable dry-run summary."""
    reasons = Counter(reason for _path, reason in planned)
    breakdown = ", ".join(f"{n} {reason}" for reason, n in sorted(reasons.items()))
    written = f"{pages} HTML pages"
    if feeds:
        written += f" and {feeds} feed{'s' if feeds > 1 else ''}"
    lines = [f"Would write {written}; would encode {len(planned)} files"]
    if breakdown:
        lines[0] += f" ({breakdown})"
    lines += [f"  {path}  [{reason}]" for path, reason in planned]
    return "\n".join(lines)


def convert_config(topdir: Path, source: Path | None, prog: str = "dorothea") -> int:
    """Convert expose.sh's ``_config.sh`` and every ``metadata.txt`` to YAML (#46).

    Returns an exit code: 2 if something couldn't be done, else 0.
    """
    report = convert_site(topdir, source)
    for line in report.written:
        click.echo(f"Wrote {line}")
    for note in report.notes:
        click.echo(f"Note: {note}", err=True)
    for error in report.errors:
        click.echo(f"{prog}: {error}", err=True)
    if not (report.written or report.notes or report.errors):
        click.echo("Nothing to convert: no _config.sh or metadata.txt here")
    return 2 if report.errors else 0


def _print_version(ctx: click.Context, value: bool) -> None:
    """``--version``: print the name the command was invoked as, and the version.

    (``click.version_option`` caches the program name from its first call, which goes stale when
    the command runs more than once in a process.)
    """
    if value and not ctx.resilient_parsing:
        click.echo(f"{ctx.find_root().info_name} {__version__}")
        ctx.exit()


_BUILD_OPTIONS = [
    click.option(
        "-d", "--draft", is_flag=True, help="Draft mode: single resolution, fast encoding."
    ),
    click.option(
        "-n", "--dry-run", is_flag=True, help="Show what would be built without writing anything."
    ),
    click.option(
        "-c",
        "--config",
        "config_path",
        type=click.Path(dir_okay=False, path_type=Path),
        metavar="PATH",
        help="Config file to use, .yml or expose.sh .sh "
        "(default: ./_config.yml, else ./_config.sh).",
    ),
    click.option(
        "-s",
        "--set",
        "overrides",
        multiple=True,
        metavar="KEY=VALUE",
        help="Override a setting; VALUE is parsed as JSON when possible "
        "(e.g. --set jpeg_quality=85 --set 'resolution=[1920,640]'). Repeatable.",
    ),
    click.option(
        "-j",
        "--jobs",
        type=int,
        metavar="N",
        help="Parallel workers for images (default: one per CPU).",
    ),
    click.option(
        "--ffmpeg",
        metavar="auto|bundled|system|PATH",
        help="Which ffmpeg to use for video: system if installed, else bundled (auto, the "
        "default); only the bundled one; only the system one; or a path to an ffmpeg binary.",
    ),
    click.option(
        "--sort",
        metavar="MODE",
        help="Order of galleries and photos: natural (1, 2, 10; the default), name (plain "
        "alphabetical, like expose.sh), or capture (when taken); add -desc for the reverse.",
    ),
    click.option(
        "--legacy/--no-legacy",
        default=None,
        help="Use expose.sh's default settings, so the output matches expose.sh "
        "(--no-legacy overrides legacy: true in the config file).",
    ),
]


def build_options[F: Callable[..., Any]](f: F) -> F:
    """The build options, shared by ``dorothea`` and ``dorothea serve``."""
    for option in reversed(_BUILD_OPTIONS):
        f = option(f)
    return f


def load_config(
    ctx: click.Context,
    config_path: Path | None,
    overrides: tuple[str, ...],
    jobs: int | None,
    ffmpeg: str | None,
    sort: str | None,
    legacy: bool | None,
) -> tuple[Config, list[str]]:
    """The config for the current directory, validated, and its warnings (already printed).

    Exits with 2 on a config error.
    """
    prog = ctx.find_root().info_name or "dorothea"
    topdir = Path.cwd()
    try:
        settings = dict(parse_override(item) for item in overrides)
        if jobs is not None:
            settings["jobs"] = jobs
        if ffmpeg is not None:
            settings["ffmpeg"] = ffmpeg
        if sort is not None:
            settings["sort"] = sort
        if legacy is not None:
            settings["legacy"] = legacy
        config = Config.load(topdir, Path(__file__).parent, config_path, overrides=settings)
        warnings = config.load_warnings + config.validate(topdir)
    except ConfigError as e:
        click.echo(f"{prog}: {e}", err=True)
        ctx.exit(2)
    for warning in warnings:
        click.echo(f"Warning: {warning}", err=True)
    return config, warnings


def merge_parent_options(ctx: click.Context, options: dict[str, Any]) -> dict[str, Any]:
    """Options given before a command count too (`dorothea -d serve`); the ones after it win."""
    for key, value in (ctx.obj or {}).items():
        if options.get(key) in (None, False, ()):
            options[key] = value
    return options


def build(
    ctx: click.Context,
    draft: bool,
    dry_run: bool,
    config_path: Path | None,
    overrides: tuple[str, ...],
    jobs: int | None,
    ffmpeg: str | None,
    sort: str | None,
    legacy: bool | None,
) -> None:
    """Build the site in the current directory (exits with 2 on a config error)."""
    topdir = Path.cwd()
    # scriptdir is the dorothea package directory; themes are bundled inside it
    scriptdir = Path(__file__).parent.resolve()
    config, _warnings = load_config(ctx, config_path, overrides, jobs, ffmpeg, sort, legacy)

    if draft:
        config.apply_draft_mode()

    # Progress bars on an interactive terminal (plain output in logs/pipes); a dry run only lists
    progress = Reporter(enabled=False) if dry_run else Reporter()
    generator = ExposeGenerator(
        topdir, scriptdir, config, draft=draft, dry_run=dry_run, progress=progress
    )

    if dry_run:
        generator.run()
        feeds = generator.planned_feeds
        feeds = feeds if isinstance(feeds, int) else 0  # (a mocked generator's is a Mock)
        click.echo(format_plan(generator.planned_pages, generator.planned, feeds))
        return

    # Set up signal handlers for cleanup
    def signal_handler(sig: int, frame: FrameType | None) -> None:
        generator.cleanup()
        sys.exit(0)

    previous = (
        signal.signal(signal.SIGINT, signal_handler),
        signal.signal(signal.SIGTERM, signal_handler),
    )
    atexit.register(generator.cleanup)

    generator.run()
    signal.signal(signal.SIGINT, previous[0])
    signal.signal(signal.SIGTERM, previous[1])


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Run inside a folder of photos and videos; the site is written to ./_site. "
    "Every setting is described at https://dorothea.readthedocs.io/configuration/",
)
@build_options
@click.option(
    "--convert-config",
    "convert",
    is_flag=True,
    help="Convert expose.sh's _config.sh (or --config FILE.sh) to _config.yml and each "
    "gallery's metadata.txt to gallery.yml, deleting the originals once the new files give "
    "the same settings; then exit.",
)
@click.option(
    "--version",
    is_flag=True,
    expose_value=False,
    is_eager=True,
    callback=lambda ctx, _param, value: _print_version(ctx, value),
    help="Show the version and exit.",
)
@click.pass_context
def main(ctx: click.Context, convert: bool, **options: Any) -> None:
    """Dorothea: a static photography website generator (a port of expose.sh).

    Without a command, builds the site in the current directory.
    """
    # Gallery names can be in any script: a console or log in a legacy code page (cp1252 on
    # Windows) shows what it can't encode as escapes instead of crashing the build
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    if ctx.invoked_subcommand is not None:
        ctx.obj = options  # build options given before the command, e.g. `dorothea -d serve`
        return
    if convert:
        ctx.exit(convert_config(Path.cwd(), options["config_path"], ctx.info_name or "dorothea"))
    build(ctx, **options)


@main.command()
@build_options
@click.option("-p", "--port", type=int, default=8000, show_default=True, help="Port to listen on.")
@click.option(
    "--bind",
    default="127.0.0.1",
    show_default=True,
    metavar="ADDRESS",
    help="Address to listen on; 0.0.0.0 makes the preview reachable from other devices "
    "(e.g. a phone on the same network).",
)
@click.option("--no-build", is_flag=True, help="Serve the existing _site without building.")
@click.pass_context
def serve(ctx: click.Context, port: int, bind: str, no_build: bool, **options: Any) -> None:
    """Build the site, then preview it at http://localhost:8000/.

    Gallery links point at folders, which only work through a web server: opened from disk,
    they show a folder listing (see the link_index_html setting for that case).
    """
    from dorothea.serve import make_server, run

    prog = ctx.find_root().info_name or "dorothea"
    options = merge_parent_options(ctx, options)
    if options["dry_run"]:
        raise click.UsageError("serve can't be combined with --dry-run")
    if not no_build:
        build(ctx, **options)
    site = Path.cwd() / "_site"
    if not (site / "index.html").is_file():
        click.echo(f"{prog}: no site to serve: {site / 'index.html'} doesn't exist", err=True)
        ctx.exit(2)
    try:
        server = make_server(site, bind, port)
    except OSError as e:
        click.echo(f"{prog}: can't listen on {bind}:{port}: {e.strerror or e}", err=True)
        ctx.exit(2)
    run(server, site)


@main.command()
@build_options
@click.pass_context
def check(ctx: click.Context, **options: Any) -> None:
    """Check the settings, gallery files and captions for mistakes, without building.

    Lists each problem with its file and line (typos in keys, keys in the wrong place, values
    Dorothea can't use, captions that match no photo). Exits with 1 if there are any.
    """
    from dorothea.check import check_site

    options = merge_parent_options(ctx, options)
    config, warnings = load_config(
        ctx, options["config_path"], options["overrides"], options["jobs"],
        options["ffmpeg"], options["sort"], options["legacy"],
    )  # fmt: skip
    topdir = Path.cwd()
    checker = check_site(topdir, config)
    for problem in checker.problems:
        click.echo(problem.show(topdir))
    count = len(checker.problems) + len(warnings)

    def some(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"

    galleries = some(checker.galleries, "gallery", "galleries")
    captions = some(checker.captions, "caption", "captions")
    found = some(count, "problem", "problems") + "." if count else "no problems found."
    click.echo(f"Checked the settings, {galleries} and {captions}: {found}")
    ctx.exit(1 if count else 0)


if __name__ == "__main__":
    main()
