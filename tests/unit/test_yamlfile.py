"""YAML config files (#46): YAML 1.2 typing, line numbers, and what errors say."""

import pytest

from dorothea.config import Config, ConfigError
from dorothea.yamlfile import YamlError, dump_mapping, load_mapping


class TestTypes:
    """YAML 1.2 core schema, like js-yaml in the docs' configurator (not PyYAML's YAML 1.1)."""

    @pytest.mark.parametrize("word", ["off", "on", "yes", "no", "y", "n", "Off", "NO"])
    def test_only_true_and_false_are_booleans(self, word):
        assert load_mapping(f"exif_display: {word}\n")[0] == {"exif_display": word}

    @pytest.mark.parametrize("word,value", [("true", True), ("False", False), ("TRUE", True)])
    def test_booleans(self, word, value):
        assert load_mapping(f"a: {word}\n")[0] == {"a": value}

    @pytest.mark.parametrize(
        "text,value",
        [("85", 85), ("012", 12), ("-3", -3), ("0x1F", 31), ("0o17", 15), ("1.5", 1.5),
         (".5", 0.5), ("1e3", 1000.0)],
    )  # fmt: skip
    def test_numbers(self, text, value):
        loaded = load_mapping(f"a: {text}\n")[0]["a"]
        assert loaded == value and type(loaded) is type(value)

    @pytest.mark.parametrize("text", ["2022-07-14", "1:30", "12:00:00", "1_000"])
    def test_dates_and_times_stay_text(self, text):
        assert load_mapping(f"a: {text}\n")[0] == {"a": text}

    @pytest.mark.parametrize("text", ["", "~", "null"])
    def test_empty_is_null(self, text):
        assert load_mapping(f"a: {text}\n")[0] == {"a": None}

    def test_lists_and_quoted_text(self):
        values, _ = load_mapping(
            'r: [2560, 1280]\np:\n  - "#000000"\n  - rgba(0,0,0,.5)\nu: https://example.com/\n'
        )
        assert values == {
            "r": [2560, 1280],
            "p": ["#000000", "rgba(0,0,0,.5)"],
            "u": "https://example.com/",
        }

    def test_no_python_objects(self):
        """A SafeLoader: YAML tags can't run code or build Python objects."""
        with pytest.raises(YamlError, match="line 1: could not determine a constructor"):
            load_mapping("x: !!python/object/apply:os.system [echo hi]\n")


class TestFile:
    def test_line_numbers(self):
        _, lines = load_mapping(
            "# comment\n\nsite_title: Trip\nresolution:\n  - 1920\nsort: name\n"
        )
        assert lines == {"site_title": 3, "resolution": 4, "sort": 6}

    def test_empty_file(self):
        assert load_mapping("# nothing yet\n") == ({}, {})

    @pytest.mark.parametrize(
        "text,message",
        [
            ("a: [1, 2\n", "line 2: expected ',' or ']'"),
            ("a: b\n  c: d\n", "line 2: mapping values are not allowed here"),
            ("just words\n", "expected `key: value` lines"),
            ("- a\n- b\n", "expected `key: value` lines"),
        ],
    )
    def test_errors(self, text, message):
        with pytest.raises(YamlError, match=message):
            load_mapping(text)

    def test_dump_round_trips(self):
        values = {
            "site_title": "Iceland 2022",
            "exif_display": "off",
            "sort": "no",
            "backgroundcolor": "#000000",
            "resolution": [2560, 640],
            "site_url": "https://example.com/",
            "text_toggle": False,
            "date": "2022-07-14",
        }
        text = dump_mapping(values, header="# hi\n")
        assert text.startswith("# hi\nsite_title: Iceland 2022\nexif_display: 'off'\n")
        assert "resolution: [2560, 640]\n" in text
        assert load_mapping(text)[0] == values

    def test_dump_without_lists_is_still_one_line_per_key(self):
        """PyYAML writes a mapping of plain values as {a: 1} unless told otherwise."""
        assert dump_mapping({"site_title": "Trip", "jpeg_quality": 85}) == (
            "site_title: Trip\njpeg_quality: 85\n"
        )


class TestConfigMessages:
    """What Config.load/validate say about a _config.yml."""

    def test_errors_name_the_line(self, tmp_path):
        (tmp_path / "_config.yml").write_text("site_title: Trip\nsort: random\ntheme_dir: nope\n")
        config = Config.load(tmp_path, tmp_path)
        with pytest.raises(ConfigError) as e:
            config.validate(tmp_path)
        assert "sort must be one of" in str(e.value)
        assert "got 'random' (_config.yml line 2)" in str(e.value)
        assert "theme_dir: Theme 'nope' not found" in str(e.value)
        assert "(_config.yml line 3)" in str(e.value)

    def test_unknown_keys_suggest_a_setting(self, tmp_path):
        (tmp_path / "_config.yml").write_text("site_titel: Trip\njpg_quality: 80\nzzz: 1\n")
        warnings = Config.load(tmp_path, tmp_path).validate()
        assert warnings == [
            "Unknown setting site_titel ignored (_config.yml line 1); did you mean site_title?",
            "Unknown setting jpg_quality ignored (_config.yml line 2); did you mean jpeg_quality?",
            "Unknown setting zzz ignored (_config.yml line 3)",
        ]

    def test_overrides_are_not_given_a_file_line(self, tmp_path):
        (tmp_path / "_config.yml").write_text("jpeg_quality: 80\n")
        config = Config.load(tmp_path, tmp_path, overrides={"jpeg_quality": 500})
        with pytest.raises(ConfigError) as e:
            config.validate()
        assert "got 500" in str(e.value) and "line" not in str(e.value)

    def test_key_without_value_uses_the_default(self, tmp_path):
        (tmp_path / "_config.yml").write_text("site_title: Trip\nsite_url:\n")
        config = Config.load(tmp_path, tmp_path)
        assert config["site_url"] == ""
        assert config.load_warnings == [
            "site_url has no value in _config.yml (line 2); using the default"
        ]
        # (a machine without ffmpeg gets a warning about that, which is fine here)
        assert [w for w in config.validate() if "ffmpeg" not in w] == []

    def test_off_is_a_value_not_false(self, tmp_path):
        """The reason for YAML 1.2: `exif_display: off` must mean the "off" mode."""
        (tmp_path / "_config.yml").write_text("exif_display: off\nsort: name\n")
        config = Config.load(tmp_path, tmp_path)
        assert config["exif_display"] == "off"
        config.validate()

    def test_yes_is_not_true(self, tmp_path):
        (tmp_path / "_config.yml").write_text("download_album: yes\n")
        with pytest.raises(ConfigError, match=r"download_album must be true or false, got 'yes'"):
            Config.load(tmp_path, tmp_path).validate()

    def test_explicit_json_file_says_to_use_yaml(self, tmp_path):
        other = tmp_path / "settings.json"
        other.write_text('{"site_title": "Trip"}')
        with pytest.raises(ConfigError, match="rename _config.json to _config.yml"):
            Config.load(tmp_path, tmp_path, config_path=other)

    def test_yml_is_used_even_with_an_old_json_next_to_it(self, tmp_path):
        (tmp_path / "_config.json").write_text('{"site_title": "Old"}')
        (tmp_path / "_config.yml").write_text("site_title: New\n")
        assert Config.load(tmp_path, tmp_path)["site_title"] == "New"
