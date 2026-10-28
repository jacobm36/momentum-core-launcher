"""Shortcut discovery is read-only; imports preserve existing library edits."""
import copy
import importlib.util
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

import game_import


class GameImport(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.apps = self.root / "applications"
        self.apps.mkdir()
        self.launcher = self.root / "launcher"
        self.launcher.mkdir()

    def shortcut(self, filename="game.desktop", name="My Game", command='"/path with spaces/game" %U', extra=""):
        path = self.apps / filename
        path.write_text(f"[Desktop Entry]\nType=Application\nName={name}\nExec={command}\nCategories=Game;\n{extra}")
        return path

    def test_read_only_discovery_and_selected_import_no_execution(self):
        source = self.shortcut(extra="Path=/games with spaces\n")
        original = source.read_bytes()
        with mock.patch("subprocess.Popen", side_effect=AssertionError("Must not execute")):
            scan = game_import.discover([], self.apps)
            candidate = scan["candidates"][0]
            self.assertFalse(candidate["reason"])
            self.assertEqual(shlex.split(candidate["entry"]["exec"]), ["/path with spaces/game"])
            self.assertFalse(list(self.launcher.iterdir()))
            chosen = game_import.selected(scan, [{"source": candidate["source"], "sha256": candidate["sha256"]}])
            games, result = game_import.add([], chosen, self.launcher)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(games[0]["cwd"], "/games with spaces")
        self.assertEqual(source.read_bytes(), original)

    def test_existing_edits_and_duplicate_names_commands_are_preserved(self):
        self.shortcut()
        self.shortcut("copy.desktop", "Other Name", "existing-launch")
        games = [{"id": "my-game", "name": "Edited name", "exec": "custom-launch",
                  "cwd": "/custom", "favorite": True, "icon": "custom.png"},
                 {"id": "another", "exec": "existing-launch"}]
        original = copy.deepcopy(games)
        scan = game_import.discover(games, self.apps)
        self.assertTrue(all(c["reason"] for c in scan["candidates"]))
        output, result = game_import.add(games, scan["candidates"], self.launcher)
        self.assertEqual(output, original)
        self.assertEqual(games, original)
        self.assertEqual(len(result["skipped"]), 2)

    def test_duplicate_new_shortcuts_are_reported(self):
        self.shortcut("a.desktop")
        self.shortcut("b.desktop")
        scan = game_import.discover([], self.apps)
        output, result = game_import.add([], scan["candidates"], self.launcher)
        self.assertEqual(len(output), 1)
        self.assertEqual(len(result["skipped"]), 1)

    def test_candidates_are_alphabetical_by_name_not_filename(self):
        self.shortcut("a.desktop", "zork", "zork")
        self.shortcut("b.desktop", "Ábaco", "abaco")
        self.shortcut("c.desktop", "Doom", "doom")
        self.shortcut("d.desktop", "alien", "alien")
        self.shortcut("e.desktop", "Doom", "doom2")
        self.shortcut("f.desktop", "Bad\tName", "bad")
        self.shortcut("g.desktop", "Aa\tName", "aa")
        scan = game_import.discover([], self.apps)
        self.assertEqual([c["entry"]["name"] for c in scan["candidates"]], ["Ábaco", "alien", "Doom", "Doom", "zork"])
        self.assertEqual([c["source"] for c in scan["candidates"]][2:4], ["c.desktop", "e.desktop"])
        self.assertEqual([c["reason"] for c in scan["candidates"]][2:4], [None, "Duplicate of another discovered game"])
        self.assertEqual([c["source"] for c in scan["skipped"]], [str(self.apps / "g.desktop"), str(self.apps / "f.desktop")])

    def test_emulators_are_opt_in_but_game_shortcuts_using_engines_remain(self):
        self.shortcut("uzdoom.desktop", "UZDoom", "uzdoom")
        self.shortcut("mame.desktop", "MAME", "mame")
        self.shortcut("unknown.desktop", "Another Emulator", "another",
                      extra="Categories=Game;Emulator;\n")
        self.shortcut("mod.desktop", "Brutal Doom", "uzdoom -file brutal.pk3")
        self.shortcut("track.desktop", "TrackMania", "/snap/bin/tmnationsforever")
        self.shortcut("arcade.desktop", "L.A. Machineguns", "/custom/game-launcher",
                      extra="Categories=Game;Emulator;\n")
        scan = game_import.discover([], self.apps)
        self.assertEqual({c["entry"]["name"] for c in scan["candidates"]},
                         {"Brutal Doom", "TrackMania", "L.A. Machineguns"})
        self.assertEqual(scan["emulators_hidden"], 3)
        expanded = game_import.discover([], self.apps, include_emulators=True)
        self.assertEqual(len(expanded["candidates"]), 6)
        self.assertEqual(expanded["emulators_hidden"], 0)
        candidate = next(c for c in expanded["candidates"] if c["entry"]["name"] == "MAME")
        selection = [{"source": candidate["source"], "sha256": candidate["sha256"]}]
        with self.assertRaises(game_import.ImportError):
            game_import.selected(scan, selection)
        self.assertEqual(game_import.selected(expanded, selection), [candidate])

    def test_changed_missing_and_invalid_selections_make_no_changes(self):
        path = self.shortcut()
        scan = game_import.discover([], self.apps)
        selected = [{"source": c["source"], "sha256": c["sha256"]} for c in scan["candidates"]]
        path.write_text(path.read_text().replace("My Game", "Changed Game"))
        with self.assertRaisesRegex(game_import.ImportError, "changed"):
            game_import.selected(game_import.discover([], self.apps), selected)
        path.unlink()
        with self.assertRaisesRegex(game_import.ImportError, "disappeared"):
            game_import.selected(game_import.discover([], self.apps), selected)
        for value in (None, [], ["game.desktop"], [{"source": "../other", "sha256": "0" * 64}],
                      selected * 2, [{"source": "game.desktop", "sha256": "0", "exec": "injected"}]):
            with self.subTest(value=value), self.assertRaises(game_import.ImportError):
                game_import.selected(scan, value)
        self.assertFalse(list(self.launcher.iterdir()))

    def test_unrelated_hidden_terminal_and_malformed_shortcuts_reported(self):
        self.shortcut("hidden.desktop", extra="Hidden=true\n")
        self.shortcut("terminal.desktop", extra="Terminal=true\n")
        self.shortcut("missing.desktop", extra="TryExec=/not/installed\n")
        self.shortcut("empty.desktop", command="")
        self.shortcut("not-game.desktop").write_text("[Desktop Entry]\nName=Tool\nCategories=Utility;\n")
        self.shortcut("broken.desktop").write_bytes(b"\xff")
        scan = game_import.discover([], self.apps)
        self.assertFalse(scan["candidates"])
        self.assertEqual(len(scan["skipped"]), 5)
        self.assertEqual(scan["ignored"], 1)

    def test_desktop_fields_steam_and_quoted_arguments(self):
        self.shortcut(command="steam steam://rungameid/123")
        candidate = game_import.discover([], self.apps)["candidates"][0]
        self.assertEqual(shlex.split(candidate["entry"]["exec"]), ["steam", "steam://rungameid/123"])
        command = game_import.command('engine "%c" %% %i %k %f', "Game Name", Path("/a file.desktop"), "/icon.png")
        self.assertEqual(shlex.split(command), ["engine", "Game Name", "%", "--icon", "/icon.png", "/a file.desktop"])
        for invalid in ('engine %z', 'engine "unterminated', 'engine --file=%U', ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                game_import.command(invalid, "Name", Path("/file.desktop"), "")

    def test_icon_copy_is_absent_only_and_warnings_are_explicit(self):
        icon = self.root / "icon.png"
        icon.write_bytes(b"icon")
        self.shortcut(extra=f"Icon={icon}\n")
        candidate = game_import.discover([], self.apps)["candidates"][0]
        output, result = game_import.add([], [candidate], self.launcher)
        self.assertEqual((self.launcher / output[0]["icon"]).read_bytes(), b"icon")
        self.assertFalse(result["warnings"])
        (self.launcher / output[0]["icon"]).write_bytes(b"user edit")
        output, result = game_import.add([], [candidate], self.launcher)
        self.assertEqual(len(result["added"]), 1)
        self.assertIn("Existing icon preserved", result["warnings"][0]["reason"])
        self.assertEqual((self.launcher / "media/my-game/icon.png").read_bytes(), b"user edit")

    def test_cli_default_preserves_edits_update_is_explicit(self):
        self.shortcut(extra="Path=/new/path\n")
        library = self.launcher / "games.json"
        original = [{"id": "my-game", "name": "Edited", "exec": "custom-launch", "cwd": "/custom", "favorite": True}]
        library.write_text(json.dumps(original))
        spec = importlib.util.spec_from_file_location("import_cli", Path(__file__).parents[1] / "import_games.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.object(cli, "HERE", self.launcher), mock.patch("game_import.application_directories", return_value=[self.apps]):
            self.assertEqual(cli.main([]), 0)
            self.assertEqual(json.loads(library.read_text()), original)
            self.assertEqual(cli.main(["--update"]), 0)
            updated = json.loads(library.read_text())[0]
            self.assertEqual(updated["exec"], "'/path with spaces/game'")
            self.assertEqual(updated["cwd"], "/new/path")
            self.assertEqual(updated["name"], "Edited")
            self.assertTrue(updated["favorite"])
            self.assertEqual(cli.main([]), 0)
            self.assertEqual(len(json.loads(library.read_text())), 1)

    def test_limits_and_missing_applications_directory(self):
        self.assertEqual(game_import.discover([], self.root / "absent")["candidates"], [])
        source = self.shortcut()
        source.write_bytes(b"x" * (game_import.MAX_SHORTCUT_BYTES + 1))
        self.assertIn("too large", game_import.discover([], self.apps)["skipped"][0]["reason"])
        with mock.patch.object(game_import, "MAX_SHORTCUTS", 0):
            with self.assertRaisesRegex(game_import.ImportError, "Too many"):
                game_import.discover([], self.apps)

    def test_menu_roots_include_xdg_flatpak_snap_and_deduplicate(self):
        with mock.patch.dict("os.environ", {
                "XDG_DATA_HOME": str(self.root / "data"),
                "XDG_DATA_DIRS": "/custom/share:/usr/share:/custom/share:relative:"}):
            roots = game_import.application_directories()
        self.assertEqual(roots[:3], [self.root / "data/applications",
                                    Path("/custom/share/applications"), Path("/usr/share/applications")])
        self.assertEqual(len(roots), len(set(roots)))
        self.assertIn(Path("/var/lib/snapd/desktop/applications"), roots)
        self.assertIn(Path("/var/lib/flatpak/exports/share/applications"), roots)
        self.assertIn(Path.home() / ".local/share/flatpak/exports/share/applications", roots)

    def test_multiple_roots_precedence_hidden_masks_and_selection_identity(self):
        system = self.root / "system"
        system.mkdir()
        self.shortcut("override.desktop", command="user-game")
        for name, command in (("override.desktop", "system-game"), ("hidden.desktop", "hidden-game"),
                              ("utility.desktop", "old-game"), ("snap.desktop", "/snap/bin/tmnationsforever")):
            (system / name).write_text(
                f"[Desktop Entry]\nName={name}\nExec={command}\nCategories=Game;\n")
        self.shortcut("hidden.desktop", extra="Hidden=true\n")
        self.shortcut("utility.desktop").write_text(
            "[Desktop Entry]\nName=Not a game\nExec=utility\nCategories=Utility;\n")
        with mock.patch.object(game_import, "application_directories", return_value=[self.apps, system]), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("Discovery must not execute")):
            scan = game_import.discover([])
            self.assertEqual([c["entry"]["exec"] for c in scan["candidates"]],
                             ["user-game", "/snap/bin/tmnationsforever"])
            self.assertEqual(len(scan["skipped"]), 1)
            selection = [{"source": c["source"], "sha256": c["sha256"]} for c in scan["candidates"]]
            self.assertEqual(len(game_import.selected(scan, selection)), 2)
            self.assertTrue(all(Path(c["source"]).is_absolute() for c in scan["candidates"]))
            (system / "snap.desktop").write_text("[Desktop Entry]\nName=Changed\nCategories=Game;\nExec=other\n")
            with self.assertRaisesRegex(game_import.ImportError, "changed"):
                game_import.selected(game_import.discover([]), selection)

    def test_nested_desktop_id_override_and_global_limit(self):
        system = self.root / "system"
        (system / "vendor").mkdir(parents=True)
        (system / "vendor/game.desktop").write_text(
            "[Desktop Entry]\nName=System\nExec=system\nCategories=Game;\n")
        self.shortcut("vendor-game.desktop", command="user")
        with mock.patch.object(game_import, "application_directories", return_value=[self.apps, system]):
            self.assertEqual(len(game_import.discover([])["candidates"]), 1)
            with mock.patch.object(game_import, "MAX_SHORTCUTS", 1):
                with self.assertRaisesRegex(game_import.ImportError, "Too many"):
                    game_import.discover([])
