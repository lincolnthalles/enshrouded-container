"""Tests for backup child execution through injected seams."""

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from enshctl.backup.category import Category
from enshctl.backup.format import BackupFormat
from enshctl.backup.run import BackupSeams, lower_priority, run_request
from enshctl.backup_protocol import BackupOutcome, BackupRequest
from enshctl.config import SaveDirectories
from enshctl.disk_space import SpaceGuard
from enshctl.paths import SAVE_DIR
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.backup.core import BackupPlan


class FakeLock:
    def __init__(self, results: list[int | None] | None = None) -> None:
        self._results = iter(results if results is not None else [3])
        self.acquired: list[Path] = []
        self.released: list[int] = []

    def acquire(self, path: Path) -> int | None:
        self.acquired.append(path)
        return next(self._results)

    def release(self, fd: int) -> None:
        self.released.append(fd)


class FakeClock:
    def __init__(self, times: list[float]) -> None:
        self._times = iter(times)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return next(self._times)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class FakeCreator:
    def __init__(self, result: Path | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[Category, BackupPlan, SpaceGuard]] = []

    def __call__(self, category: Category, plan: BackupPlan, *, space: SpaceGuard) -> Path | None:
        self.calls.append((category, plan, space))
        if self.error is not None:
            raise self.error
        return self.result


def _seams(
    *,
    lock: FakeLock | None = None,
    clock: FakeClock | None = None,
    saves_dir: Path = Path("/data/saves"),
    resolve_saves_dir: Callable[[AppSettings], Path] | None = None,
    create: FakeCreator | None = None,
    lower_priority: Callable[[], None] | None = None,
) -> BackupSeams:
    return BackupSeams(
        lock=lock or FakeLock(),
        clock=clock or FakeClock([0.0]),
        space_guard=SpaceGuard(),
        resolve_saves_dir=resolve_saves_dir or (lambda _settings: saves_dir),
        create_backup=create or FakeCreator(),
        lower_priority=lower_priority or (lambda: None),
    )


def _make_backup_file(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"backup")
    return path


def test_run_request_locks_plans_and_creates(tmp_path: Path) -> None:
    # GIVEN a request carrying compression options and injected seams
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    saves = tmp_path / "saves"
    lock = FakeLock()
    create = FakeCreator()
    priority: list[bool] = []
    seams = _seams(
        lock=lock,
        saves_dir=saves,
        create=create,
        lower_priority=lambda: priority.append(True),
    )

    # WHEN running the request
    result = run_request(BackupRequest(category=Category.COLD, fmt="gzip", level=5), settings, seams=seams)

    # THEN it lowers priority, locks, builds the plan, and releases the lock
    assert result == BackupOutcome.SUCCESS
    assert priority == [True]
    assert lock.acquired == [tmp_path / "backups" / ".lock"]
    assert lock.released == [3]
    assert len(create.calls) == 1
    category, plan, space_guard = create.calls[0]
    assert category is Category.COLD
    assert plan.saves_dir == saves
    assert plan.fmt is BackupFormat.GZIP
    assert plan.level == 5
    assert space_guard is seams.space_guard


def test_run_request_prefers_request_saves_dir(tmp_path: Path) -> None:
    # GIVEN a request carrying a resolved Save directory and a fallback resolver
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    saves = tmp_path / "resolved" / "saves"
    resolved: list[AppSettings] = []

    def resolve_fallback(settings: AppSettings) -> Path:
        resolved.append(settings)
        return tmp_path / "fallback" / "saves"

    create = FakeCreator()
    seams = _seams(create=create, resolve_saves_dir=resolve_fallback)

    # WHEN running the request
    result = run_request(BackupRequest(saves_dir=saves), settings, seams=seams)

    # THEN the request value reaches the plan and the fallback is skipped
    assert result == BackupOutcome.SUCCESS
    _category, plan, _space = create.calls[0]
    assert plan.saves_dir == saves
    assert resolved == []


