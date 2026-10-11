# Private Marvel Infinity War candidate

This is a bounded integration for Marvel Infinity War with the supplied OpenBOR
6391 runtime, not a general OpenBOR manager. The owner accepted the private r1
candidate on the debug PC and approved the unchanged 0.2.0 package for the public
store. The frontend and candidate bundles remain private.

- The package carries the exact tested AppImage and its verified extracted native
  runtime. Preparation uses the extracted files and needs no FUSE, engine download,
  administrator access, or engine launch.
- Momentum checks every runtime file, size, hash and mode before reuse. An altered
  runtime blocks setup; it is not replaced or repaired automatically.
- New installations use `~/Games/marvel-infinity-war`. Existing receipts retain
  their recorded directories. The shared runtime lives separately under
  `~/.local/share/momentum-core/software/openbor/6391`.
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

Host library checks do not certify graphics, audio or input. The prior manual
setup used Ubuntu 24.04 x86_64 and an 8BitDo SNES Pro, with fullscreen and **CRT
scanlines TV**. Other controllers may require in-game remapping. Do not claim
universal controller support, a fully tested campaign, or packaged gameplay
acceptance from that earlier evidence.

## Debug PC test

Extract the complete private candidate to a new folder. Close any other Momentum
server and run `bash start-isolated-test.sh`. This uses the existing isolated
acceptance HOME, leaving normal games, engines and receipts untouched. Always
relaunch the candidate with the same script; do not install desktop shortcuts
from isolated mode.

Choose **Add game > Browse the package store > Local packages > Marvel Infinity
War**. For online setup, leave downloading checked and the optional offline
folder blank. Allow at least 2 GiB free temporary/destination space plus the
candidate bundle. Review engine preparation, then the separate game download
and install plan. A repeated complete install should not download again.

Connect the controller before launch. Check fullscreen, the shader, controls,
audio, progression beyond the tutorial, normal exit and relaunch. Confirm that
settings and saved progress persist. To remap, use Control Options > Player 1:
press Enter on an action, release Enter, then press the controller input.

The automated lifecycle test exercises verify, repair, and game-only
removal/reinstall through the actual runner. This candidate does not add new
buttons for those operations. Your debug-PC acceptance focuses on installation,
gameplay and relaunch; do not manually delete game files to simulate removal.
Keep failed jobs and their journals for diagnosis rather than deleting them or
bypassing checks. Additional OpenBOR versions remain outside this scope.
