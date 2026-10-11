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
        with mock.patch.object(cli, "HERE", self.launcher), mock.patch("game_import.applications", return_value=self.apps):
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
