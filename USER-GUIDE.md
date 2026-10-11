# Momentum Core Launcher: User Guide

One window to launch all your games.

The supported public catalog currently contains SWTA 0.2.1 and L.A. Machineguns
0.2.2 only. Other historical installers are withdrawn pending current-standard
acceptance; their downloads remain for reference. Existing installations are
not removed. Startup no longer needs `curl`: Python performs bounded local
server checks. Missing Python or `flock` must be installed through your system
tools; Momentum never elevates itself automatically. Failed startup reports
the server log at `~/.cache/momentum-core-launcher/server.log`.

## Local acceptance candidate

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

The October 9 public launcher release contains the same exact-build evidence
and runtime/recovery helpers as the accepted local candidate. Game ZIPs are
downloaded separately through **Add game**. Update the launcher before using
SWTA 0.2.1 or L.A. Machineguns 0.2.2; old launchers lack their evidence.

The acceptance bundle is a complete, separate launcher, not a four-file patch.
Extract it into a new folder without replacing an existing launcher. Run
`bash start-candidate.sh` from that folder. It refuses to reuse an already
responding launcher and defaults to a normal window. It does not change desktop
shortcuts, install system dependencies, import old jobs or delete old data.

Use **Add game → Local packages / import...** to select the bundled SWTA
0.2.1, L.A. Machineguns 0.2.2, Episode Enyo 0.2.1 or HOD2 0.2.0.
These are local candidates, not necessarily the versions in the public catalog.
Brutal Doom 0.2.0 installer validation is recorded, but its archive is not bundled
pending approval of voxel-addon redistribution rights.

The candidate has exact package/build installer evidence. Changing a package
or using a different emulator build still blocks approval; missing host
prerequisites still require the displayed manual Ubuntu commands. Existing
supported engines are reused in place. New games use `~/Games/<package-id>`.
Receipts and game state remain shared user data even when the launcher folder
is different; a separate folder is not an isolated test account.

Installer tests use synthetic media and do not prove fresh-system gameplay,
graphics capability, calibration or input. Native Supermodel/vkQuake acquisition
is tested in disposable homes; Flatpak acquisition/pinning is covered by
command-level tests rather than a newly provisioned Ubuntu machine.
SWTA retains stock credit settings (**3** for credit, **1** for Start); free play
is a manual cabinet setting. Episode Enyo does not import root `vkQuake.cfg` or
force the reference laptop's display mode.

L.A. Machineguns 0.2.2 seeds absent isolated NVRAM with the clean calibration
confirmed on the reference and debug laptops. It never overwrites existing
NVRAM, including older uncalibrated state; existing installations may still
need manual AIM SET. Calibration persists across launches.

## 1. Opening the launcher

- Click **Momentum Core Launcher** in the app menu or on the Desktop.
- Pick a game on the left, then click **▶ PLAY** (or press Enter / gamepad A).
- A green dot next to a game means it's running. The launcher closes its background server by itself shortly after you close the window.

If the icon is ever missing, or you move the project folder, run:

```bash
cd ~/Projects/GamesRepo/momentum-core-launcher
./install.sh
```

## 2. Controls

| Action | Keyboard | Gamepad |
|---|---|---|
| Move up/down (wraps from the last game to the first and back) | ↑ / ↓ | D-pad / left stick |
| Play | Enter | A |
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

Alt + ↑ / ↓ moves the selected game up or down within its category (keyboard only; see section 4).

Typing in the search box filters by game name or tag. If your controller isn't detected, press any button once.

### Using a gamepad for everything

