"""Minimal RomM (5.x) API client.

Stdlib only (urllib) so it runs inside Decky's bundled Python *and* in the
standalone download worker / CLI without vendoring anything. All calls are
blocking; async callers should wrap them in ``asyncio.to_thread``.

Checked against RomM 5.4.1's /openapi.json (kept in docs/openapi.json).

Auth: a client token (``Authorization: Bearer``), normally obtained through
RomM's device-auth flow (``device_auth_init`` / ``device_auth_poll``); or HTTP
Basic with username/password, which the dev CLI uses.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .common import net
from .common.net import Image, PluginError, ssl_context, urlopen  # noqa: F401 (re-exported)

USER_AGENT = "romm-decky/0.1"
net.set_user_agent(USER_AGENT)
DEFAULT_TIMEOUT = 15.0

# One error type for the whole plugin, shared with the common modules (an alias, so
# `except RommError` also catches what they raise).
RommError = PluginError

# Scopes the plugin asks for when pairing. Read-only on the library; devices.*
# lets us register as a RomM device (and later take "send to device" installs).
DEVICE_SCOPES = [
    "me.read",
    "roms.read",
    "platforms.read",
    "assets.read",
    "firmware.read",
    "collections.read",
    "roms.user.read",
    "devices.read",
    "devices.write",
]


def normalize_base_url(url: str) -> str:
    """'192.168.1.5:8080/' -> 'http://192.168.1.5:8080'. Tolerates CRLF/whitespace."""
    url = (url or "").strip()
    if not url:
        raise RommError("Server URL is empty", code="no_url")
    if "://" not in url:
        url = "http://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RommError(f"Invalid server URL: {url}", code="bad_url")
    return url.rstrip("/")


def q(segment: Any) -> str:
    """Quote one path segment (file names contain spaces, parens, '#', ...)."""
    return urllib.parse.quote(str(segment), safe="")


class RommClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = normalize_base_url(base_url)
        self.token = (token or "").strip()
        self.username = (username or "").strip()
        self.password = password or ""
        self.timeout = timeout

    @property
    def has_auth(self) -> bool:
        return bool(self.token or (self.username and self.password))

    # ---- transport -------------------------------------------------------

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        return url

    def _auth_header(self) -> str:
        if self.token:
            return "Bearer " + self.token
        if self.username and self.password:
            raw = f"{self.username}:{self.password}".encode("utf-8")
            return "Basic " + base64.b64encode(raw).decode("ascii")
        raise RommError("Not signed in to RomM", code="no_auth")

    def _open(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        auth: bool = True,
        method: str = "GET",
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ):
        h = {"User-Agent": USER_AGENT, "Accept": "application/json, image/*;q=0.9, */*;q=0.5"}
        if auth:
            h["Authorization"] = self._auth_header()
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        req = urllib.request.Request(self._url(path, params), data=data, headers=h, method=method)
        try:
            return urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except urllib.error.URLError as e:
            raise RommError(f"Can't reach server: {e.reason}", code="unreachable") from None
        except TimeoutError:
            raise RommError("Server timed out", code="timeout") from None
        except OSError as e:
            raise RommError(f"Network error: {e}", code="network") from None

    @staticmethod
    def _http_error(e: urllib.error.HTTPError) -> RommError:
        # FastAPI: {"detail": "..."} or {"detail": [{msg, loc, ...}]} for 422.
        detail = None
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, list):
                detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
            elif detail is not None and not isinstance(detail, str):
                detail = json.dumps(detail)
        except Exception:
            pass
        if e.code == 401:
            return RommError("RomM rejected the credentials (wrong, expired or revoked)", 401, "unauthorized")
        if e.code == 403:
            return RommError("Missing RomM permission" + (f": {detail}" if detail else ""), 403, "forbidden")
        if e.code == 404:
            return RommError(detail or "Not found", 404, "not_found")
        return RommError(f"Server error {e.code}" + (f": {detail}" if detail else ""), e.code, detail)

    def _json(self, path: str, params: dict[str, Any] | None = None, **kw) -> Any:
        with self._open(path, params, **kw) as resp:
            raw = resp.read()
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            raise RommError(f"Unexpected non-JSON response from {path}", code="bad_response") from None

    # ---- server / user ---------------------------------------------------

    def heartbeat(self) -> dict:
        """Unauthenticated. SYSTEM.VERSION is the server version."""
        return self._json("/api/heartbeat", auth=False)

    def me(self) -> dict:
        return self._json("/api/users/me")

    # ---- device auth (pairing) -------------------------------------------
    # Flow: init -> show verification_path_complete (QR) -> user approves in the
    # RomM web UI -> poll /token with device_code until it returns a client token.

    def device_auth_init(self, identifier: str, name: str, client_version: str | None = None,
                         scopes: list[str] | None = None) -> dict:
        """-> {device_code, user_code, verification_path, verification_path_complete, expires_in, interval}"""
        return self._json("/api/auth/device/init", auth=False, method="POST", body={
            "client_device_identifier": identifier,
            "name": name,
            "client": "romm-decky",
            "platform": "SteamOS",
            "client_version": client_version,
            "requested_scopes": scopes or DEVICE_SCOPES,
        })

    def device_auth_poll(self, device_code: str) -> dict | None:
        """The token response once approved; None while still pending.

        RomM answers RFC 8628 style: HTTP 400 with detail authorization_pending /
        slow_down (keep polling), or expired_token / access_denied (give up).
        Verified against RomM 5.4.1.
        """
        try:
            return self._json("/api/auth/device/token", auth=False, method="POST",
                              body={"device_code": device_code})
        except RommError as e:
            if e.status != 400:
                raise
            if e.code in ("authorization_pending", "slow_down"):
                return None
            if e.code == "expired_token":
                raise RommError("The pairing code expired. Start pairing again.", 400, "expired") from None
            if e.code == "access_denied":
                raise RommError("Pairing was denied in RomM.", 400, "denied") from None
            raise

    # ---- library ---------------------------------------------------------

    def list_platforms(self) -> list[dict]:
        return self._json("/api/platforms")

    def list_roms(
        self,
        *,
        platform_id: int | None = None,
        collection_id: int | None = None,
        smart_collection_id: int | None = None,
        virtual_collection_id: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
        order_by: str = "name",
        order_dir: str = "asc",
    ) -> dict:
        """CustomLimitOffsetPage: {items: [SimpleRom], total, limit, offset, ...}.

        Items do not include ``files``; use get_rom for those. Each item is ~9 KB,
        so slim them (library.py) before sending to the frontend.
        """
        return self._json("/api/roms", {
            "platform_ids": platform_id,
            "collection_id": collection_id,
            "smart_collection_id": smart_collection_id,
            "virtual_collection_id": virtual_collection_id,
            "search_term": search,
            "offset": offset,
            "limit": limit,
            "order_by": order_by,
            "order_dir": order_dir,
            "with_char_index": "false",
            "with_filter_values": "false",
        })

    def get_rom(self, rom_id: int) -> dict:
        """DetailedRom, including files[] ({id, file_name, file_size_bytes, md5_hash, category, ...})."""
        return self._json(f"/api/roms/{int(rom_id)}")

    def list_collections(self) -> list[dict]:
        return self._json("/api/collections")

    def list_smart_collections(self) -> list[dict]:
        return self._json("/api/collections/smart")

    def list_virtual_collections(self, kind: str, limit: int | None = None) -> list[dict]:
        """kind: collection | franchise | genre | company | mode (ids are opaque strings)."""
        return self._json("/api/collections/virtual", {"type": kind, "limit": limit})

    def list_firmware(self, platform_id: int) -> list[dict]:
        return self._json("/api/firmware", {"platform_id": int(platform_id)})

    # ---- downloads -------------------------------------------------------
    # The server honours Range (206) on single files, so downloads can resume.

    def open_rom_file(self, rom_id: int, file_id: int, file_name: str, offset: int = 0,
                      timeout: float = 60.0):
        """Stream one file of a ROM. Caller must close the response.

        Uses /content/{name}?file_ids=<id>, which serves the raw file (no zip) and
        supports Range. ``offset`` > 0 asks for a resume; check ``resp.status``
        (206 = resumed, 200 = server restarted from 0).
        """
        headers = {"Range": f"bytes={int(offset)}-"} if offset else None
        return self._open(f"/api/roms/{int(rom_id)}/content/{q(file_name)}", {"file_ids": int(file_id)},
                          headers=headers, timeout=timeout)

    def open_firmware(self, firmware_id: int, file_name: str, timeout: float = 60.0):
        return self._open(f"/api/firmware/{int(firmware_id)}/content/{q(file_name)}", timeout=timeout)

    def fetch_image(self, path: str) -> Image:
        """Fetch a server asset such as rom['path_cover_small'] ('/assets/romm/resources/...')."""
        if path.startswith(self.base_url):
            path = path[len(self.base_url):]
        if not path.startswith("/assets/"):
            raise RommError(f"Refusing to fetch non-asset URL: {path}", code="bad_image_url")
        parsed = urllib.parse.urlsplit(path)
        params = dict(urllib.parse.parse_qsl(parsed.query)) or None
        with self._open(urllib.parse.quote(parsed.path), params) as resp:
            ctype = resp.headers.get_content_type() or "application/octet-stream"
            return Image(resp.read(), ctype)

    # ---- composite -------------------------------------------------------

    def test_connection(self) -> dict:
        """Probe what the plugin needs: server version, identity, library read."""
        hb = self.heartbeat() or {}
        result: dict[str, Any] = {"ok": False, "server_version": (hb.get("SYSTEM") or {}).get("VERSION")}
        me = self.me()
        result["username"] = me.get("username")
        platforms = self.list_platforms()
        populated = [p for p in platforms if p.get("rom_count")]
        result["platform_count"] = len(populated)
        result["rom_count"] = sum(p.get("rom_count") or 0 for p in populated)
        result["ok"] = True
        return result
