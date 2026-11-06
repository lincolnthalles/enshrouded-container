"""Tests for the Auto Pause controller state machine."""

import threading
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, override

from enshctl.config import QueryEndpoint
from enshctl.lifecycle.autopause import AutoPauseController
from enshctl.lifecycle.control import AutoPauseStatus, ControlFiles
from enshctl.lifecycle.pause_gate import PauseGate
from enshctl.lifecycle.saves import SaveSignature
from enshctl.lifecycle.wake import WakeEvent
from enshctl.presence import MAX_SESSION_MACHINES, PresenceTracker
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


class _Driver:
    def __init__(self, stop_at: float, on_wait: Callable[[], None] | None = None) -> None:
        self.now = 0.0
        self.stop_at = stop_at
        self.on_wait = on_wait

    def clock(self) -> float:
        return self.now

    def wall_clock(self) -> float:
        return 1_000.0 + self.now

    def wait(self, event: threading.Event, timeout: float) -> bool:
        if self.on_wait is not None:
            self.on_wait()
        self.now += timeout
        if self.now >= self.stop_at:
            event.set()
            return True
        return False


class _Process:
    def __init__(self, *, suspend_error: Exception | None = None, resume_result: bool = True) -> None:
        self.suspended = 0
        self.resumed = 0
        self.suspend_error = suspend_error
        self.resume_result = resume_result

    def suspend_all(self) -> bool:
        if self.suspend_error is not None:
            raise self.suspend_error
        self.suspended += 1
        return True

    def resume_all(self) -> bool:
        self.resumed += 1
        return self.resume_result


class _Wake:
    def __init__(self) -> None:
        self.armed = 0
        self.closed = 0
        self.event: WakeEvent | None = None
        self.ignored_source_endpoints: list[frozenset[tuple[str, int]] | None] = []

    def arm(self) -> bool:
        self.armed += 1
        return True

    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None:
        self.ignored_source_endpoints.append(endpoints)

    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None:
        del stop_event, timeout
        event = self.event
        self.event = None
        return event

    def close(self) -> None:
        self.closed += 1


class _A2S:
    def __init__(self, players: int | None) -> None:
        self.result = players
        self.last_local_endpoints = frozenset({("127.0.0.1", 50000)})

    def players(self) -> int | None:
        return self.result


class _ActivityA2S(_A2S):
    def __init__(self, tracker: PresenceTracker, clock: Callable[[], float]) -> None:
        super().__init__(0)
        self.tracker = tracker
        self.clock = clock
        self.calls = 0

    @override
    def players(self) -> int | None:
        self.calls += 1
        if self.calls == 2:
            now = self.clock()
            self.tracker.observe("[I 00:00:00,000] [session] Remote player added. Player handle: 0(8)", now=now)
            self.tracker.observe("[I 00:00:00,100] [session] Player removed. Player handle: 0(8)", now=now)
        return self.result


class _SaveProbe:
    def __init__(self, signatures: list[SaveSignature]) -> None:
        self.signatures = signatures
        self.index = 0

    def __call__(self, _saves_dir: Path) -> SaveSignature | None:
        index = min(self.index, len(self.signatures) - 1)
        self.index += 1
        return self.signatures[index]


class _ActivitySaveProbe:
    def __init__(self, tracker: PresenceTracker, clock: Callable[[], float]) -> None:
        self.tracker = tracker
        self.clock = clock
        self.calls = 0

    def __call__(self, _saves_dir: Path) -> SaveSignature | None:
        self.calls += 1
        if self.calls == 2:
            now = self.clock()
            self.tracker.observe("[I 00:00:00,000] [session] Remote player added. Player handle: 0(9)", now=now)
            self.tracker.observe("[I 00:00:00,100] [session] Player removed. Player handle: 0(9)", now=now)
            return _NEW_SAVE
        return _NEW_SAVE if self.calls > 2 else _OLD_SAVE


_OLD_SAVE = SaveSignature(Path("/tmp/world.ksd"), 10, 1_000)
_NEW_SAVE = SaveSignature(Path("/tmp/world.ksd"), 12, 2_000)
_SAVE_SEQUENCE = [_OLD_SAVE, _OLD_SAVE, _NEW_SAVE, _NEW_SAVE, _NEW_SAVE]


def _settings() -> AppSettings:
    return replace(
        AppSettings(),
        auto_pause_enabled=True,
        auto_pause_idle_timeout=2,
        auto_pause_wake_filter="any",
    )


