# Momentum Core Launcher: User Guide

One window to launch all your games.

## Finding your place and game folders

The library count above the list shows total entries, or matching entries out
of that total when search/tag filters or an artwork-layout collection are active.
Favorites and Recently played never count as extra games.

Your selected game, search text, tag filters, List/Tiles/Grid view and library scroll positions are
remembered across launcher restarts using the same browser profile. Clear the
search/tags (or press controller B outside menu mode) to see the whole library.
If the remembered game no longer matches, reopening selects the first match.

Expand **Settings & tools** at the bottom of the sidebar and choose
**About Momentum** for the version/build identity,
platform and launcher folder. Development checkouts show their Git description,
including a dirty marker for tracked local edits. Candidate bundles show their
base revision and scope; copies without build metadata say unversioned.

Choose **Folders** beside a game's Play controls to open recorded directories.
The working folder comes from the library entry; managed installation receipts
can also supply the game and saves/settings folders. Only existing directories
are offered, and missing folder information is explained rather than guessed.
Some engines store saves elsewhere. Opening a folder requires `xdg-open` and a
working desktop file manager; it does not modify the game or run its launch
command.

On a controller, use Start for menu mode, move focus to About or Folders, and
press A. In these dialogs, A activates a button and B closes the dialog. The
Classic and Featured panels support 1280x720 with scrollable long descriptions
and visible focus outlines.

## SteamGridDB artwork

Edit a game and expand **Find details & artwork online** below the game details.
It groups **Game details — Steam** and **Artwork — SteamGridDB** without
crowding the main form. Both lookups and all manual media controls remain available.
In the artwork section, open **API key setup** and enter
your personal key from https://www.steamgriddb.com/profile/preferences, then
choose **Save / remove key**. The key is stored in
`~/.config/momentum-core/steamgriddb-key` with owner-only permissions. It is
not included in your library, launcher backups or game packages. It is stored
as a local plaintext credential, not in an encrypted keyring. Leave the key
field blank and use that same button to remove the stored key. Never share it
in bug reports.

Expand **Search options & game ID** to use an optional **Artwork search title**
or edit a match manually. These advanced settings and API key setup start
collapsed. An alternate title does not rename your game; otherwise the search
uses the game name. Choose a result,
then choose a background, grid cover or icon. Backgrounds fill **Background art**,
grid covers fill the separate **Grid cover** slot, and icons fill **Icon**. They do not
replace a configured background video. Save the game to apply the artwork and
remember the selected SteamGridDB game ID. **Load saved match** fetches artwork
for that ID without another title search. You may also enter a known
SteamGridDB game ID manually; it is not a Steam app ID. Clear the ID or search
title and save to remove those optional fields.

Grid artwork selected before the separate slot was introduced remains in
Background art; it is not automatically moved or deleted. Choose the portrait
art again for Grid cover if you want to keep different artwork for each layout.

Only explicitly selected full-size artwork is saved, through the normal media
import flow. Search queries go to SteamGridDB and thumbnails load from its
CDN; a network connection is required. Static artwork is requested with NSFW,
humor and epilepsy-tagged results excluded. Missing matches, API errors and
rate limits appear in the artwork section. This is separate from **Get
Steam details**, which still provides Steam descriptions and screenshots.

Imported artwork and videos are untrusted media. Media responses are sandboxed:
SVG icons can still display, but opening a saved icon directly cannot run its
scripts or grant it access to launcher APIs. External resources referenced by
an SVG are blocked; use self-contained artwork or a raster image.

The store lists the currently published packages and their required original
files. Package availability changes independently of launcher releases; use a
current compatible launcher and review each package's setup guidance.
Existing installations are not removed when the catalog changes. Python performs bounded local
server checks. Missing Python or `flock` must be installed through your system
tools; Momentum never elevates itself automatically. Failed startup reports
the server log at `~/.cache/momentum-core-launcher/server.log`.

## Package setup and recovery

### Installed games, uninstall and cached installers

Store cards distinguish **Set up game** (installer not downloaded), **Installer
ready** (downloaded, not installed), **Installed**, and **New version available**.
These use installation receipts, not the age of a download job. An installed
game may still need manual gameplay confirmation; that does not mean its
installation needs to be repeated.

For a package-installed game, choose **Manage installation** in its game details
or List panel. Clicking **Installed** in the store opens the same management
screen; a newer store version also offers **Manage installation** separately.
Choose **Review uninstall**, consent to running the installed package's
preflight code, then review the exact removals/preserved files and explicitly
**Approve and uninstall**. Close the game/engine first. Preflight alone does not
remove files, and cancellation before approval leaves the installation intact.

Uninstall uses the exact version and digest in the receipt, not whichever
version is newest in the store. It removes unchanged installer-owned files,
preserving originals, saves, settings, modified/user-added files, shared engines
and retained lifecycle support. The library entry stays, marked uninstalled with
Play disabled. **Remove from library** is separate: it only removes that entry,
not installed files. Untracked/manual entries have no package uninstall receipt.
Packages include an `uninstall.sh` lifecycle entrypoint, but it requires runner
context and approval evidence; do not run it as a standalone deletion script.

To clear an unused downloaded installer, open **Local packages / import...** in
the store and choose **Remove cached installer** for that exact version. This
does not uninstall games or erase receipts. The installed version's cache is
protected until uninstall; active jobs and recovery journals also block removal.
An old, unused cached version can be removed without changing a newer install.
Exact retained support can restore missing uninstall intake automatically.
Completed job messages can be **Dismissed** in **Installs & jobs**; do not delete
receipts or journals to clear a status. A missing or damaged receipt/support
produces an explicit error rather than guessing which files to delete.

### When approval is blocked

