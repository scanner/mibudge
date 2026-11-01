"""
Where the importers' credentials are kept, and how they are read.

A secret store is one record named by a URL whose scheme picks the
backend, so nothing above this module knows which one is in use.

    op://<vault>/<item>
        A 1Password item.  Fields are read with `op read`, so which
        `op` runs decides which account is reachable -- see
        MIBUDGE_OP_BIN.

    hcvault://<host>/<mount>/<path>
        A HashiCorp Vault secret in a KV version 2 engine.  The host is
        the Vault server, reached over https, falling back to VAULT_ADDR
        when the URL omits it; the first path segment is the engine's
        mount point and the rest is the path under it.  The Vault token
        comes from VAULT_TOKEN, then ~/.vault-token -- whatever `vault
        login` left behind -- and VAULT_CACERT names a CA bundle, as for
        the `vault` command line.

The importers name two records: the mibudge credentials
(`--mibudge-creds-url`, fields `api_key` and `password`) and a bank
login (`--bofa-creds-url`, fields `username` and `password`).  Stores
are only ever read.
"""

# system imports
import os
import subprocess
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

# 3rd party imports
import httpx

# Names the `op` binary.  More than one can be on a PATH and only the
# one the 1Password desktop app authorised can reach an account.
#
OP_BIN_ENV = "MIBUDGE_OP_BIN"

# The scheme a HashiCorp Vault store is named by.  `vault` alone is too
# general a word to claim, and is also 1Password's word for a folder.
#
VAULT_SCHEME = "hcvault"

# Where Vault's own command line keeps what it needs, read here the
# same way so that a `vault login` is all the setup a store requires.
#
VAULT_ADDR_ENV = "VAULT_ADDR"
VAULT_TOKEN_ENV = "VAULT_TOKEN"
VAULT_CACERT_ENV = "VAULT_CACERT"
VAULT_TOKEN_FILE = Path.home() / ".vault-token"

# Seconds before a request to Vault is abandoned.
#
VAULT_TIMEOUT = 15.0

# The fields a store is asked for.
#
API_KEY = "api_key"
USERNAME = "username"
PASSWORD = "password"


########################################################################
########################################################################
#
class SecretError(Exception):
    """A store could not be reached, or would not answer."""


########################################################################
########################################################################
#
class SecretStore(Protocol):
    """Reads the fields of one secret record."""

    # The URL the store was named by, for messages.
    #
    url: str

    ####################################################################
    #
    def get(self, field: str) -> str | None:
        """
        Read one field.

        Args:
            field: The field name, such as `username`.

        Returns:
            The value, or None when the record carries no such field.

        Raises:
            SecretError: The store itself could not be reached.
        """
        ...


