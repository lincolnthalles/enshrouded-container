"""Child-process environment allowlist."""

from os import environ
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def base_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Minimal allowlist inherited by child processes — never whole `environ`."""
    env = environ if source is None else source
    keep = ("PATH", "LANG", "LC_ALL", "TZ", "HOME", "USER", "LOGNAME", "TMPDIR")
    return {key: value for key in keep if (value := env.get(key)) is not None}
