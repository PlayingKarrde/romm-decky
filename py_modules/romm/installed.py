"""Local record of installed ROMs, and the places ROMs can be installed."""

from __future__ import annotations

import json
import os
import threading
import time

from .installer import free_bytes


class InstalledStore:
    """{rom_id: record} in installed.json. Record fields:

    rom_id, title, platform_id, platform_slug, platform_fs_slug, platform_name,
    cover, platform_dir, game_dir_rel, game_dir_owned, files [{rel, size, owned}],
    launch_target, size, emulator, launcher, appid, collection, installed_at

    Callers run in asyncio.to_thread, so two installs finishing together would race
    their read-modify-write and drop a record; the lock serialises them.
    """

    def __init__(self, directory: str):
        self.path = os.path.join(directory, "installed.json")
        self._lock = threading.Lock()

    def load(self) -> dict[str, dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def get(self, rom_id) -> dict | None:
        return self.load().get(str(rom_id))

    def put(self, rom_id, record: dict) -> dict:
        with self._lock:
            data = self.load()
            prev = data.get(str(rom_id), {})
            rec = {**prev, **record, "rom_id": str(rom_id)}
            rec.setdefault("installed_at", int(time.time()))
            data[str(rom_id)] = rec
            self._save(data)
            return rec

    def remove(self, rom_id) -> dict | None:
        with self._lock:
            data = self.load()
            rec = data.pop(str(rom_id), None)
            self._save(data)
            return rec


# ---- install roots -------------------------------------------------------------


def _removable_mounts() -> list[str]:
    out = []
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                mnt = line.split()[1].encode().decode("unicode_escape")
                if mnt.startswith("/run/media/"):
                    out.append(mnt)
    except OSError:
        pass
    return out


def install_roots(home: str, custom: str = "") -> list[dict]:
    """[{id, label, path, free}]. EmuDeck's roms folders are offered when they exist."""
    roots = []
    emu = os.path.join(home, "Emulation", "roms")
    if os.path.isdir(emu):
        roots.append({"id": "emudeck", "label": "EmuDeck ROMs folder", "path": emu})
    roots.append({"id": "internal", "label": "Internal storage", "path": os.path.join(home, "Games", "RomM")})
    for mnt in _removable_mounts():
        sd_emu = os.path.join(mnt, "Emulation", "roms")
        if os.path.isdir(sd_emu):
            roots.append({"id": f"sd-emudeck:{mnt}", "label": f"SD card EmuDeck ROMs ({os.path.basename(mnt)})",
                          "path": sd_emu})
        roots.append({"id": f"sd:{mnt}", "label": f"SD card ({os.path.basename(mnt)})",
                      "path": os.path.join(mnt, "Games", "RomM")})
    if custom and os.path.normpath(custom) not in {os.path.normpath(r["path"]) for r in roots}:
        roots.append({"id": "custom", "label": "Custom folder", "path": custom})
    for r in roots:
        try:
            r["free"] = free_bytes(r["path"])
        except OSError:
            r["free"] = None
    return roots


def default_root(home: str, chosen: str = "") -> str:
    """The configured root, else EmuDeck's roms folder if present, else ~/Games/RomM."""
    if chosen:
        return chosen
    return install_roots(home)[0]["path"]
