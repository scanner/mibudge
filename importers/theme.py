"""
Shared Rich terminal theme definitions for mibudge importers.

Both importers support a ``--theme`` option (``light`` | ``dark``) so
that output reads well on both light and dark terminal backgrounds.
All Rich markup in the importers uses the semantic colour names defined
here (``success``, ``error``, ``warning``, ``accent``, ``money_pos``,
``money_neg``) rather than hard-coded colour names.

Usage::

    from importers.theme import get_theme, theme_option

    @click.command(...)
    @theme_option
    def cli_cmd(theme_name: str, ...) -> None:
        theme = get_theme(theme_name)
        console = Console(theme=theme.rich)
        ...
"""

# system imports
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 3rd party imports
import click
from rich.theme import Theme


########################################################################
########################################################################
#
@dataclass(frozen=True)
class _Theme:
    """Bundles a Rich Theme with associated Rule/Panel style strings."""

    rich: Theme
    rule_style: str
    border_style: str


_LIGHT_THEME = _Theme(
    rich=Theme(
        {
            "success": "dark_green",
            "error": "red",
            "warning": "dark_orange3",
            "accent": "dark_cyan",
            "money_pos": "dark_green",
            "money_neg": "red",
        }
    ),
    rule_style="blue",
    border_style="blue",
)

_DARK_THEME = _Theme(
    rich=Theme(
        {
            "success": "green",
            "error": "bright_red",
            "warning": "yellow",
            "accent": "cyan",
            "money_pos": "bright_green",
            "money_neg": "bright_red",
        }
    ),
    rule_style="bright_blue",
    border_style="bright_blue",
)

_THEMES: dict[str, _Theme] = {
    "light": _LIGHT_THEME,
    "dark": _DARK_THEME,
}


########################################################################
########################################################################
#
def get_theme(name: str) -> _Theme:
    """
    Return the ``_Theme`` for *name*.

    Args:
        name: Theme name -- ``"light"`` or ``"dark"``.

    Returns:
        The corresponding ``_Theme`` instance.
    """
    return _THEMES[name]


########################################################################
########################################################################
#
def theme_option[F: Callable[..., Any]](func: F) -> F:
    """
    Click decorator that adds a ``--theme`` option to a command.

    The option is exposed as ``theme_name: str`` in the function
    signature (``"light"`` or ``"dark"``) to avoid shadowing Python
    builtins.  Pass it to :func:`get_theme` to obtain the active
    ``_Theme``.

    Usage::

        @click.command(...)
        @theme_option
        def cli_cmd(theme_name: str, ...) -> None:
            theme = get_theme(theme_name)
            console = Console(theme=theme.rich)
    """
    decorated: F = click.option(
        "--theme",
        "theme_name",
        type=click.Choice(["light", "dark"]),
        default="light",
        show_default=True,
        help=(
            "Colour theme for terminal output.  Use 'dark' for dark "
            "terminal backgrounds, 'light' (default) for light ones."
        ),
    )(func)
    return decorated
