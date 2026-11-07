"""Tests for the Auto Update controller state machine."""

import logging
import threading
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

from enshctl.download.types import ManifestRecord
from enshctl.lifecycle.auto_update import AutoUpdateController, is_auto_update_active
from enshctl.lifecycle.pause_gate import PauseGate
from enshctl.lifecycle.types import RestartRequest
from enshctl.presence import PresenceTracker
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

_CHECK_INTERVAL = 100.0


class _Driver:
    def __init__(self, stop_at: float) -> None:
        self.now = 0.0
        self.stop_at = stop_at

    def clock(self) -> float:
        return self.now

    def wait(self, event: threading.Event, timeout: float) -> bool:
        self.now += timeout
        if self.now >= self.stop_at:
            event.set()
            return True
        return False


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), auto_update_enabled=True, version="latest", **overrides)  # type: ignore[arg-type]


def _tracker() -> PresenceTracker:
    return PresenceTracker()


def _ready(tracker: PresenceTracker, now: float = 0.0) -> None:
    tracker.observe("[game_server] Switching state from LoadEcsScene to Run after 495.18 ms", now=now)


def _session(tracker: PresenceTracker, now: float = 0.0) -> None:
    tracker.observe("-------------- Session ----------------", now=now)
    tracker.observe("Machines:", now=now)
    tracker.observe(
        "  m#0(128): up 0 (0), down 0 (0), remote 0 (0), limit 256, lost 0, ping 0 ms, OperatingNormally",
        now=now,
    )
    tracker.observe("----------------------------------------", now=now)


def _controller(
    driver: _Driver,
    tracker: PresenceTracker,
    *,
    active: ManifestRecord | None = None,
    list_latest: Callable[[], ManifestRecord | None],
    download: Callable[[ManifestRecord], None],
    restart_request: RestartRequest | None = None,
    settings: AppSettings | None = None,
    is_paused: Callable[[], bool] | None = None,
    stream_healthy: Callable[[], bool] | None = None,
    wait: Callable[[threading.Event, float], bool] | None = None,
    pause_gate: PauseGate | None = None,
) -> AutoUpdateController:
    return AutoUpdateController(
        settings=settings or _settings(),
        active_manifest=active or ManifestRecord("111", "05/29/2026 12:00:00"),
        tracker=tracker,
        pause_gate=pause_gate or PauseGate(),
        list_latest=list_latest,
        download=download,
        restart_request=restart_request or RestartRequest(),
        stream_healthy=stream_healthy or (lambda: True),
        is_paused=is_paused or (lambda: False),
        clock=driver.clock,
        wait=wait or driver.wait,
    )


def _run(controller: AutoUpdateController, stop_event: threading.Event) -> threading.Thread:
    with patch("enshctl.lifecycle.auto_update.parse_cron", return_value=_CHECK_INTERVAL):
        thread = controller.start(stop_event)
        thread.join(timeout=2)
    return thread


def _candidate(manifest_id: str = "222", timestamp: str = "05/29/2026 14:00:00") -> ManifestRecord:
    return ManifestRecord(manifest_id, timestamp)


def _session_with_remote(tracker: PresenceTracker, now: float) -> None:
    tracker.observe("-------------- Session ----------------", now=now)
    tracker.observe("Machines:", now=now)
    tracker.observe(
        "  m#0(128): up 0 (0), down 0 (0), remote 0 (0), limit 256, lost 0, ping 0 ms, OperatingNormally",
        now=now,
    )
    tracker.observe(
        "  m#1(128): up 0 (0), down 0 (0), remote 1 (1), limit 256, lost 0, ping 0 ms, OperatingNormally",
        now=now,
    )
    tracker.observe("----------------------------------------", now=now)


def _assert_gate_blocked(
    setup: Callable[[PresenceTracker], None],
    *,
    stream_healthy: Callable[[], bool] | None = None,
) -> None:
    driver = _Driver(stop_at=105)
    tracker = _tracker()
    _ready(tracker)
    setup(tracker)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=downloaded.append,
        restart_request=restart,
        stream_healthy=stream_healthy,
    )
    thread = _run(controller, threading.Event())
    assert not thread.is_alive()
    assert downloaded == [_candidate()]
    assert restart.event.is_set() is False


