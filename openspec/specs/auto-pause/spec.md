# auto-pause Specification

## Purpose

Suspend the whole Wine tree when the server is idle and no player evidence remains, then resume it
on client traffic or operator control.

## Requirements

### Requirement: Automatic pause enablement

Auto Pause SHALL be opt-in via `AUTO_PAUSE_ENABLED` (default false). When enabled, it SHALL wait
for the world-ready marker before considering a pause. `AUTO_PAUSE_IDLE_TIMEOUT` SHALL default to
300 seconds and SHALL accept integers. A negative value SHALL clamp to 0; a non-integer value SHALL
fall back to 300. A timeout of 0 SHALL disable automatic pauses while leaving manual pause
available.

#### Scenario: Disabled by default

- **WHEN** the server runs with no Auto Pause settings
- **THEN** it SHALL remain running after the default idle period
- **AND** `autopause status` SHALL report an unavailable controller

#### Scenario: Ready marker is required

- **WHEN** Auto Pause is enabled and the world-ready marker has not appeared
- **THEN** no pause SHALL occur even after the idle timeout
- **AND** a pause SHALL become eligible only after the marker appears and the idle timeout expires

#### Scenario: Zero timeout disables automatic pause

- **WHEN** `AUTO_PAUSE_IDLE_TIMEOUT=0` and no player is connected
- **THEN** no automatic pause SHALL occur
- **AND** an explicit `autopause pause` SHALL still be eligible

### Requirement: Activity evidence

Auto Pause SHALL reset the idle timer when a `Session accepted`, Steam authentication, `Remote
player added`, machine login, player name, `Remove Entity`, `Player removed`, world-ready, or
positive A2S result is observed. It SHALL also reset the timer when a complete Session block
contains an `m#N` with `N>0`. A complete Session block containing only `m#0`, an A2S zero result,
or an A2S timeout SHALL NOT reset the timer.

#### Scenario: Player activity resets the timer

- **WHEN** the idle timeout is 60 seconds and a player joins, is named, and leaves 50 seconds after
  the previous activity
- **THEN** the next pause SHALL NOT occur until 60 seconds after the leave

#### Scenario: Remote machine entry resets the timer

- **WHEN** the idle timeout is 60 seconds and a complete Session block reports an `m#N` entry with
  `N>0` 50 seconds after the previous activity
- **THEN** the next pause SHALL NOT occur until 60 seconds after that block

#### Scenario: Periodic empty block does not reset the timer

- **WHEN** the only new output is a complete Session block that still contains only `m#0`
- **THEN** the idle timer SHALL continue from the last player activity
- **AND** the block SHALL NOT be treated as player activity

### Requirement: Pending join evidence

A `Session accepted` or Steam authentication line SHALL open or extend a 60-second pending-join
window. A `Remote player added`, machine login, or player name line SHALL clear it. A removal line
SHALL NOT clear an unrelated pending join. Expiry SHALL log a warning and SHALL clear the window.

#### Scenario: Pending join opens and clears

- **WHEN** stdout contains `Session accepted with peer` and then a `Remote player added` line
- **THEN** `status.json` SHALL report a pending join after the first line
- **AND** it SHALL report no pending join after the second line

#### Scenario: Unrelated removal does not clear a pending join

- **WHEN** an existing player leaves while a second client has an open pending-join window
- **THEN** `status.json` SHALL still report a pending join
- **AND** no pause SHALL occur until the window clears or expires

#### Scenario: Pending join expires

- **WHEN** a pending-join window opens and no clearing line arrives within 60 seconds
- **THEN** `status.json` SHALL report no pending join after the window expires
- **AND** a warning SHALL be logged

### Requirement: World-ready evidence

A `Switching state from LoadEcsScene to Run` line SHALL mark the world ready and start the idle
timer. Lines before that marker SHALL NOT start the idle timer.

#### Scenario: Ready marker starts the timer

- **WHEN** the world-ready marker appears and no player is connected
- **THEN** the idle timer SHALL start at that moment
- **AND** no pause SHALL be attempted before the marker

### Requirement: Session machine evidence

The latest complete Session block SHALL be the empty-server evidence. `m#0` SHALL be the local
baseline. `remote N` SHALL be ignored. A block that starts but does not close within 90 seconds
SHALL be malformed. A pause SHALL require a complete block at most 90 seconds old, not malformed,
containing only `m#0`.

