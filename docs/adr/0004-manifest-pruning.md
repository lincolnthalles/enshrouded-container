# Keep two Manifest installs for latest-tracking deployments

This ADR partially supersedes ADR 0003's decision to keep every Manifest install.

Auto Update adds a full game copy per release. Keeping every install, as ADR 0003 decided, preserves
every rollback target but eventually fills the manifests volume and blocks the next update download.
For a long-running latest-tracking deployment, the usual rollback target is only the previously
active release. The container now keeps only the Active Manifest install and the Previous Active
Manifest install, and deletes older complete installs after a start or update restart prepares the
Active Manifest install and Game tree. Before a Download, when the initial free-space evaluation shows
the Install disk-space check would fail, reclamation removes installs outside the reclamation keep set
and the check is re-evaluated. The keep set is the requested Manifest install, the recorded Active
Manifest install, the Manifest install backing the current Game tree when present, and the recorded
Previous Active Manifest install when complete, or the fallback install in its place when no complete
recorded previous exists. The Activation record itself is never removed. Pinned Version specs keep
every install.

Pruning is enabled by default and disabled with `MANIFEST_PRUNE_ENABLED=false`, because unattended
self-updating deployments gain the most from bounded storage. The Activation record is updated when
a start or update restart successfully prepares the Active Manifest install and Game tree, so the
previous install reflects what actually ran, not install order; when no complete recorded previous
exists, the fallback is the most recently completed other install. Only Manifest install directories are
pruned; `.manifest` snapshots and `depot.keys` stay available for auth-free re-downloads. Candidates
from pruning or reclamation are renamed into the `.prune` staging directory before deletion, so an
interrupted cleanup cannot leave a partial directory that still looks installed.

## Considered Options

- **Keep every install**: rejected because it preserves every rollback target but makes disk
  exhaustion the normal failure mode for self-updating deployments.
- **Keep only the active install**: rejected because it removes the rollback target for a bad game
  release.
- **Make pruning opt-in**: rejected because the deployments most likely to run out of disk are the
  unattended self-updating ones that would not opt in.
- **Prune `.manifest` snapshots too**: rejected because snapshots are much smaller and keep older
  pins downloadable without ManifestHub credentials.
- **Background-only pruning**: rejected because a disk-full deployment could never download the next
  Manifest. Reclamation runs synchronously when the initial free-space evaluation would fail, and the
  disk-space check is re-evaluated before the Download; post-activation deletion stays in the
  background.

## Consequences

- A latest-tracking deployment keeps one rollback target; older pins require a re-download.
- An update temporarily needs free space for three complete installs: the Active Manifest install,
  the Previous Active Manifest install, and the requested Manifest install.
- Pinned Version specs are unaffected and continue to keep every install.
- Incomplete Manifest installs are preserved for resume, so abandoned partial downloads still need
  operator cleanup.
- An interrupted background deletion leaves staged data in `.prune` that the next start removes.
- Operators who want every install set `MANIFEST_PRUNE_ENABLED=false`.
