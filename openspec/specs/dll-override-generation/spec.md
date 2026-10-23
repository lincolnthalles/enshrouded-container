## Purpose

Generation of Wine DLL overrides from mod DLL files at startup.

## Requirements

### Requirement: DLL override generation

The orchestrator SHALL scan the mods volume for files with a `.dll` extension (case-insensitive) and generate `WINEDLLOVERRIDES` entries for each DLL found. DLLs whose filename (without extension) starts with `win` (case-insensitive) SHALL receive the `n,b` override (native then builtin). All other DLLs SHALL receive the `n` override (native only). The standard baseline `mscoree,mshtml=` SHALL always be included, first, with generated entries sorted alphabetically after it.

#### Scenario: No mod DLLs present

- **WHEN** the mods volume contains no `.dll` files
- **THEN** the generated `WINEDLLOVERRIDES` SHALL be `mscoree,mshtml=`

#### Scenario: Mod DLLs with win prefix

- **WHEN** the mods volume contains `winhttp.dll`
- **THEN** the generated `WINEDLLOVERRIDES` SHALL include `winhttp=n,b` alongside the baseline

#### Scenario: Mod DLLs without win prefix

- **WHEN** a mod DLL exists in a subdirectory
- **THEN** the generated `WINEDLLOVERRIDES` SHALL include its `n` entry alongside the baseline

#### Scenario: Mixed mod DLLs sorted after baseline

- **WHEN** the mods volume contains both `winhttp.dll` and `dinput8.dll`
- **THEN** the generated `WINEDLLOVERRIDES` SHALL be the baseline first, then the entries sorted alphabetically

#### Scenario: User-provided WINEDLLOVERRIDES overrides generated value

- **WHEN** the container receives `WINEDLLOVERRIDES` as an environment variable at runtime, including an empty or whitespace-only value
- **THEN** the raw environment value SHALL be used verbatim and the generated value SHALL NOT be applied

#### Scenario: Empty WINEDLLOVERRIDES suppresses overrides

- **WHEN** `WINEDLLOVERRIDES` is set to an empty string
- **THEN** the effective `WINEDLLOVERRIDES` SHALL be the empty string and no generated entries SHALL be applied

#### Scenario: Startup logging of overrides

- **WHEN** the DLL override string is computed
- **THEN** the orchestrator SHALL log the final `WINEDLLOVERRIDES` value at INFO level