def _tracker(driver: _Driver) -> PresenceTracker:
    return PresenceTracker(clock=driver.clock)


def _ready(tracker: PresenceTracker) -> None:
    tracker.observe("[game_server] Switching state from LoadEcsScene to Run after 495.18 ms", now=0)


def _session_machine(index: int) -> str:
    return f"  m#{index}(128): up 0 (0), down 0 (0), remote 0 (0), limit 256, lost 0, ping 0 ms, OperatingNormally"


def _empty_session(tracker: PresenceTracker) -> None:
    tracker.observe("-------------- Session ----------------", now=0)
    tracker.observe("Machines:", now=0)
    tracker.observe(_session_machine(0), now=0)
    tracker.observe("----------------------------------------", now=0)


def _controller(
    *,
    tmp_path: Path,
    driver: _Driver,
    tracker: PresenceTracker,
    process: _Process,
    control: ControlFiles,
    wake: _Wake,
    a2s: _A2S | None = None,
    stream_healthy: Callable[[], bool] = lambda: True,
    save_probe: Callable[[Path], SaveSignature | None] | None = None,
    settings: AppSettings | None = None,
    pause_gate: PauseGate | None = None,
) -> AutoPauseController:
    return AutoPauseController(
        settings=settings or _settings(),
        tracker=tracker,
        process_control=process,
        control_files=control,
        saves_dir=tmp_path,
        query_endpoint=QueryEndpoint("127.0.0.1", 15637),
        a2s=a2s or _A2S(0),
        wake_source=wake,
        pause_gate=pause_gate or PauseGate(),
        stream_healthy=stream_healthy,
        clock=driver.clock,
        wall_clock=driver.wall_clock,
        wait=driver.wait,
        save_probe=save_probe or _SaveProbe(_SAVE_SEQUENCE),
        pid=42,
    )


def _run(controller: AutoPauseController, driver: _Driver) -> None:
    thread = controller.start(threading.Event())
    thread.join(timeout=3)
    assert thread.is_alive() is False


def test_automatic_pause_suspends_after_idle(tmp_path: Path) -> None:
    # GIVEN a ready empty server with a stable save
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    wake = _Wake()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    gate = PauseGate()
    controller = _controller(
        tmp_path=tmp_path,
        driver=driver,
        tracker=tracker,
        process=process,
        control=control,
        wake=wake,
        pause_gate=gate,
    )

    # WHEN the controller passes the idle timeout
    _run(controller, driver)

    # THEN the tree is suspended and the pause marker exists
    assert process.suspended == 1
    assert gate.is_quiet is True
    assert wake.ignored_source_endpoints[-1] == frozenset({("127.0.0.1", 50000)})
    assert control.is_paused() is True
    assert control.read_status() is not None
    assert control.read_status().state == "paused"  # type: ignore[union-attr]

    # AND shutdown resume is idempotent
    controller.resume_for_shutdown()
    assert process.resumed >= 1
    assert gate.is_quiet is False
    assert control.is_paused() is False


def test_pause_waits_for_background_work(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN a ready empty server and a held unit of background work
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    statuses: list[tuple[float, str]] = []
    original_write_status = ControlFiles.write_status

    def _record(control_files: ControlFiles, status: AutoPauseStatus) -> None:
        statuses.append((driver.now, status.state))
        original_write_status(control_files, status)

    monkeypatch.setattr(ControlFiles, "write_status", _record)
    gate = PauseGate()
    assert gate.acquire(threading.Event()) is True
    released = False
    refusal: list[AutoPauseStatus] = []

    def _finish_work() -> None:
        nonlocal released
        if not released and not refusal and driver.now >= 3:
            status = control.read_status()
            if status is not None:
                refusal.append(status)
        if driver.now >= 4 and not released:
            gate.release()
            released = True

    driver.on_wait = _finish_work

    # WHEN the controller passes the idle timeout while the work runs
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=control,
                wake=_Wake(),
                pause_gate=gate,
            ),
            driver,
        )

    # THEN the pause is refused until the work finishes and then proceeds without a new idle timeout
    assert process.suspended == 1
    assert "background work in progress" in caplog.text
    assert refusal[0].state == "active"
    assert refusal[0].last_error is None
    first_pending = next(timestamp for timestamp, state in statuses if state == "pause-pending")
    assert first_pending == 5.0
    assert gate.is_quiet is True


