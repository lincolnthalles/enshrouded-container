# player-presence Specification

## Purpose

Derive the connected-player roster from the dedicated server's stdout and report roster changes
and periodic summaries on the orchestrator console.

## Requirements

### Requirement: Player roster tracking

The container SHALL derive the connected-player set from the dedicated server's stdout. A
`Remote player added. Player handle: <handle>` line SHALL add the handle. A
`Machine '<n>': Player '<handle>' logged in` line SHALL confirm the handle and add it when the
add line was missed.

#### Scenario: Add line adds a player

- **WHEN** stdout contains `Remote player added. Player handle: 0(0)`
- **THEN** a `Player joined: 0(0)` line is logged
- **AND** the next roster summary reports one player

#### Scenario: Machine line confirms a missed add

- **WHEN** stdout contains `Machine '1': Player '0(0)' logged in` without a preceding add line
- **THEN** a `Player joined: 0(0)` line is logged and the roster summary reports one player

### Requirement: Player name pairing

A `Player '<name>' logged in with Permissions:` line SHALL attach the name to the oldest handle
awaiting a name, or to the oldest unnamed handle when none is awaiting. A duplicate add or
machine line SHALL NOT cause a later name to attach to the same handle twice. A name line with no
unnamed handle SHALL leave the roster unchanged and log a warning.

#### Scenario: Names attach in login order

- **WHEN** handles `0(0)` and `0(1)` are added and name lines for Alice and Bob arrive in that
  order
- **THEN** the roster summary is `Players online: 2 - Alice, Bob`

#### Scenario: Duplicate add and machine line do not mispair

- **WHEN** the add line and the machine login line both precede the name line for one handle
- **THEN** the first name is reported for that handle
- **AND** a later name line with no other unnamed handle logs a warning
- **AND** the roster summary still reports only the first name

#### Scenario: Name line without a handle is ignored

- **WHEN** a name line arrives with no unnamed handle
- **THEN** the roster summary is unchanged and a warning is logged

### Requirement: Name pairing bounds

At most 16 handles SHALL await names; a handle beyond that SHALL remain tracked but unnamed until
the fallback. A removed or expired handle SHALL NOT consume a later name.

#### Scenario: More handles than name slots

- **WHEN** 17 handles are added and 17 name lines arrive in first-add order
- **THEN** a warning is logged for the handle that could not be queued for pairing
- **AND** the roster summary lists all 17 names in first-add order

#### Scenario: Removed handle does not consume a name

- **WHEN** an unnamed handle is removed, a later handle is added, and the later handle is named
  Alice
- **THEN** the roster summary is `Players online: 1 - Alice`

#### Scenario: Expired handle does not consume a name

- **WHEN** an unnamed handle expires after 5 minutes, a later handle is added, and the later
  handle is named Alice
- **THEN** the roster summary is `Players online: 1 - Alice`

### Requirement: Player removal lifecycle

`Remove Entity for Player '<name>'` SHALL mark the named handle leaving without changing membership
or logging a leave. `Remove Player '<name>'` and `Remove player from session. Not found in online
game info.` SHALL NOT change presence. `Player removed. Player handle: <handle>` SHALL remove the
handle. A removal for an unknown handle or an `Remove Entity` for an unknown name SHALL be ignored
with a warning.

#### Scenario: Player leaves

- **WHEN** stdout contains `Remove Entity for Player '<name>'` followed by
  `Player removed. Player handle: <handle>`
- **THEN** a `Player left: <name>` line is logged
- **AND** the next roster summary reports zero players

#### Scenario: Remove Entity keeps membership

- **WHEN** stdout contains `Remove Entity for Player '<name>'` without a following `Player removed`
  line
- **THEN** no `Player left` line is logged
- **AND** the roster still reports that player

#### Scenario: Removal-adjacent lines do not remove

- **WHEN** stdout contains `Remove Player '<name>'` without a following `Player removed` line
- **THEN** no `Player left` line is logged
- **AND** the next roster summary still reports the player

#### Scenario: Clean-logout warning is neutral

- **WHEN** stdout contains `Remove player from session. Not found in online game info.` without a
  `Player removed` line
- **THEN** the roster is unchanged

#### Scenario: Unknown removal is ignored

- **WHEN** stdout contains `Player removed. Player handle: <handle>` for a handle that was never
  added
- **THEN** no `Player left` line is logged
- **AND** a warning is logged

#### Scenario: Unknown Remove Entity is ignored

- **WHEN** stdout contains `Remove Entity for Player '<name>'` for a name that is not tracked
- **THEN** the roster is unchanged
- **AND** a warning is logged

### Requirement: Handle identity

