"""Which emulator runs which RomM platform, and the command line to launch a ROM.

Step 3 scope: RetroArch (Flatpak) with per-platform cores. Standalone
emulators, per-platform overrides and core downloads come in step 4.

RetroArch's own paths are read from its retroarch.cfg, because EmuDeck (and
users) redirect them, e.g. system_directory -> ~/Emulation/bios.
"""

from __future__ import annotations

import os
import re

from .client import RommError

FLATPAK = "/usr/bin/flatpak"
RA_APP = "org.libretro.RetroArch"

# RomM platform slug -> RetroArch cores, best first. Only cores that run well on a
# Deck; the first one present in RetroArch's cores dir is used.
RA_CORES: dict[str, list[str]] = {
    "nes": ["mesen", "nestopia", "fceumm"],
    "famicom": ["mesen", "nestopia", "fceumm"],
    "fds": ["mesen", "nestopia", "fceumm"],
    "snes": ["snes9x", "bsnes", "mesen-s"],
    "sfc": ["snes9x", "bsnes", "mesen-s"],
    "n64": ["mupen64plus_next", "parallel_n64"],
    "gb": ["gambatte", "sameboy", "mgba"],
    "gbc": ["gambatte", "sameboy", "mgba"],
    "gba": ["mgba", "vba_next", "gpsp"],
    "nds": ["melondsds", "melonds", "desmume"],
    "virtualboy": ["mednafen_vb"],
    "genesis": ["genesis_plus_gx", "picodrive"],
    "sms": ["genesis_plus_gx", "picodrive"],
    "gamegear": ["genesis_plus_gx"],
    "sg1000": ["genesis_plus_gx"],
    "segacd": ["genesis_plus_gx", "picodrive"],
    "sega32x": ["picodrive"],
    "saturn": ["mednafen_saturn", "kronos", "yabasanshiro"],
    "dc": ["flycast"],
    "psx": ["swanstation", "mednafen_psx_hw", "pcsx_rearmed", "mednafen_psx"],
    "psp": ["ppsspp"],
    "tg16": ["mednafen_pce_fast", "mednafen_pce"],
    "turbografx-cd": ["mednafen_pce_fast", "mednafen_pce"],
    "supergrafx": ["mednafen_supergrafx", "mednafen_pce"],
    "ngp": ["mednafen_ngp"],
    "ngpc": ["mednafen_ngp"],
    "wonderswan": ["mednafen_wswan"],
    "wonderswan-color": ["mednafen_wswan"],
    "atari2600": ["stella", "stella2014"],
    "atari7800": ["prosystem"],
    "lynx": ["handy", "mednafen_lynx"],
    "neogeo": ["fbneo"],
    "arcade": ["fbneo", "mame2003_plus", "mame"],
    "atomiswave": ["flycast"],
    "naomi": ["flycast"],
    "amiga": ["puae"],
    "msx": ["bluemsx", "fmsx"],
    "colecovision": ["bluemsx", "gearcoleco"],
    "pico8": ["retro8"],
}

_CFG_LINE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$')


def ra_config_dir(home: str) -> str:
    return os.path.join(home, ".var", "app", RA_APP, "config", "retroarch")


def ra_installed(home: str) -> bool:
    return any(os.path.isdir(p) for p in (
        os.path.join(home, ".local", "share", "flatpak", "app", RA_APP),
        os.path.join("/var/lib/flatpak/app", RA_APP),
    ))


def _read_cfg(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _CFG_LINE.match(line)
                if m:
                    out[m.group(1)] = m.group(2)
    except OSError:
        pass
    return out


def _expand(p: str, home: str, base: str) -> str:
    if p.startswith("~"):
        p = home + p[1:]
    elif p.startswith(":"):  # RetroArch's ":/" means "relative to the config dir"
        p = os.path.join(base, p[1:].lstrip("/"))
    return os.path.normpath(p)


def ra_paths(home: str) -> dict[str, str]:
    """{cores, system}: RetroArch's cores and BIOS dirs, honouring retroarch.cfg."""
    base = ra_config_dir(home)
    cfg = _read_cfg(os.path.join(base, "retroarch.cfg"))
    cores = cfg.get("libretro_directory") or ""
    system = cfg.get("system_directory") or ""
    return {
        "cores": _expand(cores, home, base) if cores and cores != "default" else os.path.join(base, "cores"),
        "system": _expand(system, home, base) if system and system != "default" else os.path.join(base, "system"),
    }


def platform_keys(slug: str, fs_slug: str = "") -> list[str]:
    """RomM slugs differ from folder names (genesis vs megadrive); try both."""
    keys = [slug]
    if fs_slug and fs_slug.lower() != slug:
        keys.append(fs_slug.lower())
    return keys


def supported(slug: str, fs_slug: str = "") -> bool:
    return any(k in RA_CORES for k in platform_keys(slug, fs_slug))


def resolve(home: str, slug: str, fs_slug: str = "") -> dict:
    """The emulator for a platform: {emulator, name, core, core_path}. Raises if none usable."""
    cores = next((RA_CORES[k] for k in platform_keys(slug, fs_slug) if k in RA_CORES), None)
    if not cores:
        raise RommError(f"No emulator is set up for this platform ({slug}) yet", code="unsupported_platform")
    if not ra_installed(home):
        raise RommError("RetroArch isn't installed (Flatpak org.libretro.RetroArch)", code="no_emulator")
    cores_dir = ra_paths(home)["cores"]
    for core in cores:
        path = os.path.join(cores_dir, f"{core}_libretro.so")
        if os.path.isfile(path):
            return {"emulator": "retroarch", "name": f"RetroArch ({core})", "core": core, "core_path": path}
    raise RommError(f"RetroArch has no core for {slug}. Install one of: {', '.join(cores)}",
                    code="no_core")


def argv(res: dict, rom_path: str) -> list[str]:
    if res["emulator"] == "retroarch":
        return [FLATPAK, "run", RA_APP, "-L", res["core_path"], rom_path]
    raise RommError(f"Unknown emulator {res['emulator']}", code="internal")
