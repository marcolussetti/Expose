"""Theme directory resolution for PyExpose.

Bundled themes live inside the package at src/pyexpose/themes/.
Users can override by placing a theme directory in their gallery folder.
"""

from pathlib import Path

BUNDLED_THEMES_DIR = Path(__file__).parent / "themes"


def resolve_theme_dir(theme_name: str, topdir: Path) -> Path:
    """Resolve theme directory path.

    Resolution order:
    1. Absolute path — used as-is if it exists.
    2. Local theme inside topdir — allows per-gallery custom themes.
    3. Bundled theme shipped with the package.

    Args:
        theme_name: Theme name (e.g. "theme1") or absolute path.
        topdir: Gallery root directory.

    Returns:
        Resolved Path to the theme directory.

    Raises:
        FileNotFoundError: If the theme cannot be found anywhere.
    """
    theme_path = Path(theme_name)
    if theme_path.is_absolute():
        if theme_path.exists():
            return theme_path
        raise FileNotFoundError(f"Theme not found: {theme_path}")

    local = topdir / theme_name
    if local.exists():
        return local

    bundled = BUNDLED_THEMES_DIR / theme_name
    if bundled.exists():
        return bundled

    raise FileNotFoundError(f"Theme '{theme_name}' not found in {topdir} or {BUNDLED_THEMES_DIR}")
