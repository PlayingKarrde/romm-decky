import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

from romm import library  # noqa: E402
from romm.client import RommClient, RommError, normalize_base_url  # noqa: E402
from romm.pairing import DevicePairing  # noqa: E402
from romm.settings import SettingsStore  # noqa: E402


class SettingsTest(unittest.TestCase):
    def test_identifier_created_once_and_token_private(self):
        with tempfile.TemporaryDirectory() as d:
            s = SettingsStore(d).load()
            self.assertTrue(s.device_identifier.startswith("romm-decky-"))
            s.token = "secret"
            SettingsStore(d).save(s)
            again = SettingsStore(d).load()
            self.assertEqual(again.device_identifier, s.device_identifier)
            self.assertNotIn("secret", json.dumps(again.public()))
            self.assertEqual(os.stat(os.path.join(d, "settings.json")).st_mode & 0o777, 0o600)

    def test_corrupt_and_bad_types_load_as_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "settings.json")
            for content in ("{not json", "[]", json.dumps({"platform_overrides": [1], "server_url": "x"})):
                with open(p, "w") as f:
                    f.write(content)
                s = SettingsStore(d).load()
                self.assertEqual(s.platform_overrides, {})


class ClientTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_base_url(" romm.local:8080/ \r"), "http://romm.local:8080")
        with self.assertRaises(RommError):
            normalize_base_url("")

    def test_basic_and_bearer(self):
        self.assertTrue(RommClient("h", token="t")._auth_header().startswith("Bearer "))
        self.assertTrue(RommClient("h", username="u", password="p")._auth_header().startswith("Basic "))
        with self.assertRaises(RommError):
            RommClient("h")._auth_header()

    def test_poll_maps_rfc8628_codes(self):
        c = RommClient("h")
        for code, expect in (("authorization_pending", None), ("slow_down", None)):
            with mock.patch.object(c, "_json", side_effect=RommError("x", 400, code)):
                self.assertIs(c.device_auth_poll("d"), expect)
        for code, mapped in (("expired_token", "expired"), ("access_denied", "denied")):
            with mock.patch.object(c, "_json", side_effect=RommError("x", 400, code)):
                with self.assertRaises(RommError) as cm:
                    c.device_auth_poll("d")
                self.assertEqual(cm.exception.code, mapped)


class PairingTest(unittest.TestCase):
    def _session(self):
        p = DevicePairing("http://romm.local", "id", "Deck")
        init = {"device_code": "dc", "user_code": "ABCD1234", "verification_path_complete": "/pair/device?user_code=ABCD1234",
                "expires_in": 600, "interval": 5}
        with mock.patch.object(p.client, "device_auth_init", return_value=init):
            p.start()
        return p

    def test_flow(self):
        p = self._session()
        self.assertEqual(p.status()["url"], "http://romm.local/pair/device?user_code=ABCD1234")
        p._next_poll = 0
        with mock.patch.object(p.client, "device_auth_poll", return_value=None):
            self.assertEqual(p.poll()["state"], "waiting")
        # Rate limited: a second immediate poll doesn't hit the server.
        with mock.patch.object(p.client, "device_auth_poll", side_effect=AssertionError("polled too soon")):
            self.assertEqual(p.poll()["state"], "waiting")
        p._next_poll = 0
        with mock.patch.object(p.client, "device_auth_poll", side_effect=RommError("down", 502)):
            st = p.poll()
        self.assertEqual((st["state"], st["error"]), ("waiting", "down"))
        p._next_poll = 0
        with mock.patch.object(p.client, "device_auth_poll", return_value={"access_token": "tok", "device_id": "dev"}):
            self.assertEqual(p.poll()["state"], "done")
        self.assertEqual(p.result["access_token"], "tok")

    def test_denied_and_expired(self):
        p = self._session()
        p._next_poll = 0
        with mock.patch.object(p.client, "device_auth_poll", side_effect=RommError("no", 400, "denied")):
            self.assertEqual(p.poll()["state"], "denied")
        p = self._session()
        p._deadline = 0
        self.assertEqual(p.poll()["state"], "expired")


class LibraryTest(unittest.TestCase):
    def test_game_files_drop_placeholders(self):
        r = {"fs_path": "roms/psx", "fs_name": "CC", "files": [
            {"id": 1, "file_name": "CC (Disc 1).chd", "file_size_bytes": 10, "category": "game", "is_top_level": True,
             "file_path": "roms/psx/CC"},
            {"id": 2, "file_name": "noload.txt", "file_size_bytes": 0, "category": "game", "is_top_level": True},
            {"id": 3, "file_name": "manual.pdf", "file_size_bytes": 5, "category": "manual", "is_top_level": True},
            {"id": 4, "file_name": "track.bin", "file_size_bytes": 7, "category": None, "is_top_level": False,
             "file_path": "roms/psx/CC/data"},
        ]}
        files = library.rom_detail(r)["files"]
        self.assertEqual([f["id"] for f in files], [1, 4])
        self.assertEqual(files[1]["subdir"], "data")

    def test_playlist_only_rom(self):
        r = {"id": 5269, "files": [{"id": 1, "file_name": "CC.m3u", "file_size_bytes": 78, "category": None}],
             "sibling_roms": [{"id": 5268, "name": "Chrono Cross"}]}
        self.assertEqual(library.rom_detail(r)["playlist_for"], [{"id": 5268, "name": "Chrono Cross"}])
        r["files"].append({"id": 2, "file_name": "CC (Disc 1).chd", "file_size_bytes": 9, "category": None})
        self.assertIsNone(library.rom_detail(r)["playlist_for"])

    def test_platforms_hide_empty(self):
        out = library.platforms_summary([{"id": 1, "display_name": "B", "rom_count": 2},
                                         {"id": 2, "display_name": "A", "rom_count": 0},
                                         {"id": 3, "display_name": "a", "rom_count": 1}])
        self.assertEqual([p["id"] for p in out], [3, 1])

    def test_duplicate_platform_names_get_folder(self):
        out = library.platforms_summary([{"id": 1, "display_name": "Arcade", "fs_slug": "MAME", "rom_count": 2},
                                         {"id": 2, "display_name": "Arcade", "fs_slug": "arcade", "rom_count": 1}])
        self.assertEqual(sorted(p["name"] for p in out), ["Arcade (MAME)", "Arcade (arcade)"])


if __name__ == "__main__":
    unittest.main()
