# auto-update Specification

## Purpose

Check for a newer game Manifest when the Version spec resolves to `latest` and restart the server
into it when the empty-server gate is clear.

## Requirements

### Requirement: Auto Update scope and enablement

Auto Update SHALL be enabled by default and SHALL run only when the Version spec resolves to
`latest`, including an unset or empty `VERSION`. It SHALL NOT check or apply updates for an explicit
Manifest ID or a `build:` Version spec. An invalid `AUTO_UPDATE_ENABLED` value SHALL use the default.

#### Scenario: Default enabled for latest

- **WHEN** `VERSION=latest` and no Auto Update setting is provided
- **THEN** update checks SHALL be scheduled
- **AND** an available update SHALL be eligible to apply

#### Scenario: Unset version enables the default

- **WHEN** `VERSION` is unset or empty and no Auto Update setting is provided
- **THEN** update checks SHALL be scheduled

#### Scenario: Pinned version never checks

- **WHEN** `VERSION` is an explicit Manifest ID or `build:<id>`
- **THEN** no update check SHALL run
- **AND** no update SHALL apply

#### Scenario: Disabled

- **WHEN** `AUTO_UPDATE_ENABLED=false`
- **THEN** no update check SHALL run
- **AND** no update warning SHALL be logged

#### Scenario: Invalid enable value

- **WHEN** `AUTO_UPDATE_ENABLED` is not a recognized boolean
- **THEN** update checks SHALL be scheduled
- **AND** an available update SHALL be eligible to apply

### Requirement: Update schedule

`AUTO_UPDATE_CRON` SHALL default to `*/60 * * * *` and SHALL use the minute-level schedule parsing
and non-minute-field handling of `backup-system`; its fallback interval on a parsing failure SHALL be
3600 seconds. The first check SHALL occur at the first scheduled trigger after the server launches,
not at launch.

#### Scenario: Default schedule

- **WHEN** no schedule is configured
- **THEN** the first check SHALL occur at the next hourly trigger
- **AND** later checks SHALL follow the same hourly schedule

#### Scenario: Custom schedule

- **WHEN** `AUTO_UPDATE_CRON` requests every 5 minutes
- **THEN** update checks SHALL follow that schedule

#### Scenario: Invalid schedule falls back

- **WHEN** `AUTO_UPDATE_CRON` cannot be parsed
- **THEN** checks SHALL continue every 3600 seconds

#### Scenario: No check at launch

- **WHEN** the server launches
- **THEN** no update check SHALL run before the first scheduled trigger

### Requirement: Update detection

The Active Manifest and its timestamp SHALL be captured when the server launches and SHALL remain
the comparison baseline until the restart. Each check SHALL compare the newest Manifest candidate
selected by `versioned-game-install` with that baseline.

#### Scenario: No update candidate

- **WHEN** the newest candidate is not newer than the Active Manifest and no update is pending
- **THEN** no update warning SHALL be logged
- **AND** the server SHALL remain on the Active Manifest

#### Scenario: Older candidate never applies

- **WHEN** a check finds a Manifest older than the Active Manifest and no update is pending
- **THEN** no update warning SHALL be logged
- **AND** the server SHALL remain on the Active Manifest

#### Scenario: Unknown Active Manifest timestamp

- **WHEN** the Active Manifest timestamp is unavailable
- **THEN** a warning SHALL describe the missing evidence
- **AND** no update restart SHALL occur

#### Scenario: Downloaded update keeps the baseline

- **WHEN** an update is downloaded and players delay the restart
- **THEN** each scheduled check SHALL still compare candidates with the Active Manifest
- **AND** pending warnings SHALL continue

### Requirement: Pending target selection

A candidate newer than the Active Manifest SHALL start a pending update. While a pending target
exists, only a candidate newer than the pending target SHALL replace it; a candidate that is not
newer SHALL NOT replace or clear the pending target.

#### Scenario: Newer candidate supersedes a pending update

