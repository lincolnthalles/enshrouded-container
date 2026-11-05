"""Tests for connected-player tracking."""

from dataclasses import FrozenInstanceError

import pytest
from enshctl.presence import (
    MAX_HANDLES,
    MAX_NAME_LENGTH,
    MAX_PARSED_LINE,
    Player,
    PlayerJoined,
    PlayerLeft,
    PresenceSnapshot,
    PresenceTracker,
    PresenceWarning,
)

_ADD = "[I 00:00:01,000] [session] Remote player added. Player handle: {handle}"
_MACHINE = "[I 00:00:02,000] [server] Machine '1': Player '{handle}' logged in"
_NAME = "[I 00:00:03,000] [server] Player '{name}' logged in with Permissions:"
_REMOVE_ENTITY = "[I 00:00:04,000] [server] Remove Entity for Player '{name}'"
_REMOVE_PLAYER = "[I 00:00:04,100] [server] Remove Player '{name}'"
_CLEAN_LOGOUT = (
    "[W 00:00:04,200] [session] Remove player from session. Not found in online game info. Player Handle: {handle}"
)
_REMOVED = "[I 00:00:04,300] [session] Player removed. Player handle: {handle}"


def _add(handle: str) -> str:
    return _ADD.format(handle=handle)


def _machine(handle: str) -> str:
    return _MACHINE.format(handle=handle)


def _name(name: str) -> str:
    return _NAME.format(name=name)


def _removed(handle: str) -> str:
    return _REMOVED.format(handle=handle)


def test_add_and_name_tracks_named_player() -> None:
    # GIVEN a tracker and the verified join sequence
    tracker = PresenceTracker()

    # WHEN the add, machine, and name lines are observed
    add_events = tracker.observe(_add("0(0)"), now=0)
    machine_events = tracker.observe(_machine("0(0)"), now=1)
    name_events = tracker.observe(_name("Morgan"), now=2)

    # THEN one join is reported and the roster holds the named player
    assert add_events == (PlayerJoined("0(0)"),)
    assert machine_events == ()
    assert name_events == ()
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Morgan"),))


def test_machine_line_adds_a_missed_handle() -> None:
    # GIVEN a tracker that never saw the remote-player add line
    tracker = PresenceTracker()

    # WHEN the machine login line is observed
    events = tracker.observe(_machine("0(0)"), now=0)

    # THEN the handle is added and reported
    assert events == (PlayerJoined("0(0)"),)
    assert tracker.snapshot().handles == frozenset({"0(0)"})


def test_logout_sequence_removes_only_on_player_removed() -> None:
    # GIVEN a named player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_name("Morgan"), now=1)

    # WHEN the full verified logout sequence arrives
    entity_events = tracker.observe(_REMOVE_ENTITY.format(name="Morgan"), now=2)
    player_events = tracker.observe(_REMOVE_PLAYER.format(name="Morgan"), now=3)
    warning_events = tracker.observe(_CLEAN_LOGOUT.format(handle="0(0)"), now=4)

    # THEN the removal-adjacent lines are neutral
    assert entity_events == ()
    assert player_events == ()
    assert warning_events == ()
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Morgan"),))

    # AND only the session removal deletes
    removed_events = tracker.observe(_removed("0(0)"), now=5)
    assert removed_events == (PlayerLeft("0(0)", "Morgan"),)
    assert tracker.snapshot().is_empty is True


def test_player_removed_removes_and_reports_leave() -> None:
    # GIVEN a named player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_name("Morgan"), now=1)

    # WHEN the session removal line arrives
    events = tracker.observe(_removed("0(0)"), now=2)

    # THEN the leave is reported with the attached name
    assert events == (PlayerLeft("0(0)", "Morgan"),)
    assert tracker.snapshot().is_empty is True


def test_clean_logout_warning_is_neutral() -> None:
    # GIVEN a tracked player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN the clean-logout warning is observed
    events = tracker.observe(_CLEAN_LOGOUT.format(handle="0(0)"), now=1)

    # THEN presence is unchanged
    assert events == ()
    assert tracker.snapshot().handles == frozenset({"0(0)"})


def test_duplicate_add_and_machine_line_are_idempotent() -> None:
    # GIVEN a tracked player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN the add and machine lines are observed again
    duplicate_add = tracker.observe(_add("0(0)"), now=1)
    duplicate_machine = tracker.observe(_machine("0(0)"), now=2)

    # THEN no duplicate player is added
    assert duplicate_add == ()
    assert duplicate_machine == ()
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)"),))


def test_unknown_removal_warns_without_changing_roster() -> None:
    # GIVEN a tracked player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN an unknown handle is removed
    events = tracker.observe(_removed("0(9)"), now=1)

    # THEN a warning is emitted and the roster is unchanged
    assert events == (PresenceWarning("Player removed for unknown handle 0(9)"),)
    assert tracker.snapshot().handles == frozenset({"0(0)"})