Handles SHALL be treated as opaque identifiers for one connection. Peer handles on `[online]`
lines SHALL NOT be treated as player handles. Duplicate adds SHALL be idempotent.

#### Scenario: Duplicate add is idempotent

- **WHEN** stdout contains the same `Remote player added` line twice
- **THEN** only one `Player joined` line is logged
- **AND** the roster summary reports one player

#### Scenario: Separate connections are not conflated

- **WHEN** one connection adds and removes handle `0(0)` and a later connection adds handle `0(1)`
- **THEN** the roster summary reports one player, not a merged or duplicated entry

#### Scenario: Peer line is not a player

- **WHEN** stdout contains `Disconnecting peer 0(2)` without a player add or remove line
- **THEN** the roster is unchanged

### Requirement: Player console output

The container SHALL log `Player joined: <name-or-handle>` when a handle is first added and
`Player left: <name-or-handle>` when `Player removed` deletes a handle. Join and leave lines SHALL
be logged before the next roster summary. It SHALL log `Players online: <count> - <names>` or
`Players online: 0` every `PLAYER_POLL_INTERVAL` seconds. Summaries SHALL list players in order of
first add and SHALL use the handle for unnamed players.

#### Scenario: Join and leave line format

- **WHEN** a player is added before the name line arrives and is later removed by `Player removed`
  after being named
- **THEN** the console contains `Player joined: <handle>` and `Player left: <name>`
- **AND** both lines appear before the next roster summary

#### Scenario: Summary lists names in first-add order

- **WHEN** handles `0(2)` and `0(10)` are online in that order as Alice and Bob
- **THEN** the summary is `Players online: 2 - Alice, Bob`

#### Scenario: Unknown name uses the handle

- **WHEN** a player has been added but no name line has arrived
- **THEN** the join line and roster summary use the handle

#### Scenario: Empty summary

- **WHEN** no players are online at a summary tick
- **THEN** the summary is `Players online: 0`

#### Scenario: Default interval

- **WHEN** no player output settings are provided
- **THEN** roster lines are enabled and the first summary is logged one 60-second interval after
  startup with the server running

### Requirement: Player output level

Player roster lines SHALL be logged at INFO through the orchestrator logger and follow the
existing file-logging level rules (see `orchestrator-file-logging`).

#### Scenario: File logging defaults exclude roster lines

- **WHEN** roster lines are emitted and file logging uses its default WARNING level
- **THEN** the lines appear on the console but not in the orchestrator file

### Requirement: Player name display

The name SHALL be the text between `Player '` and the last `' logged in with Permissions:`, so
apostrophes inside a name are preserved. Names SHALL have surrounding whitespace removed,
characters in Unicode category `Cc` or DEL (U+007F) replaced with `?`, and SHALL be truncated to
64 characters. An empty name after sanitization SHALL leave the handle unnamed, SHALL NOT consume
a name assignment, and SHALL log a warning.

#### Scenario: Names are sanitized and truncated

- **WHEN** a player name contains a control character or exceeds 64 characters
- **THEN** the reported name replaces the control character with `?` and is at most 64 characters
  long

#### Scenario: Apostrophe in name is preserved

- **WHEN** the name line contains `Player 'O'Brien' logged in with Permissions:`
- **THEN** the roster summary reports `O'Brien`

#### Scenario: Empty name keeps the handle

- **WHEN** a handle is added, a whitespace-only name line arrives, and a later real name line
  follows
- **THEN** the roster summary after the first line is `Players online: 1 - 0(0)`
- **AND** the roster summary after the second line is `Players online: 1 - Alice`

### Requirement: Player output controls

`PLAYER_LOG` SHALL default to true and SHALL suppress all player roster lines when false.
`PLAYER_POLL_INTERVAL` SHALL default to 60 seconds and SHALL accept integers. A negative value
SHALL clamp to 0; a non-integer value SHALL fall back to 60. `PLAYER_POLL_INTERVAL=0` SHALL
suppress only the periodic summary; join and leave lines SHALL continue when `PLAYER_LOG` is true.

#### Scenario: Output disabled

- **WHEN** `PLAYER_LOG=false`
- **THEN** no `Player joined`, `Player left`, or `Players online` lines are logged

#### Scenario: Summary disabled

- **WHEN** `PLAYER_LOG=true` and `PLAYER_POLL_INTERVAL=0`
- **THEN** no `Players online` summary is logged
- **AND** join and leave lines are still logged

#### Scenario: Invalid interval falls back

- **WHEN** `PLAYER_POLL_INTERVAL` is not an integer
- **THEN** join and leave lines are still logged
- **AND** the first summary appears one 60-second interval after startup with the server running

#### Scenario: Negative interval disables summaries

