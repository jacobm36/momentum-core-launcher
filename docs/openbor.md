# Marvel Infinity War setup

## OpenBOR, without the setup

OpenBOR is home to a large library of fan-made beat 'em ups. Momentum packages
make them Linux-native. A package pins the engine version the game was tested
with and seeds the controller preset, display settings and shader. It keeps
your saves and settings and adds the game to your library with artwork. No
ROMs. No mystery configurations. Just games that work.

Marvel Infinity War is the first OpenBOR package. The details below describe
exactly what it does.

## How the package works

This is a bounded integration for Marvel Infinity War with the supplied OpenBOR
6391 runtime, not a general OpenBOR manager. Version 0.2.0 is published in the
public store and has owner-reported debug-PC acceptance. The frontend and
launcher bundles remain private.

- The package carries the exact tested AppImage and its verified extracted native
  runtime. Preparation uses the extracted files and needs no FUSE, engine download,
  administrator access, or engine launch.
- Momentum checks every runtime file, size, hash and mode before reuse. An altered
  copy at the 0.2.0 runtime path blocks setup; it is not replaced or repaired
  automatically.
- New installations use `~/Games/marvel-infinity-war`. Existing receipts retain
  their recorded directories. The shared runtime lives separately under
  `~/.local/share/momentum-core/software/openbor/6391`. The published 0.2.0
  package and its launcher script require this exact path, so it never moves.
- Game acquisition is package-owned, after the separate game plan approval:
  the pinned ZVitor archive is downloaded and verified, and only its game PAK is
  extracted. Alternatively, disable downloading and supply the matching PAK.
  No upstream executable, settings or player progress is imported.
- The captured 352-byte configuration is seeded only when absent. Settings,
  progress, logs and screenshots stay game-local. Game-only removal preserves
  player state and the shared engine. Modified managed files block removal for
  explicit reconciliation instead of being silently deleted or reclassified.
- Cover and preview media are copied from validated retained package support to
  launcher-served media on first association only. Existing library artwork
  stays unchanged.

### Build-specific runtime folders (launcher groundwork)

The launcher also supports a build-specific runtime folder,
`~/.local/share/momentum-core/software/openbor/builds/6391-<archive hash prefix>`.
A package opts in by declaring `"layout": "build"` on its OpenBOR requirement. If
the field is absent, the package uses the legacy `openbor/6391` path described
above, so Marvel Infinity War 0.2.0 is unaffected. No published package uses the
build layout yet. A future package release must opt in and be tested before it
does.

When a build-specific copy has been altered, the preparation plan names a
side-by-side recovery folder (`<build>.altered-1`, `-2`, …). Only after you
approve that plan does Momentum move the altered copy there unchanged and
publish a fresh verified copy. Both renames refuse to overwrite anything. The
move is recorded in the job's transaction journal, and nothing is deleted.

Host library checks do not certify graphics, audio or input. The configuration
was tested on Ubuntu 24.04 x86_64 with an 8BitDo SNES Pro, fullscreen and **CRT
scanlines TV**. Other controllers may require in-game remapping. Do not claim
universal controller support, a fully tested campaign, or packaged gameplay
acceptance beyond the reported checks.

## Installation and controls

Extract the complete private candidate to a new folder. Close any other Momentum
server and run `bash start-isolated-test.sh`. This uses the existing isolated
acceptance HOME, leaving normal games, engines and receipts untouched. Always
relaunch the candidate with the same script; do not install desktop shortcuts
from isolated mode.

Choose **Add game > Browse the package store > Marvel Infinity War**, or import
a supplied installer through **Local packages**. For online setup, leave downloading checked and the optional offline
folder blank. Allow at least 2 GiB free temporary/destination space plus the
candidate bundle. Review engine preparation, then the separate game download
and install plan. A repeated complete install should not download again.

Connect the controller before launch. Check fullscreen, the shader, controls,
audio, progression beyond the tutorial, normal exit and relaunch. Confirm that
settings and saved progress persist. To remap, use Control Options > Player 1:
press Enter on an action, release Enter, then press the controller input.

Verify, repair and game-only removal/reinstall are available through the package
runner, not dedicated new UI buttons. Do not manually delete game files to simulate removal.
Keep failed jobs and their journals for diagnosis rather than deleting them or
bypassing checks. Additional OpenBOR versions remain outside this scope.