#### Scenario: Remote machine vetoes

- **WHEN** the latest complete Session block contains `m#1`
- **THEN** no pause SHALL occur
- **AND** `status.json` SHALL report a session veto
- **AND** the `remote N` value SHALL NOT affect the veto

#### Scenario: Empty block clears the veto

- **WHEN** the latest complete Session block contains only `m#0`
- **THEN** `status.json` SHALL report no session veto
- **AND** Auto Pause SHALL have the required empty-server evidence

#### Scenario: Missing or stale block vetoes

- **WHEN** no complete Session block exists, or the latest one is older than 90 seconds
- **THEN** no pause SHALL occur
- **AND** a throttled warning SHALL explain the missing evidence

#### Scenario: Open block becomes malformed

- **WHEN** a Session block starts and has not closed 90 seconds later
- **THEN** no pause SHALL occur
- **AND** `status.json` SHALL report a session veto
- **AND** a warning SHALL be logged

### Requirement: Presence vetoes

A pause SHALL require an empty active handle set, no pending-join window, a healthy stdout stream,
and no tracker degradation. A handle marked leaving SHALL count as active. A rejected distinct
handle at the 64-handle cap SHALL mark presence degraded until the roster shrinks below the cap.

#### Scenario: Pending join blocks a pause

- **WHEN** a `Session accepted` line opens the pending-join window and the idle timeout expires
- **THEN** no pause SHALL occur
- **AND** `status.json` SHALL report a pending join

#### Scenario: Player handle blocks a pause

- **WHEN** a player handle is active and the idle timeout expires
- **THEN** no pause SHALL occur
- **AND** the idle timer SHALL be reset

#### Scenario: Leaving handle still blocks a pause

- **WHEN** `Remove Entity for Player '<name>'` has marked a handle leaving and `Player removed` has
  not arrived
- **THEN** no pause SHALL occur
- **AND** the idle timer SHALL reset on the leave transition

#### Scenario: Tracker degradation blocks a pause

- **WHEN** the handle cap rejects a distinct handle and the idle timeout expires
- **THEN** no pause SHALL occur
- **AND** `status.json` SHALL report a degraded tracker
- **AND** a throttled warning SHALL explain the degraded tracker

#### Scenario: Recovered roster clears degradation

- **WHEN** the roster shrinks below 64 handles after a cap rejection
- **THEN** the degraded veto SHALL clear
- **AND** a later idle period SHALL be eligible for a pause

### Requirement: A2S advisory veto

Auto Pause SHALL query `A2S_INFO` through the query endpoint resolved by `config-management`. A
positive player count SHALL veto a pause and reset the idle timer. Zero or timeout SHALL be neutral
and SHALL NOT clear handles or confirm an empty server. An unresolved endpoint SHALL prevent a
pause and report A2S as unavailable.

#### Scenario: Positive A2S count keeps the server running

- **WHEN** automatic pause is eligible and A2S reports one player
- **THEN** no pause SHALL occur
- **AND** the idle timer SHALL reset

#### Scenario: A2S zero does not bypass the tracker

- **WHEN** A2S reports zero players while the tracker still holds a handle
- **THEN** no pause SHALL occur
- **AND** the handle SHALL remain tracked

#### Scenario: A2S timeout is neutral

- **WHEN** A2S times out with no other veto present
- **THEN** the pause decision SHALL continue using log-derived evidence
- **AND** a throttled warning SHALL be logged

#### Scenario: Unresolved endpoint prevents pause

- **WHEN** `ip` or `queryPort` cannot be resolved from the Generated config
- **THEN** no pause SHALL occur
- **AND** `status.json` SHALL report A2S as unavailable

### Requirement: Save quiescence

A pause SHALL observe a new top-level `*.ksd` signature from the same save directory used by Backup
and Restore (see `save-management`), wait 2 seconds, then re-stat size and mtime. If either changed,
it SHALL wait for the next save. No new save within 60 seconds or no save file SHALL skip the pause
with a warning. A forced pause SHALL ignore new player activity during the wait; tracker
degradation, the `disabled` marker, or shutdown SHALL still abort it.

#### Scenario: Stable save permits pause

