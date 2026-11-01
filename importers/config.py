"""
The importers' config directory and config file.

Every importer command keeps what it remembers in one directory,
`config_dir()` (`~/.config/mibudge-importers/`), which is meant to be
synced across machines:

    config.toml                 option values for every command
    bofa-accounts.json          the live BofA importer's account cache
    backfill-vendor-rules.json  the budget backfill's vendor rules

`config.toml` supplies option values.  A value is resolved in this
order, first wins: CLI flag, environment variable (or `.env`), config
file, the option's built-in default.

Keys are option names, spelled like the flag with or without its
dashes (`save-dir` or `save_dir`).  A top-level key applies to every
command that has that option and is ignored by the rest.  A table
named for a command holds keys for that command alone and wins over
the top level::

    url = "https://dev.mibudge.money"
    email = "me@example.com"
    mibudge_creds_url = "op://Personal/mibudge"
    category_map = "categories.yaml"

    [bofa_live]
    bofa_creds_url = "op://Personal/BofA"
    save_dir = "~/bofa-scrapes"

The tables are `[bofa_live]`, `[bofa_saved]`, `[statements]` and
`[backfill_budget]` (see `COMMANDS`).  A key that is no option of any
command, or of its table's command, is an error.

Relative paths resolve against the config file's directory, and `~`
is expanded.  Secrets (`password`, `api_key`, `bofa_passcode`) are
refused: the directory is synced between machines.  Name a secret
store with `mibudge_creds_url` / `bofa_creds_url` instead.
"""

# system imports
import importlib
import os
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# 3rd party imports
import click

CONFIG_DIR_NAME = "mibudge-importers"
CONFIG_FILE_NAME = "config.toml"
SECRET_OPTIONS = frozenset({"password", "api_key", "bofa_passcode"})

# Config file table -> the module whose `cli_cmd` it configures.
#
COMMANDS = {
    "bofa_live": "importers.import_bofa_live",
    "bofa_saved": "importers.import_bofa_saved",
    "statements": "importers.import_transactions",
    "backfill_budget": "importers.backfill_budget",
}


####################################################################
#
def config_dir() -> Path:
    """Return the importers' config directory.

    `$XDG_CONFIG_HOME/mibudge-importers`, falling back to
    `~/.config/mibudge-importers`.  Not created here.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / CONFIG_DIR_NAME


####################################################################
#
def default_config_path() -> Path:
    """Return the default path of the importers' config file."""
    return config_dir() / CONFIG_FILE_NAME


####################################################################
#
def _commands() -> dict[str, click.Command]:
    """Return every configurable command, keyed by its table name.

    The command modules import this one, so they are imported here
    when a config file is read rather than at module load.
    """
    return {
        table: importlib.import_module(module).cli_cmd
        for table, module in COMMANDS.items()
    }


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
    path: Path, section: str, commands: Mapping[str, click.Command]
) -> dict[str, Any]:
    """Read the config file and return a click `default_map`.

    The whole file is checked against every command, so a typo in
    another command's table is reported whichever command runs.

    Args:
        path: The TOML config file.
        section: The table of the command being run, a key of
            *commands*.
        commands: Every configurable command, keyed by table name.

    Returns:
        The running command's option values keyed by parameter name,
        its table's values winning over the top level's.

    Raises:
        click.ClickException: If the file cannot be read or parsed,
            names an unknown table or option, or holds a secret.
    """

    ####################################################################
    #
    def _fail(message: str) -> click.ClickException:
        """An error naming the config file."""
        return click.ClickException(f"Config file {path}: {message}")

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise _fail(str(e)) from e

    shared = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for name in tables:
        if name not in commands:
            raise _fail(
                f"unknown table [{name}]; expected one of "
                + ", ".join(f"[{t}]" for t in commands)
                + "."
            )

    options = {table: _options_by_key(cmd) for table, cmd in commands.items()}

    ####################################################################
    #
    def _check_secret(key: str, param: click.Option) -> None:
        """Refuse a key that names a secret option."""
        if param.name in SECRET_OPTIONS:
            raise _fail(
                f"{key!r} is a secret and is not read from the config "
                "file.  Pass it as a flag, or name a secret store with "
                "mibudge_creds_url / bofa_creds_url instead."
            )

    default_map: dict[str, Any] = {}
    for key, value in shared.items():
        name = key.replace("-", "_")
        params = [o[name] for o in options.values() if name in o]
        if not params:
            raise _fail(
                f"{key!r} at the top level is not an option of any "
                "importer command."
            )
        _check_secret(key, params[0])
        if (param := options[section].get(name)) is not None:
            assert param.name is not None
            default_map[param.name] = _config_value(param, value, path.parent)

    for table, entries in tables.items():
        for key, value in entries.items():
            param = options[table].get(key.replace("-", "_"))
            if param is None:
                raise _fail(f"{key!r} in [{table}] is not an option of it.")
            _check_secret(key, param)
            if table == section:
                assert param.name is not None
                default_map[param.name] = _config_value(
                    param, value, path.parent
                )
    return default_map


####################################################################
#
def config_option[F: Callable[..., Any]](section: str) -> Callable[[F], F]:
    """Click decorator that adds a `--config` option to a command.

    The option is eager, so the file is read before every other
    option and its values become the command's `default_map`.  Without
    `--config` the default file is read when it exists.

    Args:
        section: The command's table in the config file, a key of
            `COMMANDS`.
    """

    def _callback(
        ctx: click.Context, _param: click.Parameter, value: Path | None
    ) -> None:
        path = value or default_config_path()
        if value is None and not path.is_file():
            return
        ctx.default_map = {
            **load_config(path, section, _commands()),
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
            "TOML file of option values for the importer commands.  "
            "[default: $XDG_CONFIG_HOME/mibudge-importers/config.toml, "
            "i.e. ~/.config/...]  [env var: MIBUDGE_CONFIG]"
        ),
    )
