"""Quiet-window gate between Auto Pause and non-essential background work."""

import threading

_WAIT_SLICE = 1.0


class PauseGate:
    """Admit non-essential work only while no Auto Pause quiet window is held."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0
        self._quiet = False

    @property
    def is_quiet(self) -> bool:
        with self._condition:
            return self._quiet

    def acquire(self, stop_event: threading.Event) -> bool:
        """Admit one unit of work, or return False while quiet or stopping."""
        with self._condition:
            if self._quiet or stop_event.is_set():
                return False
            self._active += 1
            return True

    def acquire_ignoring_quiet(self, stop_event: threading.Event) -> bool:
        """Admit work that must proceed while quiet, or return False when stopping."""
        with self._condition:
            if stop_event.is_set():
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._condition:
            if self._active == 0:
                msg = "PauseGate release without acquire"
                raise RuntimeError(msg)
            self._active -= 1
            self._condition.notify_all()

    def try_quiet(self) -> bool:
        """Start a quiet window only when no admitted work is in flight."""
        with self._condition:
            if self._active > 0:
                return False
            self._quiet = True
            return True

    def resume(self) -> None:
        with self._condition:
            self._quiet = False
            self._condition.notify_all()

    def wait_until_running(self, stop_event: threading.Event) -> bool:
        """Block until the quiet window ends; return False when stopping first."""
        with self._condition:
            while self._quiet and not stop_event.is_set():
                self._condition.wait(timeout=_WAIT_SLICE)
            return not self._quiet and not stop_event.is_set()