- **WHEN** a pause is pending and a top-level `*.ksd` file changes, then remains unchanged for 2
  seconds
- **THEN** the save gate SHALL pass
- **AND** the pause SHALL continue to the final veto checks

#### Scenario: Changing save waits for the next one

- **WHEN** the save size or mtime changes during the 2-second settle window
- **THEN** the pause SHALL wait for the next save
- **AND** the server SHALL remain running

#### Scenario: No new save skips the pause

- **WHEN** no top-level `*.ksd` signature changes within 60 seconds
- **THEN** that pause attempt SHALL be skipped with a warning
- **AND** a later idle period SHALL retry

#### Scenario: Player activity aborts an automatic save wait

- **WHEN** a player handle appears while an automatic pause is waiting for save quiescence
- **THEN** the pending pause SHALL abort
- **AND** the idle timer SHALL reset

#### Scenario: Forced pause ignores new activity

- **WHEN** a player appears while a forced pause is waiting for save quiescence
- **THEN** the save wait SHALL continue
- **AND** the eventual pause SHALL include the new player

#### Scenario: Disable aborts the save wait

- **WHEN** the `disabled` marker appears while a pause is waiting for save quiescence
- **THEN** the pending pause SHALL abort
- **AND** no `paused` marker SHALL be written

#### Scenario: Status heartbeat continues during save wait

- **WHEN** the save gate waits for a new save
- **THEN** `status.json` SHALL be refreshed at least every 5 seconds
- **AND** `autopause status` SHALL remain live during the wait

### Requirement: Save re-stat before suspension

Auto Pause SHALL re-stat the same save signature after the final A2S probe and immediately before
suspension. A changed size or mtime SHALL wait for the next save.

#### Scenario: Save changes during the final probe

- **WHEN** the save size or mtime changes after the settle window but before suspension
- **THEN** the pause SHALL wait for the next save
- **AND** the server SHALL remain running

### Requirement: Whole-tree suspension and resume

A pause SHALL `SIGSTOP` the game first and matching Wine services second, verify every PID is
stopped, and write the `paused` marker only after verification. A failed verification SHALL
`SIGCONT` the whole tree, log an error, and leave the server running. Resume SHALL `SIGCONT`
services first and the game second, verify no matching PID remains stopped, retry once, and log an
error if the tree still shows stopped processes.

#### Scenario: Successful suspension

- **WHEN** the final veto checks pass and the wake source is armed
- **THEN** the game and matching Wine services SHALL enter the stopped state
- **AND** the `paused` marker SHALL appear only after every PID is verified stopped

#### Scenario: Verification failure rolls back

- **WHEN** one Wine PID is not stopped within 2 seconds of the suspend attempt
- **THEN** the whole tree SHALL receive `SIGCONT`
- **AND** no `paused` marker SHALL be written
- **AND** an error SHALL be logged

#### Scenario: Resume verifies the tree

- **WHEN** the server resumes from a pause
- **THEN** services and the game SHALL receive `SIGCONT`
- **AND** no matching PID SHALL remain stopped
- **AND** a failed verification SHALL retry once and log an error

### Requirement: Pause transition guards

A pause SHALL re-check the `disabled` marker and every veto not explicitly bypassed by `pause
--force` immediately before arming the wake source. After arming, it SHALL run the final A2S probe
and save re-stat before suspending; an abort SHALL close the wake source and write no `paused`
marker. A shutdown latch SHALL prevent a new pause from starting or completing.

#### Scenario: Final A2S self-reply does not wake

- **WHEN** a pause reaches the final veto checks with the wake source armed
- **THEN** outgoing probe traffic and its reply SHALL NOT create a wake event
- **AND** a later client packet to the query port SHALL still wake the server

#### Scenario: Disable during the final guard aborts

- **WHEN** the `disabled` marker appears immediately before the suspend
- **THEN** the pause SHALL abort
- **AND** no `paused` marker SHALL be written

#### Scenario: Shutdown latches out a pause

- **WHEN** shutdown begins while a pause is waiting for save quiescence
- **THEN** the pause SHALL abort
- **AND** no `paused` marker SHALL be written

### Requirement: Wake source

