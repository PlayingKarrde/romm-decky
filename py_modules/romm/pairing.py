"""RomM device-auth pairing session (RFC 8628 style).

1. ``start`` asks RomM for a device code and a user code.
2. The Deck shows ``verification_url`` (QR code + user code). The user opens it
   on a phone or PC where they're signed in to RomM and approves.
3. The frontend calls ``poll`` repeatedly; we hit RomM's token endpoint at
   most once per ``interval`` seconds. Once approved, ``result`` holds
   ``{access_token, device_id, scopes, expires_at}``.
"""

from __future__ import annotations

import threading
import time

from .client import RommClient, RommError
from .common.phoneform import sgdb_section, shell


class DevicePairing:
    def __init__(self, server_url: str, identifier: str, name: str, version: str | None = None):
        self.client = RommClient(server_url)
        self.identifier = identifier
        self.name = name
        self.version = version
        self.state = "starting"  # starting | waiting | done | expired | denied | error
        self.error: str | None = None
        self.result: dict | None = None
        self.user_code = ""
        self.verification_url = ""
        self._device_code = ""
        self._interval = 5.0
        self._deadline = 0.0
        self._next_poll = 0.0
        self._lock = threading.Lock()

    def start(self) -> "DevicePairing":
        r = self.client.device_auth_init(self.identifier, self.name, self.version)
        self._device_code = r["device_code"]
        self.user_code = r.get("user_code") or ""
        path = r.get("verification_path_complete") or r.get("verification_path") or "/"
        self.verification_url = self.client.base_url + (path if path.startswith("/") else "/" + path)
        self._interval = float(r.get("interval") or 5)
        now = time.monotonic()
        self._deadline = now + float(r.get("expires_in") or 600)
        self._next_poll = now + self._interval
        self.state = "waiting"
        return self

    def poll(self) -> dict:
        """Advance the session if it's time to ask RomM again; return status()."""
        with self._lock:
            now = time.monotonic()
            if self.state == "waiting" and now >= self._deadline:
                self.state, self.error = "expired", "The pairing code expired. Start pairing again."
            if self.state == "waiting" and now >= self._next_poll:
                self._next_poll = now + self._interval
                try:
                    res = self.client.device_auth_poll(self._device_code)
                except RommError as e:
                    if e.code in ("expired", "denied"):
                        self.state, self.error = e.code, str(e)
                    else:
                        # Transient (network, 5xx): keep waiting, show the reason.
                        self.error = str(e)
                else:
                    if res and res.get("access_token"):
                        self.result = res
                        self.state, self.error = "done", None
            return self.status()

    def stop(self) -> None:
        with self._lock:
            if self.state in ("starting", "waiting"):
                self.state = "stopped"

    def status(self) -> dict:
        return {
            "state": self.state,
            "user_code": self.user_code,
            "url": self.verification_url,
            "expires_in": max(0, int(self._deadline - time.monotonic())) if self._deadline else None,
            "error": self.error,
        }


# ---- SteamGridDB key from a phone ------------------------------------------------

SGDB_PHONE_TITLE = "SteamGridDB key for RomM on your Deck"


def sgdb_phone_page(has_key: bool) -> str:
    """The phone page for the SteamGridDB API key (served by common.phoneform.PhoneForm)."""
    return shell(SGDB_PHONE_TITLE, f"<h1>{SGDB_PHONE_TITLE}</h1>" + sgdb_section(has_key, optional=False))