- **Menu mode:** press **Start** to move a focus ring between every button (Edit, Remove, the sidebar buttons ➕ ✨ 🔊 ⛶ ⏻, the search box and each category's ▲ ▼ ✎). The D-pad moves the ring, **A** presses the button and **B** or **Start** returns to the game list. Pressing PLAY also returns to the list.
- **Add/edit form:** **X** or **Y** open it. The D-pad moves between fields, **A** on a text field opens an on-screen keyboard, **Start** saves and **B** cancels (if you changed anything it asks before discarding). **Look up on Steam** and its result thumbnails can be chosen with A, which fills in the description, tags and art without typing much.
- **On-screen keyboard:** D-pad to a key, **A** to type it, **X** backspace, **Y** space, **Start** done, **B** cancel. ⇧ Shift capitalizes the next letter. A real keyboard also works in it. Renaming a category uses the same keyboard.
- **Confirmations** (Remove, Exit, Discard) are plain dialogs: D-pad to a button and press A, or B to cancel.
- Choosing a file from disk and drag-and-drop still need a mouse. Pasting a link or using the Steam lookup is the controller-friendly way to add art.

## 2d. Fullscreen

The launcher opens as a fullscreen kiosk by default: no window frame, title bar or taskbar. Use the **⏻** button (section 2e) to exit, since there is no close button. Alt+F4 also works.

To use a normal maximized window instead (with a title bar, and the **⛶** / F11 fullscreen toggle), run `MCL_WINDOWED=1 ./launch.sh`, or in the app-menu entry change the `Exec=` line to `env MCL_WINDOWED=1 /path/to/launch.sh`. The **⛶** button only appears in windowed mode.

On X11, Momentum temporarily releases its kiosk window's fullscreen state before
launching a game, so it does not cover the game's window. Fullscreen is restored
after the last tracked game exits. This requires `wmctrl` and `xprop`
(`sudo apt install wmctrl x11-utils` on Ubuntu); Momentum never installs them
or elevates itself. A missing tool or failed handoff is reported explicitly.
Windowed Momentum and other browser windows are not changed. This handoff does
not apply to Wayland. Game fullscreen, input settings and saves are unchanged.

If the launcher was already open when you start it again, Chrome reuses that window. Exit first, then reopen.

## 2e. Exiting

Click the **⏻** button in the sidebar, or press **Ctrl+Q** (**Esc** only clears the search box), and confirm (use ←/→ or ↑/↓ to switch between Cancel and Exit, Enter to choose, Esc to cancel) to close the launcher window and its background server. Games you started keep running. If an install is still running, only the window closes: the install carries on in the background and the server stops once it finishes. Reopen the launcher to check on it. Closing the window with the window's own close button still works too, and the server stops by itself shortly afterwards.

## 2a. Animations and intro

- A short Momentum splash plays when the launcher opens. Press any key, click, or press a gamepad button to skip it.
- Switching games fades in the background art and slides in the title and description. The art drifts slowly, the grid pulses, and PLAY glows gently.
- Pressing PLAY punches the art in, blooms a flash from the PLAY button with a whoosh and impact, then dims the screen with a "launching" spinner for a couple of seconds.
- **Accent colors:** each game tints the launcher's highlights (title line, PLAY button, selection bar, glows) with the dominant color of its art, fading smoothly as you switch. Grey or very dark art keeps the default blue/violet/orange. To choose a color yourself, put a hex value like `#ff3030` in **Accent color** in the Edit form (or `"accent": "#ff3030"` in `games.json`); leave it blank for automatic.
- **Selected-game panel:** use the **▣ Featured / ▣ Classic** button in the sidebar to switch between the original presentation and a glassy artwork-and-details card. The card includes running/favorite status, play history and the usual game actions. Your choice is remembered.
- **Selection highlight:** the selected game is brighter and outlined in the game's accent color, with a soft pulse that is shared with the Featured artwork. The pulse stops when animations are off (✨ button) or reduced motion is requested.
- **Controller rumble:** with a gamepad connected, it buzzes when you launch a game (a strong build-up), switch categories, save or favorite, and on errors or removals. A **📳** button appears next to 🔊 while a gamepad is connected; click it (or press A on it) to turn rumble off. Rumble works even if sound is muted, and not every controller or browser supports it.
- Click **✨ On** next to **+ Add game** to turn all of this off (it then shows **✨ Off**). The setting is remembered, and the effects are also off automatically if your system is set to reduce motion.

## 2b. Sound effects

Short synthesized sounds play for moving through the list, switching category, opening the form, saving, removing, errors and launching a game. There are no audio files to manage. Click the **🔊** button next to **✨** to mute (**🔇**). The setting is remembered. The splash intro builds a rising turbine-like whoosh with climbing arcade synth notes, then crests in a punchy electronic hit and short echo; it is switched off with the 🔇 button and with ✨ Off, which skips the intro. The launcher icon starts Chrome with autoplay allowed so the intro sound works without a click. If you open the page in a normal browser tab instead and hear nothing at first, click or press a key once; browsers only allow sound after you interact with the page.

## 2c. Play tracking

- Every launch is recorded: when you last played, how many times, and how long.
- The game page shows a line like "Last played 2 hours ago · 5 launches · 3h 20m played".
- Favorites you mark with ☆ appear under **★ Favorites** at the very top of the sidebar, above Recently played. They also keep their normal place in their category and show a ★. Both sections are hidden while searching. Favorites are saved in `games.json` and are not affected by editing or reordering.
- The 5 most recently played games appear under **Recently played** at the top of the sidebar (hidden while searching).
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
├── tests/                ← automated tests (python3 -m unittest discover -s tests)
├── server.py             ← small local server that starts games
├── launch.sh             ← what the icon runs
├── install.sh            ← creates the app menu + Desktop icon
├── import_games.py       ← imports games from .desktop shortcuts
└── cleanup_shortcuts.py  ← moves old Desktop shortcuts to a backup (app menu untouched)
```

## 4. Managing games in the launcher

You can do everything from the launcher window with the mouse and keyboard, and nearly everything with a gamepad (see section 2). Only choosing a file from disk and drag-and-drop need a mouse. Changes are saved to `games.json` straight away.

**Add a game:** click **+ Add game** at the bottom of the sidebar. Three choices are visible here and on the empty-library welcome screen:

- **Import installed games:** review game shortcuts from `~/.local/share/applications`. Select the games you trust, then choose **Import selected games**. Momentum shows what was added or skipped; existing entries and edited commands are never refreshed by this UI. Scanning and importing do not run game commands or install software. Steam games appear if they have game shortcuts in this folder; this does not enumerate every Steam library. Hidden, invalid and terminal-only game shortcuts are reported as skipped. File-based icons are copied only when absent; icon warnings are shown.
- **Add a game manually:** use your own launch command or script. Name and launch command are required; working directory, category, tagline, description, tags and artwork are optional.
- **Browse the package store:** choose a supported game and set it up from your local files. See [guided setup](#notifications-installs-and-backups) below. The store is optional; existing Steam, native and emulator launches do not require a Momentum package.

**Edit a game:** select it and click **Edit** under the PLAY button. Change any field, choose a new file to replace art or video, or click **remove** next to a current file to clear it.

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
- **Video frame as cover:** with a video file chosen, click **Use current frame as cover**. Pause the preview where you like first. This works for videos you've picked from your computer or already saved, not for pasted links.
- **Look up on Steam:** type the game's name and click **Look up on Steam**, then click the right match. It fills in the description, tags and tagline (the developer), and offers screenshots to pick as the background, plus an icon. Check the result and edit it freely. Games that aren't on Steam (most Doom mods, arcade ports) usually won't match. Steam trailers can't be downloaded this way, so add videos yourself.
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
| `icon` | Optional small sidebar icon, e.g. `media/my-game/icon.png`. |

Changes show up within a few seconds, with no restart needed. If the launcher shows nothing, there is probably a typo in `games.json`: a missing comma or quote. You can check the file with `python3 -m json.tool games.json`.

**Handy `exec` examples**
- Steam game: `steam steam://rungameid/<AppID>` (the AppID is in the game's Steam store page URL)
- Script: `/home/you/Games/GZDoom/Sigil.sh`
- RetroArch: `/usr/bin/retroarch -f -L /path/to/core_libretro.so /path/to/rom.zip`

**Easier option:** choose **Import installed games** to review and select `.desktop` game shortcuts. The command-line alternative, `./import_games.py`, imports all eligible user game shortcuts and reports additions/skips, leaving existing entries alone. Only the explicit CLI option `./import_games.py --update` refreshes matching entries' `exec`/`cwd`; the UI never uses this option.

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

## 7. Removing the old shortcuts

Once everything launches from the launcher:

```bash
./cleanup_shortcuts.py          # preview what would be moved
./cleanup_shortcuts.py --apply  # move old Desktop shortcuts to a backup (app-menu launchers stay)
./cleanup_shortcuts.py --menu --apply  # also move the app-menu launchers
./cleanup_shortcuts.py --restore  # put them back
```

Only shortcuts whose launch command matches a game in `games.json` are moved. They go to `~/.local/share/momentum-core-launcher-shortcut-backup/`. Steam, Discord and Chrome apps are never touched.

## 8. Troubleshooting

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

## 9. Good to know

- The launcher only runs commands listed in `games.json`, and only accepts requests from your own computer. It goes online only when you use Steam lookup or paste a link.
- The launcher rewrites `games.json` when you add, edit, remove or reorder games. Keep a backup copy if you've hand-edited it heavily.
- Closing the launcher doesn't close games you started. They keep running on their own.
- It needs Python 3 and Chrome or Chromium. Otherwise it falls back to your default browser.

## Sorting, tag filter and playtime summary

- The **⇅** button (or **S**) cycles the sidebar order: Category (default), Last played, Most played, A–Z. Your choice is remembered. Non-category orders show one flat list, so drag-to-reorder and Alt+arrow nudging are disabled until you go back to Category.
- Click (or press Enter on) a tag chip in the game panel to search for that tag.
- The **📊** button (or **T**) opens a summary: total playtime, launches, games played, and your five most-played games. Select a game there to jump to it. It also shows your current and best play streaks and a last-7-days chart. Daily history is recorded per game from the first session after this feature was added, so streaks start from then (older totals are kept but have no day attached).

## Notifications, installs and backups

- **🔔 Notifications (N):** pop-up messages (launch errors, finished installs, backups) also land in a history of the last 50.
- **📥 Installs & jobs (I):** background jobs with progress, a live log, Cancel, Retry and Dismiss.
  - **Exiting never stops a running job.** The window closes but the job finishes in the background.
  - **Cancel is a request, not a kill.** The job shows "cancel requested" and stops at the next safe point.
  - **Results:** *succeeded*, *needs action* (a prerequisite or manual setup needs attention; this does not necessarily mean installed), *conflicted* (existing files are in the way), *failed*, *cancelled*, or *interrupted* (the computer restarted or the launcher crashed mid-job).
  - **Awaiting approval:** choose **Review plan** to see the saved plan's destination, changes, backups, dependency facts, preserved state and manual requirements. Approval requires a separate confirmation of those exact plan bytes. Closing the review does not cancel the job; **Cancel job** does.
  - **Leftover processes:** if a job's programs are still running after a crash, Retry and Dismiss stay unavailable until they exit.
  - **Retry:** installs restart preflight; simple jobs resume from the failed step. If an install wrote mutation intents or its receipt/catalog commit was interrupted, automatic retry/new package jobs are blocked until those changes are reconciled. A failed install with a successful apply proposal may offer **Reconcile install**. After confirmation, Momentum revalidates the saved approval, mutation journal and current files before committing its receipt. Only missing optional `user-state` files from the approved media inventory can be omitted; missing or changed managed package files stop recovery and retain the journal. Recovery records cannot be dismissed until reconciled.
  - **Step progress:** bars show the current step's measurable progress, not an estimated overall installation percentage. Unknown totals display an indeterminate bar.
  - **Add a supported game:**
    1. Choose **+ Add game → Browse the package store** (or **Add game...** in **Installs & jobs**) and select a supported game.
    2. Momentum downloads and checks the installer from its public GitHub distribution repository. No GitHub account is required. It checks the ZIP size/checksum, package identity/digest and platform; no installer scripts run during downloading.
    3. Under **Where are your game files?**, use **Choose folder...** to select the folder described by that game's setup screen, or type/paste its full path. For HOD2, it contains your USA CUE and matching BIN tracks; Virtua Cop 2 needs its Japan GDI and all 39 tracks; the Model 3 games need their named ROM ZIP kept zipped. The optional installation folder has the same picker. Cancelling leaves the path unchanged. Native selection requires Zenity or KDialog; if unavailable, Momentum shows an error and you can still enter paths manually. No game files are uploaded through the browser. Review trust, request the installation plan, then approve its changes. Your original files stay untouched.
    4. Downloads show progress and can be cancelled. Closing the interface leaves a download running. Reopen **Installs & jobs → Continue setup**, or select the game again after it finishes. Failed downloads can be retried; incomplete files are discarded. Downloads are not completed game installations.
    - The catalog includes HOD2, Virtua Cop 2, Star Wars Trilogy Arcade, L.A. Machineguns, Episode Enyo, Brutal Doom 64, Duke Nukem 3D, Brutal Doom, Aliens: Eradication, Ashes 2063: Enriched and Quake Brutalist Jam III. Momentum selects required software; there are no emulator choices or automatic package upgrades. An internet connection is needed to load the public catalog/download new installers. Errors are shown rather than silently falling back to stale data.
    - **System prerequisites are never installed by Momentum and never require passwordless sudo.** If Flatpak is missing, the package screen provides `sudo apt update` and `sudo apt install -y flatpak`; if an emulator lacks required host libraries, it identifies the missing library and shows its known Ubuntu package; Episode Enyo lists `libfuse2t64` and/or `libvulkan1`; and a pinned EDuke32 source build lists its compiler/development packages. Run the displayed commands yourself in a terminal, then retry the job or reopen setup. An unknown library is named but never guessed. Flatpak installs, remotes and runtimes are user-scope only; Momentum does not install or update system-wide software.
    - For a package with exact Flatpak build evidence, a missing UZDoom or Flycast is prepared in user scope and pinned to that evidence-backed commit before any game files are changed. The approved plan shows the commands. A current Flathub build is never silently accepted as compatible; if Flathub no longer offers the tested commit, preparation stops and the package remains blocked until evidence is refreshed. Already-installed engines, including system-wide engines, are not downgraded or otherwise changed.
    - **Episode Enyo** bundles the complete Slave Zero X mod. Choose your Quake folder containing `id1/pak0.pak` and `id1/pak1.pak`; you do not need to download or select the mod separately. Existing `enyo` settings/saves are copied without modifying originals. Momentum uses the pinned official vkQuake 1.36.0 AppImage, never the Snap build. FUSE2 and Vulkan loaders are prerequisites, not gameplay certification. Confirm display, controls, audio and save/relaunch; no fullscreen or new control mapping is forced. Game-only removal retains base copies, settings, saves and the shared engine.
    - **Brutal Doom 64** bundles all four mod files in the guide's loading order. Choose the folder containing `DOOM2.WAD`. Momentum reuses the exact compatible UZDoom 5.0.1 Flatpak in user or default-system scope; missing software is prepared only for your account after separate approval. No GZDoom/Zandronum fallback, persistent sandbox overrides or forced video/input settings. UZDoom settings/saves remain under `~/.var/app/org.zdoom.UZDoom/`. Runtime metadata checks do not prove graphical gameplay; confirm controls, display, sound and save/relaunch.
    - **Brutal Doom**, **Aliens: Eradication** and **Ashes 2063: Enriched** use the same approved UZDoom flow and require your `DOOM2.WAD`. Brutal Doom preserves the v21 baseline: Doom Metal Volume 5 is included but enabled only with `~/.local/bin/brutal-doom --metal`; the incompatible Complete voxel addon is excluded. Aliens 2.0 loads its TC before the eight-map campaign; enable/bind mouse-look, jumping and crouching, with dynamic lights/dark sector lighting recommended. Ashes follows the exact Enriched 2.23 main PK3, without the undocumented Freedoom patch or copied engine resources. Each has separate game content/artwork and preserved original data; shared UZDoom preferences/saves remain untouched. See each included player guide and legal notices, and confirm actual gameplay.
    - **Duke Nukem 3D** includes the complete upscale, voxel and SC-55 music packs. Choose the folder containing registered original/Atomic `DUKE3D.GRP`; optional `DUKE.RTS` and root settings/saves are copied without touching originals. Native EDuke32 is reused from guide locations or built from pinned official source after separate approval, without elevation. Missing Ubuntu build prerequisites require system setup; unknown compiled bytes stay gated. State stays in `~/Games/Duke Nukem 3D - Momentum`. Display/input preferences are not forced. Shareware, World Tour and expansions are outside the verified baseline. Confirm graphics, sound, controls and save/relaunch.
    - **Quake Brutalist Jam III** uses exact official Ironwail 0.8.2, not another Quake engine. Choose your licensed Quake folder containing `id1/pak0.pak` and `id1/pak1.pak`. A complete `qbj3` 1.3 source is reused read-only; optionally choose it separately. Restricted mod assets are not bundled. If source or engine is missing, **Approve software / source preparation** permits only the listed pinned downloads, followed by separate game installation approval. QBJ3 downloads about 2.7 GB and extracts about 6.2 GB; allow about 17 GiB free for a fresh setup. No download resume or commercial base download. Existing incomplete/modified sources need manual reconciliation, not silent replacement. Shared engine/cache remain after removal; installed settings/saves are isolated in the game folder. Fullscreen and mouse-look are launch flags. Confirm actual graphics, sound, controls and save/load/relaunch.
    - Virtua Cop 2 uses standalone Flycast. The Model 3 games use the exact pinned native Supermodel release, prepared after a separate software approval if missing. Existing emulator configuration and saves are not copied or changed. New game settings, NVRAM/calibration and saves are isolated and retained. Installer tests are not gameplay certification: confirm controls, display, sound and saved progress yourself. L.A. Machineguns follows the 1920x1080 X11 borderless reference; fresh calibration may need the cabinet menu.
    - **Add a game manually** opens the original library editor. Custom artwork uploads and Steam lookup are unchanged.
  - **Install packages (advanced local import):**
    1. Obtain a ZIP from a publisher you trust, or use a package already imported on this computer.
    2. Open **Add game → Browse the package store → Local packages / import...** and **Choose package ZIP...**, or enter an absolute local package-folder/ZIP path and choose **Import path**. ZIP uploads are limited to 1 GiB. Intake validates and copies the package; no package code runs.
    3. Choose **Set up**. Under **Where are your game files?**, choose the folder where your game files already live, or enter its full path. For HOD2, keep the CUE file and all matching BIN tracks together in that folder; the package does not include them. Momentum copies the files and leaves your originals untouched. **Momentum will install your game here** shows the destination inside your own `~/Games`, using a simple folder named after the package, such as `~/Games/the-house-of-the-dead-2`. Expand **Change installation folder** only if you want a different location. A game Momentum already installed keeps its existing folder when you upgrade or repair it, even if it has an older name such as `House of the Dead 2, The (USA)`. **Use an existing library entry** optionally links the installation to an entry without claiming ownership of existing files.
    4. Check the trust box and choose **Check installation plan**. Momentum selects the software the game needs; you do not choose an emulator. If required software is missing, review and approve its downloads first. The same game job checks the installed build and then continues to the game-file plan. An untested build stops before changing game files. Package scripts run with your user permissions; checksums establish integrity, not publisher trust or sandboxing. Unsupported platforms cannot proceed.
    5. In **Installs & jobs**, choose **Review plan**. Reopening the launcher retrieves the same saved waiting plan. **Approve and install** requires matching evidence for that exact package digest and software build. Approval rechecks evidence, receipt state and running software. Unknown builds remain gated, and game-package preflight does not install or upgrade an engine.
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
