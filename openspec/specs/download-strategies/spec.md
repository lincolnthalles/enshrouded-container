## Purpose

Shared depot download execution with credential-strategy behavior selected by Install.

## Requirements

### Requirement: Per-depot download loop

The Download SHALL fetch every discovered depot of the game, pinning the target depot to the requested Manifest ID while leaving other depots at their discovered Manifest IDs. When discovery reports nothing, the Download SHALL fall back to the default depot. A failed depot download or an expired download window SHALL fail the Install with an error naming the depot.

#### Scenario: Target depot pinned, others discovered

- **WHEN** a Download runs for a Manifest ID with the game depots discovered in a single pass
- **THEN** the target depot SHALL fetch the requested Manifest ID in one invocation per depot, and other depots SHALL fetch their discovered Manifest IDs

#### Scenario: Discovery fallback

- **WHEN** depot discovery reports no depots
- **THEN** the Download SHALL target the default depot and log the fallback

#### Scenario: Depot failure fails install

- **WHEN** DepotDownloader exits non-zero for a depot
- **THEN** the Install SHALL fail with an error naming the depot and exit code

#### Scenario: Download timeout fails install

- **WHEN** a depot download exceeds its time window
- **THEN** the Install SHALL fail with an error naming the depot

### Requirement: Auth-free credential strategy

When Install selects the auth-free strategy, the Download SHALL pass the depot keys and Manifest file to DepotDownloader instead of login credentials.

#### Scenario: Auth-free flags

- **WHEN** the auth-free strategy is selected with keys and Manifest file present
- **THEN** DepotDownloader SHALL receive the depot-keys and manifest-file inputs and no login flags

### Requirement: Steam credential strategy

When Install selects the Steam strategy, the Download SHALL authenticate with the configured username and persist the login. The password SHALL be passed only when one is configured.

#### Scenario: Steam auth flags

- **WHEN** the Steam strategy is selected with username and password configured
- **THEN** DepotDownloader SHALL receive the username, password, and login-persistence inputs

### Requirement: Anonymous strategy

When Install selects the anonymous strategy, the Download SHALL pass no credential inputs to DepotDownloader.

#### Scenario: Anonymous flags

- **WHEN** the anonymous strategy is selected
- **THEN** DepotDownloader SHALL receive the app, depot, and target-directory inputs with no credential inputs

### Requirement: Interactive login strategy

When Install selects the interactive strategy, the Download SHALL print login instructions and authenticate interactively.

#### Scenario: Interactive login prompt

- **WHEN** the interactive strategy is selected
- **THEN** the Download SHALL print login instructions and authenticate interactively