- **WHEN** `PLAYER_POLL_INTERVAL` is negative
- **THEN** no `Players online` summary is logged
- **AND** join and leave lines are still logged when `PLAYER_LOG` is true

### Requirement: Bounded presence state

Presence state SHALL be bounded to 64 active handles, 16 handles awaiting names, 64 characters
per name, and 8192 characters per parsed line. Reaching the handle cap SHALL log at most one
warning per full-to-non-full episode and reject further distinct handles while the roster is full.
A rejected handle SHALL NOT log a join. A line longer than 8192 characters SHALL NOT change the
roster or emit a player line.

#### Scenario: Handle cap logs and bounds

- **WHEN** 65 distinct handles are added
- **THEN** one warning is logged and the roster summary reports at most 64 players
- **AND** no `Player joined` line is logged for the rejected handle

#### Scenario: Overlong line is ignored

- **WHEN** a line longer than 8192 characters contains a valid `Remote player added` sequence
- **THEN** no `Player joined` line is logged for that sequence
- **AND** the roster summary is unchanged

### Requirement: Bounded stdout reading

The stdout reader SHALL read each line with a bounded buffer. A line whose content exceeds
32768 bytes SHALL be discarded before presence parsing or full relay, a warning SHALL be logged,
and reading SHALL continue with the next line.

#### Scenario: Overlong stdout line is discarded

- **WHEN** a server stdout line longer than 32768 bytes contains a valid `Remote player added`
  sequence and is followed by a normal line
- **THEN** no `Player joined` line SHALL be logged for the discarded line
- **AND** a warning SHALL be logged
- **AND** the following line SHALL still be relayed and parsed

### Requirement: Unnamed handle expiry

An unnamed handle SHALL be removed after at least 5 minutes without a name, with a warning and
without a `Player left` line. A named handle SHALL NOT expire automatically.

#### Scenario: Unnamed handle expires

- **WHEN** an unnamed handle remains unnamed for at least 5 minutes
- **THEN** an expiry warning is logged
- **AND** no `Player left` line is logged
- **AND** the next roster summary no longer reports that handle

#### Scenario: Expiry continues with summaries disabled

- **WHEN** `PLAYER_LOG=false`, `PLAYER_POLL_INTERVAL=0`, Auto Pause is enabled, and an unnamed
  handle remains unnamed for at least 5 minutes
- **THEN** the handle SHALL be removed with a warning
- **AND** no `Player left` line SHALL be logged

#### Scenario: Named handle does not expire

- **WHEN** a named player remains connected for more than 5 minutes and a summary tick runs
- **THEN** the roster summary still reports the player

### Requirement: Presence diagnostics

Bounded-state warnings SHALL be logged at WARNING even when `PLAYER_LOG` is false. Summary work
SHALL stop when shutdown begins. Player Presence SHALL NOT log Auto Pause policy messages; those
are owned by `auto-pause`.

#### Scenario: Warnings survive output suppression

- **WHEN** `PLAYER_LOG=false` and the handle cap is reached
- **THEN** the cap warning is still logged

#### Scenario: Shutdown stops summary work

- **WHEN** shutdown begins
- **THEN** no further roster summary is logged

#### Scenario: Auto Pause policy messages stay out of presence

- **WHEN** `AUTO_PAUSE_ENABLED=false` and a Session block is malformed
- **THEN** no `Auto Pause:` line SHALL be logged by Player Presence

### Requirement: Presence failure isolation

A failure to derive presence from a line SHALL NOT stop the orchestrator from relaying game
output. The first such failure SHALL be logged as a warning.

#### Scenario: Hook failure does not stop the stream

- **WHEN** one line fails presence derivation and later game lines arrive
- **THEN** the first failure is logged as a warning
- **AND** the later game lines are still relayed

### Requirement: Log envelope normalization

Player Presence SHALL match the same message with zero, one, or two leading bracketed log fields.
The game log-file form `[I ...] [module] message` and the relayed stdout form `[module] message`
SHALL produce the same roster events.

#### Scenario: Module-only stdout prefix is accepted

- **WHEN** stdout contains `[session] Remote player added. Player handle: 0(0)`
- **THEN** a `Player joined: 0(0)` line is logged
- **AND** the next roster summary reports one player

#### Scenario: Timestamped log prefix is accepted

- **WHEN** the same message arrives as `[I 00:00:01,000] [session] Remote player added. Player
  handle: 0(0)`
- **THEN** a `Player joined: 0(0)` line is logged
- **AND** the next roster summary reports one player

#### Scenario: Bare message is accepted

- **WHEN** the same message arrives without a bracketed prefix
- **THEN** a `Player joined: 0(0)` line is logged
- **AND** the next roster summary reports one player