########################################################################
########################################################################
#
class OnePasswordStore:
    """One 1Password item, read through the `op` command line."""

    ####################################################################
    #
    def __init__(self, url: str, binary: str | None = None) -> None:
        """
        Args:
            url: An `op://vault/item` URL naming the item, without a
                field.
            binary: The `op` executable.  Defaults to `MIBUDGE_OP_BIN`,
                then to whichever `op` is first on the PATH.
        """
        self.url = url.rstrip("/")
        self.binary = binary or os.environ.get(OP_BIN_ENV, "op")

    ####################################################################
    #
    def get(self, field: str) -> str | None:
        """
        Read one field of the item.

        Args:
            field: The field name.

        Returns:
            The value, or None when the item has no such field.

        Raises:
            SecretError: `op` could not answer at all.
        """
        try:
            result = subprocess.run(
                [self.binary, "read", f"{self.url}/{field}"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise SecretError(
                f"{self.binary} is not on the PATH; install the 1Password "
                f"CLI, or set {OP_BIN_ENV} to the one the desktop app "
                "authorised"
            ) from exc

        if result.returncode == 0:
            return result.stdout.strip()

        complaint = result.stderr.strip()
        if _is_missing_field(complaint):
            return None
        raise SecretError(
            f"{self.binary} read {self.url}/{field} failed: "
            f"{complaint or 'no output'}"
        )

    ####################################################################
    #
    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.url}>"


########################################################################
########################################################################
#
class HashiCorpVaultStore:
    """One secret in a HashiCorp Vault KV version 2 engine."""

    ####################################################################
    #
    def __init__(
        self, url: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        """
        Args:
            url: An `hcvault://<host>/<mount>/<path>` URL.  An empty
                host -- `hcvault:///<mount>/<path>` -- means VAULT_ADDR.
            transport: The HTTP transport, for tests.

        Raises:
            SecretError: The URL names no mount and path, or no server
                can be found for it.
        """
        self.url = url.rstrip("/")
        parsed = urlparse(self.url)

        mount, _, path = parsed.path.strip("/").partition("/")
        if not mount or not path:
            raise SecretError(
                f"{self.url} names no secret: the form is "
                f"{VAULT_SCHEME}://<host>/<mount>/<path>"
            )
        self.mount = mount
        self.path = path

        if parsed.netloc:
            self.address = f"https://{parsed.netloc}"
        else:
            address = os.environ.get(VAULT_ADDR_ENV)
            if not address:
                raise SecretError(
                    f"{self.url} names no Vault server and "
                    f"{VAULT_ADDR_ENV} is not set"
                )
            self.address = address.rstrip("/")

        self._transport = transport

    ####################################################################
    #
    def get(self, field: str) -> str | None:
        """
        Read one field of the secret.

        Args:
            field: The field name.

        Returns:
            The value, or None when the secret or the field is absent.

        Raises:
            SecretError: Vault could not be reached or refused the read.
        """
        options: dict[str, Any] = {
            "base_url": self.address,
            "headers": {"X-Vault-Token": _vault_token()},
            "timeout": VAULT_TIMEOUT,
        }
        if self._transport is not None:
            options["transport"] = self._transport
        cacert = os.environ.get(VAULT_CACERT_ENV)
        if cacert:
            options["verify"] = cacert

        try:
            with httpx.Client(**options) as client:
                response = client.get(f"/v1/{self.mount}/data/{self.path}")
        except httpx.HTTPError as exc:
            raise SecretError(
                f"could not reach Vault at {self.address}: {exc}"
            ) from exc

        if response.status_code == 404:
            return None
        if not response.is_success:
            raise SecretError(
                f"Vault would not read {self.url}: "
                f"{response.status_code} {_vault_errors(response)}"
            )

        data = ((response.json() or {}).get("data") or {}).get("data") or {}
        value = data.get(field)
        return None if value is None else str(value)

    ####################################################################
    #
    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.url}>"


####################################################################
#
def _vault_token() -> str:
    """
    The token Vault is authenticated to, as its own command line finds it.

    Raises:
        SecretError: Neither VAULT_TOKEN nor ~/.vault-token has one.
    """
    token = os.environ.get(VAULT_TOKEN_ENV)
    if token:
        return token.strip()
    try:
        token = VAULT_TOKEN_FILE.read_text().strip()
    except OSError:
        token = ""
    if token:
        return token
    raise SecretError(
        f"no Vault token: set {VAULT_TOKEN_ENV} or run `vault login`, "
        f"which writes {VAULT_TOKEN_FILE}"
    )


####################################################################
#
def _vault_errors(response: httpx.Response) -> str:
    """What Vault said when it refused: its `errors` list, joined."""
    try:
        errors = (response.json() or {}).get("errors") or []
    except ValueError:
        errors = []
    return "; ".join(str(e) for e in errors) or response.reason_phrase


####################################################################
#
def _is_missing_field(complaint: str) -> bool:
    """
    Whether `op` refused because the field is not there.

    Only `op` can tell an absent field from an unreachable store, and
    only in prose, so the wordings it uses are matched and nothing
    else: matching wider would report a broken store as a missing
    credential.  The first wording is op 2.32's (observed 2026-09-12),
    the second an older release's:

        item 'Personal/mibudge' does not have a field 'api_key'
        "api_key" isn't a field in the item

    Args:
        complaint: What `op` wrote to standard error.

    Returns:
        Whether this names an absent field.
    """
    lowered = complaint.lower()
    return "field" in lowered and (
        "does not have a field" in lowered or "isn't a field" in lowered
    )


####################################################################
#
def store_for(url: str) -> SecretStore:
    """
    Build the store a URL names.

    Args:
        url: A store URL.

    Returns:
        The store.

    Raises:
        SecretError: The URL names a scheme with no backend behind it,
            or a Vault URL that names no secret.
    """
    match urlparse(url).scheme:
        case "op":
            return OnePasswordStore(url)
        case "hcvault":
            return HashiCorpVaultStore(url)
    raise SecretError(
        f"no secret backend for {url!r}: the importers understand "
        f"op://<vault>/<item> (1Password) and "
        f"{VAULT_SCHEME}://<host>/<mount>/<path> (HashiCorp Vault)"
    )