- **WHEN** a check finds a Manifest newer than the pending target
- **THEN** a warning SHALL name the new Manifest ID
- **AND** a subsequent restart SHALL use the new Manifest ID

#### Scenario: Regressed listing keeps the pending target

- **WHEN** a check finds a Manifest older than the pending target but newer than the Active Manifest
- **THEN** the pending target SHALL remain
- **AND** the warning SHALL name the pending target

#### Scenario: Regressed listing does not become the target

- **WHEN** a check finds a Manifest older than the Active Manifest while an update is pending
- **THEN** the pending target SHALL remain
- **AND** no warning SHALL name the older Manifest

### Requirement: Update warning cadence and check failures

A pending update SHALL log a WARNING on every scheduled check while it remains pending. A failed
check, or a listing with no Manifests, SHALL log a warning, leave the running server unchanged, and
retry at the next scheduled check.

#### Scenario: Pending update warns every check

- **WHEN** a check finds an update pending
- **THEN** a warning SHALL name the pending Manifest ID and the Active Manifest
- **AND** each scheduled check SHALL repeat the warning while it remains pending

#### Scenario: Check failure retries

- **WHEN** a check fails or reports no Manifests
- **THEN** a warning SHALL describe the failure
- **AND** the running server SHALL remain unchanged
- **AND** the next scheduled check SHALL retry

### Requirement: Empty-server gate

An update restart SHALL require the empty-server vetoes of `auto-pause` to be clear, except that A2S
SHALL NOT be required. While Auto Pause reports the tree paused, the Session block requirement SHALL
be waived.

#### Scenario: Empty server passes the gate

- **WHEN** Auto Pause's empty-server vetoes are clear
- **THEN** a downloaded update SHALL restart

#### Scenario: A2S is not a veto

- **WHEN** A2S reports players or is unresolved while the log-derived gate is clear
- **THEN** the update restart SHALL occur

#### Scenario: Paused tree is eligible

- **WHEN** Auto Pause reports the tree paused and the roster is empty
- **THEN** a stale Session block SHALL NOT block the update restart

### Requirement: Update download timing

By default, a pending update SHALL be downloaded as soon as it is detected, regardless of presence.
`AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY=true` SHALL defer the download until the empty-server gate is
clear. The gate SHALL be checked again after the download and before restart. An invalid value SHALL
use the default of false.

#### Scenario: Eager download while players are online

- **WHEN** an update is pending, players are online, and the default download mode is used
- **THEN** the new Manifest SHALL download without stopping the server

#### Scenario: Download deferred until empty

- **WHEN** `AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY=true` and players are online
- **THEN** the download SHALL NOT start
- **AND** it SHALL start after the empty-server gate clears

#### Scenario: Players join during a deferred download

- **WHEN** players join while a deferred download is in progress
- **THEN** the server SHALL keep running
- **AND** the restart SHALL wait for the empty-server gate again

#### Scenario: Invalid download-only value

- **WHEN** `AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY` is not a recognized boolean
- **THEN** the download SHALL be eager

### Requirement: Update download reliability

The download SHALL use the `latest` authentication strategy selection of `versioned-game-install`
and the install disk-space guard of `disk-space-guards`. A failed download SHALL warn, leave the
running server unchanged, and retry at the next scheduled check. Interrupted-download resume SHALL
follow `versioned-game-install`.

#### Scenario: Download failure retries

- **WHEN** a download fails or the install disk-space guard rejects it
- **THEN** a warning SHALL describe the failure
- **AND** the running server SHALL remain unchanged
- **AND** the next scheduled check SHALL retry

### Requirement: Automatic update restart

When a pending Manifest is downloaded and the empty-server gate is clear, the server SHALL restart
in-process using the pending Manifest ID (see `server-lifecycle`). The exit path SHALL apply the
cold Backup policy of `backup-system`. The gate SHALL be re-evaluated after the download and until
it clears; application SHALL NOT wait for the next scheduled check. A successful relaunch SHALL
clear the pending update.

