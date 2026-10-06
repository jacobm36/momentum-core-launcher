# Momentum Core Launcher: User Guide

One window to launch all your games.

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
├── web/                  ← launcher look and feel (HTML/CSS, one small JS file per feature)
├── backup.py, jobs.py    ← backup/restore and background-job engines
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

**Add a game:** click **+ Add game** at the bottom of the sidebar. Name and launch command are required. Everything else is optional: working directory, category (pick an existing one or type a new one), tagline, description, tags, and files for background art, icon and background video.

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

**Easier option:** if the game already has a `.desktop` shortcut with `Categories=Game;`, run `./import_games.py`. It adds any new games and leaves your existing entries alone. Run `./import_games.py --update` to also refresh the `exec`/`cwd` of existing games when their shortcut has changed.

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
  - **Results:** *succeeded*, *needs action* (installed, but something must be finished by hand), *conflicted* (existing files are in the way), *failed*, *cancelled*, or *interrupted* (the computer restarted or the launcher crashed mid-job).
  - **Awaiting approval:** some installs pause after checking your system and show what they plan to do. Approve to continue or Cancel to stop. If the plan changes on retry, it asks again.
  - **Leftover processes:** if a job's programs are still running after a crash, Retry and Dismiss stay unavailable until they exit.
  - **Retry:** installs start again from the beginning and re-check everything. Simple jobs resume from the failed step.
- **💾 Backup & restore (B):** saves your game list, tags, favorites and playtime to `backups/` (optionally with artwork and videos). A config-only backup is made automatically about once a week. Restore from a snapshot or a downloaded `.zip`; the current library is saved first as a `pre-restore` snapshot. Browser settings (sound, sort order, panel style) are not included. Only restore backups you made yourself.
