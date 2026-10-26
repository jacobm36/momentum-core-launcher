# Momentum Core Launcher

### Your games. Your Linux arcade.

**Less setup. More PLAY.**

## Public preview

[Download the launcher](https://github.com/jacobm36/momentum-core-launcher/releases/tag/v2026.10.25-preview.1)
and choose the launcher ZIP, not GitHub's source-code archives. Extract into a
**new writable folder**, close any old launcher, and run:

```bash
bash start-candidate.sh
```

This opens a normal window. Use `bash launch.sh` for fullscreen and
`bash install.sh` when you want app-menu/Desktop shortcuts.
The tested baseline is **Ubuntu 24.04 x86_64 with X11**, Python 3 and
Chrome/Chromium. Other desktops, Wayland and controllers may behave differently.
This is an early public preview, not a promise of universal game compatibility.
See [requirements](#take-it-for-a-spin) below.

No games or personal library data are bundled. When trying a new version, keep
your original launcher folder, library, artwork, saves and recovery journals.
A fresh extracted folder does not automatically migrate your old library;
normal launches still use your account's shared package installation receipts.

Steam shortcuts. Native games. Emulator launches. Your own scripts. Your games
don't all come from the same place, and they don't all launch the same way.
Momentum gives every one of them a single controller-friendly home, with an
arcade-inspired interface that makes your collection feel like a collection.

Momentum Core is not a ROM frontend. It is a Linux game library plus a
compatibility and packaging platform for games that are otherwise inconvenient,
fragmented or difficult to configure. For supported titles, it goes beyond the
Play button: Momentum brings the compatible engine, launch recipe, artwork and
guided setup together, so a working configuration doesn't have to stay trapped
on the computer where you first figured it out.

![Momentum's Featured panel with game artwork and an arcade-inspired library](docs/screenshot.png)

## One front door. Three ways in.

**Already installed? Bring it in.** Review your Linux game shortcuts and import
the ones you want. Momentum leaves your existing commands and installations
alone. Steam games with local shortcuts, native games and emulator launches can
sit side by side.

Discovery reads user and system application menus, including Flatpak and Snap
exports. It respects XDG data locations and desktop-entry precedence: a user
override, including a hidden entry, masks the same desktop ID in later locations.
It does not scan your whole disk or enumerate Steam libraries.

**Have your own setup? Make it yours.** Add a command or script, give it a name,
drop in some artwork and hit Play. You don't need a Momentum package to use
Momentum.

The library shows its total game count above the list. Search and tag filters
show matching games out of that total; Favorites and Recently played do not
count the same library entry twice.

Momentum remembers your selected game, search, tag filters and library scroll
position across restarts in the same browser profile. Choose **List**, landscape
**Tiles**, or portrait **Grid** above the library. List retains the Classic or
Featured presentation and organization controls. Both artwork layouts keep
compact game actions; opening a card shows a details dialog with description,
screenshots, existing preview video, play history and Play.
The browsing view and each view's scroll position are remembered separately.
Grid has a separate **Grid cover** slot; existing covers fit without cropping
when portrait art is missing, followed by icons or initials. Tiles still use
background art and icons. No artwork setup is required. **About Momentum** shows
the launcher build identity and platform. A selected game's **Folders** action
opens recorded working, game and saves/settings directories where available;
it never guesses a save location from a launch command.

Landscape Tiles can preview an existing game video when selected by keyboard or
controller, or hovered with the mouse. Artwork stays still until a half-second
delay, then a single muted looping preview plays; portrait Grid stays static.
In Edit, pause/scrub the video and choose **Capture frame for Tiles** to review
and save a still image without changing the portrait cover.

In Tiles/Grid, the sidebar navigates **All games**, **Favorites**,
**Recently played**, and categories with game counts. Search and tags narrow the
selected collection, which is remembered across restarts; List still shows the
full library. Add game stays at the bottom, with less-used controls under
**Settings & tools**, including About, playtime, backup, and presentation settings.

The game editor separates **Game details — Steam** (**Get Steam details**) from
**Artwork — SteamGridDB** in a compact **Find details & artwork online**
section. Advanced search and key setup stay collapsed until needed, with an
optional alternate search title and remembered SteamGridDB game ID. Choose
background, portrait grid cover or icon artwork without renaming the game or changing its launch
command. A personal API key is stored privately outside the library; see the
[user guide](USER-GUIDE.md#steamgriddb-artwork) for setup and removal.

**Want a supported game set up? Let the recipe do the work.** Browse the package
store, supply the required game files and review the setup plan. Momentum checks
the installer, looks for a compatible runtime and walks you through the changes
before making them.

## Where the package store shines

**Community games. Arcade oddities. Boomer shooters.**
All the stuff enthusiasts love, without the setup pain.

Your library can hold any game you can launch on Linux. The package store is
where Momentum goes further: guided, tested setups for the kinds of games that
are usually the hardest to get right. Today it specializes in three areas, and
it will grow one real game at a time.

### Momentum Mouse Arcade: rail shooters become mouse games

Momentum Core can turn compatible light-gun and rail-shooter titles into
natural mouse-driven games on Linux. **Point, click, play.** Each package
carries a tested emulator setup with fullscreen mouse aiming.
Bring your own legally obtained game files. Momentum handles the rest.

### Boomer Shooters: classic engines, modern mods

**Classic engines. Modern mods. Less setup.** The best of Quake, Doom, Duke and
beyond, configured for Linux and ready to launch.

A Momentum package doesn't just run `-file something.pk3` or `-game modfolder`.
It handles the parts people repeatedly trip over:

- engine selection and per-game engine pinning
- required base-game files
- mod load order
- fullscreen and display settings
- launch arguments
- controller and mouse configuration
- artwork and metadata
- preserving saves and user state
- clean removal

Every store card shows a runtime badge, such as UZDoom or vkQuake, so you can
see the engine without having to configure it. The launcher also has adapters
for EDuke32 and Ironwail. Packages bundle mod and engine components or fetch
them from their sources; where a mod needs commercial base-game files, such as
Quake's `pak0.pak`/`pak1.pak` or `DOOM2.WAD`, you supply them.

### OpenBOR: fan-made beat 'em ups, made Linux-native

**OpenBOR, without the setup.** A Momentum package turns an OpenBOR game into a
polished Linux experience. Each package can pin the engine version the game was
tested with, configure the controller, apply display settings and shaders,
preserve your saves and add the game to your library.
No ROMs. No mystery configurations. Just games that work.

The game files already existed. Momentum turns them into a polished Linux game.

> **Go behind the Play button.**
> [Explore Momentum Core](https://jacobm36.github.io/momentum-core-explorer/)
> in your browser: follow a package from store to library, click through the
> system map, and try the interactive package lab. No downloads, installs or
> sign-in required - just a hands-on look at how Momentum brings the setup.

## Not just a shortcut with a nice cover

Getting a Linux game running is often a little adventure: the right emulator
build, a particular mod order, fullscreen flags, a wrapper script, controller
settings, and a forum tab you hope you'll find again.

**Momentum Packages turn that knowledge into a reproducible setup.**

A game-specific package carries the recipe: which runtime it supports, how to
prepare it, how to launch the game, what presentation to use, and which files
belong to the installation. Where a title needs a tested preset, the package can
seed it without replacing your existing settings.

For example, Marvel Infinity War pairs its game PAK with the tested OpenBOR 6391
runtime, fullscreen/CRT configuration, artwork and preview video. You can use
the pinned author download or supply the matching PAK yourself. The result is a
game entry you can launch from Momentum, rather than another setup checklist to
rebuild by hand.

**Bring your games; Momentum brings the setup.**

## Make the library part of the fun

- **An arcade front door:** fullscreen kiosk or a normal app window, with
  Classic and Featured views, per-game colors, artwork and looping previews.
- **Couch-friendly browsing:** gamepad navigation, menu focus and an on-screen
  keyboard, alongside familiar mouse and keyboard controls.
- **A collection, not a pile:** categories, drag-to-reorder, search, favorites,
  tags and recently played games, with optional tiled browsing for larger libraries.
- **Your own presentation:** drop or paste artwork, add video, look up Steam
  metadata, or grab a video frame as a cover.
- **A little history:** playtime, launch counts, streaks and a weekly chart.
- **The practical bits:** launch logs, background-job progress, notifications,
  and library backups with optional artwork.

![Playtime summary with streaks and a weekly chart](docs/stats.png)

## Built to respect the setup you already have

Momentum reuses supported engines where they are instead of moving them.
Original game files stay untouched. Existing settings, saves and edited library
entries are preserved. New package installs default to `~/Games/<package-id>`;
existing installations keep the directory recorded in their receipt.

Software preparation and game installation have separate approvals. When an
existing engine is incompatible, supported HOD2 and Brutal Doom packages can
offer a separately approved, isolated known-working runtime without changing
your existing copy. There are no automatic engine upgrades or profile migrations.

Momentum does not install system prerequisites or elevate itself. If a host
dependency is missing, setup tells you what needs attention. Packages run as
your user, so only approve installers from publishers you trust.

The browser interface talks to a **loopback-only local server**, not a hosted
account service. Keep it local; do not expose or reverse-proxy it to a network.
Checksums verify package integrity, not publisher trust. Approved package scripts
and game commands run with your user permissions, not in a sandbox.

Installed packages have **Manage installation → Review uninstall**. You approve
the exact removal plan; unchanged installer-owned files are removed while player
state, modified files and shared engines are retained. **Remove from library**
only removes the entry. **Remove cached installer** deletes an unused installer
download, not a game; active installations and recovery data are protected.
Newer package versions are indicated in the store; there is no automatic update.

## In the package store today

The store groups packages by experience, and each card shows the runtime it
uses.

| Pillar | Game | Runtime |
|---|---|---|
| OpenBOR | Marvel Infinity War | OpenBOR 6391 |
| OpenBOR | Ultimate Double Dragon 3 | OpenBOR 6391 |
| Momentum Mouse Arcade | Star Wars Trilogy Arcade | Supermodel |
| Momentum Mouse Arcade | L.A. Machineguns | Supermodel |
| Momentum Mouse Arcade | The House of the Dead 2 | Flycast |
| Momentum Mouse Arcade | Virtua Cop 2 | Flycast |
| Momentum Mouse Arcade | Time Crisis II | MAME |
| Boomer Shooters | Brutal Doom | UZDoom |
| Boomer Shooters | Brutal Doom 64 | UZDoom |
| Boomer Shooters | Slave Zero X: Episode Enyo | vkQuake |

The [public distribution repository](https://github.com/jacobm36/momentum-distribution)
hosts the catalog and installer downloads; no GitHub account is needed to obtain
them. It is separate from this public launcher repository. For current package
versions, use the [store catalog](https://github.com/jacobm36/momentum-distribution/blob/main/catalog.json).
Package-authoring development remains separate.

You supply commercial base-game files, ROMs and BIOS files where required.
Packages may bundle mod content or obtain a pinned release from its source;
Enyo downloads its mod or reuses verified files. Runtime compatibility is
game-specific, not a promise that every engine build or controller will work.
Installer validation and reported gameplay acceptance are tracked separately.

## Take it for a spin

Momentum is a **Linux launcher**. You'll need:

- Python 3.9+ (3.12 tested).
- Google Chrome or Chromium for the kiosk/app experience; otherwise it opens
  your default browser through `xdg-open`.
- `flock`, usually provided by `util-linux`.
- For X11 fullscreen game handoff: `wmctrl` and `xprop` (`wmctrl` and
  `x11-utils` on Ubuntu). Windowed mode doesn't need that handoff.

From your launcher folder, open a normal window:

```bash
MCL_WINDOWED=1 bash launch.sh
```

Choose **+ Add game**, then **Import installed games**, **Add a game manually**
or **Browse the package store**. No sample-library copy is needed.

For the fullscreen arcade experience, close the window and run `bash launch.sh`.
To add an app-menu/Desktop shortcut, run `bash install.sh`.
If you're testing a supplied candidate bundle, use its `start-candidate.sh`
or isolated-test instructions instead.

**Quick controls:** arrows to browse, **Enter** to open details in Tiles/Grid
(or play in List), **F** to favorite,
**S** to sort, **T** for playtime, **Ctrl+Q** to exit.
On a gamepad, use the D-pad and **A** to open a card's details (or play in List);
choose **Play** to launch from details. **Start** opens menu navigation.
Controller navigation pauses while any tracked game is running, while a launch
request is pending, or whenever the launcher is hidden or unfocused. After
returning, release the buttons and center the sticks before browsing resumes.
Mouse and keyboard remain available if you deliberately return to the launcher.

### Fullscreen game windows

Fullscreen is selected by each game's launch command, not by shrinking the
desktop or rewriting shared emulator settings. For native X11 commands whose
fullscreen flag is ignored by the window manager, an individual library entry
can use `python3 /path/to/window_handoff.py <original command and arguments>`.
This opt-in wrapper requests fullscreen only on a unique window belonging to
the launched process, waits for window-manager acknowledgement, and tracks the
game until exit. Missing X11 tools block this opt-in launch with an error;
a window that cannot be identified or changed is reported in the game log.
Commands that delegate the actual window to a different process are not covered.

## Small launcher. Big games.

The launcher uses a Python standard-library backend and vanilla HTML/CSS/JS.
It uses your installed browser instead of bundling an Electron runtime.
Games and emulators remain separate from the launcher.

The development repository also contains tests, release tools and reference
material; those aren't all required in the shipped application. Runtime-only
deliveries use an explicit inventory. The external browser, game runtimes and
your artwork have their own memory and storage costs.

Your library, play history and artwork are stored locally. Online features
include store downloads, approved source/runtime acquisition, Steam lookup and
media-link fetching.

## Keep exploring

- [User guide](USER-GUIDE.md): controls, library editing, setup, backups and recovery.
- [OpenBOR setup](docs/openbor.md): Marvel Infinity War's runtime and controls.
- [Shared-engine fallback](docs/shared-engine-fallback.md): how isolated runtimes work.
- [Repository versus delivery contents](docs/delivery-layout.md): what actually ships.

Developers: the source checkout also includes `docs/development.md` for tests,
build profiles, engine integration and release checks. It is not shipped in
runtime-only deliveries.

### Feedback and support

This is an individual's noncommercial hobby project; support is best-effort.
[Report a problem](https://github.com/jacobm36/momentum-core-launcher/issues)
with the build shown in **About Momentum**, Linux distribution, X11/Wayland
session, package version if relevant, and steps to reproduce. Review logs before
sharing: remove personal paths, API keys and other private information. Do not
upload ROMs, BIOS files, commercial game data or your complete player-state folder.
Installer checks are not gameplay certification; please describe which controls,
display settings or saved-state behavior you actually tested.

---

Launcher code is **MIT licensed**; see [LICENSE](LICENSE). Game content and
package components retain their own notices.

**Build your arcade. Keep your setup. Hit PLAY.**
