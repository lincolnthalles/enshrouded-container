"""CPU/memory resource monitoring for the game server process tree."""

import logging
import threading
from os import getpid, sysconf, sysconf_names
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.utils import human_size

if TYPE_CHECKING:
    from enshctl.lifecycle.pause_gate import PauseGate

logger = logging.getLogger(__name__)

CLK_TCK: int = sysconf(sysconf_names["SC_CLK_TCK"])


def get_all_child_pids(parent_pid: int) -> list[int]:
    """Recursively collect all descendant PIDs from /proc/[pid]/task/[pid]/children."""
    pids: list[int] = []
    try:
        for line in Path(f"/proc/{parent_pid}/task/{parent_pid}/children").read_text().splitlines():
            for child_str in line.split():
                try:
                    child = int(child_str)
                except ValueError:
                    continue
                pids.append(child)
                pids.extend(get_all_child_pids(child))
    except OSError:
        pass
    return pids


def read_pid_rss(pid: int) -> int:
    """Read VmRSS from /proc/[pid]/status, return kB."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError, ValueError, IndexError:
        pass
    return 0


def read_pid_cpu_ticks(pid: int) -> int:
    """Read total CPU ticks from /proc/[pid]/stat."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        return int(fields[13]) + int(fields[14]) + int(fields[15]) + int(fields[16])
    except OSError, ValueError, IndexError:
        return 0


def read_system_cpu_ticks() -> int:
    """Read total CPU ticks from first line of /proc/stat."""
    try:
        parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        return sum(int(p) for p in parts)
    except OSError, ValueError, IndexError:
        return 0


def _read_baselines(
    server_pid: int,
    enshctl_pid: int,
    pause_gate: PauseGate,
    stop_event: threading.Event,
) -> tuple[int, int, int] | None:
    """Read starting CPU counters while admitted, or return None when stopping."""
    while not pause_gate.acquire(stop_event):
        if stop_event.is_set() or not pause_gate.wait_until_running(stop_event):
            return None
    try:
        return (
            read_pid_cpu_ticks(enshctl_pid),
            read_system_cpu_ticks(),
            sum(read_pid_cpu_ticks(p) for p in [server_pid, *get_all_child_pids(server_pid)]),
        )
    finally:
        pause_gate.release()


def _resource_poller(
    server_pid: int,
    interval: int,
    stop_event: threading.Event,
    pause_gate: PauseGate,
) -> None:
    """Thread target: periodically log CPU/MEM of enshctl and the game server."""
    enshctl_pid = getpid()

    logger.info(
        "Resource polling every %ds (enshctl PID=%d, server wrapper PID=%d)",
        interval,
        enshctl_pid,
        server_pid,
    )

    baselines = _read_baselines(server_pid, enshctl_pid, pause_gate, stop_event)
    if baselines is None:
        return
    prev_enshctl_ticks, prev_sys_ticks, prev_server_ticks = baselines

    while not stop_event.wait(interval):
        if not pause_gate.acquire(stop_event):
            if stop_event.is_set():
                break
            logger.info("Resource polling suspended by Auto Pause")
            if not pause_gate.wait_until_running(stop_event) or stop_event.is_set():
                break
            logger.info("Resource polling resumed")
            baselines = _read_baselines(server_pid, enshctl_pid, pause_gate, stop_event)
            if baselines is None:
                break
            prev_enshctl_ticks, prev_sys_ticks, prev_server_ticks = baselines
            continue
        try:
            server_pids = [server_pid, *get_all_child_pids(server_pid)]
            cur_server_ticks = sum(read_pid_cpu_ticks(p) for p in server_pids)
            server_rss = sum(read_pid_rss(p) for p in server_pids)

            cur_enshctl_ticks = read_pid_cpu_ticks(enshctl_pid)
            cur_sys_ticks = read_system_cpu_ticks()

            sys_delta = cur_sys_ticks - prev_sys_ticks
            if sys_delta > 0:
                enshctl_pct = (cur_enshctl_ticks - prev_enshctl_ticks) / sys_delta * 100
                server_pct = (cur_server_ticks - prev_server_ticks) / sys_delta * 100
            else:
                enshctl_pct = 0.0
                server_pct = 0.0

            enshctl_rss = read_pid_rss(enshctl_pid)

            logger.info(
                "enshctl: %.1f%% CPU, %s RSS | enshrouded_server.exe: %.1f%% CPU, %s RSS (%d procs)",
                enshctl_pct,
                human_size(enshctl_rss * 1024),
                server_pct,
                human_size(server_rss * 1024),
                len(server_pids),
            )

            prev_enshctl_ticks = cur_enshctl_ticks
            prev_server_ticks = cur_server_ticks
            prev_sys_ticks = cur_sys_ticks
        except OSError:
            break
        finally:
            pause_gate.release()


def start_resource_poller(
    server_pid: int,
    stop_event: threading.Event,
    *,
    pause_gate: PauseGate,
    interval: int = 60,
) -> threading.Thread | None:
    """Spawn a daemon thread that logs CPU/memory usage periodically.

    Returns the thread, or ``None`` if polling is disabled (interval <= 0).
    """
    if interval <= 0:
        logger.info("Resource polling disabled (interval=%d)", interval)
        return None
    thread = threading.Thread(
        target=_resource_poller,
        args=(server_pid, interval, stop_event, pause_gate),
        daemon=True,
    )
    thread.start()
    return thread
