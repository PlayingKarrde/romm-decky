import asyncio
import dataclasses
import os
import platform
import socket
import subprocess
import threading
from typing import Any, Callable

# decky is injected by Decky Loader at runtime; decky.pyi provides type hints.
import decky

from romm import emulators, jobs, launchers, library, provision, status
from romm.client import RommClient, RommError, normalize_base_url
from romm.images import ImageCache
from romm.installed import InstalledStore, default_root, install_roots
from romm.installer import check_space, delete_owned
from romm.pairing import DevicePairing
from romm.settings import Settings, SettingsStore

log = decky.logger


def _ok(data: Any = None) -> dict:
    return {"ok": True, "data": data}


def _err(e: Exception) -> dict:
    if isinstance(e, RommError):
        return {"ok": False, "error": e.to_dict()}
    log.exception("Unexpected backend error")
    return {"ok": False, "error": {"message": f"Internal error: {e}", "status": None, "code": "internal"}}


class Plugin:
    store: SettingsStore
    settings: Settings
    images: ImageCache
    installed: InstalledStore
    jobs_root: str
    _install_lock: threading.Lock
    pairing: DevicePairing | None = None

    def _client(self) -> RommClient:
        if not self.settings.configured:
            raise RommError("Not paired with a RomM server", code="not_configured")
        return RommClient(self.settings.server_url, token=self.settings.token)

    async def _call(self, fn: Callable[[], Any]) -> dict:
        """Run blocking client code off the event loop and wrap the result."""
        try:
            return _ok(await asyncio.to_thread(fn))
        except Exception as e:  # noqa: BLE001 — surfaced to UI via envelope
            return _err(e)

    # ---- diagnostics -------------------------------------------------------

    async def ping(self) -> dict:
        return {"ok": True, "python": platform.python_version(), "user": decky.DECKY_USER,
                "version": decky.DECKY_PLUGIN_VERSION}

    # ---- settings ----------------------------------------------------------

    async def get_settings(self) -> dict:
        return _ok(self.settings.public())

    async def set_platform_collections(self, enabled: bool) -> dict:
        self.settings = dataclasses.replace(self.settings, steam_platform_collections=bool(enabled))
        self.store.save(self.settings)
        return _ok(self.settings.public())

    async def test_connection(self) -> dict:
        res = await self._call(lambda: self._client().test_connection())
        log.info("Test connection: %s", res["data"] if res["ok"] else res["error"])
        return res

    async def sign_out(self) -> dict:
        """Forget the token locally. The RomM Device/token stays until removed in RomM."""
        self.settings = dataclasses.replace(self.settings, token="", device_id="", username="")
        self.store.save(self.settings)
        log.info("Signed out")
        return _ok(self.settings.public())

    # ---- pairing (RomM device auth) ---------------------------------------

    async def start_pairing(self, server_url: str) -> dict:
        def run():
            url = normalize_base_url(server_url)
            if self.pairing:
                self.pairing.stop()
            name = f"Steam Deck ({socket.gethostname()})"
            self.pairing = DevicePairing(url, self.settings.device_identifier, name,
                                         decky.DECKY_PLUGIN_VERSION).start()
            log.info("Pairing started with %s (user code %s)", url, self.pairing.user_code)
            return self.pairing.status()
        return await self._call(run)

    async def get_pairing_status(self) -> dict:
        def run():
            p = self.pairing
            if not p:
                return {"state": "stopped"}
            st = p.poll()
            if st["state"] == "done" and p.result and self.settings.token != p.result["access_token"]:
                self.settings = dataclasses.replace(
                    self.settings, server_url=p.client.base_url, token=p.result["access_token"],
                    device_id=str(p.result.get("device_id") or ""))
                try:
                    self.settings.username = self._client().me().get("username") or ""
                except RommError as e:
                    log.warning("Paired, but /users/me failed: %s", e)
                self.store.save(self.settings)
                log.info("Paired with %s as %s (device %s, scopes %s)", self.settings.server_url,
                         self.settings.username, self.settings.device_id, p.result.get("scopes"))
            if st["state"] == "done":
                st["settings"] = self.settings.public()
            return st
        return await self._call(run)

    async def stop_pairing(self) -> dict:
        if self.pairing:
            self.pairing.stop()
            self.pairing = None
        return _ok(None)

    # ---- library -----------------------------------------------------------

    async def list_platforms(self) -> dict:
        """Platforms that have ROMs: [{id, slug, fs_slug, name, rom_count, firmware_count}]."""
        return await self._call(lambda: library.platforms_summary(self._client().list_platforms()))

    async def list_collections(self, group: str = "mine") -> dict:
        """group: 'mine' (user + smart) or a virtual kind (franchise, genre, ...)."""
        def run():
            c = self._client()
            if group == "mine":
                return library.collections_summary(c.list_collections(), c.list_smart_collections())
            if group not in library.VIRTUAL_KINDS:
                raise RommError(f"Unknown collection group {group}", code="bad_request")
            return library.virtual_summary(group, c.list_virtual_collections(group))
        return await self._call(run)

    async def list_roms(self, scope: str = "all", scope_id: Any = None, query: str = "", offset: int = 0,
                        limit: int = 50) -> dict:
        """scope: all | platform | collection | smart | virtual. -> {items, total, offset, limit}"""
        limit = max(1, min(int(limit), 100))

        def run():
            kw: dict[str, Any] = {"search": (query or "").strip() or None, "offset": max(0, int(offset)),
                                  "limit": limit}
            if scope == "platform":
                kw["platform_id"] = int(scope_id)
            elif scope == "collection":
                kw["collection_id"] = int(scope_id)
            elif scope == "smart":
                kw["smart_collection_id"] = int(scope_id)
            elif scope == "virtual":
                kw["virtual_collection_id"] = str(scope_id)
            elif scope != "all":
                raise RommError(f"Unknown scope {scope}", code="bad_request")
            return library.page_summary(self._client().list_roms(**kw))
        return await self._call(run)

    async def get_rom(self, rom_id: int) -> dict:
        return await self._call(lambda: library.rom_detail(self._client().get_rom(int(rom_id))))

    # ---- images ------------------------------------------------------------

    async def get_image(self, image_url: str) -> dict:
        """{thumb: dataURL} if cached, else {content_type, size, chunks} for chunked fetch."""
        return await self._call(lambda: self.images.describe(self._client(), image_url))

    async def get_image_chunk(self, image_url: str, index: int) -> dict:
        return await self._call(lambda: self.images.chunk(image_url, index))

    async def save_thumbnail(self, image_url: str, data_url: str) -> dict:
        return await self._call(lambda: self.images.save_thumbnail(image_url, data_url))

    async def get_artwork(self, image_url: str) -> dict:
        """Full-size original as {content_type, size, chunks}; fetch slices with get_image_chunk."""
        return await self._call(lambda: self.images.describe_original(self._client(), image_url))

    # ---- install -----------------------------------------------------------

    def _home(self) -> str:
        return decky.DECKY_USER_HOME

    async def get_install_roots(self) -> dict:
        """{roots: [{id, label, path, free}], selected: path}."""
        def run():
            roots = install_roots(self._home(), self.settings.install_root)
            return {"roots": roots, "selected": default_root(self._home(), self.settings.install_root)}
        return await self._call(run)

    async def set_install_root(self, path: str) -> dict:
        """'' = automatic (EmuDeck's roms folder if present, else ~/Games/RomM)."""
        path = (path or "").strip()
        if path and not os.path.isabs(path):
            return _err(RommError("Install folder must be an absolute path", code="bad_path"))
        self.settings = dataclasses.replace(self.settings, install_root=os.path.normpath(path) if path else "")
        self.store.save(self.settings)
        log.info("Install root set to %s", self.settings.install_root or "(automatic)")
        return _ok(self.settings.public())

    def _resolve(self, slug: str, fs_slug: str = "") -> dict:
        key = emulators.platform_key(slug, fs_slug) or slug
        return emulators.resolve(self._home(), slug, fs_slug, self.settings.platform_overrides.get(key))

    async def get_emulator(self, platform_slug: str, platform_fs_slug: str = "") -> dict:
        """What would run this platform: describe() dict, or an error explaining what's missing."""
        return await self._call(lambda: self._resolve(platform_slug, platform_fs_slug))

    async def get_emulator_settings(self) -> dict:
        """{retroarch: bool, emulators: [{id, name}], platforms: [{key, name, rom_count, options, override, chosen}]}

        Platforms are the server's populated ones that we know how to run.
        """
        def run():
            home = self._home()
            found = emulators.detected(home)
            out, seen = [], set()
            for p in library.platforms_summary(self._client().list_platforms()):
                key = emulators.platform_key(p["slug"], p["fs_slug"])
                if not key or key in seen:
                    continue
                seen.add(key)
                opts = [emulators.describe(home, c, found) for c in emulators.candidates_for(key)]
                try:
                    chosen = self._resolve(p["slug"], p["fs_slug"])["id"]
                except RommError:
                    chosen = None
                out.append({"key": key, "name": p["name"], "rom_count": p["rom_count"], "options": opts,
                            "override": self.settings.platform_overrides.get(key), "chosen": chosen})
            return {
                "retroarch": "retroarch" in found,
                "emulators": [{"id": i, "name": emulators.EMULATORS[i].name} for i in found],
                "platforms": out,
            }
        return await self._call(run)

    async def set_platform_emulator(self, key: str, candidate: str = "") -> dict:
        """Pick the emulator for a platform ('' = automatic), then rewrite the launch
        scripts of installed ROMs on it. Downloads a RetroArch core if needed."""
        def run():
            home = self._home()
            if candidate and candidate not in emulators.candidates_for(key):
                raise RommError("That emulator can't run this platform", code="bad_request")
            overrides = dict(self.settings.platform_overrides)
            if candidate:
                overrides[key] = candidate
            else:
                overrides.pop(key, None)
            self.settings = dataclasses.replace(self.settings, platform_overrides=overrides)
            self.store.save(self.settings)
            updated = self._rewrite_launchers(key)
            log.info("Emulator for %s set to %s; %d launchers rewritten", key, candidate or "(auto)", updated)
            return {"updated": updated}
        return await self._call(run)

    def _rewrite_launchers(self, key: str | None, download: bool = True) -> int:
        """Re-resolve the emulator for installed ROMs (of one platform, or all) and rewrite
        launch scripts whose command changed. download=False skips ROMs whose new choice
        needs a core download (they keep their current script). Returns how many changed."""
        home, n = self._home(), 0
        for rec in self.installed.load().values():
            rkey = emulators.platform_key(rec.get("platform_slug", ""), rec.get("platform_fs_slug", ""))
            if key is not None and rkey != key:
                continue
            choice = self._resolve(rec["platform_slug"], rec["platform_fs_slug"])
            if choice.get("core") and choice["status"] == "core_missing":
                if not download:
                    continue
                provision.download_core(home, choice["core"])
            target = os.path.join(rec["platform_dir"], rec["launch_target"])
            if launchers.write(home, rec["rom_id"], rec["title"], emulators.argv(home, choice, target)):
                self.installed.put(rec["rom_id"], {"emulator": choice["name"]})
                n += 1
        return n

    def _refresh_launchers(self) -> None:
        """At load: keep "Automatic" launchers in step with what's installed now."""
        try:
            n = self._rewrite_launchers(None, download=False)
            if n:
                log.info("Updated %d launch scripts for newly preferred emulators", n)
        except Exception:  # noqa: BLE001 — never block plugin load on this
            log.exception("Refreshing launch scripts failed")

    async def install_retroarch(self) -> dict:
        """flatpak install --user RetroArch, in its own systemd unit (it can take minutes)."""
        def run():
            if "retroarch" in emulators.detected(self._home()):
                return {"started": False, "installed": True}
            cmd = ["systemd-run", "--user", "--quiet", "--collect", "--unit=romm-retroarch-install",
                   emulators.FLATPAK, "install", "--user", "-y", "--noninteractive", "flathub", emulators.RA_APP]
            subprocess.run(cmd, env=jobs.clean_env(), check=True, capture_output=True, timeout=15)
            log.info("Started RetroArch Flatpak install")
            return {"started": True, "installed": False}
        return await self._call(run)

    async def start_install(self, rom_id: int) -> dict:
        return await self._call(lambda: self._launch_install(int(rom_id)))

    async def update_rom(self, rom_id: str) -> dict:
        """Re-download a ROM whose files changed on the server, into the same folder.
        Files the install recorded may be overwritten; the shortcut is kept."""
        def run():
            rec = self.installed.get(rom_id)
            if not rec:
                raise RommError("This ROM isn't installed", code="not_found")
            return self._launch_install(int(rom_id), update=rec)
        return await self._call(run)

    def _launch_install(self, rom_id: int, update: dict | None = None) -> dict:
        rom = library.rom_detail(self._client().get_rom(int(rom_id)))
        if rom.get("playlist_for") is not None:
            other = ", ".join(s["name"] for s in rom["playlist_for"]) or "the game it belongs to"
            raise RommError(f"This is only a disc playlist. Install {other} instead.", code="playlist_only")
        choice = self._resolve(rom["platform_slug"], rom["platform_fs_slug"])  # fails early if none
        # An update stays where the game is; a (re)install goes to the current root.
        root = (os.path.dirname(update["platform_dir"].rstrip("/")) if update
                else default_root(self._home(), self.settings.install_root))
        os.makedirs(root, exist_ok=True)
        total = sum(f["size"] for f in rom["files"])
        # Rough check here (adopted files would need less); the worker checks exactly.
        if not self.installed.get(rom_id):
            check_space(root, total)
        with self._install_lock:
            active = [j for j in jobs.list_jobs(self.jobs_root)
                      if str(j.get("rom_id")) == str(rom_id) and j.get("phase") not in jobs.TERMINAL]
            if active:
                raise RommError("This ROM is already being installed", code="busy")
            job_dir = jobs.create_job(self.jobs_root, {
                "rom_id": str(rom_id), "title": rom["name"], "root": root, "total_bytes": total,
                "server_url": self.settings.server_url, "settings_path": self.store.path,
                "home": self._home(),
                "core": choice.get("core") if choice["status"] == "core_missing" else None,
                "bios_dir": emulators.bios_dir(self._home(), choice["emulator"]),
                "kind": "update" if update else "install",
                "replace": [f["rel"] for f in (update or {}).get("files") or []],
            })
        how = jobs.launch_worker(job_dir, os.path.join(decky.DECKY_PLUGIN_DIR, "py_modules"))
        log.info("%s %s (%s) -> %s via %s", "Update" if update else "Install", rom_id, rom["name"], root, how)
        return {"job_id": os.path.basename(job_dir)}

    async def get_jobs(self) -> dict:
        def run():
            out = []
            for j in jobs.list_jobs(self.jobs_root):
                j = dict(j)
                j.pop("result", None)  # finalize_install reads it; the UI doesn't need it
                out.append(j)
            return out
        return await self._call(run)

    async def cancel_install(self, job_id: str) -> dict:
        def run():
            jd = os.path.join(self.jobs_root, os.path.basename(job_id))
            if not os.path.isdir(jd):
                raise RommError("No such job", code="not_found")
            jobs.request_cancel(jd)
        return await self._call(run)

    async def dismiss_job(self, job_id: str) -> dict:
        return await self._call(lambda: jobs.remove_job(self.jobs_root, job_id))

    async def finalize_install(self, job_id: str) -> dict:
        """After the worker finishes: write the launch script and the install record.

        Returns what the frontend needs for the Steam shortcut:
        {rom_id, name, exe, start_dir, cover, collection, appid (previous, if any)}.
        """
        def run():
            st = jobs.read_state(os.path.join(self.jobs_root, os.path.basename(job_id)))
            if not st or st.get("phase") != "done" or not st.get("result"):
                raise RommError("That install hasn't finished", code="not_ready")
            res, rom_id = st["result"], st["rom_id"]
            rom = res["rom"]
            prev = self.installed.get(rom_id) or {}
            # A file we downloaded earlier and that is unchanged now looks "adopted" to the
            # worker; it's still ours to delete. Same for the game folder.
            prev_owned = {f["rel"] for f in prev.get("files") or [] if f.get("owned")}
            for f in res["files"]:
                f["owned"] = f["owned"] or f["rel"] in prev_owned
            res["game_dir_owned"] = res["game_dir_owned"] or bool(prev.get("game_dir_owned"))
            if st.get("kind") == "update" and prev:
                # Owned files the server no longer has (e.g. a renamed disc) go away.
                keep = {f["rel"] for f in res["files"]}
                gone = [f for f in prev.get("files") or [] if f.get("owned") and f["rel"] not in keep]
                if gone:
                    delete_owned({**prev, "files": gone, "game_dir_owned": False})
            self.installed.put(rom_id, {
                "title": rom["name"], "platform_id": rom["platform_id"], "platform_slug": rom["platform_slug"],
                "platform_fs_slug": rom["platform_fs_slug"], "platform_name": rom["platform_name"],
                "cover": rom["cover"], "platform_dir": res["platform_dir"], "game_dir_rel": res["game_dir_rel"],
                "game_dir_owned": res["game_dir_owned"], "files": res["files"],
                "launch_target": res["launch_target"], "size": res["size"],
                "cover_large": rom.get("cover_large"), "server_files": res.get("server_files"),
            })
            info = self._shortcut_info(rom_id)
            log.info("Finalized %s (%s) via %s; bios %s", rom_id, rom["name"], info["emulator"],
                     res.get("bios_error") or res.get("bios"))
            return {**info, "kind": st.get("kind", "install"),
                    "bios_added": (res.get("bios") or {}).get("added", []), "bios_error": res.get("bios_error")}
        return await self._call(run)

    def _shortcut_info(self, rom_id) -> dict:
        """Write the launch script for an install record; return what the Steam shortcut needs."""
        rec = self.installed.get(rom_id)
        if not rec:
            raise RommError("This ROM isn't installed", code="not_found")
        emu = self._resolve(rec["platform_slug"], rec["platform_fs_slug"])
        if emu.get("core") and emu["status"] == "core_missing":
            provision.download_core(self._home(), emu["core"])
        target = os.path.join(rec["platform_dir"], rec["launch_target"])
        launchers.write(self._home(), rom_id, rec["title"], emulators.argv(self._home(), emu, target))
        exe = launchers.script_path(self._home(), rom_id)
        self.installed.put(rom_id, {"emulator": emu["name"], "launcher": exe})
        coll = library.collection_name(rec["platform_slug"], rec["platform_name"])
        return {
            "rom_id": str(rom_id), "name": rec["title"], "exe": exe, "start_dir": os.path.dirname(exe),
            "cover": rec.get("cover_large") or rec.get("cover"), "emulator": emu["name"],
            "collection": coll if self.settings.steam_platform_collections else None,
            "appid": rec.get("appid"),
        }

    async def readd_info(self, rom_id: str) -> dict:
        """For "Re-add to Steam": rewrite the launch script and return the shortcut info."""
        return await self._call(lambda: self._shortcut_info(rom_id))

    async def forget_installed(self, rom_id: str) -> dict:
        """Drop the record (and launch script) but leave files alone: for missing or moved files."""
        def run():
            rec = self.installed.remove(rom_id)
            launchers.remove(self._home(), rom_id)
            log.info("Forgot install record %s (%s)", rom_id, (rec or {}).get("title"))
        return await self._call(run)

    async def get_install_status(self) -> dict:
        """[{rom_id, files, update_available, server_missing, server_size, error}] for every install."""
        def run():
            records = list(self.installed.load().values())
            try:
                client = self._client()
                get_rom = lambda rid: library.rom_detail(client.get_rom(rid))  # noqa: E731
            except RommError:
                get_rom = None  # not paired: local file state only
            out = status.check_all(get_rom, records)
            for st in out:
                if "baseline" in st:
                    self.installed.put(st["rom_id"], {"server_files": st.pop("baseline")})
            return out
        return await self._call(run)

    async def set_installed_appid(self, rom_id: str, appid: int, collection: str | None = None) -> dict:
        return await self._call(lambda: self.installed.put(rom_id, {"appid": int(appid), "collection": collection}))

    async def get_installed(self) -> dict:
        return await self._call(lambda: list(self.installed.load().values()))

    async def uninstall_rom(self, rom_id: str, delete_existing: bool = False) -> dict:
        """Frontend removes the Steam shortcut first. Deletes the files we downloaded, and
        files that were already there only if delete_existing is set."""
        def run():
            rec = self.installed.get(rom_id)
            if not rec:
                raise RommError("This ROM isn't installed", code="not_found")
            removed = delete_owned(rec, include_adopted=bool(delete_existing))
            launchers.remove(self._home(), rom_id)
            self.installed.remove(rom_id)
            kept = [] if delete_existing else [f["rel"] for f in rec.get("files") or [] if not f.get("owned")]
            log.info("Uninstalled %s (%s): removed %d files, kept %d adopted", rom_id, rec.get("title"),
                     len(removed), len(kept))
            return {"removed": len(removed), "kept": len(kept)}
        return await self._call(run)

    # ---- lifecycle ---------------------------------------------------------

    async def _main(self):
        self.store = SettingsStore(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.settings = self.store.load()
        self.images = ImageCache(decky.DECKY_PLUGIN_RUNTIME_DIR)
        self.installed = InstalledStore(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.jobs_root = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "jobs")
        self._install_lock = threading.Lock()
        os.makedirs(self.jobs_root, exist_ok=True)
        if self.settings.configured:
            asyncio.get_running_loop().run_in_executor(None, self._refresh_launchers)
        log.info("RomM plugin loaded (configured=%s)", self.settings.configured)

    async def _unload(self):
        if self.pairing:
            self.pairing.stop()
        log.info("RomM plugin unloading")

    async def _uninstall(self):
        log.info("RomM plugin uninstalled")
