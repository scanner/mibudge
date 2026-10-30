"""
Config file for the BofA importers.

`config.toml` in the BofA importers' config directory
(`bofa_config_dir()`) supplies option values to `import_bofa_live`
and `import_bofa_saved`.  A value is resolved in this order, first
wins: CLI flag, environment variable (or `.env`), config file, the
option's built-in default.

Keys are option names, spelled like the flag with or without its
dashes (`save-dir` or `save_dir`).  Top-level keys apply to both
importers, so each must be an option of both; a `[import_bofa_live]`
or `[import_bofa_saved]` table holds keys for one importer and wins
over the top level::

    url = "https://dev.mibudge.money"
    api_key_onepassword_url = "op://Personal/mibudge/API key"
    category_map = "categories.yaml"

    [import_bofa_live]
    bofa_onepassword_url = "op://Personal/BofA"
    save_dir = "~/bofa-scrapes"

Relative paths resolve against the config file's directory, and `~`
is expanded.  Secrets (`password`, `api_key`, `bofa_passcode`) are
refused: the directory is synced between machines.  Name a 1Password
reference or a Vault path instead.
"""

# system imports
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 3rd party imports
import click

# Project imports
from importers.bofa_accounts import bofa_config_dir

CONFIG_FILE_NAME = "config.toml"
CONFIG_SECTIONS = ("import_bofa_live", "import_bofa_saved")
SECRET_OPTIONS = frozenset({"password", "api_key", "bofa_passcode"})


####################################################################
#
def default_config_path() -> Path:
    """Return the default path of the BofA importers' config file."""
    return bofa_config_dir() / CONFIG_FILE_NAME


####################################################################
#
def _options_by_key(command: click.Command) -> dict[str, click.Option]:
    """Map every accepted config key of *command* to its option.

    A key is the option's parameter name or a long flag without its
    leading dashes, with dashes turned into underscores.
    """
    options: dict[str, click.Option] = {}
    for param in command.params:
        if not isinstance(param, click.Option) or param.name is None:
            continue
        if param.name == "config":
            continue
        options[param.name] = param
        for opt in param.opts:
            if opt.startswith("--"):
                options[opt[2:].replace("-", "_")] = param
    return options


####################################################################
#
def _config_value(param: click.Option, value: Any, base_dir: Path) -> Any:
    """Expand `~` and resolve relative paths for path-typed options."""
    if not isinstance(param.type, click.Path) or not isinstance(value, str):
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return str(path)


####################################################################
#
def load_config(
    path: Path, section: str, command: click.Command
) -> dict[str, Any]:
    """Read the config file and return a click `default_map`.

    Args:
        path: The TOML config file.
        section: The table holding this importer's own keys, one of
            `CONFIG_SECTIONS`.
        command: The importer's click command; its options are the
            keys the file may set.

    Returns:
        Option values keyed by parameter name, the table's values
        winning over the top level's.

    Raises:
        click.ClickException: If the file cannot be read or parsed,
            names an unknown table or option, or holds a secret.
    """
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise click.ClickException(f"Config file {path}: {e}") from e

    shared = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for name in tables:
        if name not in CONFIG_SECTIONS:
            raise click.ClickException(
                f"Config file {path}: unknown table [{name}]; expected "
                + " or ".join(f"[{s}]" for s in CONFIG_SECTIONS)
                + "."
            )

    options = _options_by_key(command)
    default_map: dict[str, Any] = {}
    for where, entries in (
        ("the top level", shared),
        (f"[{section}]", tables.get(section, {})),
    ):
        for key, value in entries.items():
            param = options.get(key.replace("-", "_"))
            if param is None:
                hint = (
                    "; a key for one importer goes in its own table"
                    if where == "the top level"
                    else ""
                )
                raise click.ClickException(
                    f"Config file {path}: {key!r} at {where} is not an "
                    f"option of {section}{hint}."
                )
            assert param.name is not None
            if param.name in SECRET_OPTIONS:
                raise click.ClickException(
                    f"Config file {path}: {key!r} is a secret and is not "
                    "read from the config file.  Pass it as a flag, or "
                    "name a 1Password reference or a Vault path instead."
                )
            default_map[param.name] = _config_value(param, value, path.parent)
    return default_map


####################################################################
#
def config_option[F: Callable[..., Any]](section: str) -> Callable[[F], F]:
    """Click decorator that adds a `--config` option to an importer.

    The option is eager, so the file is read before every other
    option and its values become the command's `default_map`.  Without
    `--config` the default file is read when it exists.

    Args:
        section: The importer's table in the config file.
    """

    def _callback(
        ctx: click.Context, _param: click.Parameter, value: Path | None
    ) -> None:
        path = value or default_config_path()
        if value is None and not path.is_file():
            return
        ctx.default_map = {
            **load_config(path, section, ctx.command),
            **(ctx.default_map or {}),
        }

    return click.option(
        "--config",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
        is_eager=True,
        expose_value=False,
        callback=_callback,
        help=(
            "TOML file of option values for the BofA importers.  "
            "[default: $XDG_CONFIG_HOME/mibudge-bofa-importer/config.toml, "
            "i.e. ~/.config/...]  [env var: MIBUDGE_CONFIG]"
        ),
    )
