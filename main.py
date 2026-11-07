import asyncio
import dataclasses
import platform
import socket
from typing import Any, Callable

# decky is injected by Decky Loader at runtime; decky.pyi provides type hints.
import decky

from romm.client import RommClient, RommError, normalize_base_url
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

    # ---- lifecycle ---------------------------------------------------------

    async def _main(self):
        self.store = SettingsStore(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.settings = self.store.load()
        log.info("RomM plugin loaded (configured=%s)", self.settings.configured)

    async def _unload(self):
        if self.pairing:
            self.pairing.stop()
        log.info("RomM plugin unloading")

    async def _uninstall(self):
        log.info("RomM plugin uninstalled")