def test_auto_update_active_only_for_latest() -> None:
    # GIVEN default, empty, pinned, and disabled Version specs
    # WHEN checking Auto Update activity
    # THEN only latest and empty are active
    assert is_auto_update_active(AppSettings()) is True
    assert is_auto_update_active(replace(AppSettings(), version="")) is True
    assert is_auto_update_active(replace(AppSettings(), version="123")) is False
    assert is_auto_update_active(replace(AppSettings(), auto_update_enabled=False)) is False


def test_first_check_waits_for_the_scheduled_trigger() -> None:
    # GIVEN a controller whose stop time precedes the first schedule tick
    driver = _Driver(stop_at=50)
    tracker = _tracker()
    calls: list[None] = []

    def _list() -> ManifestRecord | None:
        calls.append(None)
        return _candidate()

    controller = _controller(driver, tracker, list_latest=_list, download=lambda _manifest: None)

    # WHEN the controller runs
    thread = _run(controller, threading.Event())

    # THEN no check runs before the first trigger
    assert not thread.is_alive()
    assert calls == []


def test_quiet_window_delays_the_update_check() -> None:
    # GIVEN a held quiet window at the first scheduled check
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    gate = PauseGate()
    assert gate.try_quiet() is True
    check_times: list[float] = []
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()
    released = False

    def _list() -> ManifestRecord | None:
        check_times.append(driver.now)
        return _candidate()

    def _wait(event: threading.Event, timeout: float) -> bool:
        nonlocal released
        result = driver.wait(event, timeout)
        if driver.now >= 150 and not released:
            gate.resume()
            _session(tracker, now=driver.now)
            released = True
        return result

    controller = _controller(
        driver,
        tracker,
        list_latest=_list,
        download=downloaded.append,
        restart_request=restart,
        pause_gate=gate,
        wait=_wait,
    )

    # WHEN the window resumes and the next scheduled check runs
    thread = _run(controller, threading.Event())

    # THEN the check starts only after the window ends
    assert not thread.is_alive()
    assert check_times == [200.0]
    assert downloaded == [_candidate()]
    assert restart.event.is_set() is True


def test_newer_manifest_downloads_and_restarts_when_empty() -> None:
    # GIVEN an empty ready server with recent local-only Session evidence
    driver = _Driver(stop_at=150)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=downloaded.append,
        restart_request=restart,
    )

    # WHEN the controller checks and the gate is clear
    thread = _run(controller, threading.Event())

    # THEN the candidate downloads and requests a restart
    assert not thread.is_alive()
    assert downloaded == [_candidate()]
    assert restart.event.is_set()


def test_players_delay_restart_and_warnings_repeat(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a player is online when the update downloads
    driver = _Driver(stop_at=350)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    tracker.observe("Remote player added. Player handle: 0(0)", now=50)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=downloaded.append,
        restart_request=restart,
    )

    # WHEN several scheduled checks run while the player remains
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN the download happens once, warnings repeat, and no restart occurs
    assert not thread.is_alive()
    assert downloaded == [_candidate()]
    assert restart.event.is_set() is False
    assert sum("is available" in record.message for record in caplog.records) >= 3


def test_log_only_warns_without_download_or_restart(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN log-only mode with an available update
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=downloaded.append,
        restart_request=restart,
        settings=_settings(auto_update_log_only=True),
    )

    # WHEN scheduled checks run
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN warnings repeat without download or restart
    assert not thread.is_alive()
    assert downloaded == []
    assert restart.event.is_set() is False
    assert sum("is available" in record.message for record in caplog.records) >= 2


def test_download_failure_retries_at_the_next_check(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a download that fails once and then succeeds
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()

    def _download(manifest: ManifestRecord) -> None:
        downloaded.append(manifest)
        if len(downloaded) == 1:
            msg = "network failed"
            raise OSError(msg)

    refreshed = False

    def _wait(event: threading.Event, timeout: float) -> bool:
        nonlocal refreshed
        result = driver.wait(event, timeout)
        if driver.now >= 150 and not refreshed:
            _session(tracker, now=driver.now)
            refreshed = True
        return result

    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=_download,
        restart_request=restart,
        wait=_wait,
    )

    # WHEN the first download fails
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN the next check retries and the restart eventually happens
    assert not thread.is_alive()
    assert downloaded == [_candidate(), _candidate()]
    assert restart.event.is_set() is True
    assert "download of manifest 222 failed" in caplog.text