def test_manual_pause_refused_while_background_work_runs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for action in ("pause", "pause-force"):
        # GIVEN a ready empty server, held background work, and a manual pause request
        driver = _Driver(stop_at=10)
        tracker = _tracker(driver)
        _ready(tracker)
        _empty_session(tracker)
        process = _Process()
        control = ControlFiles(root=tmp_path, puid=0, pgid=0)
        control.write_request(action, f"{action}-token", now=1_000.0)
        gate = PauseGate()
        assert gate.acquire(threading.Event()) is True

        # WHEN the controller consumes the request
        with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
            _run(
                _controller(
                    tmp_path=tmp_path,
                    driver=driver,
                    tracker=tracker,
                    process=process,
                    control=control,
                    wake=_Wake(),
                    pause_gate=gate,
                ),
                driver,
            )

        # THEN the pause is refused and no suspend attempt is made
        gate.release()
        assert process.suspended == 0
        assert "background work in progress" in caplog.text
        status = control.read_status()
        assert status is not None
        assert status.state == "active"
        assert status.last_error is None
        assert status.last_result == "refused"
        caplog.clear()


def test_aborted_pause_ends_quiet_window(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a ready empty server whose save never changes
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    gate = PauseGate()

    # WHEN the pause attempt waits for save quiescence and aborts
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=ControlFiles(root=tmp_path, puid=0, pgid=0),
                wake=_Wake(),
                pause_gate=gate,
                save_probe=_SaveProbe([_OLD_SAVE]),
            ),
            driver,
        )

    # THEN no pause occurs and the quiet window is released
    assert process.suspended == 0
    assert gate.is_quiet is False
    assert "no new save within 60s" in caplog.text


def test_status_heartbeat_continues_during_save_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN a ready empty server whose save never changes during the save wait
    driver = _Driver(stop_at=25)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    statuses: list[AutoPauseStatus] = []
    original_write_status = ControlFiles.write_status

    def _record(control_files: ControlFiles, status: AutoPauseStatus) -> None:
        statuses.append(status)
        original_write_status(control_files, status)

    monkeypatch.setattr(ControlFiles, "write_status", _record)
    settings = replace(_settings(), auto_pause_idle_timeout=1)

    # WHEN the controller waits for a save that never changes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            settings=settings,
            save_probe=_SaveProbe([_OLD_SAVE]),
        ),
        driver,
    )

    # THEN state changes are written immediately and the wait keeps a heartbeat
    assert [status.state for status in statuses[:2]] == ["waiting-for-ready", "active"]
    pending_timestamps = [status.updated_at for status in statuses if status.state == "pause-pending"]
    gaps = [later - earlier for earlier, later in pairwise(pending_timestamps)]
    assert len(pending_timestamps) >= 3
    assert max(gaps) <= 10.0


def test_a2s_positive_veto_keeps_server_awake(tmp_path: Path) -> None:
    # GIVEN a ready empty server and A2S reporting a player
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()

    # WHEN the controller reaches the idle timeout
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=ControlFiles(root=tmp_path, puid=0, pgid=0),
            wake=_Wake(),
            a2s=_A2S(1),
        ),
        driver,
    )

    # THEN no pause occurs
    assert process.suspended == 0


def test_pending_join_vetoes_pause(tmp_path: Path) -> None:
    # GIVEN a ready server with an open pending join
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    tracker.observe("[I 00:00:00,000] [online] Session accepted with peer (steamid:99999999999999999)", now=0)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the idle timeout passes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
        ),
        driver,
    )

    # THEN no pause occurs and status reports the pending join
    assert process.suspended == 0
    assert control.read_status() is not None
    assert control.read_status().pending_join is True  # type: ignore[union-attr]


def test_player_handle_vetoes_pause(tmp_path: Path) -> None:
    # GIVEN a ready server with an active player
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[I 00:00:00,000] [session] Remote player added. Player handle: 0(0)", now=0)
    process = _Process()

    # WHEN the idle timeout passes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=ControlFiles(root=tmp_path, puid=0, pgid=0),
            wake=_Wake(),
        ),
        driver,
    )

    # THEN no pause occurs
    assert process.suspended == 0


def test_missing_session_block_vetoes_pause(tmp_path: Path) -> None:
    # GIVEN a ready server without Session block evidence
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the idle timeout passes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
        ),
        driver,
    )

    # THEN no pause occurs and status reports the session veto
    assert process.suspended == 0
    assert control.read_status() is not None
    assert control.read_status().session_veto is True  # type: ignore[union-attr]