Setup and plan review distinguish missing package evidence, unsupported
platforms, host prerequisites and installed-software mismatches. Missing
evidence includes **Get the latest Momentum launcher**: a newer package may
require a newer launcher. This is not proof that updating will approve arbitrary
package bytes. If the latest launcher still blocks them, the publisher must
validate the exact package/build. Never bypass approval.

Close the old launcher before starting an updated copy; keep its folders and
journals. Missing host packages or an incompatible emulator require the shown
prerequisite/software guidance, not just a launcher update.

### Recovering an incomplete installation

Failed or interrupted package jobs requiring manual attention show **Review
recovery**, not a misleading retry or dismiss shortcut. The review is read-only.
If package apply completed successfully and the saved evidence/files still
match, it offers **Finish registration** after displaying the exact missing
optional user-state paths that will be excluded from the receipt.

Check the consent box to finish the receipt/library entry; this does not reinstall
the game or reset settings. The server rechecks evidence and the reviewed
exclusion list before committing. Managed-file changes, incomplete apply or
uncertain dependency transactions block automatic recovery. The screen explains
the reason and tells you to retain the journal and consult the log. Pending
catalog recovery resumes on restart. Do not delete journals to unblock installs.

### Before installing a store game

After the installer is downloaded (or when you open an already imported package),
setup begins with **Before you install**. This section shows the package's declared
source-folder instructions, distinguishes required files from optional/alternate
sources, and explains software preparation. Download-capable packages show their
content options rather than claiming ROMs are always required.

Only use ROMs and other game files you are legally entitled to use. Momentum does
not supply the original commercial game files required by these setups.
The requirements notice adds no extra consent checkbox. Choose the source folder
in the same window; preflight still validates actual contents, not just filenames.
Older packages without detailed file instructions show general guidance rather
than an invented compatibility claim.

### Using a supplied launcher bundle

Extract a complete launcher bundle into a new folder, without replacing
an existing launcher. Run `bash start-candidate.sh` for a normal window. It
refuses to reuse an already responding server and does not change shortcuts.
Use the same entrypoint for subsequent launches.

Private acceptance bundles also include `start-isolated-test.sh` for separate
test state; runtime-only deliveries do not. In an acceptance bundle, it uses an
acceptance HOME under your real
`~/.local/share/momentum-core/isolated-acceptance-home-v1`; always relaunch with
that script and do not install desktop shortcuts in isolated mode.

Normal mode uses the same user's receipts and installed games even when the
launcher folder differs. New games use `~/Games/<package-id>`; existing receipts
retain their recorded directories. Originals, existing engines and player state
are preserved. Installer validation is separate from gameplay acceptance.

Bundles may include selected installers or just the launcher. Use **Add game >
Browse the package store > Local packages / import...** for bundled/local
installers, or choose a current title from the online store. See
[delivery contents](docs/delivery-layout.md) for what is included.

## 1. Opening the launcher

Game details and the Classic background prefer a preview video, then the first
screenshot (or saved Background art), then the icon. Only one main media item is
shown at a time. If video cannot load or autoplay, still artwork remains
available. The Featured panel retains its separate cover.

- Click **Momentum Core Launcher** in the app menu or on the Desktop.
- Pick a game, then click **▶ PLAY**. In Tiles/Grid, click a card, press
  Enter/Space on it, or press gamepad A to open details before choosing Play.
  In List, Enter/gamepad A still launches directly.
- A green dot next to a game means it's running. The launcher closes its background server by itself shortly after you close the window.

If the icon is ever missing, or you move the project folder, run:

```bash
cd /path/to/your/momentum-core-launcher
./install.sh
```

## 2. Controls

| Action | Keyboard | Gamepad |
|---|---|---|
| Move in List (wraps from the last game to the first and back) | ↑ / ↓ | D-pad / left stick |
| Move in Tiles/Grid (stops at the edges) | ← / ↑ / ↓ / → | D-pad / left stick |
| Open a card's details in Tiles/Grid | Enter / Space on a card | A |
| Play in List, or activate focused Play in details | Enter | A |
| Close details or its topmost dialog | Esc | B |
| Previous/next category | PgUp / PgDn | LB / RB |
| Clear search | Esc | B |
| Favorite / unfavorite the selected game | F, or the ☆ Favorite button | Back / Select |
| Jump to Recently played (press again for the next one) | R | LT |
| Jump to Favorites (press again for the next one) | Shift+F | RT |
| Cycle sort order (Category / Last played / Most played / A–Z) | S | L3 (stick click) |
| Playtime summary | T | R3 (stick click) |
| Notifications history | N | |
| Installs & background jobs | I | |
| Backup & restore | B | |
| Add a game | + Add game button | X |
| Edit the selected game | Edit button | Y |
| Menu mode (reach every button) | Tab | Start |

Alt + ↑ / ↓ moves the selected game up or down within its category in **List
view** (keyboard only; see section 4).

Typing in the search box filters by game name or tag. If your controller isn't detected, press any button once.

### List, Tiles and Grid browsing

Choose a layout above the library: **List**, landscape **Tiles**, or portrait
**Grid** (2:3 covers, like a Steam library). Click a card to open game details
without launching. Use all four arrow keys or the controller
D-pad/left stick to select cards; up/down goes to the closest column in
the adjacent rendered row, including across category headings. Movement stops
at the edges rather than wrapping. Enter/Space on a card or controller A opens
details; choose **PLAY** there or in the compact library bar to launch.
Arrow keys on a focused toolbar control do not browse the cards.

Tiles and Grid share search, tag filters, sorting, category jumps, Favorites and Recently
played with List. In artwork layouts, the sidebar provides **All games**,
**Favorites**, **Recently played**, and **Categories** with counts. Selecting one
filters the cards without opening details or launching a game. All games shows
each entry once; Recently played includes every game with recorded play history,
newest first with the default Category sort. Other sort choices still apply.
Counts beside collections describe the full library, while the count above
reflects the current collection plus search/tag filters.