def test_peer_lines_are_not_players() -> None:
    # GIVEN a tracker
    tracker = PresenceTracker()

    # WHEN the session and peer lines are observed
    events = [
        tracker.observe("[I 00:00:01,000] [online] Session accepted with peer (steamid:99999999999999999)", now=0),
        tracker.observe("[I 00:00:01,100] [online] Added peer 0(1) (steamid:99999999999999999)", now=1),
        tracker.observe("[I 00:00:01,200] [online] Client '99999999999999999' authenticated by steam", now=2),
        tracker.observe("[I 00:00:01,300] [online] Disconnecting peer 0(2)", now=3),
    ]

    # THEN no player is tracked
    assert events == [(), (), (), ()]
    assert tracker.snapshot().is_empty is True


def test_separate_connections_are_not_conflated() -> None:
    # GIVEN one connection that has already left
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_removed("0(0)"), now=1)

    # WHEN a later connection adds a different session suffix
    tracker.observe(_add("0(1)"), now=2)

    # THEN only the later connection is present
    assert tracker.snapshot().handles == frozenset({"0(1)"})


def test_names_pair_in_login_order() -> None:
    # GIVEN two handles awaiting names
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_add("0(1)"), now=1)

    # WHEN the name lines arrive in the same order
    tracker.observe(_name("Alice"), now=2)
    tracker.observe(_name("Bob"), now=3)

    # THEN the roster pairs Alice and Bob in first-add order
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Alice"), Player("0(1)", "Bob")))


def test_duplicate_name_candidate_does_not_mispair() -> None:
    # GIVEN one handle seen by both the add and machine lines
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_machine("0(0)"), now=1)

    # WHEN two name lines arrive
    tracker.observe(_name("Alice"), now=2)
    events = tracker.observe(_name("Bob"), now=3)

    # THEN the extra name is rejected rather than renaming the handle
    assert events == (PresenceWarning("Player name 'Bob' has no unnamed handle"),)
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Alice"),))


def test_name_queue_overflow_uses_oldest_unnamed_fallback() -> None:
    # GIVEN more unnamed handles than the name queue can hold
    tracker = PresenceTracker()
    warnings: list[PresenceWarning] = []
    for index in range(17):
        events = tracker.observe(_add(f"0({index})"), now=float(index))
        warnings.extend(event for event in events if isinstance(event, PresenceWarning))

    # WHEN the unqueued handle is seen again and all names arrive in first-add order
    duplicate_events = tracker.observe(_machine("0(16)"), now=99.0)
    for index in range(17):
        tracker.observe(_name(f"P{index}"), now=100.0 + float(index))

    # THEN the overflow warning is reported once and every handle is named
    assert duplicate_events == ()
    assert warnings == [PresenceWarning("Name pairing queue full; 0(16) will use the unnamed fallback")]
    assert tracker.snapshot() == PresenceSnapshot(tuple(Player(f"0({index})", f"P{index}") for index in range(17)))


def test_name_cannot_spoof_an_add_line() -> None:
    # GIVEN a tracked handle
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN the name text contains a valid add-line phrase
    events = tracker.observe(_name("Remote player added. Player handle: 0(1)"), now=1)

    # THEN the text is treated as a name, not a second player
    assert events == ()
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Remote player added. Player handle: 0(1)"),))


def test_name_cannot_spoof_a_removal_line() -> None:
    # GIVEN a named player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_name("Morgan"), now=1)

    # WHEN a removal-adjacent line carries a player-controlled name containing a removal phrase
    events = tracker.observe(_REMOVE_ENTITY.format(name="Player removed. Player handle: 0(0)"), now=2)

    # THEN presence is unchanged
    assert events == ()
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Morgan"),))


def test_removed_handle_does_not_consume_a_name() -> None:
    # GIVEN an unnamed handle that leaves before being named
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_removed("0(0)"), now=1)

    # WHEN a later handle is added and named
    tracker.observe(_add("0(1)"), now=2)
    tracker.observe(_name("Alice"), now=3)

    # THEN the later handle receives the name
    assert tracker.snapshot() == PresenceSnapshot((Player("0(1)", "Alice"),))


def test_expired_handle_does_not_consume_a_name() -> None:
    # GIVEN an unnamed handle that expires before being named
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.expire(now=300)

    # WHEN a later handle is added and named
    tracker.observe(_add("0(1)"), now=301)
    tracker.observe(_name("Alice"), now=302)

    # THEN the later handle receives the name
    assert tracker.snapshot() == PresenceSnapshot((Player("0(1)", "Alice"),))


def test_empty_name_does_not_consume_a_name() -> None:
    # GIVEN an unnamed handle
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN a whitespace-only name is followed by a real name
    empty_events = tracker.observe(_name("   "), now=1)
    tracker.observe(_name("Alice"), now=2)

    # THEN the empty name is warned about and the real name is attached
    assert empty_events == (PresenceWarning("Ignoring empty player name"),)
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Alice"),))


