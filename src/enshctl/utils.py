"""Cross-cutting utility functions used by multiple modules."""


def human_size(size_bytes: float) -> str:
    """Format a byte count as a human-readable string (B, KB, MB, GB, TB)."""
    size = size_bytes
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