def test_check_failure_retries_at_the_next_check() -> None:
    # GIVEN a listing that fails once and then returns a candidate
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    calls = 0
    restart = RestartRequest()

    def _list() -> ManifestRecord | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            msg = "listing failed"
            raise OSError(msg)
        return _candidate()

    refreshed = False

    def _wait(event: threading.Event, timeout: float) -> bool:
        nonlocal refreshed
        result = driver.wait(event, timeout)
        if driver.now >= 150 and not refreshed:
            _session(tracker, now=driver.now)
            refreshed = True
        return result

    controller = _controller(
        driver,
        tracker,
        list_latest=_list,
        download=lambda _manifest: None,
        restart_request=restart,
        wait=_wait,
    )

    # WHEN the first check fails
    thread = _run(controller, threading.Event())

    # THEN the next check retries and requests the restart
    assert not thread.is_alive()
    assert calls >= 2
    assert restart.event.is_set() is True


def test_deferred_download_waits_for_the_empty_gate() -> None:
    # GIVEN deferred downloads and a player who leaves at 180 seconds
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=0)
    tracker.observe("Remote player added. Player handle: 0(0)", now=0)
    released = False

    def _wait(event: threading.Event, timeout: float) -> bool:
        nonlocal released
        result = driver.wait(event, timeout)
        if driver.now >= 180 and not released:
            tracker.observe("Player removed. Player handle: 0(0)", now=driver.now)
            _session(tracker, now=driver.now)
            released = True
        return result

    download_times: list[float] = []
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=lambda _manifest: download_times.append(driver.now),
        restart_request=restart,
        settings=_settings(auto_update_download_only_when_empty=True),
        wait=_wait,
    )

    # WHEN the controller runs through the player departure
    thread = _run(controller, threading.Event())

    # THEN the download starts only after the gate clears
    assert not thread.is_alive()
    assert len(download_times) == 1
    assert download_times[0] >= 180
    assert restart.event.is_set() is True


def test_paused_tree_waives_the_session_block() -> None:
    # GIVEN a paused, ready server with no Session evidence
    driver = _Driver(stop_at=150)
    tracker = _tracker()
    _ready(tracker)
    restart = RestartRequest()
    downloaded: list[ManifestRecord] = []
    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=downloaded.append,
        restart_request=restart,
        is_paused=lambda: True,
    )

    # WHEN the controller checks
    thread = _run(controller, threading.Event())

    # THEN the stale Session block does not block the restart
    assert not thread.is_alive()
    assert downloaded == [_candidate()]
    assert restart.event.is_set() is True


def test_pending_join_blocks_the_restart() -> None:
    # GIVEN an unexpired pending join
    def _setup(tracker: PresenceTracker) -> None:
        _session(tracker, now=50)
        tracker.observe("Session accepted with peer (steamid:123)", now=50)

    # WHEN the controller checks
    _assert_gate_blocked(_setup)


def test_stale_session_block_blocks_the_restart() -> None:
    # GIVEN a Session block older than the staleness bound
    _assert_gate_blocked(lambda tracker: _session(tracker, now=0))


def test_remote_machine_blocks_the_restart() -> None:
    # GIVEN a Session block with a remote machine entry
    _assert_gate_blocked(lambda tracker: _session_with_remote(tracker, now=50))


def test_ended_stream_blocks_the_restart() -> None:
    # GIVEN a stdout stream that has ended
    _assert_gate_blocked(lambda tracker: _session(tracker, now=50), stream_healthy=lambda: False)


def test_older_candidate_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a listed candidate older than the Active Manifest
    driver = _Driver(stop_at=150)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        list_latest=lambda: _candidate(timestamp="05/28/2026 12:00:00"),
        download=downloaded.append,
        restart_request=restart,
    )

    # WHEN the controller checks
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN the older candidate is ignored
    assert not thread.is_alive()
    assert downloaded == []
    assert restart.event.is_set() is False
    assert "is available" not in caplog.text