def test_session_machine_cap_vetoes_pause(tmp_path: Path) -> None:
    # GIVEN a ready server with a Session block beyond the machine cap
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("-------------- Session ----------------", now=0)
    for index in range(MAX_SESSION_MACHINES + 1):
        tracker.observe(_session_machine(index), now=0)
    tracker.observe("----------------------------------------", now=0)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the idle timeout passes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
        ),
        driver,
    )

    # THEN no pause occurs and status reports the session veto
    assert process.suspended == 0
    assert control.read_status() is not None
    assert control.read_status().session_veto is True  # type: ignore[union-attr]


def test_enabled_controller_logs_malformed_session_veto(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a ready server with a malformed Session block
    driver = _Driver(stop_at=5)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[session] -------------- Session ----------------", now=0)
    tracker.observe(
        "[session]   m#1(129): up 2 (3), down 2 (3), remote 2 (3), limit 256, lost 0, ping 15 ms, EstablishingBaseline",
        now=0,
    )
    tracker.observe("[session] ----------------------------------------", now=0)
    process = _Process()

    # WHEN the controller runs
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=ControlFiles(root=tmp_path, puid=0, pgid=0),
                wake=_Wake(),
            ),
            driver,
        )

    # THEN the enabled controller names the veto
    assert "session block malformed" in caplog.text


def test_controller_logs_pending_join_expiry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a ready server with a pending join that will expire
    driver = _Driver(stop_at=65)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[online] Session accepted with peer (steamid:99999999999999999)", now=0)
    process = _Process()
    settings = replace(_settings(), auto_pause_idle_timeout=300)

    # WHEN the controller reaches the expiry
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=ControlFiles(root=tmp_path, puid=0, pgid=0),
                wake=_Wake(),
                settings=settings,
            ),
            driver,
        )

    # THEN the controller logs the expiry
    assert "pending player join expired" in caplog.text


def test_completed_join_before_deadline_does_not_log_expiry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a pending join and a completed join just before the deadline
    driver = _Driver(stop_at=65)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[online] Session accepted with peer (steamid:99999999999999999)", now=0)

    def _join_before_deadline() -> None:
        if driver.now >= 59.0 and tracker.snapshot().pending_join_until is not None:
            tracker.observe("[session] Remote player added. Player handle: 0(0)", now=59.5)

    driver.on_wait = _join_before_deadline
    process = _Process()
    settings = replace(_settings(), auto_pause_idle_timeout=300)

    # WHEN the controller runs past the deadline
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=ControlFiles(root=tmp_path, puid=0, pgid=0),
                wake=_Wake(),
                settings=settings,
            ),
            driver,
        )

    # THEN no false expiry warning is emitted
    assert "pending player join expired" not in caplog.text


def test_paused_controller_does_not_log_session_vetoes(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a paused server whose Session block becomes stale
    driver = _Driver(stop_at=100)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()

    # WHEN the controller remains paused past the Session freshness window
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=ControlFiles(root=tmp_path, puid=0, pgid=0),
                wake=_Wake(),
            ),
            driver,
        )

    # THEN it does not emit a misleading cannot-pause warning while paused
    assert process.suspended == 1
    assert "Auto Pause: cannot pause" not in caplog.text


def test_operator_disabled_controller_is_silent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN Auto Pause is enabled but the operator disabled marker exists
    driver = _Driver(stop_at=5)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[session] -------------- Session ----------------", now=0)
    tracker.observe(
        "[session]   m#1(129): up 2 (3), down 2 (3), remote 2 (3), limit 256, lost 0, ping 15 ms, EstablishingBaseline",
        now=0,
    )
    tracker.observe("[session] ----------------------------------------", now=0)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    control.set_disabled()
    process = _Process()

    # WHEN the controller runs
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=control,
                wake=_Wake(),
            ),
            driver,
        )

    # THEN it does not emit an Auto Pause veto and reports disabled
    assert "Auto Pause: cannot pause" not in caplog.text
    assert control.read_status() is not None
    assert control.read_status().state == "disabled"  # type: ignore[union-attr]


