# Approved Ironwail and QBJ3 preparation

This is a narrow launcher-owned preparation path for Quake Brutalist Jam III
0.1.0, not a general engine installer or arbitrary mod downloader.
Ubuntu 24.04 x86_64 only. Commercial Quake PAKs are supplied by the user.

## Separate approvals

1. Select the Quake base folder and optional complete extracted `qbj3` folder.
2. Trust the installer publisher and check the plan. Invalid base files or an
   existing incomplete/modified source stop rather than silently downloading.
3. If missing, review pinned software/source URLs, bytes, hashes and destinations.
   Preparation downloads do not authorize any game installation changes.
4. After full preparation verification, review and approve the separate game
   plan. Saved exact plan bytes and dependency facts must still match.

Preparation reuses complete local source read-only, or downloads QBJ3 1.3 from
the official-site-linked US mirror. Its observed archive SHA-256 is not a
publisher-signed checksum. Restricted assets are not in the installer ZIP.
Ironwail is reused only when executable and companion match exact official
0.8.2 bytes. Unknown/incomplete installations are preserved and block fallback.
No upgrades, elevation, system-package installation or engine invocation.

## Limits and state

- QBJ3 archive: 2,689,872,444 bytes; extracted: 6,168,990,590 bytes, 1,937 files.
- Conservative free-space check: archive + two expanded copies + 1 GiB,
  checked on the source-cache filesystem; allow about 17 GiB.
- Download: trusted HTTPS hosts only, exact size/hash, 30-second I/O timeout,
  one-hour wall deadline; no partial-download resume.
- Tar whitelist and ZIP inventory/type/path/size checks reject unsafe resources;
  extracted bytes are checked before no-replace atomic publication.
- Runner JSON results are read with a strict 4 MiB bound, including full
  inventories and retained-state reinstall plans; oversized results fail.
- Engine: `~/.local/share/momentum-core/software/ironwail/0.8.2`.
- Source: `~/.cache/momentum-core/qbj3/<archive SHA-256>/qbj3`.
- Settings/saves: isolated installed game tree; official Linux engine is built
  with DO_USERDIRS=0. Original sources and shared software/cache remain.
- Cancellation is checked at safe boundaries. Scratch downloads/extractions
  are removed; published shared resources are retained. An uncertain journal
  requires manual reconciliation before retry, never blind replay.

Read-only ELF/library checks use `readelf` and `ldconfig`, not `ldd` or a game
launch. Missing Ubuntu host libraries require system setup. Installer evidence
is bound to exact package/runtime bytes and is not graphical gameplay proof.
Every new game remains **setup required** until its user confirms display,
sound, input, save/load/relaunch and clean exit.

See [exact evidence](qbj3-installer-evidence.json). The package's separate
standalone adapter is not used by the trusted runner and has independent
ownership/receipts; do not mix independently owned installations.

## Existing-installation revisit

The canonical laptop's managed 0.1.0 installation passed the package's read-only
verify entrypoint with its current receipt and freshly checked Ironwail host
facts. Verification covered pinned mod assets, base PAK structure, wrapper,
desktop entry, artwork and installed support bytes/modes. Existing settings,
saves and other unrecognized game files were backed up and checked unchanged;
the receipt and edited catalog were also unchanged. All 24 targeted Ironwail
unit tests passed.

The historical source and reference-engine folders are absent, but the installed
game and managed runtime remain intact. Those absent reference folders did not
block installed verification and do not justify a repair or new download.
No repair, reinstallation, engine upgrade or engine invocation was performed.
Display, audio, input, representative-map performance and save/load/relaunch
still need owner confirmation. Readiness remains **setup required**.
