import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "py_modules"))
sys.path.insert(0, HERE)

from fake_romm import FakeRomm  # noqa: E402
from romm import emulators, launchers, library, provision  # noqa: E402
from romm.client import RommClient, RommError  # noqa: E402
from romm.installer import PART_SUFFIX, Cancelled, cleanup_parts, delete_owned, install, platform_dir  # noqa: E402

NO_CANCEL = lambda: False  # noqa: E731


def progress_log():
    seen = []
    return seen, lambda phase, done, total: seen.append((phase, done, total))


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRomm()
        self.fake.add_rom(1, "snes", "ActRaiser.smc", {"ActRaiser.smc": os.urandom(300_000)})
        self.fake.add_rom(2, "psx", "Chrono Cross", {
            "Chrono Cross (Disc 1).chd": os.urandom(200_000),
            "Chrono Cross (Disc 2).chd": os.urandom(150_000),
        }, multi=True)
        self.fake.add_rom(3, "arcade", "pacman.zip", {"pacman.zip": b"z" * 1000}, fs_slug="MAME")
        self.client = RommClient(self.fake.start(), token="t")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.fake.stop()
        self.tmp.cleanup()

    def rom(self, rid):
        return library.rom_detail(self.client.get_rom(rid))

    def test_single_file(self):
        seen, prog = progress_log()
        res = install(self.client, self.rom(1), self.root, "snes", prog, NO_CANCEL)
        path = os.path.join(self.root, "snes", "ActRaiser.smc")
        self.assertEqual(os.path.getsize(path), 300_000)
        self.assertEqual(res["launch_target"], "ActRaiser.smc")
        self.assertEqual(res["files"], [{"rel": "ActRaiser.smc", "size": 300_000, "owned": True}])
        self.assertEqual(seen[-1][0], "finalizing")
        self.assertFalse(os.path.exists(path + PART_SUFFIX))

    def test_multi_disc_gets_m3u(self):
        res = install(self.client, self.rom(2), self.root, "psx", lambda *a: None, NO_CANCEL)
        gd = os.path.join(self.root, "psx", "Chrono Cross")
        self.assertEqual(res["launch_target"], os.path.join("Chrono Cross", "Chrono Cross.m3u"))
        with open(os.path.join(gd, "Chrono Cross.m3u")) as f:
            self.assertEqual(f.read().splitlines(), ["Chrono Cross (Disc 1).chd", "Chrono Cross (Disc 2).chd"])
        self.assertTrue(res["game_dir_owned"])
        removed = delete_owned(res)
        self.assertEqual(len(removed), 3)
        self.assertFalse(os.path.exists(gd))

    def test_adopts_existing_and_uninstall_keeps_it(self):
        rom = self.rom(1)
        os.makedirs(os.path.join(self.root, "snes"))
        path = os.path.join(self.root, "snes", "ActRaiser.smc")
        with open(path, "wb") as f:
            f.write(self.fake.roms[1]["content"][100])
        self.fake.requests.clear()
        res = install(self.client, rom, self.root, "snes", lambda *a: None, NO_CANCEL)
        self.assertFalse(res["files"][0]["owned"])
        self.assertFalse(any("/content/" in p for p, _ in self.fake.requests), "should not download")
        self.assertEqual(delete_owned(res), [])
        self.assertTrue(os.path.exists(path))
        # Only when asked: the adopted file goes too.
        self.assertEqual(delete_owned(res, include_adopted=True), [path])
        self.assertFalse(os.path.exists(path))

    def test_conflicting_file_is_not_overwritten(self):
        os.makedirs(os.path.join(self.root, "snes"))
        path = os.path.join(self.root, "snes", "ActRaiser.smc")
        with open(path, "wb") as f:
            f.write(b"something else")
        with self.assertRaises(RommError) as cm:
            install(self.client, self.rom(1), self.root, "snes", lambda *a: None, NO_CANCEL)
        self.assertEqual(cm.exception.code, "conflict")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"something else")

    def test_resumes_partial_download(self):
        data = self.fake.roms[1]["content"][100]
        os.makedirs(os.path.join(self.root, "snes"))
        with open(os.path.join(self.root, "snes", "ActRaiser.smc" + PART_SUFFIX), "wb") as f:
            f.write(data[:120_000])
        self.fake.requests.clear()
        install(self.client, self.rom(1), self.root, "snes", lambda *a: None, NO_CANCEL)
        self.assertIn(("/api/roms/1/content/ActRaiser.smc", "bytes=120000-"), self.fake.requests)
        with open(os.path.join(self.root, "snes", "ActRaiser.smc"), "rb") as f:
            self.assertEqual(f.read(), data)

    def test_server_ignoring_range_restarts_cleanly(self):
        self.fake.honour_range = False
        data = self.fake.roms[1]["content"][100]
        os.makedirs(os.path.join(self.root, "snes"))
        with open(os.path.join(self.root, "snes", "ActRaiser.smc" + PART_SUFFIX), "wb") as f:
            f.write(data[:120_000])
        install(self.client, self.rom(1), self.root, "snes", lambda *a: None, NO_CANCEL)
        with open(os.path.join(self.root, "snes", "ActRaiser.smc"), "rb") as f:
            self.assertEqual(f.read(), data)

    def test_cancel_then_cleanup(self):
        rom = self.rom(2)
        with self.assertRaises(Cancelled):
            install(self.client, rom, self.root, "psx", lambda *a: None, lambda: True)
        cleanup_parts(platform_dir(self.root, "psx"), rom)
        self.assertEqual(os.listdir(os.path.join(self.root, "psx")), [])

    def test_zip_hash_is_of_the_member(self):
        import hashlib, io, zipfile
        inner = os.urandom(5000)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("game.nes", inner)
        self.fake.add_rom(4, "nes", "game.zip", {"game.zip": buf.getvalue()})
        self.fake.roms[4]["rom"]["files"][0]["md5_hash"] = hashlib.md5(inner).hexdigest()
        res = install(self.client, self.rom(4), self.root, "nes", lambda *a: None, NO_CANCEL)
        self.assertTrue(res["files"][0]["owned"])
        # And a second install adopts it (same member hash).
        res = install(self.client, self.rom(4), self.root, "nes", lambda *a: None, NO_CANCEL)
        self.assertFalse(res["files"][0]["owned"])
        # A wrong member hash is still caught.
        os.remove(os.path.join(self.root, "nes", "game.zip"))
        self.fake.roms[4]["rom"]["files"][0]["md5_hash"] = "0" * 32
        with self.assertRaises(RommError):
            install(self.client, self.rom(4), self.root, "nes", lambda *a: None, NO_CANCEL)

    def test_platform_dir_reuses_case_variant(self):
        os.makedirs(os.path.join(self.root, "mame"))
        res = install(self.client, self.rom(3), self.root, "MAME", lambda *a: None, NO_CANCEL)
        self.assertEqual(res["platform_dir"], os.path.join(self.root, "mame"))

    def test_unsafe_names_rejected(self):
        bad = {"id": 9, "name": "x", "fs_name": "..", "multi_file": True,
               "files": [{"id": 1, "name": "a.bin", "size": 1, "md5": None, "subdir": ""},
                         {"id": 2, "name": "b.bin", "size": 1, "md5": None, "subdir": ""}]}
        with self.assertRaises(RommError):
            install(self.client, bad, self.root, "psx", lambda *a: None, NO_CANCEL)


class EmulatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.makedirs(os.path.join(self.home, ".local/share/flatpak/app/org.libretro.RetroArch"))
        self.cfgdir = emulators.ra_config_dir(self.home)
        os.makedirs(os.path.join(self.cfgdir, "cores"))

    def tearDown(self):
        self.tmp.cleanup()

    def core(self, name):
        open(os.path.join(self.cfgdir, "cores", f"{name}_libretro.so"), "w").close()

    def flatpak(self, app):
        os.makedirs(os.path.join(self.home, ".local/share/flatpak/app", app))

    def appimage(self, name, exe=True):
        d = os.path.join(self.home, "Applications")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        open(p, "w").close()
        os.chmod(p, 0o755 if exe else 0o644)
        return p

    def test_prefers_ready_core_then_downloadable(self):
        self.assertEqual(emulators.resolve(self.home, "snes")["status"], "core_missing")
        self.assertEqual(emulators.resolve(self.home, "snes")["core"], "snes9x")
        self.core("bsnes")
        self.assertEqual(emulators.resolve(self.home, "snes")["core"], "bsnes")  # ready beats a download
        self.core("snes9x")
        self.assertEqual(emulators.resolve(self.home, "snes")["core"], "snes9x")

    def test_standalone_first_and_override(self):
        self.core("swanstation")
        self.assertEqual(emulators.resolve(self.home, "psx")["id"], "retroarch:swanstation")
        self.appimage("DuckStation-x64.AppImage")
        self.assertEqual(emulators.resolve(self.home, "psx")["id"], "duckstation")
        self.assertEqual(emulators.resolve(self.home, "psx", override="retroarch:swanstation")["id"],
                         "retroarch:swanstation")
        # An override that isn't installed falls back to the default.
        self.assertEqual(emulators.resolve(self.home, "psx", override="nope")["id"], "duckstation")

    def test_appimage_vs_flatpak_preference(self):
        self.flatpak("net.pcsx2.PCSX2")
        self.assertEqual(emulators.detect(self.home, "pcsx2"), ["/usr/bin/flatpak", "run", "net.pcsx2.PCSX2"])
        p = self.appimage("pcsx2-Qt.AppImage")
        self.assertEqual(emulators.detect(self.home, "pcsx2"), [p])  # EmuDeck's AppImage wins
        self.flatpak("org.ppsspp.PPSSPP")
        self.appimage("PPSSPP.AppImage")
        self.assertEqual(emulators.detect(self.home, "ppsspp")[0], "/usr/bin/flatpak")

    def test_errors(self):
        with self.assertRaises(RommError) as cm:
            emulators.resolve(self.home, "ps2")
        self.assertEqual(cm.exception.code, "no_emulator")
        with self.assertRaises(RommError) as cm:
            emulators.resolve(self.home, "ps4")
        self.assertEqual(cm.exception.code, "unsupported_platform")
        # RomM slug unknown, folder name known: falls back to the folder name.
        self.assertEqual(emulators.resolve(self.home, "sega-genesis", "genesis")["core"], "genesis_plus_gx")

    def test_argv_and_appimage_exec_bit(self):
        p = self.appimage("pcsx2-Qt.AppImage", exe=False)
        choice = emulators.resolve(self.home, "ps2")
        self.assertEqual(emulators.argv(self.home, choice, "/r/g.chd"), [p, "-batch", "-fullscreen", "/r/g.chd"])
        self.assertTrue(os.access(p, os.X_OK))
        self.core("snes9x")
        ra = emulators.argv(self.home, emulators.resolve(self.home, "snes"), "/r/a.smc")
        self.assertEqual(ra[:4], ["/usr/bin/flatpak", "run", "org.libretro.RetroArch", "-L"])
        self.assertTrue(ra[4].endswith("snes9x_libretro.so"))

    def test_reads_redirected_paths_from_cfg(self):
        with open(os.path.join(self.cfgdir, "retroarch.cfg"), "w") as f:
            f.write('system_directory = "/home/deck/Emulation/bios"\nlibretro_directory = "~/cores"\n')
        p = emulators.ra_paths(self.home)
        self.assertEqual(p["system"], "/home/deck/Emulation/bios")
        self.assertEqual(p["cores"], os.path.join(self.home, "cores"))
        self.assertEqual(emulators.bios_dir(self.home, "retroarch"), "/home/deck/Emulation/bios")

    def test_standalone_bios_dirs(self):
        self.appimage("DuckStation.AppImage")
        d = os.path.join(self.home, ".local/share/duckstation")
        os.makedirs(d)
        with open(os.path.join(d, "settings.ini"), "w") as f:
            f.write("[Main]\nX = 1\n[BIOS]\nSearchDirectory = /home/deck/Emulation/bios\n")
        self.assertEqual(emulators.bios_dir(self.home, "duckstation"), "/home/deck/Emulation/bios")
        # PCSX2 Flatpak: relative "bios" is relative to its config dir.
        self.flatpak("net.pcsx2.PCSX2")
        fp = os.path.join(self.home, ".var/app/net.pcsx2.PCSX2/config/PCSX2")
        os.makedirs(os.path.join(fp, "inis"))
        with open(os.path.join(fp, "inis", "PCSX2.ini"), "w") as f:
            f.write("[Folders]\nBios = bios\n")
        self.assertEqual(emulators.bios_dir(self.home, "pcsx2"), os.path.join(fp, "bios"))
        self.assertIsNone(emulators.bios_dir(self.home, "dolphin"))

    def test_launcher_script(self):
        self.core("snes9x")
        res = emulators.resolve(self.home, "snes")
        argv = emulators.argv(self.home, res, "/roms/snes/It's (USA).smc")
        self.assertTrue(launchers.write(self.home, 4023, "Act\nRaiser", argv))
        self.assertFalse(launchers.write(self.home, 4023, "Act\nRaiser", argv))  # unchanged
        path = launchers.script_path(self.home, 4023)
        self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR)
        with open(path) as f:
            body = f.read()
        self.assertEqual(body.count("\n"), 3)
        self.assertIn("exec /usr/bin/flatpak run org.libretro.RetroArch -L", body)
        self.assertIn("'/roms/snes/It'\"'\"'s (USA).smc' \"$@\"", body)
        launchers.remove(self.home, 4023)
        self.assertFalse(os.path.exists(path))


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_download_core_from_zip(self):
        import io, zipfile
        from unittest import mock
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("snes9x_libretro.so", b"ELF...")

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()

        with mock.patch.object(provision, "urlopen", return_value=Resp(buf.getvalue())) as u:
            path = provision.download_core(self.home, "snes9x")
            self.assertIn("buildbot.libretro.com", u.call_args[0][0].full_url)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"ELF...")
        self.assertTrue(os.access(path, os.X_OK))
        with self.assertRaises(RommError):
            provision.download_core(self.home, "../evil")

    def test_fetch_bios_keeps_existing(self):
        fake = FakeRomm()
        fake.firmware[7] = [(1, "scph5501.bin", b"A" * 100), (2, "ps2.bin", b"B" * 50)]
        client = RommClient(fake.start(), token="t")
        try:
            bios = os.path.join(self.home, "bios")
            os.makedirs(bios)
            with open(os.path.join(bios, "scph5501.bin"), "wb") as f:
                f.write(b"mine")
            res = provision.fetch_bios(client, 7, bios)
            self.assertEqual(res, {"added": ["ps2.bin"], "present": ["scph5501.bin"]})
            with open(os.path.join(bios, "scph5501.bin"), "rb") as f:
                self.assertEqual(f.read(), b"mine")
        finally:
            fake.stop()


if __name__ == "__main__":
    unittest.main()
