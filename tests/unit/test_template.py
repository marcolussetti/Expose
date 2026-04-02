"""Unit tests for pyexpose.template module.

Tests the TemplateEngine class that provides sed-like template substitution.
"""


from pyexpose.template import TemplateEngine


class TestTemplateSubstitute:
    """Test TemplateEngine.substitute() method."""

    def test_basic_substitution(self):
        """Test basic {{key}} replacement."""
        text = "Hello {{name}}"
        result = TemplateEngine.substitute(text, "name", "World")
        assert result == "Hello World"

    def test_substitution_with_default(self):
        """Test {{key:default}} replacement."""
        text = "Hello {{name:Guest}}"
        result = TemplateEngine.substitute(text, "name", "World")
        assert result == "Hello World"

    def test_multiple_occurrences(self):
        """Test multiple occurrences of same variable."""
        text = "{{greeting}} {{name}}, {{greeting}}!"
        result = TemplateEngine.substitute(text, "greeting", "Hello")
        assert result == "Hello {{name}}, Hello!"

    def test_whitespace_collapse(self):
        """Test that whitespace is collapsed like shell's unquoted echo."""
        text = "Value: {{key}}"
        result = TemplateEngine.substitute(text, "key", "hello   world    test")
        assert result == "Value: hello world test"

    def test_special_characters(self):
        """Test special characters in replacement value."""
        text = "Path: {{path}}"
        result = TemplateEngine.substitute(text, "path", "/home/user/file.txt")
        assert result == "Path: /home/user/file.txt"

    def test_ampersand_in_value(self):
        """Test ampersand character (& is special in sed)."""
        text = "URL: {{url}}"
        result = TemplateEngine.substitute(text, "url", "http://example.com?a=1&b=2")
        assert result == "URL: http://example.com?a=1&b=2"

    def test_backslash_in_value(self):
        """Test backslash character (backslash is special in sed)."""
        text = "Path: {{path}}"
        result = TemplateEngine.substitute(text, "path", r"C:\Users\Test")
        assert result == r"Path: C:\Users\Test"

    def test_key_with_whitespace(self):
        """Test key with surrounding whitespace is stripped."""
        # Note: The template pattern doesn't match {{ key }} (spaces inside braces)
        # It only matches {{key}} (no spaces inside braces)
        text = "Value: {{key}}"
        result = TemplateEngine.substitute(text, " key ", "value")
        assert result == "Value: value"

    def test_default_not_replaced_by_other_key(self):
        """Test that default values aren't affected by other keys."""
        text = "{{name:Guest}} and {{age:unknown}}"
        result = TemplateEngine.substitute(text, "name", "Alice")
        assert result == "Alice and {{age:unknown}}"

    def test_empty_value(self):
        """Test substitution with empty value."""
        text = "Hello {{name}}"
        result = TemplateEngine.substitute(text, "name", "")
        assert result == "Hello "

    def test_no_occurrences(self):
        """Test when key doesn't exist in text."""
        text = "Hello World"
        result = TemplateEngine.substitute(text, "name", "Alice")
        assert result == "Hello World"


class TestTemplateApplyDefaults:
    """Test TemplateEngine.apply_defaults() method."""

    def test_basic_default(self):
        """Test applying default values."""
        text = "Hello {{name:Guest}}"
        result = TemplateEngine.apply_defaults(text)
        assert result == "Hello Guest"

    def test_multiple_defaults(self):
        """Test multiple default values."""
        text = "{{greeting:Hello}} {{name:Guest}}, welcome!"
        result = TemplateEngine.apply_defaults(text)
        assert result == "Hello Guest, welcome!"

    def test_no_defaults(self):
        """Test text with no default values."""
        text = "Hello {{name}}"
        result = TemplateEngine.apply_defaults(text)
        assert result == "Hello {{name}}"

    def test_empty_default(self):
        """Test empty default value."""
        text = "Value: {{key:}}"
        result = TemplateEngine.apply_defaults(text)
        assert result == "Value: "

    def test_default_with_special_chars(self):
        """Test default value with special characters."""
        text = "Path: {{path:/home/user}}"
        result = TemplateEngine.apply_defaults(text)
        assert result == "Path: /home/user"

    def test_colon_in_default(self):
        """Test default value containing a colon."""
        text = "URL: {{url:http://example.com}}"
        result = TemplateEngine.apply_defaults(text)
        assert result == "URL: http://example.com"