#### Scenario: Empty server restarts

- **WHEN** the update is downloaded and the empty-server gate is clear
- **THEN** the server SHALL stop and relaunch with a new PID

#### Scenario: Pending update clears after relaunch

- **WHEN** the server relaunches from the pending Manifest
- **THEN** the pending update SHALL be cleared
- **AND** the new server SHALL keep that Manifest as the Active Manifest

#### Scenario: Players delay the restart

- **WHEN** the update is downloaded but a player is online
- **THEN** the server SHALL keep running
- **AND** the restart SHALL occur as soon as the empty-server gate clears

#### Scenario: Paused tree restarts

- **WHEN** Auto Pause reports the tree paused and an update is ready
- **THEN** the update restart SHALL occur

### Requirement: Log-only mode

`AUTO_UPDATE_LOG_ONLY=true` SHALL keep scheduled checks and update-available warnings but SHALL NOT
download, stop, or restart the server. An invalid value SHALL use the default of false.

#### Scenario: Log-only warns without acting

- **WHEN** `AUTO_UPDATE_LOG_ONLY=true` and an update is available
- **THEN** a warning SHALL be logged on every scheduled check
- **AND** no download, stop, or restart SHALL occur

#### Scenario: Invalid log-only value

- **WHEN** `AUTO_UPDATE_LOG_ONLY` is not a recognized boolean
- **THEN** Auto Update SHALL NOT use log-only mode

### Requirement: Mod compatibility warning

When Auto Update is enabled for `latest` and at least one file exists in the Mod overlay, startup
SHALL log a warning that automatic updates may break mods. Log-only mode SHALL still warn. A pinned
Version spec or disabled Auto Update SHALL NOT warn.

#### Scenario: Modded latest server warns

- **WHEN** Auto Update is enabled, `VERSION=latest`, and the Mod overlay contains a file
- **THEN** startup SHALL log a warning about automatic updates and mods

#### Scenario: Log-only mode still warns

- **WHEN** `AUTO_UPDATE_LOG_ONLY=true`, `VERSION=latest`, and the Mod overlay contains a file
- **THEN** startup SHALL log the mod compatibility warning

#### Scenario: Pinned or disabled server stays quiet

- **WHEN** Auto Update is disabled or the Version spec is pinned
- **THEN** no mod compatibility warning SHALL be logged

### Requirement: Update failure isolation and shutdown

A check or download failure, including an unexpected error, SHALL be isolated by Auto Update and
SHALL NOT trigger the container's unexpected-failure exit path. It SHALL be logged as a warning and
SHALL NOT stop the running server. Restart failures SHALL follow `server-lifecycle`. Shutdown SHALL
stop update checks, abort an in-flight download without waiting for it, and SHALL NOT restart the
server.

#### Scenario: Unexpected failure keeps the server running

- **WHEN** an update check or download raises an unexpected error
- **THEN** the failure SHALL be logged
- **AND** the server SHALL keep running on the Active Manifest

#### Scenario: Shutdown during a pending update

- **WHEN** shutdown begins while an update is pending
- **THEN** no further update check or warning SHALL be logged
- **AND** no restart SHALL occur

#### Scenario: Shutdown during a download

- **WHEN** shutdown begins while an update Manifest is downloading
- **THEN** the download SHALL be aborted without waiting
- **AND** the next run SHALL resume the interrupted Manifest install (see `versioned-game-install`)

### Requirement: Auto Update logging

Auto Update warnings SHALL be logged at WARNING through the orchestrator logger and SHALL follow the
orchestrator file-logging level rules (see `orchestrator-file-logging`).

#### Scenario: Warnings reach the orchestrator file

- **WHEN** Auto Update logs a warning and file logging uses its default WARNING level
- **THEN** the warning SHALL appear in the orchestrator file