def test_unknown_active_timestamp_warns_and_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN an Active Manifest without a recorded timestamp
    driver = _Driver(stop_at=150)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    restart = RestartRequest()
    controller = _controller(
        driver,
        tracker,
        active=ManifestRecord("111", ""),
        list_latest=_candidate,
        download=lambda _manifest: None,
        restart_request=restart,
    )

    # WHEN the controller checks
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN it warns and does not update
    assert not thread.is_alive()
    assert "cannot compare Manifest timestamps" in caplog.text
    assert restart.event.is_set() is False


def test_newer_candidate_supersedes_the_pending_target(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a pending target and a later listing newer than that target
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    tracker.observe("Remote player added. Player handle: 0(0)", now=50)
    pending = _candidate("222", "05/29/2026 14:00:00")
    newer = _candidate("444", "05/29/2026 15:00:00")
    calls = 0
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()

    def _list() -> ManifestRecord | None:
        nonlocal calls
        calls += 1
        return pending if calls == 1 else newer

    controller = _controller(
        driver,
        tracker,
        list_latest=_list,
        download=downloaded.append,
        restart_request=restart,
    )

    # WHEN the second check lists the newer candidate
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN both targets download and the warning moves to the newer ID
    assert not thread.is_alive()
    assert downloaded == [pending, newer]
    assert restart.event.is_set() is False
    assert "manifest 444 is available" in caplog.text


def test_players_join_during_a_deferred_download() -> None:
    # GIVEN a deferred download that starts on an empty server
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()

    def _download(manifest: ManifestRecord) -> None:
        downloaded.append(manifest)
        tracker.observe("Remote player added. Player handle: 0(0)", now=driver.now)

    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=_download,
        restart_request=restart,
        settings=_settings(auto_update_download_only_when_empty=True),
    )

    # WHEN a player joins while the download is in progress
    thread = _run(controller, threading.Event())

    # THEN the server keeps running and the restart waits
    assert not thread.is_alive()
    assert downloaded == [_candidate()]
    assert restart.event.is_set() is False


def test_shutdown_during_a_download_does_not_restart() -> None:
    # GIVEN a download that observes shutdown while in progress
    driver = _Driver(stop_at=500)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    stop = threading.Event()
    restart = RestartRequest()
    downloaded: list[ManifestRecord] = []

    def _download(manifest: ManifestRecord) -> None:
        downloaded.append(manifest)
        stop.set()

    controller = _controller(
        driver,
        tracker,
        list_latest=_candidate,
        download=_download,
        restart_request=restart,
    )

    # WHEN the controller runs through the download
    thread = _run(controller, stop)

    # THEN it exits without requesting a restart
    assert not thread.is_alive()
    assert downloaded == [_candidate()]
    assert restart.event.is_set() is False


def test_regressed_candidate_keeps_the_pending_target(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a pending target and a later listing older than that target
    driver = _Driver(stop_at=250)
    tracker = _tracker()
    _ready(tracker)
    _session(tracker, now=50)
    tracker.observe("Remote player added. Player handle: 0(0)", now=50)
    pending = _candidate("222", "05/29/2026 14:00:00")
    regressed = _candidate("333", "05/29/2026 13:00:00")
    calls = 0
    downloaded: list[ManifestRecord] = []
    restart = RestartRequest()

    def _list() -> ManifestRecord | None:
        nonlocal calls
        calls += 1
        return pending if calls == 1 else regressed

    controller = _controller(
        driver,
        tracker,
        list_latest=_list,
        download=downloaded.append,
        restart_request=restart,
    )

    # WHEN the second check lists the older candidate
    with caplog.at_level(logging.WARNING, logger="enshctl.lifecycle.auto_update"):
        thread = _run(controller, threading.Event())

    # THEN the pending target remains and the warning names it
    assert not thread.is_alive()
    assert downloaded == [pending]
    assert restart.event.is_set() is False
    assert "manifest 222 is available" in caplog.text