class TestTemplateCleanUnused:
    """Test TemplateEngine.clean_unused() method."""

    def test_remove_unused_variable(self):
        """Test removing unused {{key}} variables."""
        text = "Hello {{name}}"
        result = TemplateEngine.clean_unused(text)
        assert result == "Hello "

    def test_remove_multiple_unused(self):
        """Test removing multiple unused variables."""
        text = "{{greeting}} {{name}}, how are you?"
        result = TemplateEngine.clean_unused(text)
        assert result == " , how are you?"  # Each {{var}} replaced with empty string

    def test_no_unused_variables(self):
        """Test text with no template variables."""
        text = "Hello World"
        result = TemplateEngine.clean_unused(text)
        assert result == "Hello World"

    def test_remove_with_defaults(self):
        """Test that variables with defaults are also removed."""
        text = "Hello {{name:Guest}}"
        result = TemplateEngine.clean_unused(text)
        assert result == "Hello "


class TestTemplateEndToEnd:
    """Test complete template substitution workflows."""

    def test_full_workflow_with_defaults(self):
        """Test complete workflow: substitute -> apply_defaults -> clean_unused."""
        template = """
        <h1>{{title:My Site}}</h1>
        <p>Welcome, {{username}}!</p>
        <p>{{description:No description}}</p>
        <p>{{unused}}</p>
        """

        # Substitute username
        result = TemplateEngine.substitute(template, "username", "Alice")

        # Apply defaults
        result = TemplateEngine.apply_defaults(result)

        # Clean unused
        result = TemplateEngine.clean_unused(result)

        assert "My Site" in result
        assert "Alice" in result
        assert "No description" in result
        assert "{{unused}}" not in result

    def test_workflow_override_default(self):
        """Test that explicit values override defaults."""
        template = "{{greeting:Hello}} {{name:Guest}}"

        # Substitute both keys
        result = TemplateEngine.substitute(template, "greeting", "Hi")
        result = TemplateEngine.substitute(result, "name", "Bob")

        # Apply defaults (should have no effect)
        result = TemplateEngine.apply_defaults(result)

        # Clean unused (should have no effect)
        result = TemplateEngine.clean_unused(result)

        assert result == "Hi Bob"

    def test_workflow_partial_substitution(self):
        """Test workflow with partial substitution."""
        template = "{{a:1}} {{b}} {{c:3}}"

        # Only substitute b
        result = TemplateEngine.substitute(template, "b", "2")

        # Apply defaults
        result = TemplateEngine.apply_defaults(result)

        # Clean unused
        result = TemplateEngine.clean_unused(result)

        assert result == "1 2 3"


class TestTemplateParityWithSed:
    """Test that template engine matches sed behavior."""

    def test_sed_substitution_parity(self):
        """Verify substitute() matches: sed 's/{{key}}/value/g; s/{{key:[^}]*}}/value/g'"""
        test_cases = [
            ("{{name}}", "name", "Alice", "Alice"),
            ("{{name:Guest}}", "name", "Alice", "Alice"),
            ("{{a}} {{a}}", "a", "test", "test test"),
            ("Path: {{path}}", "path", "/home/user", "Path: /home/user"),
        ]

        for template, key, value, expected in test_cases:
            result = TemplateEngine.substitute(template, key, value)
            assert result == expected

    def test_sed_defaults_parity(self):
        """Verify apply_defaults() matches: sed 's/{{[^{}]*:\\([^}]*\\)}}/\\1/g'"""
        test_cases = [
            ("{{key:default}}", "default"),
            ("{{a:1}} {{b:2}}", "1 2"),
            ("{{path:/home/user}}", "/home/user"),
        ]

        for template, expected in test_cases:
            result = TemplateEngine.apply_defaults(template)
            assert result == expected

    def test_sed_cleanup_parity(self):
        """Verify clean_unused() matches: sed 's/{{[^}]*}}//g'"""
        test_cases = [
            ("{{unused}}", ""),
            ("a {{b}} c", "a  c"),
            ("{{a}} {{b}} {{c}}", "  "),
        ]

        for template, expected in test_cases:
            result = TemplateEngine.clean_unused(template)
            assert result == expected

    def test_whitespace_collapse_matches_shell(self):
        """Verify whitespace collapse matches shell's unquoted echo $value."""
        # In shell: value="a  b   c" ; echo $value → "a b c"
        text = "{{key}}"
        result = TemplateEngine.substitute(text, "key", "a  b   c")
        assert result == "a b c"

        # Multiple spaces, tabs, newlines all become single space
        result = TemplateEngine.substitute(text, "key", "a\t\tb\n\nc")
        assert result == "a b c"