Search and tags narrow the chosen collection. Clearing them (Esc/controller B)
keeps that collection selected; choose All games to leave it. A changed collection
or filter selects a matching game or clears selection when there are no matches.
Empty Favorites/Recently played remain selectable. If a selected category is
removed or renamed, browsing returns to All games.

Tiles and Grid remember the selected collection across layout changes and
restarts. List ignores it and retains the full library, search/tags, favorite/recent
shortcuts and organization controls. Returning to Tiles/Grid restores the
collection. R/LT and Shift+F/RT open the corresponding focused collection in
artwork layouts, then step through those shortcuts on subsequent presses.

Tiles show static background art, falling back to the game's icon over a color
gradient, then an initial if neither image is available or can load. Grid first
uses **Grid cover**, then fits existing background art without cropping, then
uses the icon or initial. Titles remain visible without artwork. Existing
portrait package art, such as MIW's cover, works without reassignment.
In landscape **Tiles**, the selected card starts its existing video after a
half-second delay. Keyboard/controller movement selects a card; mouse hover
selects without opening details. Only one preview plays, muted and looping.
Moving to another card (or moving the mouse away) restores static artwork.
Missing or unplayable video leaves the image in place; playback failures show
**Preview unavailable** instead of an empty card. Routine refreshes do not
restart a playing preview.

Previews stop when the tile scrolls out of view, any dialog opens, a game is
launching/running, or the launcher loses focus or becomes hidden. Returning can
resume the selected card after the same delay. System reduced-motion preference
disables tile previews. Portrait **Grid** cards remain static; List and the
details dialog retain their existing video behavior.
Decorative selection accents and the Play glow stay static to avoid continuous
idle repainting. Artwork entry, splash and launch transitions remain; the launch
spinner runs only while its overlay is active. Hidden windows pause CSS
animations. Controller discovery checks four times per second when disconnected
or input is suspended, returning to frame-rate polling for an active controller.
The existing effects-off and reduced-motion preferences still apply. The
four-second server refresh remains active so window-close detection and job
status continue to work.
The compact panel below the cards offers Play, Favorite, Folders, Edit, Remove,
tags and play history.

The shared details dialog includes the recorded description, category, runtime,
tags, screenshots and the same management actions. A compact play-history row
labels **Time played**, **Last played** and **Launches** separately. This history
only covers launches tracked by Momentum; play time updates when a game closes.
Unplayed games show **Not played yet** instead of empty statistics.
Below the artwork, **About this version** shows the recorded **Engine / runtime**
and installed **Package version**, when available. Package version identifies
the installer release, not necessarily the game's own version. Unknown details
are omitted; runtime names/builds are displayed as recorded, not inferred from
launch commands. The runtime remains editable in the game's Add/Edit form.
Play is focused
when available; running games cannot be launched again. Screenshots open a
lightbox above details. Existing preview videos play muted and loop, replacing
the still image rather than appearing underneath it. Hover over the video or
Tab to its playback control to reveal the **Pause preview** icon. When paused,
the **Play preview** icon remains visible; touch devices always show the control.
Missing or failed video leaves still artwork and an explanation. Hidden pages
pause playback and resume only previews that were playing, without overriding a
manual pause. Closing details releases the preview, and launching pauses it.
No new videos are fetched automatically. Close/Esc/controller B returns
to the selected card without clearing filters; if a lightbox or another dialog is
on top, close that first. Edit closes details before opening the editor.

Choose **List** to return to full descriptions, screenshots and preview
videos using your existing **Classic/Featured** preference. That preference is
independent of the browsing layout, and its button is hidden in Tiles/Grid.
Drag-to-reorder, Alt+arrow reordering and category move/rename controls remain
in List only.

The chosen browsing view and each view's scroll position are remembered in the
same browser profile. Switching views retains the selected game; navigating
brings it into view. Background refreshes retain your scroll and focus.
Controller **Start** reaches the view switch and other controls in menu mode
without stepping through every tile.

New and revised Momentum packages include a description, portrait Grid art and
a real screenshot; a preview video is preferred. Compatible packages retain
these assets locally so Tiles, Grid and Classic can use them without a network
request. A fresh library entry receives the package presentation. Upgrades
preserve edited descriptions and existing artwork, including explicit clears;
only a previously absent artwork field can be introduced. NVRAM and control
presets seed missing state only, never replacing existing saves or settings.

The sidebar navigation scrolls independently, so long category lists do not push
**Add game** or **Exit** away. Sorting, notifications, and jobs stay beside these
bottom controls. **Settings & tools** groups About Momentum, playtime, backup,
theme, panel style, animations, sound, rumble and fullscreen (when available).
Expand it with a click, Enter/Space on its heading, or controller A in menu mode;
the tool area scrolls if needed. Keyboard T/B and their existing controller
shortcuts still work without opening this group.

### Using a gamepad for everything

