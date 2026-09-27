"""Caption markdown must match expose.sh's Markdown.pl after whitespace collapsing."""

import shutil
import subprocess

import pytest

from dorothea.media.markdown import MarkdownProcessor, normalize_to_markdown_pl
from dorothea.template import TemplateEngine
from tests.conftest import REFDIR

CASES = {
    "paragraph": "Just a simple caption.",
    "emphasis": "Some *em* and _em_ and **strong** and __strong__ and ***both***.",
    "links": 'A [link](http://x.com) and [titled](http://x.com "The Title") and <http://auto.com>.',
    "reference_link": 'See [ref][1].\n\n[1]: http://ref.com "Ref"',
    "code": "Inline `code <b>` here.\n\n    block code\n    more",
    "tight_list": "- a\n- b\n- c",
    "loose_list": "- a\n\n- b",
    "ordered_list": "1. one\n2. two",
    "nested_list": "- a\n    - b\n    - c\n- d",
    "blockquote": "> quoted\n> text",
    "hard_break": "line one  \nline two",
    "headers": "# H1\n\n## H2\n\nSetext\n======",
    "rule": "above\n\n---\n\nbelow",
    "image": "![alt text](a.jpg)",
    "image_title": '![alt](a.jpg "Title")',
    "image_in_link": "[![alt](i.jpg)](http://x.com)",
    "inline_html": 'Text with <span class="x">span</span> and <br> break.',
    "block_html": "<div>\nblock\n</div>",
    "entities": "AT&T &copy; 5 < 6 > 4",
    "escapes": "\\*not em\\* and \\_x\\_",
    "paragraphs": "First para.\n\nSecond para.",
    "unicode": "Café naïve – “quotes”",
}


def collapse(html: str) -> str:
    """What actually lands in the page: the template engine collapses whitespace."""
    return TemplateEngine.substitute("{{post}}", "post", html)


MARKDOWN_PL = REFDIR / "Markdown_1.0.1" / "Markdown.pl"


def run_markdown_pl(source):
    return subprocess.run(
        ["perl", str(MARKDOWN_PL), "--html4tags", str(source)], capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def markdown_pl_works(tmp_path_factory):
    """Skip unless Markdown.pl runs (minimal perls such as Debian's perl-base lack modules)."""
    if shutil.which("perl") is None:
        pytest.skip("perl not available")
    probe = tmp_path_factory.mktemp("md") / "probe.md"
    probe.write_text("probe\n")
    if run_markdown_pl(probe).returncode != 0:
        pytest.skip("Markdown.pl can't run with this perl")


@pytest.mark.parametrize("name", list(CASES))
def test_matches_markdown_pl(name, tmp_path, markdown_pl_works):
    source = tmp_path / "caption.md"
    source.write_text(CASES[name] + "\n")
    result = run_markdown_pl(source)
    assert result.returncode == 0, result.stderr
    expected = result.stdout
    assert collapse(MarkdownProcessor().render(CASES[name])) == collapse(expected)


@pytest.mark.parametrize(
    "rendered,expected",
    [
        ("<li>\n<p>a</p>\n</li>", "<li><p>a</p></li>"),
        ("<li>a<ul>\n<li>b</li>\n</ul>\n</li>", "<li>a\n<ul>\n<li>b</li>\n</ul></li>"),
        ("<p>one<br>\ntwo</p>", "<p>one <br>\ntwo</p>"),
        ('<img alt="x y" src="a.jpg">', '<img src="a.jpg" alt="x y" title="">'),
        ('<img alt src="a.jpg" title="T">', '<img src="a.jpg" alt="alt" title="T">'),
        ("<p>5 &gt; 4</p><code>a &gt; b</code>", "<p>5 > 4</p><code>a &gt; b</code>"),
        # user-written inline HTML is left alone
        ('<img class="c" src="a.jpg">', '<img class="c" src="a.jpg">'),
    ],
)
def test_normalizer_rules(rendered, expected):
    assert normalize_to_markdown_pl(rendered) == expected
