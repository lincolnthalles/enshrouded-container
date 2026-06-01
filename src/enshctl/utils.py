"""Cross-cutting utility functions used by multiple modules."""

from os import environ


def human_size(size_bytes: float) -> str:
    """Format a byte count as a human-readable string (B, KB, MB, GB, TB)."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


_TRUTHY = frozenset({"1", "true", "on", "yes"})
_FALSY = frozenset({"0", "false", "off", "no"})


def is_truthy(env_var: str, default: bool = True) -> bool:
    """Parse a boolean-like env var (1/true/on/yes = True, 0/false/off/no = False).

    Returns ``default`` if the variable is unset or unrecognized.
    """
    value = environ.get(env_var, "").lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def get_uid_gid() -> tuple[int, int]:
    """Return (uid, gid) from PUID/PGID environment variables."""
    uid = int(environ.get("PUID", "1000"))
    gid = int(environ.get("PGID", "1000"))
    return uid, gid
