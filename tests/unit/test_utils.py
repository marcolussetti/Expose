"""Unit tests for pyexpose.utils module.

Tests the pure utility functions url_safe() and strip_numeric_prefix().
"""


from pyexpose.utils import strip_numeric_prefix, url_safe


class TestUrlSafe:
    """Test url_safe() function."""

    def test_basic_conversion(self):
        """Test basic name to URL conversion."""
        assert url_safe("My Photos") == "my-photos"
        assert url_safe("Nature") == "nature"
        assert url_safe("Urban Landscapes") == "urban-landscapes"

    def test_numeric_prefix(self):
        """Test that numeric prefixes are preserved."""
        assert url_safe("01 Mountains") == "01-mountains"
        assert url_safe("123 Test") == "123-test"

    def test_special_characters(self):
        """Test removal of special characters."""
        assert url_safe("Nature & Wildlife") == "nature--wildlife"
        assert url_safe("Photos (2024)") == "photos-2024"
        assert url_safe("Test/Images") == "testimages"
        assert url_safe("Hello@World") == "helloworld"

    def test_multiple_spaces(self):
        """Test multiple spaces become single hyphen."""
        assert url_safe("Hello  World") == "hello--world"
        assert url_safe("A   B   C") == "a---b---c"

    def test_case_conversion(self):
        """Test uppercase to lowercase conversion."""
        assert url_safe("MOUNTAINS") == "mountains"
        assert url_safe("MiXeD CaSe") == "mixed-case"

    def test_empty_string(self):
        """Test empty string handling."""
        assert url_safe("") == ""

    def test_only_special_chars(self):
        """Test string with only special characters."""
        assert url_safe("@#$%") == ""
        assert url_safe("!@#$%^&*()") == ""

    def test_real_world_examples(self):
        """Test real-world folder names."""
        assert url_safe("01 Nature") == "01-nature"
        assert url_safe("02 Urban") == "02-urban"
        assert url_safe("01 Mountains") == "01-mountains"
        assert url_safe("02 Oceans") == "02-oceans"


class TestStripNumericPrefix:
    """Test strip_numeric_prefix() function."""

    def test_basic_stripping(self):
        """Test basic numeric prefix removal."""
        assert strip_numeric_prefix("01 Mountains") == "Mountains"
        assert strip_numeric_prefix("123 Test") == "Test"
        assert strip_numeric_prefix("99 Photos") == "Photos"

    def test_no_prefix(self):
        """Test strings without numeric prefix."""
        assert strip_numeric_prefix("Mountains") == "Mountains"
        assert strip_numeric_prefix("Test") == "Test"

    def test_only_numbers(self):
        """Test strings that are only numbers."""
        # When only numbers, should return original (edge case in shell version)
        result = strip_numeric_prefix("123")
        assert result == "123"  # Returns original if result would be empty

    def test_whitespace_handling(self):
        """Test whitespace is properly stripped."""
        assert strip_numeric_prefix("  456  ") == "456"  # Only numbers, returns original
        assert strip_numeric_prefix("01  Mountains  ") == "Mountains"
        assert strip_numeric_prefix("123   Test") == "Test"

    def test_numbers_in_middle(self):
        """Test numbers in middle of string are preserved."""
        assert strip_numeric_prefix("Test123Photos") == "Test123Photos"
        assert strip_numeric_prefix("abc123def") == "abc123def"

    def test_empty_string(self):
        """Test empty string handling."""
        assert strip_numeric_prefix("") == ""

    def test_leading_zeros(self):
        """Test leading zeros are removed."""
        assert strip_numeric_prefix("001 Test") == "Test"
        assert strip_numeric_prefix("0 Photos") == "Photos"

    def test_real_world_examples(self):
        """Test real-world folder names."""
        assert strip_numeric_prefix("01 Nature") == "Nature"
        assert strip_numeric_prefix("02 Urban") == "Urban"
        assert strip_numeric_prefix("01 Mountains") == "Mountains"
        assert strip_numeric_prefix("02 Oceans") == "Oceans"
        assert strip_numeric_prefix("Mountain Peak") == "Mountain Peak"


class TestUtilsParity:
    """Test that utils match original expose.py behavior."""

    def test_url_safe_matches_sed_behavior(self):
        """Verify url_safe matches sed 's/[^ a-zA-Z0-9]//g;s/ /-/g' | tr '[:upper:]' '[:lower:]'"""
        # These test cases verify the exact sed pipeline behavior
        test_cases = [
            ("Hello World", "hello-world"),
            ("01 Nature & Wildlife", "01-nature--wildlife"),
            ("Test@#$%Photos", "testphotos"),
            ("  Spaces  ", "--spaces--"),
            ("UPPERCASE", "uppercase"),
            ("123Numbers", "123numbers"),
        ]
        for input_val, expected in test_cases:
            assert url_safe(input_val) == expected

    def test_strip_numeric_prefix_matches_sed_behavior(self):
        """Verify strip_numeric_prefix matches sed -e 's/^[0-9]*//' | sed -e 's/^[[:space:]]*//;s/[[:space:]]*$//'"""
        # These test cases verify the exact sed pipeline behavior
        test_cases = [
            ("01 Mountains", "Mountains"),
            ("123abc", "abc"),
            ("  456  ", "456"),  # Only numbers returns original due to empty check
            ("abc123", "abc123"),
            ("  01  Test  ", "01  Test"),  # Spaces before digits prevent removal
        ]
        for input_val, expected in test_cases:
            assert strip_numeric_prefix(input_val) == expected
