# DepotDownloader Quirks for Game Server Containers

## Problem

Windows game servers running under Wine/Proton often require redistributable DLLs (e.g., `steamclient64.dll`, `vstdlib_s64.dll`, `tier0_s64.dll`) that are **not** in the main game depot. They live in separate redistributable depots.

Enshrouded example:

- Depot `2278521` — main game files (`enshrouded_server.exe`, `.dat` archives)
- Depot `1004` — Steam runtime (`steamclient64.dll`, `steamwebrtc64.dll`, etc.)
- Depot `228989` — additional redistributables

If you only download the main depot, the server crashes at startup:

```text
Failed to initialize Steamworks system...Generic Error
Failed to load module 'C:\Program Files (x86)\Steam\steamclient64.dll'
```

## Key Quirks

### 1. `-depot` is exclusive

```text
DepotDownloader -app 2278520 -depot 2278521 ...
```

Downloads **only** that depot. No automatic inclusion of redistributables.

### 2. Omitting `-depot` downloads everything but can't pin versions

```text
DepotDownloader -app 2278520 ...
```

Downloads all depots for the app, but you lose manifest-level version pinning. Every update pulls the latest of everything.

### 3. `-manifest` requires one ID per `-depot`

```text
DepotDownloader -app 2278520 -depot 1004 -depot 2278521 -manifest 5612... -manifest 2174...
```

DepotDownloader expects all `-depot` flags first, then all `-manifest` flags, in matching order. **Interleaved pairs don't work** — extra `-depot`/`-manifest` arguments are silently ignored.

### 4. Each depot has its own manifest ID

You cannot use a single manifest ID across all depots. The manifest ID `2174935030716737236` only applies to depot `2278521`. Depot `1004` uses `5612541580377302256`. Using the wrong manifest ID for a depot returns a 404.

### 5. `-os` filters depot discovery

```
DepotDownloader -app 2278520 -manifest-only        # finds Linux depot 1006 only
DepotDownloader -app 2278520 -os windows -manifest-only  # finds depots 1004, 228989, 2278521
```

Without `-os windows`, DepotDownloader returns Linux-only depots, which don't contain the Windows DLLs the server needs.

## Reliable Pattern

### Step 1: Discover all Windows depots and their manifest IDs

```bash
DepotDownloader -app <APP_ID> -os windows -manifest-only
```

Parse the output:

- `Got depot key for <DEPOT_ID> result: OK` — lists each depot
- `Manifest <MANIFEST_ID> (<date>)` — the manifest ID for the depot being processed

For per-depot manifest IDs, query each depot individually:

```bash
DepotDownloader -app <APP_ID> -depot <DEPOT_ID> -os windows -manifest-only
```

### Step 2: Download each depot separately

```bash
for each (depot_id, manifest_id):
    DepotDownloader -app <APP_ID> \
        -depot <DEPOT_ID> \
        -manifest <MANIFEST_ID> \
        -os windows \
        -dir <TARGET_DIR>
```

Downloading depots one at a time avoids the argument ordering issue and ensures each depot gets its correct manifest ID.

### Step 3: Verify required files

After download, check for:

- The game executable (`enshrouded_server.exe`)
- Required redistributables (`steamclient64.dll`, `steamwebrtc64.dll`, etc.)

## Maintenance Checklist

When updating this container or creating one for another game:

1. **List all depots**: Run `DepotDownloader -app <ID> -os windows -manifest-only` and note every depot ID.
2. **Check file distribution**: Download each depot to a temp dir and verify which files land where. Redistributables often live in low-numbered depots (e.g., 1004, 1006).
3. **Pin all manifests**: Store `(depot_id, manifest_id)` pairs for reproducible builds.
4. **Watch for depot changes**: Major game updates may add/remove depots. The discovery step handles this automatically, but pinning requires re-running discovery to get new manifest IDs.
5. **Test Steamworks init**: The definitive test is whether the server log shows `[OnlineProviderSteam] 'Initialize' (up)!` instead of `Failed to load module 'steamclient64.dll'`.
