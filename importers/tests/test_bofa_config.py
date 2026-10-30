"""Tests for the BofA importers' config file."""

# system imports
import json
import os
from collections.abc import Callable
from pathlib import Path

# 3rd party imports
import click
import pytest
import pytest_check as check
from click.testing import CliRunner, Result
from pytest_mock import MockerFixture

# Project imports
from importers.bofa_config import config_option, default_config_path


########################################################################
########################################################################
#
@pytest.fixture
def config_home(tmp_path: Path, mocker: MockerFixture) -> Path:
    """Point XDG_CONFIG_HOME at a temp dir with no BOFA_/MIBUDGE_ vars.

    Returns the BofA importers' config directory under it, created.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("BOFA_", "MIBUDGE_"))
    }
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    mocker.patch.dict(os.environ, env, clear=True)
    path = default_config_path().parent
    path.mkdir(parents=True)
    return path


########################################################################
########################################################################
#
@pytest.fixture
def write_config(config_home: Path) -> Callable[[str], Path]:
    """Return a function that writes the default config file."""

    def _write(text: str) -> Path:
        path = config_home / "config.toml"
        path.write_text(text)
        return path

    return _write


########################################################################
########################################################################
#
@pytest.fixture
def run_cmd() -> Callable[..., Result]:
    """Return a function that runs a stand-in BofA importer command.

    The command has options shaped like the importers' (an auto env
    var prefix, a path, a repeatable option with its own parameter
    name, and a secret) and prints the values it received as JSON.
    """

    @click.command(context_settings={"auto_envvar_prefix": "MIBUDGE"})
    @click.option("--url", default=None)
    @click.option("--bank-name", default="Bank of America")
    @click.option(
        "--save-dir",
        default=None,
        type=click.Path(file_okay=False, path_type=Path),
    )
    @click.option("--account", "account_filters", multiple=True)
    @click.option("--api-key", default=None, allow_from_autoenv=False)
    @config_option("import_bofa_live")
    def cmd(**kwargs: object) -> None:
        click.echo(json.dumps(kwargs, default=str))

    def _run(*args: str, env: dict[str, str] | None = None) -> Result:
        return CliRunner().invoke(cmd, list(args), env=env)

    return _run


########################################################################
########################################################################
#
class TestConfigFile:
    """Tests for option values read from the config file."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "args,env,expected",
        [
            ([], {}, "https://config"),
            ([], {"MIBUDGE_URL": "https://env"}, "https://env"),
            (
                ["--url", "https://cli"],
                {"MIBUDGE_URL": "https://env"},
                "https://cli",
            ),
        ],
    )
    def test_precedence(
        self,
        write_config: Callable[[str], Path],
        run_cmd: Callable[..., Result],
        args: list[str],
        env: dict[str, str],
        expected: str,
    ) -> None:
        """
        GIVEN: a config file setting url
        WHEN:  the command runs with or without an env var and a flag
        THEN:  the flag beats the env var, which beats the config file
        """
        write_config('url = "https://config"\n')

        result = run_cmd(*args, env=env)

        assert json.loads(result.output)["url"] == expected

    ####################################################################
    #
    def test_keys_tables_and_paths(
        self,
        config_home: Path,
        write_config: Callable[[str], Path],
        run_cmd: Callable[..., Result],
    ) -> None:
        """
        GIVEN: top-level keys, an importer table overriding one, a
               table for the other importer, flag-spelled keys, and a
               relative path
        WHEN:  the command runs
        THEN:  its own table wins, the other table is ignored, flag
               spellings map to their options, and the path resolves
               against the config directory
        """
        write_config(
            'url = "https://top"\n'
            'bank-name = "Top Bank"\n'
            "[import_bofa_live]\n"
            'url = "https://live"\n'
            'account = ["Checking", "1234"]\n'
            'save_dir = "scrapes"\n'
            "[import_bofa_saved]\n"
            'url = "https://saved"\n'
        )

        result = run_cmd()

        values = json.loads(result.output)
        check.equal(values["url"], "https://live", "table wins")
        check.equal(values["bank_name"], "Top Bank", "dashed key")
        check.equal(
            values["account_filters"], ["Checking", "1234"], "flag name"
        )
        check.equal(
            values["save_dir"], str(config_home / "scrapes"), "relative path"
        )

    ####################################################################
    #
    def test_no_config_file_uses_defaults(
        self, config_home: Path, run_cmd: Callable[..., Result]
    ) -> None:
        """
        GIVEN: no config file in the config directory
        WHEN:  the command runs
        THEN:  options take their built-in defaults
        """
        result = run_cmd()

        assert json.loads(result.output)["bank_name"] == "Bank of America"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "text,message",
        [
            ('bank-nmae = "x"\n', "'bank-nmae' at the top level"),
            ('[import_bofa_lve]\nurl = "x"\n', "unknown table"),
            ('api_key = "x"\n', "'api_key' is a secret"),
            ("url = \n", "Config file"),
        ],
    )
    def test_bad_config_is_an_error(
        self,
        write_config: Callable[[str], Path],
        run_cmd: Callable[..., Result],
        text: str,
        message: str,
    ) -> None:
        """
        GIVEN: a config file with a typo'd key, an unknown table, a
               secret, or invalid TOML
        WHEN:  the command runs
        THEN:  it fails and says what is wrong
        """
        write_config(text)

        result = run_cmd()

        check.not_equal(result.exit_code, 0, "fails")
        check.is_in(message, result.output, "says why")

    ####################################################################
    #
    def test_config_flag_names_another_file(
        self,
        tmp_path: Path,
        write_config: Callable[[str], Path],
        run_cmd: Callable[..., Result],
    ) -> None:
        """
        GIVEN: a default config file and another file
        WHEN:  the command runs with --config naming the other file
        THEN:  only the other file is read
        """
        write_config('url = "https://default"\n')
        other = tmp_path / "other.toml"
        other.write_text('url = "https://other"\n')

        result = run_cmd("--config", str(other))

        assert json.loads(result.output)["url"] == "https://other"
