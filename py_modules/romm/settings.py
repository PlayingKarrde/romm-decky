"""Plugin settings persisted as JSON. The token never leaves the backend."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class Settings:
    server_url: str = ""
    # RomM client token from the device-auth flow, and the RomM Device it's bound to.
    token: str = ""
    device_id: str = ""
    username: str = ""
    # Stable per-install id sent as client_device_identifier when pairing.
    device_identifier: str = ""
    # Where installs go ("" = automatic: EmuDeck's roms folder if present, else ~/Games/RomM).
    install_root: str = ""
    # Put each installed game in a Steam collection named after its platform.
    steam_platform_collections: bool = True
    # RomM platform slug -> emulator id, overriding the default choice.
    platform_overrides: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.server_url and self.token)

    def public(self) -> dict:
        """Safe view for the frontend: no token, just whether one is set."""
        return {
            "server_url": self.server_url,
            "has_token": bool(self.token),
            "username": self.username,
            "install_root": self.install_root,
            "steam_platform_collections": self.steam_platform_collections,
            "platform_overrides": dict(self.platform_overrides),
        }


class SettingsStore:
    def __init__(self, directory: str):
        self.path = os.path.join(directory, "settings.json")

    def load(self) -> Settings:
        s = self._read()
        if not s.device_identifier:
            s.device_identifier = "romm-decky-" + uuid.uuid4().hex
            self.save(s)
        return s

    def _read(self) -> Settings:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return Settings()
        except (OSError, ValueError):
            # Unreadable/corrupt: start unconfigured rather than fail plugin load.
            return Settings()
        if not isinstance(raw, dict):
            return Settings()
        known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
        if not isinstance(known.get("platform_overrides", {}), dict):
            known.pop("platform_overrides")
        try:
            return Settings(**known)
        except TypeError:
            return Settings()

    def save(self, settings: Settings) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        # 0600: contains the client token.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
        os.replace(tmp, self.path)