def test_name_line_without_unnamed_handle_warns() -> None:
    # GIVEN an empty roster
    tracker = PresenceTracker()

    # WHEN a name line arrives
    events = tracker.observe(_name("Alice"), now=0)

    # THEN the roster is unchanged and the warning is reported
    assert events == (PresenceWarning("Player name 'Alice' has no unnamed handle"),)
    assert tracker.snapshot().is_empty is True


def test_handle_cap_warns_once_per_full_episode() -> None:
    # GIVEN a tracker filled to the handle cap
    tracker = PresenceTracker()
    for index in range(MAX_HANDLES):
        tracker.observe(_add(f"0({index})"), now=float(index))

    # WHEN one more handle is added
    events = tracker.observe(_add(f"0({MAX_HANDLES})"), now=100.0)

    # THEN one cap warning is reported and the roster stays bounded
    assert events == (PresenceWarning(f"Player handle cap reached; ignoring 0({MAX_HANDLES})"),)
    assert len(tracker.snapshot().players) == MAX_HANDLES
    assert tracker.observe(_add("0(999)"), now=101.0) == ()

    # AND a new episode warns again after the roster shrinks and refills
    tracker.observe(_removed("0(0)"), now=102.0)
    tracker.observe(_add("0(0)"), now=103.0)
    second_events = tracker.observe(_add("0(1000)"), now=104.0)
    assert second_events == (PresenceWarning("Player handle cap reached; ignoring 0(1000)"),)


def test_unnamed_handle_expires_without_a_left_line() -> None:
    # GIVEN an unnamed handle added at time zero
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN the grace period has not elapsed
    assert tracker.expire(now=299.9) == ()
    assert len(tracker.snapshot().players) == 1

    # THEN the next expiry tick removes it with a warning and no leave event
    events = tracker.expire(now=300)
    assert events == (PresenceWarning("Unnamed player handle 0(0) expired after 300s"),)
    assert tracker.snapshot().is_empty is True


def test_parsed_line_triggers_expiry_before_its_events() -> None:
    # GIVEN an unnamed handle that is due to expire
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN an unrelated parsed line arrives after the grace period
    events = tracker.observe("[I 00:05:00,000] [ecss] Stats: Upd:1", now=300)

    # THEN expiry is reported before the line's own (empty) events
    assert events == (PresenceWarning("Unnamed player handle 0(0) expired after 300s"),)
    assert tracker.snapshot().is_empty is True


def test_named_handle_does_not_expire() -> None:
    # GIVEN a named player
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    tracker.observe(_name("Morgan"), now=1)

    # WHEN a long time passes
    events = tracker.expire(now=10_000)

    # THEN the player is still present
    assert events == ()
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "Morgan"),))


def test_overlong_line_is_ignored_and_does_not_trigger_expiry() -> None:
    # GIVEN an unnamed handle that is due to expire
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN an overlong line arrives after the grace period
    overlong = "x" * MAX_PARSED_LINE + _add("0(1)")
    events = tracker.observe(overlong, now=400)

    # THEN the line is ignored and expiry is not evaluated
    assert events == ()
    assert tracker.snapshot().handles == frozenset({"0(0)"})


def test_line_at_the_parse_limit_is_accepted() -> None:
    # GIVEN a line exactly at the parse limit with a valid prefix and add message
    message = "Remote player added. Player handle: 0(0)"
    base = f"[] [session] {message}"
    padding = MAX_PARSED_LINE - len(base)
    line = f"[{'x' * padding}] [session] {message}"
    assert len(line) == MAX_PARSED_LINE
    tracker = PresenceTracker()

    # WHEN the boundary line is observed
    events = tracker.observe(line, now=0)

    # THEN the handle is added
    assert events == (PlayerJoined("0(0)"),)


def test_apostrophe_in_name_is_preserved() -> None:
    # GIVEN an unnamed handle
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN a name containing an apostrophe arrives
    tracker.observe(_name("O'Brien"), now=1)

    # THEN the full name is attached
    assert tracker.snapshot() == PresenceSnapshot((Player("0(0)", "O'Brien"),))


def test_name_is_sanitized_and_truncated() -> None:
    # GIVEN an unnamed handle
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)

    # WHEN C0, DEL, C1, and an overlong name arrive
    tracker.observe(_name("\x01\x7f\x9f" + "a" * 100), now=1)

    # THEN all control characters are replaced and the name is capped
    player = tracker.snapshot().players[0]
    assert player.name is not None
    assert player.name.startswith("???")
    assert len(player.name) == MAX_NAME_LENGTH


def test_snapshot_is_immutable() -> None:
    # GIVEN a snapshot
    tracker = PresenceTracker()
    tracker.observe(_add("0(0)"), now=0)
    snapshot = tracker.snapshot()

    # WHEN attempting to mutate the snapshot
    with pytest.raises(FrozenInstanceError):
        snapshot.players = ()  # type: ignore[misc]

    # THEN the original value is unchanged
    assert snapshot == PresenceSnapshot((Player("0(0)"),))
