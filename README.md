# Momentum Core Launcher

![Momentum Core Launcher showing the Featured panel, sort button and demo games](docs/screenshot.png)

![Playtime summary with streaks and a weekly chart](docs/stats.png)

A local, controller-friendly game launcher with a cyberpunk / retro-arcade look. A tiny Python
(stdlib-only) server plus a vanilla HTML/CSS/JS front end, shown in a Chrome kiosk or app window.

Features: categories and drag-to-reorder, search, favorites, per-game accent colors, a Classic or
Featured detail panel, synthesized sound effects and intro, gamepad support, play statistics,
per-game launch logs, and artwork/trailer fetching.

## Requirements

- Linux with Python 3.9+ (3.12 tested)
- Google Chrome or Chromium (falls back to `xdg-open`)

## Quick start

```bash
cp games.example.json games.json   # or run ./import_games.py to import .desktop shortcuts
./launch.sh                        # starts the server and opens the launcher
./install.sh                       # optional: add an app-menu / Desktop shortcut
```

Handy keys: **↑/↓** select, **Enter** play, **F** favorite, **R** jump to recent games, **Shift+F** jump to favorites, **S** change sort order, **T** playtime summary, **Ctrl+Q** quit.
An empty library shows a welcome screen with an **Add a game** button. See [USER-GUIDE.md](USER-GUIDE.md) for everything else.

## Your data stays local

`games.json`, `playstats.json`, `logs/`, `jobs/`, `packages/`, `backups/` and `media/` are git-ignored: they hold your personal library,
play history and game artwork. Drop artwork into `media/<game-id>/` (`cover.jpg|png|webp`,
`video.mp4|webm`) or add it from the in-app editor.

## Notes

- Built-in notifications (N), background jobs (I) and backup/restore (B); see the user guide. Jobs keep running after the launcher closes.
- Tests: `python3 -m unittest discover -s tests`.
- Headless package UI tests (Chrome/Chromium): `MCL_BROWSER_TESTS=1 python3 -m unittest tests.test_package_ui_browser`.
- Package check (Package Contract v1): `python3 packages.py check <folder-or-zip>`; nothing in the package is run.
- Local package UI: open **Installs & jobs (I) → Install package...** to import a ZIP or local
  package folder, review trust/test evidence, enter paths and run preflight. **Review plan** shows
  exact changes, backups, dependencies and manual setup. Unsupported platforms are blocked.
  Installation is enabled for the exact tested HOD2 0.1.1 package and user-scope Flycast v2.7
  build recorded in [target evidence](docs/hod2-target-evidence.json). A different package digest
  or emulator build stays gated. Detection alone is not capability evidence. Work is scoped to
  this HOD2 flow, not a general-purpose package manager.
  A remote download catalog is separate future work.
- Game setup selects its required software automatically; users do not choose an emulator.
  If software is missing, the same game job first requests approval for required downloads,
  checks the installed build, then presents the game-file plan for approval. Detection is read-only.
  Approval can add the official user Flathub remote and install missing user-scope Flycast;
  existing software is reused without an automatic upgrade. Transactions have durable intent/outcome
  records, do not elevate, and finish safely before acknowledging cancellation. An untested installed
  build stops setup before game files change.
- Receipts reconcile approved actions, durable intents, inventories and actual hashes. Catalog
  publication is replayable after interruption without duplicating entries or overwriting later
  personal edits; ambiguous filesystem evidence remains blocked for manual recovery.
- Optional real-package/synthetic-media regression (no real emulator launches):
  `MCL_HOD_PACKAGE=/absolute/HOD-package.zip python3 -m unittest tests.test_hod_receipts`.

- The server binds to `127.0.0.1` only, validates the Host header and requires a per-session token
  for changes.
- Linux only for now (`.desktop` files, `xdg-*` tools).

## License

MIT, see [LICENSE](LICENSE). Game names, covers and trailers belong to their owners and are not
included in this repository.
