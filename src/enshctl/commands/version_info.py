"""Version-info subcommand."""

from datetime import UTC, datetime

from enshctl.settings import MANIFESTS_DIR, STATUS_FILE


def _list_versions() -> list[dict[str, str]]:
    if not MANIFESTS_DIR.exists():
        return []

    versions: list[dict[str, str]] = []
    for entry in sorted(MANIFESTS_DIR.iterdir(), reverse=True):
        marker = entry / STATUS_FILE
        if entry.is_dir() and marker.exists():
            mtime = datetime.fromtimestamp(marker.stat().st_mtime, tz=UTC)
            versions.append(
                {
                    "manifest_id": entry.name,
                    "installed_at": mtime.isoformat(),
                },
            )
    return versions


def run() -> None:
    """Run the version-info subcommand."""
    print()

    versions = _list_versions()
    if not versions:
        print("No versions installed.")
        return
    print(f"{'Manifest ID':<22} {'Branch':<12} {'Installed At'}")
    print("-" * 60)
    for v in versions:
        mid = v.get("manifest_id", "")
        ts = v.get("installed_at", "unknown")
        print(f"{mid:<22} {'<filesystem>':<12} {ts}")
