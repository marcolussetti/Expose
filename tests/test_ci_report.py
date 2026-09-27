"""The CI report script (#27): parsing CI outputs, badges, the PR comment."""

import json

import pytest

from scripts import ci_report

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests"><testsuite name="pytest" errors="{errors}" failures="{failures}"
 skipped="{skipped}" tests="{tests}" time="1.0"><testcase classname="t" name="a"/></testsuite>
</testsuites>"""

COVERAGE = """<?xml version="1.0" ?>
<coverage version="7.10" timestamp="1" lines-valid="200" lines-covered="190" line-rate="0.95"
 branches-covered="0" branches-valid="0" branch-rate="0" complexity="0">
 <!-- Based on https://raw.githubusercontent.com/cobertura/web/master/htdocs/xml/coverage-04.dtd -->
 <packages><package name="." line-rate="0.95"><classes>
  <class name="cli.py" filename="cli.py" line-rate="0.9"/>
  <class name="utils.py" filename="utils.py" line-rate="1"/>
 </classes></package></packages>
</coverage>"""

CLOC = {
    "header": {"cloc_version": "2.10"},
    "Python": {"nFiles": 3, "blank": 10, "comment": 5, "code": 1500},
    "CSS": {"nFiles": 1, "blank": 1, "comment": 0, "code": 250},
    "SUM": {"nFiles": 4, "blank": 11, "comment": 5, "code": 1750},
}


def write_inputs(tmp_path, tests=100, failures=0, errors=0, skipped=2):
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT.format(tests=tests, failures=failures, errors=errors, skipped=skipped))
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(COVERAGE)
    src, tests_loc = tmp_path / "cloc-src.json", tmp_path / "cloc-tests.json"
    src.write_text(json.dumps(CLOC))
    tests_loc.write_text(json.dumps({"Python": {"code": 1200}, "SUM": {"code": 1200}}))
    return junit, coverage, src, tests_loc


def summary_for(tmp_path, **counts):
    junit, coverage, src, tests_loc = write_inputs(tmp_path, **counts)
    out = tmp_path / "summary.json"
    ci_report.main(
        ["summary", "--junit", str(junit), "--coverage", str(coverage),
         "--cloc-src", str(src), "--cloc-tests", str(tests_loc), "-o", str(out)]
    )  # fmt: skip
    return json.loads(out.read_text())


class TestSummary:
    def test_reads_every_input(self, tmp_path):
        summary = summary_for(tmp_path, tests=100, failures=1, errors=1, skipped=3)
        assert summary["tests"] == {
            "tests": 100, "failures": 1, "errors": 1, "skipped": 3, "passed": 95,
        }  # fmt: skip
        assert summary["coverage"]["percent"] == 95.0
        assert summary["coverage"]["files"] == {"cli.py": 90.0, "utils.py": 100.0}
        assert summary["loc"]["src"] == {"code": 1750, "languages": {"CSS": 250, "Python": 1500}}
        assert summary["loc"]["tests"]["code"] == 1200

    def test_junit_counts_add_up_over_files(self, tmp_path):
        a, b = tmp_path / "a.xml", tmp_path / "b.xml"
        a.write_text(JUNIT.format(tests=10, failures=1, errors=0, skipped=0))
        b.write_text(JUNIT.format(tests=5, failures=0, errors=0, skipped=5))
        assert ci_report.junit_counts([a, b])["passed"] == 9

    def test_refuses_dtds(self, tmp_path):
        """Artifacts can come from a PR; entity tricks are ruled out by refusing any DTD."""
        evil = tmp_path / "junit.xml"
        evil.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite/>')
        with pytest.raises(ValueError, match="DTD"):
            ci_report.junit_counts([evil])


class TestBadges:
    def test_passing(self, tmp_path):
        badges = ci_report.badges(summary_for(tmp_path))
        assert badges["tests.json"] == {
            "schemaVersion": 1, "label": "tests", "message": "98 passed", "color": "brightgreen",
        }  # fmt: skip
        assert badges["coverage.json"]["message"] == "95%"
        assert badges["coverage.json"]["color"] == "brightgreen"
        assert badges["loc.json"]["message"] == "1.8k lines"
        assert badges["loc-total.json"]["message"] == "3.0k lines"

    def test_failing(self, tmp_path):
        badge = ci_report.badges(summary_for(tmp_path, failures=2, errors=1))["tests.json"]
        assert badge["message"] == "95 passed, 3 failed"
        assert badge["color"] == "red"

    @pytest.mark.parametrize(
        ("percent", "colour"),
        [(95, "brightgreen"), (85, "green"), (75, "yellowgreen"), (65, "yellow"), (40, "red")],
    )
    def test_coverage_colours(self, percent, colour):
        assert ci_report._coverage_colour(percent) == colour

    def test_writes_files_and_summary(self, tmp_path):
        summary = tmp_path / "s.json"
        summary.write_text(json.dumps(summary_for(tmp_path)))
        ci_report.main(["badges", str(summary), str(tmp_path / "badges")])
        names = sorted(p.name for p in (tmp_path / "badges").iterdir())
        assert names == [
            "coverage.json",
            "loc-total.json",
            "loc.json",
            "summary.json",
            "tests.json",
        ]


class TestComment:
    def test_first_run_has_no_main_column(self, tmp_path):
        text = ci_report.comment(summary_for(tmp_path), None)
        assert text.startswith(ci_report.TITLE)
        assert "| | This PR |\n" in text
        assert "✅ 98 passed, 2 skipped" in text
        assert "95.0% (190/200 lines)" in text
        assert "1,750 lines" in text and "2,950 lines" in text
        assert "`main`" not in text

    def test_changes_against_main(self, tmp_path):
        (tmp_path / "main").mkdir()
        base = summary_for(tmp_path / "main", tests=90, skipped=0)
        base["coverage"]["percent"] = 94.0
        base["coverage"]["files"] = {"cli.py": 80.0, "utils.py": 100.0}
        base["loc"]["src"]["code"] = 1700
        text = ci_report.comment(summary_for(tmp_path), base)
        assert "| Tests (full suite) | ✅ 98 passed, 2 skipped | 90 passed | +8 |" in text
        assert "| 94.0% | +1.0 pts |" in text
        assert "| 1,700 | +50 |" in text
        # files whose coverage changed are listed first
        table = text.split("Coverage by file")[1]
        assert table.index("`cli.py` | 90.0% | +10.0 pts") < table.index("`utils.py`")

    def test_failures_stand_out(self, tmp_path):
        text = ci_report.comment(summary_for(tmp_path, failures=4), None)
        assert "❌ 94 passed, **4 failed**, 2 skipped" in text

    def test_file_names_are_escaped(self, tmp_path):
        summary = summary_for(tmp_path)
        summary["coverage"]["files"] = {"a`b|c\nd.py": 50.0}
        text = ci_report.comment(summary, None)
        assert "| `a'b/c d.py` | 50.0% |" in text

    def test_cli_writes_to_stdout(self, tmp_path, capsys):
        summary = tmp_path / "s.json"
        summary.write_text(json.dumps(summary_for(tmp_path)))
        ci_report.main(["comment", str(summary), "--base", str(tmp_path / "missing.json")])
        assert capsys.readouterr().out.startswith(ci_report.TITLE)
