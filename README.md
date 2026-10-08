# Momentum Core Launcher

![Momentum Core Launcher showing the Featured panel, sort button and demo games](docs/screenshot.png)

![Playtime summary with streaks and a weekly chart](docs/stats.png)

A lightweight local game launcher with an arcade-inspired interface and guided game setup.
Controller-friendly, with a cyberpunk / retro-arcade look, a Python standard-library backend
and a vanilla HTML/CSS/JS front end, shown in a Chrome kiosk or app window.

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

## Meet Momentum Packages

**More time playing. Less time piecing together launch commands.**

[Momentum Packages](https://github.com/jacobm36/momentum-packages) is the companion repository
where we build game-specific setup packages. Each package brings the launch settings, artwork,
game details and installation steps together so Momentum can help turn your own game files
into a playable library entry.

The three projects work together:

- **Momentum Core Launcher** is your arcade front door: choose a game, set it up and hit **PLAY**.
- **Momentum Packages** is the private workshop where packages are built and tested.
- [**Momentum Distribution**](https://github.com/jacobm36/momentum-distribution) hosts the public
  catalog and approved installer downloads. The launcher connects here; players do not need
  access to the private workshop or a GitHub account.

In the launcher, choose **+ Add game**, pick a supported title and point Momentum at your game
files. It downloads and checks the installer, helps set up compatible required software, and
shows you the installation plan before making approved changes. Your original game files stay
untouched. Local package ZIPs can also be imported through **Advanced**.

**Bring your games; Momentum brings the setup.** Commercial base-game data, ROMs and BIOS
files come from you. Mod packages can include their complete distributable mod.
The catalog includes *The House of the Dead 2*, *Virtua Cop 2*, *Star Wars Trilogy
Arcade*, *L.A. Machineguns*, *Episode Enyo*, *Brutal Doom 64*, *Duke Nukem 3D*,
*Brutal Doom*, *Aliens: Eradication* and *Ashes 2063: Enriched*. Installer verification is separate
from gameplay confirmation. Updates are not installed automatically.

## Your data stays local

`games.json`, `playstats.json`, `logs/`, `jobs/`, `packages/`, `backups/` and `media/` are git-ignored: they hold your personal library,
play history and game artwork. Drop artwork into `media/<game-id>/` (`cover.jpg|png|webp`,
`video.mp4|webm`) or add it from the in-app editor.

## Setup and safety

See the [user guide](USER-GUIDE.md#notifications-installs-and-backups) for folder
selection, separate software/game approvals, local import, cancellation and recovery.
**Advanced → Add an existing game manually...** keeps the original library editor.

Only exact package/runtime evidence enables installation; unknown builds remain gated.
Installer checks are not gameplay certification. All new installations report **setup required**.
HOD2's approved artwork revisions inherit unchanged installer-code evidence, not new gameplay runs.
Technical evidence: [HOD2](docs/hod2-target-evidence.json),
[arcade](docs/arcade-installer-evidence.json), [Episode Enyo](docs/quake-installer-evidence.json),
[UZDoom games](docs/doom-installer-evidence.json), and [Duke Nukem 3D](docs/duke-installer-evidence.json).
[UZDoom preparation](docs/uzdoom-preparation.md) explains its scope and limits.
[EDuke32 preparation](docs/eduke32-preparation.md) covers Duke's native engine
reuse/build, complete enhancements and isolated state.

No automatic upgrades, elevation or RetroArch. Originals, personal settings and saves
are preserved; ambiguous interrupted changes require reconciliation.
Package scripts run as your user, not in a sandbox: trust the publisher before approval.
Catalog downloads are bounded to 512 MiB and ten minutes, with exact size/hash checks.
The server binds to `127.0.0.1`, validates the Host header and requires a session token for changes.

## Validation

Default tests: `python3 -m unittest discover -s tests`.
Package check without executing scripts: `python3 packages.py check <folder-or-zip>`.

| Optional check | Command |
|---|---|
| Headless package UI | `MCL_BROWSER_TESTS=1 python3 -m unittest tests.test_package_ui_browser` |
| Actual public downloads and GUI installs | `MCL_CATALOG_TESTS=1 python3 -m unittest tests.test_catalog_live_browser` |
| Arcade runner/lifecycle | `MCL_ARCADE_TESTS=1 python3 -m unittest tests.test_arcade_installs` |
| Episode Enyo runner/lifecycle | `MCL_QUAKE_TESTS=1 python3 -m unittest tests.test_quake_installs` |
| Four UZDoom games' runner/lifecycle | `MCL_DOOM_TESTS=1 python3 -m unittest tests.test_doom_installs` |
| Duke Nukem 3D runner/lifecycle | `MCL_DUKE_TESTS=1 python3 -m unittest tests.test_duke_installs` |
| HOD2 runner/lifecycle | `MCL_HOD_PACKAGE=/absolute/HOD-package.zip python3 -m unittest tests.test_hod_receipts` |

Browser checks need Chrome/Chromium; public checks need internet access.
Runner checks need built packages in the sibling package repository and temporary storage.
Native software is copied from exact pinned installations or downloaded from official releases.
Flatpak is mocked; game media is synthetic and homes/settings are isolated.
These tests never launch games or engines and do not modify working installations.

## License

MIT, see [LICENSE](LICENSE). Game names, covers and trailers belong to their owners and are not
included in this repository.
