"""YAML for people's config files (#46): ``_config.yml`` now, gallery files next.

Files are read with the YAML 1.2 core schema rather than PyYAML's default (YAML 1.1), matching
js-yaml in the docs' configurator: only ``true``/``false`` are booleans, so ``exif_display: off``
or ``sort: no`` stay text, and dates (``2022-07-14``), times (``1:30``) and leading-zero numbers
(``012``, octal in YAML 1.1) aren't converted either. Validation then reports wrong types with
the line they're on.
"""

import re
from typing import Any

import yaml

SCHEMA_URL = "https://dorothea.readthedocs.io/schema/config.json"


class YamlError(ValueError):
    """A YAML file that can't be read; the message names the line (``line 3: …``)."""

    def __init__(self, problem: str, line: int | None = None):
        super().__init__(f"line {line}: {problem}" if line else problem)
        self.problem = problem
        self.line = line  # 1-based, when known


class _Loader(yaml.SafeLoader):
    """SafeLoader with the YAML 1.2 core schema's implicit types (see the module docstring)."""


_Loader.yaml_implicit_resolvers = {}
for _tag, _pattern, _first in (
    ("bool", r"^(?:true|True|TRUE|false|False|FALSE)$", "tTfF"),
    ("int", r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$", "-+0123456789"),
    (
        "float",
        r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
        r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
        "-+0123456789.",
    ),
    ("null", r"^(?:~|null|Null|NULL|)$", "~nN"),
):
    _Loader.add_implicit_resolver(f"tag:yaml.org,2002:{_tag}", re.compile(_pattern), list(_first))
# An empty value (`site_url:`) is null too
_Loader.add_implicit_resolver("tag:yaml.org,2002:null", re.compile(r"^$"), [""])


def _construct_int(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> int:
    """Base 10 unless 0x/0o: YAML 1.1's constructor reads ``012`` as octal (10)."""
    value = str(loader.construct_scalar(node))
    return int(value, 0) if value.lstrip("+-")[:2] in ("0x", "0o") else int(value, 10)


_Loader.add_constructor("tag:yaml.org,2002:int", _construct_int)


def _error(error: yaml.YAMLError) -> YamlError:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error)
    return YamlError(problem, mark.line + 1 if mark else None)


def load_mapping(text: str) -> tuple[dict[str, Any], dict[str, int]]:
    """A YAML document that must be a mapping (or empty) → ``(values, key -> line number)``.

    Raises:
        YamlError: If it isn't valid YAML, or isn't ``key: value`` pairs at the top level.
    """
    try:
        node = yaml.compose(text, Loader=_Loader)
        data = yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as e:
        raise _error(e) from e
    if data is None:
        return {}, {}
    if not isinstance(data, dict) or not isinstance(node, yaml.MappingNode):
        raise YamlError("expected `key: value` lines")
    lines = {key.value: key.start_mark.line + 1 for key, _value in node.value}
    return {str(key): value for key, value in data.items()}, lines


def dump_mapping(values: dict[str, Any], header: str = "") -> str:
    """``key: value`` lines in the given order, with lists on one line (``[1920, 640]``).

    Text that would read back as something else (``'off'``, ``'#000000'``) is quoted.
    """
    lines = []
    for key, value in values.items():
        if isinstance(value, list):
            # PyYAML puts a whole mapping of plain values on one line ({a: 1}) unless asked for
            # block style, so each setting is written on its own, lists in flow style
            flow = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10**6)
            lines.append(f"{key}: {flow.strip()}")  # setting names are plain words
        else:
            block = yaml.safe_dump(
                {key: value}, default_flow_style=False, allow_unicode=True, width=10**6
            )
            lines.append(block.rstrip("\n"))
    return header + "".join(line + "\n" for line in lines)