def test_run_request_rejects_unsafe_request_saves_dir(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a request whose Save directory is the filesystem root
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    create = FakeCreator()
    seams = _seams(create=create)

    # WHEN running the request
    with caplog.at_level("WARNING", logger="enshctl.config"):
        result = run_request(BackupRequest(saves_dir=Path("/")), settings, seams=seams)

    # THEN the guarded default Save directory reaches the plan
    assert result == BackupOutcome.SUCCESS
    _category, plan, _space = create.calls[0]
    assert plan.saves_dir == SAVE_DIR
    assert any("Backup request Save directory" in record.message for record in caplog.records)
    assert any("overlaps protected path" in record.message for record in caplog.records)


def test_run_request_reports_lock_held_without_creating(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a lock that is already held and no wait budget
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    create = FakeCreator()
    seams = _seams(lock=FakeLock([None]), create=create)

    with caplog.at_level(logging.INFO, logger="enshctl.backup.run"):
        # WHEN running the request
        result = run_request(BackupRequest(), settings, seams=seams)

    # THEN it reports lock-held without creating a Backup
    assert result == BackupOutcome.LOCK_HELD
    assert create.calls == []
    assert "Lock held by another process" in caplog.text


def test_run_request_wait_expiry_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a lock held past the wait budget
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    clock = FakeClock([0.0, 0.0, 2.0])
    lock = FakeLock([None, None])
    seams = _seams(lock=lock, clock=clock)

    with caplog.at_level(logging.WARNING, logger="enshctl.backup.run"):
        # WHEN the wait budget expires
        result = run_request(BackupRequest(wait_seconds=1), settings, seams=seams)

    # THEN it re-checks the lock, reports lock-held, and warns with the waited seconds
    assert result == BackupOutcome.LOCK_HELD
    assert len(lock.acquired) == 2
    assert clock.sleeps == [1]
    assert "after 1s wait" in caplog.text


def test_run_request_acquires_lock_after_waiting(tmp_path: Path) -> None:
    # GIVEN a lock that becomes available after one wait interval
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    clock = FakeClock([0.0, 0.0])
    lock = FakeLock([None, 3])
    create = FakeCreator()
    seams = _seams(lock=lock, clock=clock, create=create)

    # WHEN the request waits and retries the lock
    result = run_request(BackupRequest(wait_seconds=1), settings, seams=seams)

    # THEN it proceeds with creation and releases the acquired lock
    assert result == BackupOutcome.SUCCESS
    assert len(lock.acquired) == 2
    assert clock.sleeps == [1]
    assert len(create.calls) == 1
    assert lock.released == [3]


def test_run_request_prunes_after_success(tmp_path: Path) -> None:
    # GIVEN older Backups in every Category and a keep-last-one policy
    backup_dir = tmp_path / "backups"
    live = backup_dir / "live"
    older = _make_backup_file(live, "enshrouded-20260501-120000.tar.zst")
    newer = _make_backup_file(live, "enshrouded-20260502-120000.tar.zst")
    cold = _make_backup_file(backup_dir / "cold", "enshrouded-20260501-120000-cold.tar.zst")
    emergency = _make_backup_file(
        backup_dir / "emergency",
        "enshrouded-20260501-120000-emergency.tar.zst",
    )
    settings = replace(AppSettings(), backup_dir=str(backup_dir), backup_keep_last=1)
    create = FakeCreator(result=newer)
    seams = _seams(create=create)

    # WHEN a live Backup completes successfully
    result = run_request(BackupRequest(), settings, seams=seams)

    # THEN retention runs only on the live Category
    assert result == BackupOutcome.SUCCESS
    assert not older.exists()
    assert newer.exists()
    assert cold.exists()
    assert emergency.exists()


def test_run_request_skips_prune_when_backup_is_skipped(tmp_path: Path) -> None:
    # GIVEN a keep-last-one policy and a creation step that skips
    backup_dir = tmp_path / "backups"
    live = backup_dir / "live"
    older = _make_backup_file(live, "enshrouded-20260501-120000.tar.zst")
    newer = _make_backup_file(live, "enshrouded-20260502-120000.tar.zst")
    settings = replace(AppSettings(), backup_dir=str(backup_dir), backup_keep_last=1)
    seams = _seams(create=FakeCreator(result=None))

    # WHEN the Backup is skipped
    result = run_request(BackupRequest(), settings, seams=seams)

    # THEN retention does not run
    assert result == BackupOutcome.SUCCESS
    assert older.exists()
    assert newer.exists()


def test_run_request_reports_error_and_skips_prune(tmp_path: Path) -> None:
    # GIVEN a keep-last-one policy and a creation step that raises a value error
    backup_dir = tmp_path / "backups"
    live = backup_dir / "live"
    older = _make_backup_file(live, "enshrouded-20260501-120000.tar.zst")
    _make_backup_file(live, "enshrouded-20260502-120000.tar.zst")
    settings = replace(AppSettings(), backup_dir=str(backup_dir), backup_keep_last=1)
    lock = FakeLock()
    seams = _seams(lock=lock, create=FakeCreator(error=ValueError("bad level")))

    # WHEN the request runs
    result = run_request(BackupRequest(), settings, seams=seams)

    # THEN the error is reported, the lock is released, and retention does not run
    assert result == BackupOutcome.ERROR
    assert lock.released == [3]
    assert older.exists()


def test_backup_command_passes_compression_options(tmp_path: Path) -> None:
    import enshctl.commands.backup as command

    # GIVEN CLI compression flags and a fake creation seam
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    create = FakeCreator()
    # WHEN the backup command runs
    code = command.run(settings, ["--format", "gzip", "--level", "5"], seams=_seams(create=create))

    # THEN the parsed options reach the Backup plan
    assert code == int(BackupOutcome.SUCCESS)
    assert len(create.calls) == 1
    plan = create.calls[0][1]
    assert plan.fmt is BackupFormat.GZIP
    assert plan.level == 5


def test_backup_command_rejects_unknown_format() -> None:
    import enshctl.commands.backup as command

    # GIVEN an unknown --format value
    with pytest.raises(SystemExit) as exc_info:
        # WHEN the backup command parses it
        command.run(AppSettings(), ["--format", "lz4"])

    # THEN the parser exit code propagates
    assert exc_info.value.code == 2


def test_default_saves_dir_uses_generated_config() -> None:
    # GIVEN a Generated config resolving to a save directory
    settings = AppSettings()
    expected = Path("/mnt/nfs/saves")

    with patch("enshctl.backup.run.generated_save_directories", return_value=SaveDirectories(expected)) as mock:
        # WHEN the default save-dir seam resolves the settings
        result = BackupSeams().resolve_saves_dir(settings)

    # THEN it delegates to the Generated config resolver
    assert result == expected
    mock.assert_called_once_with(settings=settings)


def test_lower_priority_sets_nice_and_ionice() -> None:
    import enshctl.backup.run as run_module

    run_module._priority_state["warned"] = False
    with (
        patch("enshctl.backup.run.nice") as mock_nice,
        patch("enshctl.backup.run.subprocess.run") as mock_run,
    ):
        # WHEN lowering backup priority
        lower_priority()

    # THEN CPU and IO priority are both lowered
    mock_nice.assert_called_once_with(19)
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0][:2] == ["ionice", "-c3"]


def test_lower_priority_warns_once_per_run(caplog: pytest.LogCaptureFixture) -> None:
    import enshctl.backup.run as run_module

    run_module._priority_state["warned"] = False
    with (
        patch("enshctl.backup.run.nice", side_effect=OSError),
        patch("enshctl.backup.run.subprocess.run", side_effect=OSError),
        caplog.at_level(logging.DEBUG, logger="enshctl.backup.run"),
    ):
        # WHEN both priority-lowering attempts fail across two runs
        lower_priority()
        lower_priority()

    # THEN only the first failure warns; the rest stay below warning level
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "CPU priority" in warnings[0].message


def test_lower_priority_warns_when_ionice_fails(caplog: pytest.LogCaptureFixture) -> None:
    import enshctl.backup.run as run_module

    run_module._priority_state["warned"] = False
    with (
        patch("enshctl.backup.run.nice"),
        patch("enshctl.backup.run.subprocess.run", side_effect=OSError),
        caplog.at_level(logging.WARNING, logger="enshctl.backup.run"),
    ):
        # WHEN CPU priority succeeds but IO priority fails
        lower_priority()

    # THEN the IO failure is warned
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "ionice" in warnings[0].message