While paused, Auto Pause SHALL resume on accepted wake traffic or a resume request. Default wake
SHALL accept any IPv4 or IPv6 UDP packet to the query port; `ignore-a2s` SHALL accept other traffic
while ignoring A2S request magic. `AF_PACKET` SHALL be preferred; queue polling SHALL be the
fallback. The queue fallback SHALL refuse `ignore-a2s` because it cannot classify payloads. If no
wake source is available, a pause SHALL be prevented.

#### Scenario: Direct-IP query wakes the server

- **WHEN** the server is paused and a client sends its pre-join A2S query to the query port
- **THEN** the tree SHALL resume
- **AND** the queued query SHALL remain available to the game

#### Scenario: Ignore-A2S filters the query

- **WHEN** `AUTO_PAUSE_WAKE_FILTER=ignore-a2s` and only an A2S query arrives
- **THEN** the server SHALL remain paused
- **AND** other UDP traffic SHALL still resume it

#### Scenario: Queue fallback refuses ignore-A2S

- **WHEN** only the queue fallback is available and the filter is `ignore-a2s`
- **THEN** no pause SHALL occur
- **AND** a warning SHALL explain that the filter cannot be honored

#### Scenario: No wake source prevents pause

- **WHEN** neither packet capture nor queue polling can be opened
- **THEN** no pause SHALL occur
- **AND** a warning SHALL be logged

### Requirement: Wake arming window

Auto Pause SHALL arm the wake source before the final A2S probe and save re-stat so a pre-join
packet in that window is retained. Outgoing probe traffic SHALL be ignored.

#### Scenario: Packet in the arming window is retained

- **WHEN** a client packet reaches the query port after the wake source is armed and before
  `SIGSTOP` completes
- **THEN** the paused controller SHALL observe it
- **AND** the server SHALL resume instead of discarding the event

### Requirement: Manual pause

`autopause pause` SHALL use the same gate and SHALL refuse when a player is online. `pause --force`
SHALL bypass pending-join, handle, Session-table, and A2S vetoes only; enabled state, no `disabled`
marker, world-ready marker, healthy stdout stream, non-degraded tracker, save gate, wake source, and
clear stop latch SHALL still apply. The command SHALL warn that a forced pause can freeze connected
players.

#### Scenario: Manual pause refuses a player

- **WHEN** a player is online and the operator runs `autopause pause`
- **THEN** no pause SHALL occur
- **AND** the command SHALL report a refusal

#### Scenario: Force pause bypasses presence only

- **WHEN** a player is online and the operator runs `autopause pause --force`
- **THEN** the presence vetoes SHALL be bypassed
- **AND** enabled state, no `disabled` marker, world-ready marker, healthy stream, non-degraded
  tracker, save gate, wake source, and clear stop latch SHALL still be required
- **AND** the command SHALL warn that connected players may be frozen

### Requirement: Reset and resume

`autopause reset` SHALL clear handles and Session evidence. `resume` when not paused SHALL reset the
idle timer and report success.

#### Scenario: Reset refuses a populated roster

- **WHEN** the status reports an active player and the operator runs `autopause reset` without
  `--yes`
- **THEN** no handles SHALL be cleared
- **AND** the command SHALL report a refusal

#### Scenario: Reset clears evidence

- **WHEN** the operator runs `autopause reset --yes`
- **THEN** the active handles and Session evidence SHALL be cleared
- **AND** the next pause SHALL require a fresh complete Session block containing only `m#0`

#### Scenario: Resume when already active

- **WHEN** the server is not paused and the operator runs `autopause resume`
- **THEN** the idle timer SHALL reset
- **AND** the command SHALL report success

### Requirement: Disable and enable

`autopause disable` SHALL write a persistent `disabled` marker and block automatic pauses. A live
controller SHALL resume a paused tree when the marker appears; without a live controller, startup
and exit resume own a leftover tree. `autopause enable` SHALL remove the marker and return a
healthy controller to waiting for readiness or active. Both commands SHALL work without a live
controller.

#### Scenario: Disable pauses automatic control

- **WHEN** the operator runs `autopause disable`
- **THEN** no automatic pause SHALL occur
- **AND** a live controller SHALL resume a paused tree

#### Scenario: Enable restores automatic control

- **WHEN** the operator runs `autopause enable` on a healthy controller
- **THEN** the `disabled` marker SHALL be removed
- **AND** the controller SHALL return to waiting for readiness or active

### Requirement: Runtime status