- **Menu mode:** press **Start** to move a focus ring between every button (Edit, Remove, the sidebar buttons ➕ ✨ 🔊 ⛶ ⏻, the search box and each category's ▲ ▼ ✎). The D-pad moves the ring, **A** presses the button and **B** or **Start** returns to the game list. Pressing PLAY also returns to the list.
- **Add/edit form:** **X** or **Y** open it. The D-pad moves between fields, **A** on a text field opens an on-screen keyboard, **Start** saves and **B** cancels (if you changed anything it asks before discarding). **Get Steam details** and its result thumbnails can be chosen with A, which fills in the description, tags and art without typing much.
- **On-screen keyboard:** D-pad to a key, **A** to type it, **X** backspace, **Y** space, **Start** done, **B** cancel. ⇧ Shift capitalizes the next letter. A real keyboard also works in it. Renaming a category uses the same keyboard.
- **Confirmations** (Remove, Exit, Discard) are plain dialogs: D-pad to a button and press A, or B to cancel.
- Choosing a file from disk and drag-and-drop still need a mouse. Pasting a link or using the Steam lookup is the controller-friendly way to add art.

### Fullscreen

The launcher opens as a fullscreen kiosk by default: no window frame, title bar or taskbar. Use the **⏻** button to exit, since there is no close button. Alt+F4 also works.

To use a normal maximized window instead (with a title bar, and the **⛶** / F11 fullscreen toggle), run `MCL_WINDOWED=1 ./launch.sh`, or in the app-menu entry change the `Exec=` line to `env MCL_WINDOWED=1 /path/to/launch.sh`. The **⛶** button only appears in windowed mode.

On X11, Momentum temporarily releases its kiosk window's fullscreen state before
launching a game, so it does not cover the game's window. Fullscreen is restored
after the last tracked game exits. This requires `wmctrl` and `xprop`
(`sudo apt install wmctrl x11-utils` on Ubuntu); Momentum never installs them
or elevates itself. A missing tool or failed handoff is reported explicitly.
Windowed Momentum and other browser windows are not changed. This handoff does
not apply to Wayland. Game fullscreen, input settings and saves are unchanged.

If the launcher was already open when you start it again, Chrome reuses that window. Exit first, then reopen.

### Exiting

Click the **⏻** button in the sidebar, or press **Ctrl+Q** (**Esc** only clears the search box), and confirm (use ←/→ or ↑/↓ to switch between Cancel and Exit, Enter to choose, Esc to cancel) to close the launcher window and its background server. Games you started keep running. If an install is still running, only the window closes: the install carries on in the background and the server stops once it finishes. Reopen the launcher to check on it. Closing the window with the window's own close button still works too, and the server stops by itself shortly afterwards.

### Animations and intro

- A short Momentum splash plays when the launcher opens. Press any key, click, or press a gamepad button to skip it.
- Switching games fades in the background art and slides in the title and description. The art drifts slowly, the grid pulses, and PLAY glows gently.
- Pressing PLAY punches the art in, blooms a flash from the PLAY button with a whoosh and impact, then dims the screen with a "launching" spinner for a couple of seconds.
- **Accent colors:** each game tints the launcher's highlights (title line, PLAY button, selection bar, glows) with the dominant color of its art, fading smoothly as you switch. Grey or very dark art keeps the default blue/violet/orange. To choose a color yourself, put a hex value like `#ff3030` in **Accent color** in the Edit form (or `"accent": "#ff3030"` in `games.json`); leave it blank for automatic.
- **Selected-game panel:** in List view, use the **▣ Featured / ▣ Classic** button in the sidebar to switch between the original presentation and a glassy artwork-and-details card. The card includes running/favorite status, play history and the usual game actions. Your choice is remembered independently of List/Tiles/Grid.
- **Selection highlight:** the selected game is brighter and outlined in the game's accent color, with a soft pulse that is shared with the Featured artwork. The pulse stops when animations are off (✨ button) or reduced motion is requested.
- **Controller rumble:** with a gamepad connected, it buzzes when you launch a game (a strong build-up), switch categories, save or favorite, and on errors or removals. A **📳** button appears next to 🔊 while a gamepad is connected; click it (or press A on it) to turn rumble off. Rumble works even if sound is muted, and not every controller or browser supports it.
- Click **✨ On** next to **+ Add game** to turn all of this off (it then shows **✨ Off**). The setting is remembered, and the effects are also off automatically if your system is set to reduce motion.

### Sound effects

Short synthesized sounds play for moving through the list, switching category, opening the form, saving, removing, errors and launching a game. There are no audio files to manage. Click the **🔊** button next to **✨** to mute (**🔇**). The setting is remembered. The splash intro builds a jet-engine roar and rising turbine whine, then hits with an explosive bass impact, cyberpunk synth layers and a short echo; it is switched off with the 🔇 button and with ✨ Off, which skips the intro. The launcher icon starts Chrome with autoplay allowed so the intro sound works without a click. If you open the page in a normal browser tab instead and hear nothing at first, click or press a key once; browsers only allow sound after you interact with the page.

### Play tracking

- Every launch is recorded: when you last played, how many times, and how long.
- The game page shows a line like "Last played 2 hours ago · 5 launches · 3h 20m played".
- In List, favorites you mark with ☆ appear under **★ Favorites** at the top of the sidebar, above Recently played. They also keep their normal place in their category and show a ★. Both shortcut sections are hidden while searching. Favorites are saved in `games.json` and are not affected by editing or reordering. Tiles/Grid use the dedicated Favorites collection instead of duplicate cards.
- In List, the 5 most recently played games appear under **Recently played** at the top of the sidebar (hidden while searching). Tiles/Grid offer a Recently played collection containing all recorded played games.
- Playtime counts the time the launched command keeps running. If a game's command just hands off to another program (some Steam or wrapper scripts do this), the time may be much shorter than your real playtime. If you close the launcher while a game is still running, the time up to that moment is counted.
- Stats are stored in `playstats.json` next to `games.json`. Delete the file to reset everything. Removing a game also removes its stats.

## 3. Folder layout

```
momentum-core-launcher/
├── games.json            ← your game list
├── playstats.json        ← play history (created automatically)
├── media/<game-id>/      ← art and video per game
├── backups/              ← backup snapshots (created automatically / on request)
├── jobs/                 ← background job records and logs
├── packages/             ← imported install packages (read-only copies, created automatically)
├── web/                  ← launcher look and feel (HTML/CSS, one small JS file per feature)
├── backup.py, jobs.py    ← backup/restore and background-job engines
├── installs.py           ← package install orchestration: context, receipts, catalog merge
├── dependencies.py       ← read-only Flycast detection and approved user-scope dependency preparation
├── packages.py           ← imports and checks install packages (folder or ZIP)
├── mcl_intent.py         ← helper install packages use to record changes before making them
├── docs/                 ← user references and required runtime compatibility evidence
├── server.py             ← small local server that starts games
├── launch.sh             ← what the icon runs
├── install.sh            ← creates the app menu + Desktop icon
└── import_games.py       ← command-line shortcut import
```

The source repository and full acceptance bundles also contain `tests/`,
developer `tools/` and the optional legacy `cleanup_shortcuts.py` utility.
Runtime-only deliveries omit those development files. Personal data and
recovery journals are not disposable application files; see
[repository versus delivery contents](docs/delivery-layout.md).

## 4. Managing games in the launcher

You can do everything from the launcher window with the mouse and keyboard, and nearly everything with a gamepad (see section 2). Only choosing a file from disk and drag-and-drop need a mouse. Changes are saved to `games.json` straight away.

**Add a game:** click **+ Add game** at the bottom of the sidebar. Three choices are visible here and on the empty-library welcome screen:

- **Import installed games:** review game shortcuts from user and system application menus, including Flatpak and Snap exports. Select the games you trust, then choose **Import selected games**. Momentum shows what was added or skipped; existing entries and edited commands are never refreshed by this UI. Scanning and importing do not run game commands or install software. Steam games appear if they have game menu shortcuts; this does not enumerate every Steam library. Hidden, invalid and terminal-only game shortcuts are reported as skipped. File-based icons are copied only when absent; icon warnings are shown.

  Discovery checks `$XDG_DATA_HOME/applications` (default
  `~/.local/share/applications`), then applications directories in
  `$XDG_DATA_DIRS` order. Standard system, user/system Flatpak and Snap menu
  locations are included even when missing from the launcher's environment.
  Emulator and game-engine launchers are excluded by default. Check **Include
  emulators and game engines** to rescan with them included; changing this
  option clears the current selections. Detection uses known launcher names
  (including MAME and UZDoom), emulator names and non-game Emulator entries.
  Game shortcuts are not excluded solely for also having an Emulator category.
  Named games/mods that use an engine remain discoverable. Existing library
  entries are unaffected. The command-line importer offers the same option as
  `--include-emulators`.

  Duplicate directories are scanned once. The first occurrence of a desktop
  ID wins, including hidden/non-game overrides; nested desktop entries use
  their standard dash-separated desktop IDs. Only entries categorized as
  games are offered. The review shows each shortcut's full source path.
- **Add a game manually:** use your own launch command or script. Name and launch command are required; working directory, category, tagline, runtime badge, description, tags and artwork are optional.
- **Browse the package store:** choose a supported game and set it up from your local files. The store currently specializes in three areas: **OpenBOR** (fan-made beat 'em ups), **Momentum Mouse Arcade** (light-gun and rail shooters played with the mouse) and **Boomer Shooters** (Quake, Doom, Duke and community mods). These sections describe what the store offers, not what your library can hold. Each card shows a badge naming the engine the package uses, such as UZDoom, vkQuake, Flycast, Supermodel or OpenBOR 6391. See [guided setup](#notifications-installs-and-backups) below. The store is optional; existing Steam, native and emulator launches do not require a Momentum package.

**Edit a game:** select it and click **Edit** under the PLAY button. Change any field, choose a new file to replace art or video, or click **remove** next to a current file to clear it.

**Grid cover** is a separate optional image slot in the editor. Upload/drop a
PNG, JPEG or WebP, paste an image URL into that slot, or choose SteamGridDB's
Grid covers. It does not replace Background art or Background video. Clearing
it returns Grid to the normal fallback artwork. Library backups preserve the
slot; include media to preserve its image bytes too.

**Remove a game:** select it and click **Remove**, then confirm. This only removes it from the launcher. The game and its `media/` folder are not deleted.

**Reorder games:**
- Drag a game in the sidebar and drop it above or below another game. A blue line shows where it will land.
- Dropping onto a game in a different category moves it into that category.
- Dropping onto a category heading puts it at the top of that category.
- Or press **Alt + ↑ / ↓** to move the selected game within its category.

**Reorder and rename categories:** hover over a category heading to show **▲ ▼ ✎**. Use the arrows to move the whole category up or down, and ✎ to rename it. Renaming to a name that already exists merges the two categories.

Reordering and dragging are turned off while the search box has text, so clear the search first.

**Art, video and descriptions in the Add/Edit form**

- **Choose, drop or paste:** for each of background art, icon and video you can click *Choose File*, drag a file onto its box, or paste a link (https://) and the launcher downloads it for you. In the form, pasting an image from your clipboard sets the background art. A preview appears before you save.
- **Video frame for tile artwork:** in Edit, find **Background video**. Use its
  player controls to scrub to a moment, or **Back 1s / Forward 1s** and
  **Play preview / Pause preview** to adjust it. Choose **Capture frame for Tiles**.
  Capture pauses playback and shows the resulting image below the controls at
  its original video resolution. It stages a JPEG in **Background art**; choose
  **Save** to apply it, **Discard captured frame** to restore your earlier artwork
  choice, or Cancel to abandon the edit. Capture/preview alone does not save or
  upload anything. Portrait Grid cover stays unchanged; Background art is also
  used by List and the details dialog. Capture requires a loaded local or already
  saved video. For a pasted remote video link, save first and reopen Edit if
  capture is blocked. Load, capture and save errors are shown explicitly.
- **Game details — Steam:** type the game's name and click **Get Steam details**, then click the right match. It fills in the description, tags and tagline (the developer), and offers screenshots to pick as the background, plus an icon. Check the result and edit it freely. Games that aren't on Steam (most Doom mods, arcade ports) usually won't match. Steam trailers can't be downloaded this way, so add videos yourself.
- **Quick art without opening the form:** drop an image or video file on the game page to set its background art or video. Pasting an image (Ctrl+V) while the game page is showing sets the background art.
- **Link safety:** only public http/https links are fetched. Addresses on your own computer or network are refused.

Files you add are copied into `media/<game-id>/`, so your original files are never touched or needed afterwards. Uploaded art is stored in `media/<game-id>/` as `cover.*`, `icon.*` and `video.*`. Accepted types are jpg, png and webp for cover, those plus svg for icon, and mp4 or webm for video (up to 1 GB each).

### Editing `games.json` by hand

You can still edit the file directly if you prefer. Open `games.json` and add an entry to the list (mind the commas):

```json
{
  "id": "my-game",
  "name": "My Game",
  "exec": "/home/you/Games/MyGame/start.sh",
  "cwd": "/home/you/Games/MyGame",
  "category": "Indie & Other",
  "tagline": "A short punchy line",
  "description": "A sentence or two about the game.",
  "tags": ["Action", "Retro"],
  "accent": "#ff3030"
}
```

| Field | Meaning |
|---|---|
| `id` | Unique, lowercase, no spaces. Also the name of its media folder. |
| `name` | Title shown in the launcher. |
| `exec` | The full command to start the game. Quote paths that contain spaces. |
| `cwd` | Optional folder to run the command from. |
| `category` | Sidebar group. Use an existing name or invent a new one. |
| `tagline`, `description`, `tags` | Optional info shown on the game page. |
| `runtime` | Optional engine badge on the game page, e.g. `UZDoom` (up to 40 characters). Also editable in the Add/Edit form. |
| `icon` | Optional small sidebar icon, e.g. `media/my-game/icon.png`. |

Changes show up within a few seconds, with no restart needed. If the launcher shows nothing, there is probably a typo in `games.json`: a missing comma or quote. You can check the file with `python3 -m json.tool games.json`.

**Handy `exec` examples**
- Steam game: `steam steam://rungameid/<AppID>` (the AppID is in the game's Steam store page URL)
- Script: `/home/you/Games/GZDoom/Sigil.sh`
- RetroArch: `/usr/bin/retroarch -f -L /path/to/core_libretro.so /path/to/rom.zip`

**Easier option:** choose **Import installed games** to review and select `.desktop` game shortcuts. The command-line alternative, `./import_games.py`, imports all eligible application-menu game shortcuts from the same locations and reports additions/skips, leaving existing entries alone. Only the explicit CLI option `./import_games.py --update` refreshes matching entries' `exec`/`cwd`; the UI never uses this option.

**Game logs:** each launch writes the game's output to `logs/<game-id>.log`. If a game exits with an error within a few seconds, the launcher shows "Last launch exited with code N" next to the Play button.

## 5. Adding art and video by hand

The easiest way is the **Edit** button (section 4). You can also drop files into `media/<game-id>/`. Create the folder if it doesn't exist. No editing of `games.json` is needed.

| File name | What it does |
|---|---|
| `cover.jpg` (or `.png`, `.webp`) | Full background for the game page. Landscape, 1920×1080 or larger works best. |
| `video.mp4` (or `.webm`) | Muted looping video behind the game info. Keep it short, and prefer H.264 MP4. |
| `icon.png` | Small icon in the sidebar (set via `"icon"` in `games.json`). |

Games with no cover get a colored background instead. Press Ctrl+Shift+R in the launcher window to refresh if art doesn't appear.

## 6. Categories

The sidebar groups games by their `category` value. Groups appear in the order they first show up in `games.json`. Use the ▲ ▼ arrows on a category heading to reorder them, or the ✎ button to rename one (see section 4). Games with no category are listed under "Other".

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| Window doesn't open | Run `./launch.sh` in a terminal to see errors. |
| Game does nothing when launched | Run its `exec` command in a terminal to check it works. |
| RetroArch opens with a title bar or a clipped game image | With RetroArch closed, back up `~/.config/retroarch/retroarch.cfg`. Set `video_fullscreen = "true"`, `video_windowed_fullscreen = "true"` (borderless fullscreen), and both `video_fullscreen_x` and `video_fullscreen_y` to `"0"` (automatic display resolution). |
| Supermodel leaves a strip above the game or clips the bottom | Use `-fullscreen` in the game's wrapper instead of `-window -borderless -window-pos=0,0`. A screen-sized window is not fullscreen: the desktop may place it below the top panel, even when Momentum is closed. |
| Page says "Failed to fetch" | The server stopped. Close the window and click the icon again. |
| Steam lookup or link download fails | It needs an internet connection. Check the link opens in your browser and points straight to an image or mp4/webm file. |
| Port in use | Set another port: `MCL_PORT=48000 ./launch.sh` |
| Controller not responding | Press a button once and make sure the launcher window is focused. |

## 8. Good to know

- Game launches use commands listed in `games.json`; approved package setup also runs the reviewed installer and software-preparation steps. The server only accepts local requests. Store browsing/downloads, approved game/source acquisition, Steam lookup and pasted media links use the internet.
- The launcher rewrites `games.json` when you add, edit, remove or reorder games. Keep a backup copy if you've hand-edited it heavily.
- Closing the launcher doesn't close games you started. They keep running on their own.
- It needs Python 3 and Chrome or Chromium. Otherwise it falls back to your default browser.

## Sorting, tag filter and playtime summary

- The **⇅** button (or **S**) cycles the sidebar order: Category (default), Last played, Most played, A–Z. Your choice is remembered. Non-category orders show one flat list, so drag-to-reorder and Alt+arrow nudging are disabled until you go back to Category.
- Click (or press Enter on) a tag chip in the game panel to search for that tag.
- The **📊** button (or **T**) opens a summary: total playtime, launches, games played, and your five most-played games. Select a game there to jump to it. It also shows your current and best play streaks and a last-7-days chart. Daily history is recorded per game from the first session after this feature was added, so streaks start from then (older totals are kept but have no day attached).

## Notifications, installs and backups

- **🔔 Notifications (N):** pop-up messages (launch errors, finished installs, backups) also land in a history of the last 50 for the current session. Reopening or refreshing the launcher starts with an empty notification history; old saved notifications are discarded. Install/job records remain available separately.
- **📥 Installs & jobs (I):** background jobs with progress, a live log, Cancel, Retry and Dismiss.
  - **Exiting never stops a running job.** The window closes but the job finishes in the background.
  - **Cancel is a request, not a kill.** The job shows "cancel requested" and stops at the next safe point.
  - **Results:** *succeeded*, *needs action* (a prerequisite or manual setup needs attention; this does not necessarily mean installed), *conflicted* (existing files are in the way), *failed*, *cancelled*, or *interrupted* (the computer restarted or the launcher crashed mid-job).
  - **Awaiting approval:** a setup you just started automatically opens each new plan while **Installs & jobs** remains the active screen. Nothing is approved automatically. Closing a review keeps that plan waiting without reopening it repeatedly; choose **Review plan** to return. Closing **Installs & jobs** stops automatic guidance, not the job. The review shows the destination, downloads and manual requirements; expand file changes, backups and technical details as needed. Approval requires a separate confirmation of those exact plan bytes. **Cancel job** cancels the job.
  - **Leftover processes:** if a job's programs are still running after a crash, Retry and Dismiss stay unavailable until they exit.
  - **Retry:** installs restart preflight; simple jobs resume from the failed step. If an install wrote mutation intents or its receipt/catalog commit was interrupted, automatic retry/new package jobs are blocked until those changes are reconciled. A failed install with a successful apply proposal may offer **Reconcile install**. After confirmation, Momentum revalidates the saved approval, mutation journal and current files before committing its receipt. Only missing optional `user-state` files from the approved media inventory can be omitted; missing or changed managed package files stop recovery and retain the journal. Recovery records cannot be dismissed until reconciled.
  - **Step progress:** bars show the current step's measurable progress, not an estimated overall installation percentage. Unknown totals display an indeterminate bar.
  - **Add a supported game:**
    1. Choose **+ Add game → Browse the package store** (or **Add game...** in **Installs & jobs**) and select a supported game.
    2. Momentum downloads and checks the installer from its public GitHub distribution repository. No GitHub account is required. It checks the ZIP size/checksum, package identity/digest and platform; no installer scripts run during downloading.
    3. Under **Where are your game files?**, use **Choose folder...** to select the folder described by that game's setup screen, or type/paste its full path. HOD2 needs your USA CUE and matching BIN tracks together; the Model 3 games need their named ROM ZIP kept zipped. Marvel Infinity War can download its pinned game archive or use the exact offline PAK. The optional installation folder has the same picker. Cancelling leaves the path unchanged. Native selection requires Zenity or KDialog; if unavailable, Momentum shows an error and you can still enter paths manually. No game files are uploaded through the browser. Review trust, request the installation plan, then approve its changes. Your original files stay untouched.
    4. Downloads show progress and can be cancelled. Closing the interface leaves a download running. Reopen **Installs & jobs → Continue setup**, or select the game again after it finishes. Failed downloads can be retried; incomplete files are discarded. Downloads are not completed game installations.
    - The public catalog lists current available titles and package versions. Momentum selects required software; there are no emulator choices or automatic package upgrades. An internet connection is needed to load the public catalog/download new installers. Errors are shown rather than silently falling back to stale data.
    - **System prerequisites are never installed by Momentum and never require passwordless sudo.** If Flatpak is missing, the package screen provides `sudo apt update` and `sudo apt install -y flatpak`; if an emulator lacks required host libraries, it identifies the missing library and shows its known Ubuntu package; Episode Enyo lists `libfuse2t64` and/or `libvulkan1`; and a pinned EDuke32 source build lists its compiler/development packages. Run the displayed commands yourself in a terminal, then retry the job or reopen setup. An unknown library is named but never guessed. Flatpak installs, remotes and runtimes are user-scope only; Momentum does not install or update system-wide software.
    - For a package with exact Flatpak build evidence, a missing UZDoom or Flycast is prepared in user scope and pinned to that evidence-backed commit before any game files are changed. The approved plan shows the commands. A current Flathub build is never silently accepted as compatible; if Flathub no longer offers the tested commit, preparation stops and the package remains blocked until evidence is refreshed. Already-installed engines, including system-wide engines, are not downgraded or otherwise changed.
    - **Episode Enyo** needs your Quake folder containing `id1/pak0.pak` and `id1/pak1.pak`. Version 0.3.0 reuses verified mod files or obtains the pinned mod from its publisher after separate approval; it does not bundle the mod. Existing `enyo` settings/saves are copied without modifying originals. Momentum uses the pinned official vkQuake 1.36.0 AppImage, never the Snap build. FUSE2 and Vulkan loaders are prerequisites. Fullscreen is requested without importing laptop display configuration or forcing a resolution; the wrapper accepts `-window`. Game-only removal retains base copies, settings, saves and the shared engine.
    - **Brutal Doom** requires your `DOOM2.WAD` and uses the approved UZDoom flow. Doom Metal Volume 5 is included but enabled only with `~/.local/bin/brutal-doom --metal`; the incompatible Complete voxel addon is excluded. Existing compatible software is reused. An incompatible existing engine is left alone; separately approved shared-engine fallback uses isolated state. See the package's included player guide for controls and saved-state locations.
    - **HOD2 and Virtua Cop 2** use exact-build Flycast evidence. Existing incompatible engines and profiles are preserved; HOD2's separately approved fallback provides its own state. Current packages seed the owner's right-click reload mapping only when absent; existing mappings are not overwritten. Confirm controls in your installation: shipping the mapping is not new gameplay acceptance.
    - **Star Wars Trilogy Arcade and L.A. Machineguns** use the pinned native Supermodel runtime, prepared after separate approval if missing. Fullscreen is requested. Current packages seed the owner's NVRAM only when absent, preserving existing calibration, scores and settings. SWTA includes the owner's Free Play seed; **L.A. Machineguns Free Play is unconfirmed**, not a promised preset. Existing NVRAM is never overwritten and may need manual cabinet settings or AIM SET. A newer seed does not change an existing cabinet's state.
    - **Marvel Infinity War** uses bundled verified OpenBOR 6391 native files without FUSE or an engine download. Approve engine preparation separately, then download/install the game or supply the exact offline PAK. The fullscreen/CRT configuration and controller preset are seeded only when absent; other controllers can be remapped in-game. Settings and progress stay game-local. See [OpenBOR setup](docs/openbor.md).
    - **Add a game manually** opens the original library editor. Custom artwork uploads and Steam lookup are unchanged.
  - **Install packages (advanced local import):**
    1. Obtain a ZIP from a publisher you trust, or use a package already imported on this computer.
    2. Open **Add game → Browse the package store → Local packages / import...** and **Choose package ZIP...**, or enter an absolute local package-folder/ZIP path and choose **Import path**. ZIP uploads are limited to 1 GiB. Intake validates and copies the package; no package code runs.
    3. Choose **Set up**. Under **Where are your game files?**, choose the folder where your game files already live, or enter its full path. For HOD2, keep the CUE file and all matching BIN tracks together in that folder; the package does not include them. Momentum copies the files and leaves your originals untouched. **Momentum will install your game here** shows the destination inside your own `~/Games`, using a simple folder named after the package, such as `~/Games/the-house-of-the-dead-2`. Expand **Change installation folder** only if you want a different location. A game Momentum already installed keeps its existing folder when you upgrade or repair it, even if it has an older name such as `House of the Dead 2, The (USA)`. **Use an existing library entry** optionally links the installation to an entry without claiming ownership of existing files.
    4. Follow the three-step setup guide: choose files and trust the package, review software if needed, then approve game installation. Software evidence and fingerprints are expandable; required inputs and trust warnings stay visible. Check the trust box and choose **Check installation plan**. This permits preflight code, not installation. Momentum selects the software the game needs; you do not choose an emulator. If required software is missing, review and approve its downloads first. The same game job checks the installed build and then continues to the game-file plan. An untested build stops before changing game files. Package scripts run with your user permissions; checksums establish integrity, not publisher trust or sandboxing. Unsupported platforms cannot proceed.
    5. Keep **Installs & jobs** open: each approval step appears automatically when ready. If you closed it, choose **Review plan** to resume. Reopening the launcher retrieves the same saved waiting plan. **Approve and install** requires matching evidence for that exact package digest and software build. Approval rechecks evidence, receipt state and running software. Unknown builds remain gated, and game-package preflight does not install or upgrade an engine.
    - HOD2 0.1.1 and its approved artwork revisions 0.1.2/0.1.3 use the tested user-scope Flycast v2.7 build. These revisions inherit unchanged installer-code evidence, not separate gameplay runs. Version 0.1.3 restores the original t00ny icon; custom artwork and Steam lookup remain available. Other catalog games have separate installer evidence and do not inherit HOD2 gameplay confirmation.
    - The isolated target test confirmed fullscreen, Start, aiming, firing, off-screen reload and clean exit, with the original Flycast config/data unchanged. This is one laptop's evidence, not fresh-machine certification. A new installation still reports **installed / setup required** until its own gameplay is confirmed.
    - Successful HOD2 receipts are reconciled against approved actions, durable intents, publication inventories and file hashes. Repeat installs retain installation identity and personal library edits. An interrupted receipt/catalog commit retains a replayable journal; ambiguous or changed files stop recovery rather than claiming new ownership.
    - For a command-line check without executing scripts: `python3 packages.py check <folder-or-zip>`.
  - **Required game software (handled within game setup):**
    - Momentum checks for the software automatically. If it is already installed and compatible, no software-preparation review is needed. Technical details and exact commands are available in expandable sections, not as emulator choices.
    - If a download is required, **Review plan → Approve required software** authorizes only that software setup. After compatibility checks, **Approve and install** separately authorizes the game files. Both reviews belong to the same game job and survive closing/reopening the launcher.
    - HOD2 uses user-scope Flycast from official Flathub. Missing Flatpak reports instructions for your Ubuntu system tools; no elevation is attempted. System remotes are untouched; an unexpected user Flathub URL stops for manual resolution. Installed software is never automatically upgraded.
    - An active software transaction is not force-killed by cancellation or UI closure. Cancellation is acknowledged between transactions or after the current one finishes. Shared software stays installed even if later game work fails or is cancelled.
    - Jobs retain a durable command-intent journal before each transaction and its observed exit/state afterward. An uncertain transaction after interruption blocks new jobs and dismissal until reconciled; retry never discards that evidence.
- **💾 Backup & restore (B):** saves your game list, tags, favorites and playtime to `backups/` (optionally with artwork and videos). A config-only backup is made automatically about once a week. Restore from a snapshot or a downloaded `.zip`; the current library is saved first as a `pre-restore` snapshot. Browser settings (sound, sort order, panel style) are not included. Only restore backups you made yourself.