def test_controller_expires_unnamed_handle_with_summaries_disabled(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN roster summaries disabled and an unnamed handle older than the grace period
    driver = _Driver(stop_at=305)
    tracker = _tracker(driver)
    tracker.observe("[session] Remote player added. Player handle: 0(0)", now=0)
    process = _Process()
    settings = replace(
        _settings(),
        player_log=False,
        player_poll_interval=0,
        auto_pause_idle_timeout=600,
    )

    # WHEN the controller maintenance tick reaches the expiry
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.autopause"):
        _run(
            _controller(
                tmp_path=tmp_path,
                driver=driver,
                tracker=tracker,
                process=process,
                control=ControlFiles(root=tmp_path, puid=0, pgid=0),
                wake=_Wake(),
                settings=settings,
            ),
            driver,
        )

    # THEN the handle expires with a warning and no pause
    assert process.suspended == 0
    assert tracker.snapshot().players == ()
    assert "expired after 300s" in caplog.text


def test_degraded_presence_vetoes_pause(tmp_path: Path) -> None:
    # GIVEN a roster that rejected a handle at the cap
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    for index in range(65):
        tracker.observe(f"[I 00:00:00,000] [session] Remote player added. Player handle: 0({index})", now=0)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the idle timeout passes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
        ),
        driver,
    )

    # THEN no pause occurs and status reports degradation
    assert process.suspended == 0
    assert control.read_status() is not None
    assert control.read_status().degraded is True  # type: ignore[union-attr]


def test_stream_end_vetoes_pause(tmp_path: Path) -> None:
    # GIVEN a ready server whose stdout stream has ended
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()

    # WHEN the idle timeout passes
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=ControlFiles(root=tmp_path, puid=0, pgid=0),
            wake=_Wake(),
            stream_healthy=lambda: False,
        ),
        driver,
    )

    # THEN no pause occurs
    assert process.suspended == 0


def test_wake_event_resumes_paused_tree(tmp_path: Path) -> None:
    # GIVEN a controller that pauses and then receives a wake event
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    wake = _Wake()
    wake.event = WakeEvent("192.0.2.1", 40000, 10, "a2s")
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=wake,
        ),
        driver,
    )

    # THEN the tree is resumed after the pause
    assert process.suspended == 1
    assert process.resumed >= 1
    assert control.is_paused() is False


def test_manual_reset_request_clears_roster(tmp_path: Path) -> None:
    # GIVEN a ready server with a player and a queued reset request
    driver = _Driver(stop_at=5)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[I 00:00:00,000] [session] Remote player added. Player handle: 0(0)", now=0)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    control.write_request("reset-force", "reset-token", now=1_000.0)
    process = _Process()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
        ),
        driver,
    )

    # THEN the roster is cleared and the request is applied
    assert tracker.snapshot().players == ()
    assert control.read_status() is not None
    assert control.read_status().last_result == "applied"  # type: ignore[union-attr]


def test_forced_pause_bypasses_pending_join(tmp_path: Path) -> None:
    # GIVEN a ready server with a pending join and a forced pause request
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    tracker.observe("[I 00:00:00,000] [online] Session accepted with peer (steamid:99999999999999999)", now=0)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    control.write_request("pause-force", "force-token", now=1_000.0)
    process = _Process()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
        ),
        driver,
    )

    # THEN the pending join is bypassed and the tree pauses
    assert process.suspended == 1


def test_controller_failure_resumes_tree(tmp_path: Path) -> None:
    # GIVEN a controller whose suspend attempt fails
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process(suspend_error=RuntimeError("suspend failed"))
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    gate = PauseGate()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            pause_gate=gate,
        ),
        driver,
    )

    # THEN the controller recovers by resuming the tree and background work
    assert process.resumed >= 1
    assert gate.is_quiet is False
    assert control.read_status() is not None
    assert control.read_status().last_error == "suspend failed"  # type: ignore[union-attr]


def test_failed_resume_preserves_paused_state(tmp_path: Path) -> None:
    # GIVEN a paused tree whose resume verification fails
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process(resume_result=False)
    wake = _Wake()
    wake.event = WakeEvent("192.0.2.1", 40000, 10, "a2s")
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    gate = PauseGate()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=wake,
            pause_gate=gate,
        ),
        driver,
    )

    # THEN the pause marker, paused state, and quiet window survive
    assert process.suspended == 1
    assert gate.is_quiet is True
    assert control.is_paused() is True
    assert control.read_status() is not None
    assert control.read_status().last_error == "resume verification failed"  # type: ignore[union-attr]


