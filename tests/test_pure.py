"""Tests for pure functions — no external dependencies required."""

from pyexpose.template import TemplateEngine
from pyexpose.utils import strip_numeric_prefix, url_safe

# --- url_safe ---


def test_url_safe_basic():
    assert url_safe("Hello World") == "hello-world"


def test_url_safe_special_chars():
    assert url_safe("café & bar!") == "caf--bar"


def test_url_safe_underscores():
    assert url_safe("my_photo") == "myphoto"


def test_url_safe_empty():
    assert url_safe("") == ""


def test_url_safe_only_specials():
    assert url_safe("!@#$%") == ""


# --- strip_numeric_prefix ---


def test_strip_numeric_prefix_basic():
    assert strip_numeric_prefix("01_Mountains") == "_Mountains"


def test_strip_numeric_prefix_no_digits():
    assert strip_numeric_prefix("Mountains") == "Mountains"


def test_strip_numeric_prefix_only_digits():
    # Fallback: stripping all chars returns empty, so original is returned
    assert strip_numeric_prefix("01234") == "01234"


def test_strip_numeric_prefix_with_space():
    assert strip_numeric_prefix("01 Mountains") == "Mountains"


# --- template ---


def test_template_simple():
    result = TemplateEngine.substitute("Hello {{name}}", "name", "World")
    assert result == "Hello World"


def test_template_default_syntax():
    result = TemplateEngine.substitute("{{name:Anon}}", "name", "Bob")
    assert result == "Bob"


def test_template_default_untouched():
    result = TemplateEngine.substitute("{{name:Anon}}", "other", "X")
    assert result == "{{name:Anon}}"


def test_template_whitespace_collapse():
    result = TemplateEngine.substitute("{{x}}", "x", "  hello   world  ")
    assert result == "hello world"


def test_template_multiple_occurrences():
    result = TemplateEngine.substitute("{{x}} and {{x}}", "x", "Y")
    assert result == "Y and Y"


def test_template_special_chars():
    result = TemplateEngine.substitute("{{x}}", "x", "a/b&c")
    assert result == "a/b&c"


def test_template_empty_value():
    result = TemplateEngine.substitute("before{{x}}after", "x", "")
    assert result == "beforeafter"


def test_template_html_content():
    """Test template with a real post-template snippet and multiple substitutions."""
    snippet = '<div style="top: {{top:70}}%"><img data-url="{{imageurl}}" /></div>'
    result = TemplateEngine.substitute(snippet, "imageurl", "peak")
    result = TemplateEngine.substitute(result, "top", "60")
    assert 'data-url="peak"' in result
    assert "top: 60%" in result
