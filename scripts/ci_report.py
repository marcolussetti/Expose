"""Test, coverage and code-size report for CI (#27): shields.io badges and a PR comment.

    python scripts/ci_report.py summary --junit reports/junit.xml --coverage reports/coverage.xml \\
        --cloc-src reports/cloc-src.json --cloc-tests reports/cloc-tests.json -o summary.json
    python scripts/ci_report.py badges summary.json badges/
    python scripts/ci_report.py comment summary.json [--base main-summary.json] -o comment.md

Inputs come from CI artifacts, which a pull request can shape, so they're only parsed (never
run) and the file names put in the comment are escaped. Standard library only.
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Marks the comment so later runs can find it (sticky-pull-request-comment uses its own header)
TITLE = "### Coverage and code size"


# --- reading CI outputs --------------------------------------------------------------------


def _parse_xml(path: Path) -> ET.Element:
    """Parse a pytest/coverage.py XML report, refusing DTDs.

    Neither tool writes a DOCTYPE, and refusing one rules out entity tricks (XXE, "billion
    laughs") in artifacts a pull request could have replaced.
    """
    data = path.read_bytes()
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError(f"{path}: unexpected DTD in a test/coverage report")
    return ET.fromstring(data)


def junit_counts(paths: list[Path]) -> dict[str, int]:
    """Test counts from pytest's JUnit XML (``--junitxml``), summed over files."""
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for path in paths:
        root = _parse_xml(path)
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            for key in counts:
                counts[key] += int(suite.get(key, 0))
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    return counts


def coverage_summary(path: Path) -> dict[str, Any]:
    """Line coverage from coverage.py's XML report (``--cov-report=xml``)."""
    root = _parse_xml(path)
    files = {
        cls.get("filename", "?"): round(float(cls.get("line-rate", 0)) * 100, 1)
        for cls in root.iter("class")
    }
    return {
        "percent": round(float(root.get("line-rate", 0)) * 100, 1),
        "covered": int(root.get("lines-covered", 0)),
        "statements": int(root.get("lines-valid", 0)),
        "files": dict(sorted(files.items())),
    }


def cloc_summary(path: Path) -> dict[str, Any]:
    """Lines of code per language from ``cloc --json``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    languages = {
        name: int(stats["code"])
        for name, stats in data.items()
        if name not in ("header", "SUM") and isinstance(stats, dict)
    }
    return {"code": sum(languages.values()), "languages": dict(sorted(languages.items()))}


def summarize(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "tests": junit_counts(args.junit),
        "coverage": coverage_summary(args.coverage),
        "loc": {"src": cloc_summary(args.cloc_src), "tests": cloc_summary(args.cloc_tests)},
    }


# --- badges ----------------------------------------------------------------------------------


def _coverage_colour(percent: float) -> str:
    for threshold, colour in (
        (90, "brightgreen"),
        (80, "green"),
        (70, "yellowgreen"),
        (60, "yellow"),
    ):
        if percent >= threshold:
            return colour
    return "red"


def _thousands(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _badge(label: str, message: str, colour: str) -> dict[str, Any]:
    """A shields.io endpoint badge (https://shields.io/badges/endpoint-badge)."""
    return {"schemaVersion": 1, "label": label, "message": message, "color": colour}


def badges(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tests = summary["tests"]
    failed = tests["failures"] + tests["errors"]
    tests_message = f"{tests['passed']} passed" + (f", {failed} failed" if failed else "")
    src, test_loc = summary["loc"]["src"]["code"], summary["loc"]["tests"]["code"]
    percent = summary["coverage"]["percent"]
    return {
        "tests.json": _badge("tests", tests_message, "red" if failed else "brightgreen"),
        "coverage.json": _badge("coverage", f"{percent:.0f}%", _coverage_colour(percent)),
        "loc.json": _badge("code", f"{_thousands(src)} lines", "blue"),
        "loc-total.json": _badge("code + tests", f"{_thousands(src + test_loc)} lines", "blue"),
    }


# --- PR comment ------------------------------------------------------------------------------


def _delta(new: float, old: float | None, unit: str = "", precision: int = 0) -> str:
    if old is None:
        return ""
    diff = round(new - old, precision)
    if diff == 0:
        return "="
    return f"{diff:+,.{precision}f}{unit}"


def _escape(name: str) -> str:
    """A file name as Markdown inline code (artifact contents are untrusted)."""
    return "`" + name.replace("`", "'").replace("|", "/").replace("\n", " ") + "`"


def comment(summary: dict[str, Any], base: dict[str, Any] | None) -> str:
    tests, cov = summary["tests"], summary["coverage"]
    src, test_loc = summary["loc"]["src"], summary["loc"]["tests"]
    failed = tests["failures"] + tests["errors"]

    def base_value(*keys: str) -> Any:
        value: Any = base
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return None
            value = value[key]
        return value

    base_src = base_value("loc", "src", "code")
    base_tests = base_value("loc", "tests", "code")
    base_total = base_src + base_tests if base_src is not None and base_tests is not None else None

    def main(value: Any, fmt: str = "{:,}") -> str:
        """The `main` column: empty until main has a summary."""
        return "" if value is None else fmt.format(value)

    status = "❌" if failed else "✅"
    test_cell = f"{status} {tests['passed']:,} passed"
    if failed:
        test_cell += f", **{failed:,} failed**"
    if tests["skipped"]:
        test_cell += f", {tests['skipped']:,} skipped"

    rows = [
        ("Tests (full suite)", test_cell, main(base_value("tests", "passed"), "{:,} passed"),
         _delta(tests["passed"], base_value("tests", "passed"))),
        ("Coverage", f"{cov['percent']:.1f}% ({cov['covered']:,}/{cov['statements']:,} lines)",
         main(base_value("coverage", "percent"), "{:.1f}%"),
         _delta(cov["percent"], base_value("coverage", "percent"), " pts", 1)),
        ("Code (`src/`)", f"{src['code']:,} lines", main(base_src),
         _delta(src["code"], base_src)),
        ("Code + tests", f"{src['code'] + test_loc['code']:,} lines", main(base_total),
         _delta(src["code"] + test_loc["code"], base_total)),
    ]  # fmt: skip
    if base:
        lines = [TITLE, "", "| | This PR | `main` | Change |", "|---|---|---|---|"]
        lines += [f"| {name} | {now} | {old} | {change} |" for name, now, old, change in rows]
    else:  # main has no summary yet (the first run after this was set up)
        lines = [TITLE, "", "| | This PR |", "|---|---|"]
        lines += [f"| {name} | {now} |" for name, now, _old, _change in rows]

    # Files whose coverage changed first, then the least covered
    base_files = base_value("coverage", "files") or {}
    files = cov["files"]
    changed = [f for f in files if f in base_files and files[f] != base_files[f]]
    new = [f for f in files if base and f not in base_files]
    rest = sorted((f for f in files if f not in changed and f not in new), key=lambda f: files[f])
    lines += ["", "<details><summary>Coverage by file</summary>", ""]
    if base:
        lines += ["| File | Coverage | Change |", "|---|---|---|"]
    else:
        lines += ["| File | Coverage |", "|---|---|"]
    for name in changed + new + rest:
        row = f"| {_escape(name)} | {files[name]:.1f}% |"
        if base:
            change = "new" if name in new else _delta(files[name], base_files.get(name), " pts", 1)
            row += f" {change} |"
        lines.append(row)
    lines += ["", "</details>"]

    lines += ["", "<details><summary>Lines of code by language</summary>", ""]
    lines += ["| Language | `src/` | `tests/` |", "|---|---|---|"]
    for language in sorted(set(src["languages"]) | set(test_loc["languages"])):
        lines.append(
            f"| {_escape(language)[1:-1]} | {src['languages'].get(language, 0):,} "
            f"| {test_loc['languages'].get(language, 0):,} |"
        )
    lines += ["", "</details>", ""]
    lines.append(
        "<sub>Line counts from cloc (`tests/` excludes the expose.sh references and test "
        "galleries). Per-job test results are in the other comment.</sub>"
    )
    return "\n".join(lines) + "\n"


# --- command line ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("summary", help="Combine CI outputs into one JSON summary.")
    p.add_argument("--junit", type=Path, nargs="+", required=True)
    p.add_argument("--coverage", type=Path, required=True)
    p.add_argument("--cloc-src", type=Path, required=True)
    p.add_argument("--cloc-tests", type=Path, required=True)
    p.add_argument("-o", "--output", type=Path, required=True)

    p = commands.add_parser("badges", help="Write shields.io endpoint JSON files.")
    p.add_argument("summary", type=Path)
    p.add_argument("outdir", type=Path)

    p = commands.add_parser("comment", help="Write the PR comment (Markdown).")
    p.add_argument("summary", type=Path)
    p.add_argument("--base", type=Path, help="main's summary.json, for the change column")
    p.add_argument("-o", "--output", type=Path, help="default: stdout")

    args = parser.parse_args(argv)
    if args.command == "summary":
        args.output.write_text(json.dumps(summarize(args), indent=2) + "\n", encoding="utf-8")
    elif args.command == "badges":
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        args.outdir.mkdir(parents=True, exist_ok=True)
        for name, badge in badges(summary).items():
            (args.outdir / name).write_text(json.dumps(badge) + "\n", encoding="utf-8")
        (args.outdir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    else:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        base = None
        if args.base and args.base.is_file() and args.base.stat().st_size:
            base = json.loads(args.base.read_text(encoding="utf-8"))
        text = comment(summary, base)
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