`status.json` SHALL report state, players, pending join, session veto, degraded tracker, paused
since, last error, wake filter, A2S state, last request token, last result, `updated_at`, and
controller PID. The controller SHALL refresh status at least every 5 seconds. Writes SHALL be
atomic and owned by `PUID`/`PGID`. Startup SHALL resume a leftover stopped tree and clear `paused`,
`request`, and `status.json` while preserving `disabled`.

#### Scenario: Status heartbeat is live

- **WHEN** the controller has written `status.json` within 15 seconds and its PID is running
- **THEN** `autopause status` SHALL report the current state and exit successfully

#### Scenario: Stale status is rejected

- **WHEN** `status.json` is older than 15 seconds or its controller PID is gone
- **THEN** `autopause status` SHALL report stale state and exit with the unavailable code

#### Scenario: Startup clears transient state

- **WHEN** the container starts with `paused`, `request`, and `status.json` left from a crash
- **THEN** those files SHALL be removed
- **AND** a leftover stopped tree SHALL be resumed
- **AND** a `disabled` marker SHALL be preserved

### Requirement: Controller request handling

The controller SHALL check the request file at least every 1 second in every state, including
during the save wait. On consumption it SHALL write the token and a pending result before acting,
then update the terminal result. A request SHALL expire after 5 seconds and SHALL be ignored after
expiry.

#### Scenario: Request token is correlated

- **WHEN** the CLI writes a tokenized request and the controller consumes it
- **THEN** `status.json` SHALL report that token with a pending, applied, or refused result
- **AND** the request file SHALL be deleted after consumption

#### Scenario: Request is checked during save wait

- **WHEN** the controller is waiting for save quiescence
- **THEN** a resume or disable request SHALL be observed within 1 second
- **AND** the save wait SHALL abort

#### Scenario: Expired request is ignored

- **WHEN** a request file remains after its 5-second lifetime
- **THEN** the controller SHALL ignore it
- **AND** no pause or resume SHALL occur from that request

### Requirement: Controller failure isolation

A controller failure SHALL set `last_error` and resume a paused tree. A stdout stream that ends
SHALL prevent a pause; if it ends while paused, Auto Pause SHALL resume and stay disabled for that
run without writing the persistent `disabled` marker. The run-scoped latch SHALL NOT be cleared by
`autopause enable`; only a restart SHALL clear it.

#### Scenario: Controller failure resumes

- **WHEN** the controller fails while the tree is paused
- **THEN** the tree SHALL receive `SIGCONT`
- **AND** `last_error` SHALL describe the failure

#### Scenario: Stream end before pause prevents suspension

- **WHEN** the stdout stream ends before a pause
- **THEN** no pause SHALL occur
- **AND** the controller SHALL log the lost stream

#### Scenario: Stream end while paused resumes

- **WHEN** the stdout stream ends while the tree is paused
- **THEN** the tree SHALL receive `SIGCONT`
- **AND** the controller SHALL stay disabled for that run
- **AND** the persistent `disabled` marker SHALL NOT be written

#### Scenario: Enable does not clear the run latch

- **WHEN** the stream-ended run latch is active and the operator runs `autopause enable`
- **THEN** the persistent marker SHALL be removed
- **AND** the run-scoped disabled latch SHALL remain until restart

### Requirement: Auto Pause settings

`AUTO_PAUSE_ENABLED` SHALL parse booleans and default to false. `AUTO_PAUSE_WAKE_FILTER` SHALL
default to `any`; `ignore-a2s` SHALL be opt-in; any other value SHALL fall back to `any` with a
warning. An invalid boolean SHALL use the default.

#### Scenario: Invalid wake filter falls back

- **WHEN** `AUTO_PAUSE_WAKE_FILTER` is not `any` or `ignore-a2s`
- **THEN** wake SHALL use `any`
- **AND** a warning SHALL name the discarded value

#### Scenario: Invalid idle timeout falls back

- **WHEN** `AUTO_PAUSE_IDLE_TIMEOUT` is not an integer
- **THEN** the timeout SHALL be 300 seconds

#### Scenario: Negative idle timeout clamps

- **WHEN** `AUTO_PAUSE_IDLE_TIMEOUT` is a negative integer
- **THEN** the timeout SHALL be 0
- **AND** automatic pauses SHALL be disabled