def test_failed_resume_after_disable_preserves_paused_state(tmp_path: Path) -> None:
    # GIVEN a paused tree whose resume fails when the disabled marker appears
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    def _disable() -> None:
        if control.is_paused():
            control.set_disabled()

    driver = _Driver(stop_at=30, on_wait=_disable)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process(resume_result=False)
    gate = PauseGate()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            pause_gate=gate,
        ),
        driver,
    )

    # THEN the paused state, marker, and quiet window survive for a later resume
    assert process.suspended == 1
    assert gate.is_quiet is True
    assert control.is_paused() is True
    assert control.read_status() is not None
    assert control.read_status().state == "paused"  # type: ignore[union-attr]


def test_transient_activity_aborts_save_wait(tmp_path: Path) -> None:
    # GIVEN a tracker that sees a join and leave during the save wait
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the controller waits for a save
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            save_probe=_ActivitySaveProbe(tracker, driver.clock),
        ),
        driver,
    )

    # THEN the transient activity aborts the pause
    assert process.suspended == 0


def test_transient_activity_after_save_wait_aborts_final_guard(tmp_path: Path) -> None:
    # GIVEN a tracker that sees a join and leave during the final A2S probe
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN the controller reaches the final guard
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            a2s=_ActivityA2S(tracker, driver.clock),
        ),
        driver,
    )

    # THEN the transient activity aborts the pause
    assert process.suspended == 0


def test_zero_idle_timeout_disables_automatic_pause(tmp_path: Path) -> None:
    # GIVEN a ready empty server with automatic pause disabled
    driver = _Driver(stop_at=10)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    settings = replace(_settings(), auto_pause_idle_timeout=0)

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=ControlFiles(root=tmp_path, puid=0, pgid=0),
            wake=_Wake(),
            settings=settings,
        ),
        driver,
    )

    # THEN no automatic pause occurs
    assert process.suspended == 0


def test_a2s_timeout_is_neutral_and_allows_pause(tmp_path: Path) -> None:
    # GIVEN a ready empty server whose A2S probe times out
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=ControlFiles(root=tmp_path, puid=0, pgid=0),
            wake=_Wake(),
            a2s=_A2S(None),
        ),
        driver,
    )

    # THEN the pause continues with log-derived evidence
    assert process.suspended == 1


def test_stream_end_while_paused_resumes_and_latches_disabled(tmp_path: Path) -> None:
    # GIVEN a paused tree whose stdout stream ends
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    healthy = True

    def _stop_stream() -> None:
        nonlocal healthy
        if control.is_paused():
            healthy = False

    driver = _Driver(stop_at=30, on_wait=_stop_stream)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    gate = PauseGate()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            stream_healthy=lambda: healthy,
            pause_gate=gate,
        ),
        driver,
    )

    # THEN the tree resumes, the run latch disables Auto Pause, and no marker is written
    assert process.suspended == 1
    assert process.resumed >= 1
    assert gate.is_quiet is False
    assert control.is_disabled() is False
    assert control.read_status() is not None
    assert control.read_status().state == "disabled"  # type: ignore[union-attr]


class _RequestSaveProbe:
    def __init__(self, control: ControlFiles) -> None:
        self.control = control
        self.calls = 0

    def __call__(self, _saves_dir: Path) -> SaveSignature | None:
        self.calls += 1
        if self.calls == 2:
            self.control.write_request("resume", "save-wait-resume", now=1_000.0)
            return _NEW_SAVE
        return _NEW_SAVE if self.calls > 2 else _OLD_SAVE


def test_request_during_save_wait_aborts_pause(tmp_path: Path) -> None:
    # GIVEN a controller whose save wait receives a resume request
    driver = _Driver(stop_at=30)
    tracker = _tracker(driver)
    _ready(tracker)
    _empty_session(tracker)
    process = _Process()
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    gate = PauseGate()

    # WHEN the controller runs
    _run(
        _controller(
            tmp_path=tmp_path,
            driver=driver,
            tracker=tracker,
            process=process,
            control=control,
            wake=_Wake(),
            pause_gate=gate,
            save_probe=_RequestSaveProbe(control),
        ),
        driver,
    )

    # THEN the pause aborts, the request is consumed, and the quiet window ends
    assert process.suspended == 0
    assert gate.is_quiet is False
    assert control.read_status() is not None
    assert control.read_status().last_result == "applied"  # type: ignore[union-attr]
