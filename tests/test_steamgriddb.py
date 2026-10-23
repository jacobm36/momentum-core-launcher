"""Artwork provider checks do not use real credentials or contact the network."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

import steamgriddb as sg


class SteamGridDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "settings" / "key"
        patch = mock.patch.object(sg, "key_path", return_value=self.path)
        patch.start()
        self.addCleanup(patch.stop)

    def test_key_permissions_replace_and_remove(self):
        self.assertEqual(sg.read_key(), "")
        sg.save_key("a" * 32)
        self.assertEqual(sg.read_key(), "a" * 32)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        sg.save_key("b" * 32)
        self.assertEqual(sg.read_key(), "b" * 32)
        for key in ("bad", None, ["a" * 32], "a" * 32 + "\n"):
            with self.subTest(key=key), self.assertRaises(sg.GridError):
                sg.save_key(key)
        sg.save_key("")
        self.assertFalse(self.path.exists())

    def test_search_and_artwork_use_explicit_provider_identity(self):
        with mock.patch.object(sg, "request", return_value=[{"id": 123, "name": "Alien³"}]) as request:
            self.assertEqual(sg.search("Alien 3 / Gun"), [{"id": "123", "name": "Alien³"}])
            request.assert_called_once_with("search/autocomplete/Alien%203%20%2F%20Gun")
        image = {"url": "https://cdn2.steamgriddb.com/hero/a.png",
                 "thumb": "https://cdn2.steamgriddb.com/thumb/a.png"}
        with mock.patch.object(sg, "request", return_value=[image, {**image, "nsfw": True}]) as request:
            self.assertEqual(sg.artwork("123", "heroes"), [image])
            self.assertIn("heroes/game/123?", request.call_args.args[0])
            self.assertIn("nsfw=false", request.call_args.args[0])
        for value in ("", "0", "-1", "a", "1/../../", None):
            with self.subTest(value=value), self.assertRaises(sg.GridError):
                sg.game_id(value)
        with self.assertRaises(sg.GridError):
            sg.artwork("123", "invalid")
        with self.assertRaises(sg.GridError):
            sg.search("")
        with mock.patch.object(sg, "request", return_value=[None]):
            with self.assertRaises(sg.GridError):
                sg.search("Game")
            with self.assertRaises(sg.GridError):
                sg.artwork("123", "heroes")
        with mock.patch.object(sg, "request", return_value=[{**image, "url": "http://localhost/private"}]):
            with self.assertRaises(sg.GridError):
                sg.artwork("123", "heroes")

    def test_authenticated_request_and_errors_never_return_key(self):
        with self.assertRaisesRegex(sg.GridError, "Set up"):
            sg.request("search/autocomplete/Game")
        sg.save_key("a" * 32)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"success": True, "data": []}).encode()
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(sg.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(sg.request("search/autocomplete/Game"), [])
            req = opener.open.call_args.args[0]
            self.assertEqual(req.get_header("Authorization"), "Bearer " + "a" * 32)
            self.assertTrue(req.full_url.startswith("https://www.steamgriddb.com/api/v2/"))
            for code in (401, 403, 429, 500, 302):
                opener.open.side_effect = urllib.error.HTTPError(
                    req.full_url, code, "a" * 32, {}, io.BytesIO(b"private"))
                with self.subTest(code=code), self.assertRaises(sg.GridError) as error:
                    sg.request("search/autocomplete/Game")
                self.assertNotIn("a" * 32, str(error.exception))
            opener.open.side_effect = None
            for body in (b"not json", b"[]", b'{"success":false}', b"x" * ((2 << 20) + 1)):
                response.__enter__.return_value.read.return_value = body
                with self.assertRaises(sg.GridError):
                    sg.request("search/autocomplete/Game")
        self.assertIsNone(sg.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere/"))
