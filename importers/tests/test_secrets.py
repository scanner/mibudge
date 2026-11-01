"""
Test the secret store layer.

`op` is never actually run, and Vault is never actually reached: what
is asserted is which command or request would be sent, and what is made
of the answer.
"""

# system imports
import os
import re
import subprocess
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

# 3rd party imports
import httpx
import pytest
import pytest_check as check
from pytest_mock import MockerFixture

# Project imports
from importers import secrets
from importers.secrets import (
    API_KEY,
    OP_BIN_ENV,
    USERNAME,
    VAULT_ADDR_ENV,
    VAULT_TOKEN_ENV,
    HashiCorpVaultStore,
    OnePasswordStore,
    SecretError,
    store_for,
)

# Invented, and only ever sent to a mock transport.
#
VAULT_TOKEN = "hvs.not-a-real-vault-token"

VaultFactory = Callable[..., tuple[HashiCorpVaultStore, list[httpx.Request]]]


####################################################################
#
def completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """One finished `op` invocation."""
    return subprocess.CompletedProcess(
        args=["op"], returncode=returncode, stdout=stdout, stderr=stderr
    )


########################################################################
########################################################################
#
@pytest.fixture(autouse=True)
def environment(
    mocker: MockerFixture, tmp_path: Path
) -> MutableMapping[str, str]:
    """
    An environment with no Vault or 1Password settings, and no Vault
    token file.

    Every test here needs it: a developer's own VAULT_TOKEN,
    ~/.vault-token or MIBUDGE_OP_BIN would otherwise leak in.  Returns
    os.environ so a test can set what it is about.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("VAULT_", "MIBUDGE_"))
    }
    mocker.patch.dict(os.environ, env, clear=True)
    mocker.patch.object(secrets, "VAULT_TOKEN_FILE", tmp_path / ".vault-token")
    return os.environ


########################################################################
########################################################################
#
@pytest.fixture
def op_run(mocker: MockerFixture) -> Callable[..., Any]:
    """Return a function that scripts `op`'s answer and returns the mock."""

    def _script(**kwargs: Any) -> Any:
        if "side_effect" in kwargs:
            return mocker.patch.object(
                secrets.subprocess, "run", side_effect=kwargs["side_effect"]
            )
        return mocker.patch.object(
            secrets.subprocess, "run", return_value=completed(**kwargs)
        )

    return _script


