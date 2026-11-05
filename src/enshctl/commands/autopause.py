"""Auto Pause control subcommand."""

import argparse
import logging
import sys
import time
import uuid
from typing import TYPE_CHECKING

from enshctl.commands.parser import CommandParser
from enshctl.lifecycle.control import AutoPauseStatus, ControlFiles
from enshctl.paths import AUTOPAUSE_DIR
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 5.0
REQUEST_POLL_INTERVAL = 0.1
STATUS_STALE = 3
STATUS_REFUSED = 2


def run(settings: AppSettings | None = None, argv: Sequence[str] = ()) -> int:
    """Run one Auto Pause operator action."""
    parser = CommandParser("Auto Pause control")
    subcommands = parser.add_subparsers(dest="action", required=True, parser_class=argparse.ArgumentParser)
    status = subcommands.add_parser("status")
    status.allow_abbrev = False
    pause = subcommands.add_parser("pause")
    pause.allow_abbrev = False
    pause.add_argument("--force", action="store_true")
    resume = subcommands.add_parser("resume")
    resume.allow_abbrev = False
    reset = subcommands.add_parser("reset")
    reset.allow_abbrev = False
    reset.add_argument("--yes", action="store_true")
    disable = subcommands.add_parser("disable")
    disable.allow_abbrev = False
    enable = subcommands.add_parser("enable")
    enable.allow_abbrev = False
    args = parser.parse(argv)

    resolved = settings or load_settings()
    control = ControlFiles(AUTOPAUSE_DIR, puid=resolved.puid, pgid=resolved.pgid)

    if args.action == "status":
        return _status(control)
    if args.action == "disable":
        control.set_disabled()
        live = control.live_status()
        if live is not None:
            control.write_request("resume", f"disable-{uuid.uuid4().hex}")
        print("Auto Pause: disabled")
        return 0
    if args.action == "enable":
        if not control.clear_disabled():
            print("Auto Pause: could not remove the disabled marker", file=sys.stderr)
            return 1
        print("Auto Pause: enabled")
        return 0

    live = control.live_status()
    if live is None:
        print("Auto Pause controller unavailable; state is stale.", file=sys.stderr)
        return STATUS_STALE

    if args.action == "pause":
        if args.force:
            print("Warning: a forced pause can freeze connected players.")
        return _request(control, "pause-force" if args.force else "pause")
    if args.action == "resume":
        return _request(control, "resume")
    if args.action == "reset":
        if live.players and not args.yes:
            print("Auto Pause reset refused: players are online. Use --yes to force.")
            return STATUS_REFUSED
        return _request(control, "reset-force" if args.yes else "reset")
    return 1


def _status(control: ControlFiles) -> int:
    live = control.live_status()
    if live is None:
        print("Auto Pause controller unavailable; state is stale.")
        return STATUS_STALE
    _print_status(live)
    return 0


def _request(control: ControlFiles, action: str) -> int:
    token = f"{action}-{uuid.uuid4().hex}"
    control.write_request(action, token)
    deadline = time.monotonic() + REQUEST_TIMEOUT
    while time.monotonic() < deadline:
        status = control.live_status()
        if status is not None and status.last_request == token:
            if status.last_result == "refused":
                print(f"Auto Pause: {action} refused")
                return STATUS_REFUSED
            print(f"Auto Pause: {action} {status.last_result or 'pending'}")
            return 0
        time.sleep(REQUEST_POLL_INTERVAL)
    print(f"Auto Pause: {action} request timed out")
    return STATUS_STALE


def _print_status(status: AutoPauseStatus) -> None:
    players = ", ".join(status.players) if status.players else "0"
    print(f"Auto Pause: {status.state}")
    print(f"Players online: {len(status.players)} - {players}" if status.players else "Players online: 0")
    print(f"Pending join: {'yes' if status.pending_join else 'no'}")
    print(f"Session veto: {'yes' if status.session_veto else 'no'}")
    print(f"A2S: {status.a2s}")
    if status.last_error:
        print(f"Last error: {status.last_error}")
