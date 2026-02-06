"""Tests for pure functions in expose.py — no external dependencies required."""

from expose import ExposeGenerator


def _gen():
    """Create a minimal generator for testing pure methods.

    Uses a dummy path since we only call pure methods that don't touch the filesystem.
    """
    return ExposeGenerator.__new__(ExposeGenerator)


# --- url_safe ---


def test_url_safe_basic():
    assert _gen().url_safe("Hello World") == "hello-world"


def test_url_safe_special_chars():
    assert _gen().url_safe("café & bar!") == "caf--bar"


def test_url_safe_underscores():
    assert _gen().url_safe("my_photo") == "myphoto"


def test_url_safe_empty():
    assert _gen().url_safe("") == ""


def test_url_safe_only_specials():
    assert _gen().url_safe("!@#$%") == ""


# --- strip_numeric_prefix ---


def test_strip_numeric_prefix_basic():
    assert _gen().strip_numeric_prefix("01_Mountains") == "_Mountains"


def test_strip_numeric_prefix_no_digits():
    assert _gen().strip_numeric_prefix("Mountains") == "Mountains"


def test_strip_numeric_prefix_only_digits():
    # Fallback: stripping all chars returns empty, so original is returned
    assert _gen().strip_numeric_prefix("01234") == "01234"


def test_strip_numeric_prefix_with_space():
    assert _gen().strip_numeric_prefix("01 Mountains") == "Mountains"


# --- template ---


def test_template_simple():
    result = _gen().template("Hello {{name}}", "name", "World")
    assert result == "Hello World"


def test_template_default_syntax():
    result = _gen().template("{{name:Anon}}", "name", "Bob")
    assert result == "Bob"


def test_template_default_untouched():
    result = _gen().template("{{name:Anon}}", "other", "X")
    assert result == "{{name:Anon}}"


def test_template_whitespace_collapse():
    result = _gen().template("{{x}}", "x", "  hello   world  ")
    assert result == "hello world"


def test_template_multiple_occurrences():
    result = _gen().template("{{x}} and {{x}}", "x", "Y")
    assert result == "Y and Y"


def test_template_special_chars():
    result = _gen().template("{{x}}", "x", "a/b&c")
    assert result == "a/b&c"


def test_template_empty_value():
    result = _gen().template("before{{x}}after", "x", "")
    assert result == "beforeafter"


def test_template_html_content():
    """Test template with a real post-template snippet and multiple substitutions."""
    snippet = '<div style="top: {{top:70}}%"><img data-url="{{imageurl}}" /></div>'
    result = _gen().template(snippet, "imageurl", "peak")
    result = _gen().template(result, "top", "60")
    assert 'data-url="peak"' in result
    assert "top: 60%" in result