########################################################################
########################################################################
#
class TestStoreFor:
    """Tests for picking a backend from a URL."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url,backend",
        [
            ("op://Personal/mibudge", OnePasswordStore),
            ("hcvault://vault.example/secret/mibudge", HashiCorpVaultStore),
        ],
    )
    def test_the_scheme_picks_the_backend(
        self, url: str, backend: type
    ) -> None:
        """
        GIVEN: an op:// or hcvault:// URL
        WHEN:  a store is built for it
        THEN:  it is that backend, holding the URL
        """
        store = store_for(url)

        check.is_instance(store, backend)
        check.equal(store.url, url)

    ####################################################################
    #
    def test_a_scheme_with_no_backend_is_refused(self) -> None:
        """
        GIVEN: a URL naming a backend that does not exist
        WHEN:  a store is built for it
        THEN:  it says so, naming both forms it does understand
        """
        with pytest.raises(SecretError) as raised:
            store_for("vault://secret/mibudge")

        check.is_in("op://", str(raised.value))
        check.is_in("hcvault://", str(raised.value))


########################################################################
########################################################################
#
class TestOnePasswordStore:
    """Tests for the 1Password backend."""

    ####################################################################
    #
    def test_a_field_is_read_through_op(
        self, op_run: Callable[..., Any]
    ) -> None:
        """
        GIVEN: an item URL (with a trailing slash) and a field
        WHEN:  the field is read
        THEN:  `op read` is run against that field, and its output used
        """
        run = op_run(stdout="mib_secret\n")
        store = OnePasswordStore("op://Personal/mibudge/", binary="/bin/op")

        value = store.get(API_KEY)

        check.equal(value, "mib_secret", "whitespace stripped")
        check.equal(
            run.call_args.args[0],
            ["/bin/op", "read", "op://Personal/mibudge/api_key"],
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "complaint,missing",
        [
            pytest.param(
                "[ERROR] could not read secret "
                "'op://Personal/mibudge/api_key': item 'Personal/mibudge' "
                "does not have a field 'api_key'",
                True,
                id="op-2.32-wording",
            ),
            pytest.param(
                '"api_key" isn\'t a field in the item',
                True,
                id="older-wording",
            ),
            pytest.param(
                "No accounts configured for use with 1Password CLI.",
                False,
                id="unauthorised-binary",
            ),
        ],
    )
    def test_only_an_absent_field_reads_as_absent(
        self, op_run: Callable[..., Any], complaint: str, missing: bool
    ) -> None:
        """
        GIVEN: op refusing with a particular complaint
        WHEN:  a field is read
        THEN:  an absent field comes back as None, and anything else
               raises carrying op's own words
        """
        op_run(returncode=1, stderr=complaint)
        store = OnePasswordStore("op://Personal/mibudge")

        if missing:
            assert store.get(API_KEY) is None
        else:
            with pytest.raises(SecretError, match=re.escape(complaint)):
                store.get(API_KEY)

    ####################################################################
    #
    def test_a_missing_binary_names_the_override(
        self, op_run: Callable[..., Any]
    ) -> None:
        """
        GIVEN: no such executable
        WHEN:  a field is read
        THEN:  the error names the variable that points at the right one
        """
        op_run(side_effect=FileNotFoundError("nope"))
        store = OnePasswordStore("op://Personal/mibudge", binary="op-missing")

        with pytest.raises(SecretError, match=OP_BIN_ENV):
            store.get(USERNAME)

    ####################################################################
    #
    def test_the_binary_comes_from_the_environment(
        self,
        environment: MutableMapping[str, str],
        op_run: Callable[..., Any],
    ) -> None:
        """
        GIVEN: MIBUDGE_OP_BIN naming a particular op
        WHEN:  a store is built without an explicit binary
        THEN:  that one is run
        """
        environment[OP_BIN_ENV] = "/usr/local/bin/op"
        run = op_run(stdout="value")

        OnePasswordStore("op://Personal/mibudge").get(USERNAME)

        assert run.call_args.args[0][0] == "/usr/local/bin/op"


########################################################################
########################################################################
#
class TestHashiCorpVaultStore:
    """Tests for the HashiCorp Vault backend."""

    ####################################################################
    #
    @pytest.fixture
    def vault(self) -> VaultFactory:
        """
        A Vault store talking to a scripted server.

        Call it with the responses the server should give, in order, as
        (status, body) pairs.  Returns the store and the list the server
        records each request into.
        """

        def build(
            *answers: tuple[int, dict[str, Any]],
        ) -> tuple[HashiCorpVaultStore, list[httpx.Request]]:
            seen: list[httpx.Request] = []
            queue = list(answers)

            def handler(request: httpx.Request) -> httpx.Response:
                seen.append(request)
                status, body = queue.pop(0)
                return httpx.Response(status, json=body)

            store = HashiCorpVaultStore(
                "hcvault://vault.example:8200/secret/apps/mibudge",
                transport=httpx.MockTransport(handler),
            )
            return store, seen

        return build

    ####################################################################
    #
    @pytest.fixture
    def vault_token(self, environment: MutableMapping[str, str]) -> str:
        """A Vault token in VAULT_TOKEN."""
        environment[VAULT_TOKEN_ENV] = VAULT_TOKEN
        return VAULT_TOKEN

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url,vault_addr,address,mount,path",
        [
            pytest.param(
                "hcvault://vault.example:8200/secret/apps/mibudge",
                None,
                "https://vault.example:8200",
                "secret",
                "apps/mibudge",
                id="host-in-url",
            ),
            pytest.param(
                "hcvault:///kv/mibudge",
                "https://from-env.example:8200/",
                "https://from-env.example:8200",
                "kv",
                "mibudge",
                id="host-from-VAULT_ADDR",
            ),
        ],
    )
    def test_the_url_names_the_server_the_mount_and_the_path(
        self,
        environment: MutableMapping[str, str],
        url: str,
        vault_addr: str | None,
        address: str,
        mount: str,
        path: str,
    ) -> None:
        """
        GIVEN: an hcvault:// URL, with or without a host
        WHEN:  a store is built
        THEN:  the server is the URL's host over https, or VAULT_ADDR;
               the first path segment is the mount and the rest the path
        """
        if vault_addr is not None:
            environment[VAULT_ADDR_ENV] = vault_addr

        store = HashiCorpVaultStore(url)

        check.equal(store.address, address)
        check.equal(store.mount, mount)
        check.equal(store.path, path)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url,complaint",
        [
            pytest.param(
                "hcvault:///kv/mibudge", VAULT_ADDR_ENV, id="no-server"
            ),
            pytest.param(
                "hcvault://vault.example/kv", "<mount>/<path>", id="no-path"
            ),
        ],
    )
    def test_a_url_that_names_nothing_usable_is_refused(
        self, url: str, complaint: str
    ) -> None:
        """
        GIVEN: a URL with no server anywhere, or no path under the mount
        WHEN:  a store is built
        THEN:  it is refused, saying what is missing
        """
        with pytest.raises(SecretError, match=re.escape(complaint)):
            HashiCorpVaultStore(url)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "in_env,in_file,expected",
        [
            pytest.param("from-env", "from-file", "from-env", id="env-first"),
            pytest.param(None, "from-file\n", "from-file", id="then-file"),
        ],
    )
    def test_the_vault_token_is_found_as_the_vault_cli_finds_it(
        self,
        environment: MutableMapping[str, str],
        vault: VaultFactory,
        in_env: str | None,
        in_file: str,
        expected: str,
    ) -> None:
        """
        GIVEN: a Vault token in VAULT_TOKEN and ~/.vault-token, or only
               the file
        WHEN:  a field is read
        THEN:  VAULT_TOKEN is sent if set, otherwise the file's
        """
        if in_env is not None:
            environment[VAULT_TOKEN_ENV] = in_env
        secrets.VAULT_TOKEN_FILE.write_text(in_file)
        store, seen = vault((404, {"errors": []}))

        store.get(API_KEY)

        assert seen[0].headers["X-Vault-Token"] == expected

    ####################################################################
    #
    def test_no_vault_token_anywhere_says_where_to_put_one(
        self, vault: VaultFactory
    ) -> None:
        """
        GIVEN: no VAULT_TOKEN and no ~/.vault-token
        WHEN:  a field is read
        THEN:  it fails naming both places
        """
        store, _ = vault()

        with pytest.raises(SecretError) as raised:
            store.get(API_KEY)

        check.is_in(VAULT_TOKEN_ENV, str(raised.value))
        check.is_in("vault login", str(raised.value))

    ####################################################################
    #
    @pytest.mark.parametrize(
        "status,body,expected",
        [
            pytest.param(
                200,
                {"data": {"data": {"api_key": "k", "password": "p"}}},
                "k",
                id="present",
            ),
            pytest.param(
                200, {"data": {"data": {"password": "p"}}}, None, id="no-field"
            ),
            pytest.param(404, {"errors": []}, None, id="no-secret"),
        ],
    )
    def test_a_field_is_read_from_the_kv2_data_path(
        self,
        vault_token: str,
        vault: VaultFactory,
        status: int,
        body: dict[str, Any],
        expected: str | None,
    ) -> None:
        """
        GIVEN: a secret holding the field, lacking it, or not existing
        WHEN:  the field is read
        THEN:  the value comes back, or None for either kind of absence
        """
        store, seen = vault((status, body))

        value = store.get(API_KEY)

        check.equal(value, expected)
        check.equal(seen[0].method, "GET")
        check.equal(seen[0].url.path, "/v1/secret/data/apps/mibudge")

    ####################################################################
    #
    def test_a_refused_read_carries_what_vault_said(
        self, vault_token: str, vault: VaultFactory
    ) -> None:
        """
        GIVEN: a Vault token without permission on the path
        WHEN:  a field is read
        THEN:  SecretError carries Vault's own words and not the token
        """
        store, _ = vault((403, {"errors": ["permission denied"]}))

        with pytest.raises(SecretError, match="permission denied") as raised:
            store.get(API_KEY)

        check.is_not_in(VAULT_TOKEN, str(raised.value))
