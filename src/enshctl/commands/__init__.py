"""Subcommand registry for the enshctl CLI."""

from typing import TYPE_CHECKING

from .backup import run as cmd_backup
from .debug_config import run as cmd_debug_config
from .download import run as cmd_download
from .install import run as cmd_install
from .prune import run as cmd_prune
from .restore import run as cmd_restore
from .start import run as cmd_start
from .verify import run as cmd_verify
from .version_info import run as cmd_version_info

if TYPE_CHECKING:
    from collections.abc import Callable

COMMANDS: dict[str, Callable[[], None]] = {
    "backup": cmd_backup,
    "debug-config": cmd_debug_config,
    "download": cmd_download,
    "install": cmd_install,
    "prune": cmd_prune,
    "restore": cmd_restore,
    "start": cmd_start,
    "verify": cmd_verify,
    "version-info": cmd_version_info,
}
