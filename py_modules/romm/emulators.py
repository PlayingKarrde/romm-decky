"""Which emulator runs which RomM platform, and the command line to launch a ROM.

Emulators are launched directly (Flatpak or AppImage), never through EmuDeck's
launcher scripts (the user's choice, 2026-11-06). Command-line arguments follow
what EmuDeck's Steam ROM Manager parsers use, since those are known to work.

A platform has an ordered list of candidates: "retroarch:<core>" or a
standalone emulator id. The first available one wins unless the user picked one
(settings.platform_overrides[slug]). A RetroArch core that isn't downloaded yet
still counts as usable: it's fetched from the libretro buildbot on install.

Each emulator's BIOS folder is read from its own config, because EmuDeck (and
users) redirect them, e.g. everything -> ~/Emulation/bios.
"""

from __future__ import annotations

import configparser
import os
import re
import stat
from dataclasses import dataclass

from .client import RommError

FLATPAK = "/usr/bin/flatpak"
RA_APP = "org.libretro.RetroArch"
BUILDBOT = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/"


@dataclass(frozen=True)
class Emulator:
    id: str
    name: str
    flatpaks: tuple[str, ...] = ()
    # Case-insensitive file-name prefixes of AppImages in ~/Applications (EmuDeck's location).
    appimages: tuple[str, ...] = ()
    # Plain executables under ~/Applications, for emulators EmuDeck unpacks into a folder.
    binaries: tuple[str, ...] = ()
    # Arguments after the executable. "{rom}" is the ROM path, "{romdir}" its folder,
    # "{romstem}" its file name without the extension, "{core}" the RetroArch core.
    args: tuple[str, ...] = ("{rom}",)
    prefer_appimage: bool = True
    # Where to read the BIOS folder from (see bios_dir()).
    bios: str | None = None


EMULATORS: dict[str, Emulator] = {e.id: e for e in (
    Emulator("retroarch", "RetroArch", flatpaks=(RA_APP,), args=("-L", "{core}", "{rom}"), bios="retroarch"),
    Emulator("duckstation", "DuckStation", flatpaks=("org.duckstation.DuckStation",), appimages=("DuckStation",),
             args=("-batch", "-fullscreen", "-nogui", "{rom}"), bios="duckstation"),
    Emulator("pcsx2", "PCSX2", flatpaks=("net.pcsx2.PCSX2",), appimages=("pcsx2-Qt", "pcsx2"),
             args=("-batch", "-fullscreen", "-nogui", "{rom}"), bios="pcsx2"),
    Emulator("dolphin", "Dolphin", flatpaks=("org.DolphinEmu.dolphin-emu",), args=("-b", "-e", "{rom}")),
    Emulator("ppsspp", "PPSSPP", flatpaks=("org.ppsspp.PPSSPP",), appimages=("PPSSPP",), args=("-f", "-g", "{rom}"),
             prefer_appimage=False),
    Emulator("melonds", "melonDS", flatpaks=("net.kuribo64.melonDS",), appimages=("melonDS",), args=("{rom}", "-f"),
             prefer_appimage=False),
    Emulator("cemu", "Cemu", flatpaks=("info.cemu.Cemu",), appimages=("Cemu",), args=("-f", "-g", "{rom}")),
    Emulator("azahar", "Azahar", flatpaks=("org.azahar_emu.Azahar",), appimages=("azahar",)),
    Emulator("citra", "Citra", flatpaks=("org.citra_emu.citra",), appimages=("citra-qt", "citra")),
    Emulator("rpcs3", "RPCS3", flatpaks=("net.rpcs3.RPCS3",), appimages=("rpcs3",), args=("--no-gui", "{rom}")),
    Emulator("xemu", "xemu", flatpaks=("app.xemu.xemu",), appimages=("xemu",),
             args=("-full-screen", "-dvd_path", "{rom}"), prefer_appimage=False),
    Emulator("flycast", "Flycast", flatpaks=("org.flycast.Flycast",), appimages=("flycast",)),
    Emulator("supermodel", "Supermodel", flatpaks=("com.supermodel3.Supermodel",)),
    # Ryubing is the maintained Ryujinx fork; EmuDeck unpacks its build into ~/Applications/publish.
    Emulator("ryujinx", "Ryujinx", flatpaks=("io.github.ryubing.Ryujinx", "org.ryujinx.Ryujinx"),
             appimages=("Ryujinx", "Ryubing"), binaries=("publish/Ryujinx",), args=("--fullscreen", "{rom}")),
    Emulator("eden", "Eden", flatpaks=("dev.eden_emu.eden",), appimages=("Eden",), args=("-f", "-g", "{rom}")),
    Emulator("citron", "Citron", appimages=("citron",), args=("-f", "-g", "{rom}")),
    Emulator("yuzu", "yuzu", appimages=("yuzu",), args=("-f", "-g", "{rom}")),
    Emulator("sudachi", "Sudachi", appimages=("sudachi",), args=("-f", "-g", "{rom}")),
    Emulator("suyu", "suyu", appimages=("suyu",), args=("-f", "-g", "{rom}")),
    Emulator("mame", "MAME", flatpaks=("org.mamedev.MAME",), args=("-rompath", "{romdir}", "{romstem}")),
    Emulator("mgba", "mGBA", flatpaks=("io.mgba.mGBA",), appimages=("mGBA",), args=("-f", "{rom}")),
    Emulator("rmg", "Rosalie's Mupen GUI", flatpaks=("com.github.Rosalie241.RMG",),
             args=("--fullscreen", "--nogui", "--quit-after-emulation", "{rom}")),
    Emulator("ares", "ares", flatpaks=("dev.ares.ares",), args=("--fullscreen", "{rom}")),
    Emulator("scummvm", "ScummVM", flatpaks=("org.scummvm.ScummVM",),
             args=("--fullscreen", "--path={romdir}", "--auto-detect")),
)}

# RomM platform slug -> candidates, best first. "retroarch:<core>" or an emulator id.
_RA = lambda *cores: [f"retroarch:{c}" for c in cores]  # noqa: E731
PLATFORMS: dict[str, list[str]] = {
    "nes": _RA("mesen", "nestopia", "fceumm"),
    "famicom": _RA("mesen", "nestopia", "fceumm"),
    "fds": _RA("mesen", "nestopia", "fceumm"),
    "snes": _RA("snes9x", "bsnes", "mesen-s"),
    "sfc": _RA("snes9x", "bsnes", "mesen-s"),
    "n64": _RA("mupen64plus_next", "parallel_n64") + ["rmg", "ares"],
    "gb": _RA("gambatte", "sameboy", "mgba") + ["mgba"],
    "gbc": _RA("gambatte", "sameboy", "mgba") + ["mgba"],
    "gba": _RA("mgba", "vba_next", "gpsp") + ["mgba"],
    "nds": _RA("melondsds", "melonds") + ["melonds"] + _RA("desmume"),
    "3ds": ["azahar", "citra"],
    "n3ds": ["azahar", "citra"],
    "ngc": ["dolphin"],
    "wii": ["dolphin"],
    "wiiu": ["cemu"],
    "switch": ["eden", "ryujinx", "citron", "yuzu", "sudachi", "suyu"],
    "virtualboy": _RA("mednafen_vb"),
    "genesis": _RA("genesis_plus_gx", "picodrive"),
    "sms": _RA("genesis_plus_gx", "picodrive"),
    "gamegear": _RA("genesis_plus_gx"),
    "sg1000": _RA("genesis_plus_gx"),
    "segacd": _RA("genesis_plus_gx", "picodrive"),
    "sega32x": _RA("picodrive"),
    "saturn": _RA("mednafen_saturn", "kronos", "yabasanshiro"),
    "dc": _RA("flycast") + ["flycast"],
    "atomiswave": _RA("flycast") + ["flycast"],
    "naomi": _RA("flycast") + ["flycast"],
    "naomi2": _RA("flycast") + ["flycast"],
    "model3": ["supermodel"],
    "psx": ["duckstation"] + _RA("swanstation", "mednafen_psx_hw", "pcsx_rearmed"),
    "ps2": ["pcsx2"],
    "ps3": ["rpcs3"],
    "psp": ["ppsspp"] + _RA("ppsspp"),
    "xbox": ["xemu"],
    "tg16": _RA("mednafen_pce_fast", "mednafen_pce"),
    "turbografx-cd": _RA("mednafen_pce_fast", "mednafen_pce"),
    "supergrafx": _RA("mednafen_supergrafx", "mednafen_pce"),
    "ngp": _RA("mednafen_ngp"),
    "ngpc": _RA("mednafen_ngp"),
    "wonderswan": _RA("mednafen_wswan"),
    "wonderswan-color": _RA("mednafen_wswan"),
    "atari2600": _RA("stella", "stella2014"),
    "atari7800": _RA("prosystem"),
    "lynx": _RA("handy", "mednafen_lynx"),
    "neogeo": _RA("fbneo") + ["mame"],
    "arcade": _RA("fbneo", "mame2003_plus", "mame") + ["mame"],
    "amiga": _RA("puae"),
    "msx": _RA("bluemsx", "fmsx"),
    "colecovision": _RA("bluemsx", "gearcoleco"),
    "pico8": _RA("retro8"),
    "scummvm": ["scummvm"] + _RA("scummvm"),
    "jaguar": _RA("virtualjaguar"),
    "3do": _RA("opera"),
    "pc-fx": _RA("mednafen_pcfx"),
    "atari5200": _RA("atari800"),
    "c64": _RA("vice_x64sc"),
    "dos": _RA("dosbox_pure"),
    "pokemon-mini": _RA("pokemini"),
    "vectrex": _RA("vecx"),
    "intellivision": _RA("freeintv"),
}

_CFG_LINE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$')
_CORE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


# ---- RetroArch ---------------------------------------------------------------


def ra_config_dir(home: str) -> str:
    return os.path.join(home, ".var", "app", RA_APP, "config", "retroarch")


def _read_ra_cfg(path: str) -> dict[str, str]:
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
    elif not os.path.isabs(p):
        p = os.path.join(base, p)
    return os.path.normpath(p)


def ra_paths(home: str) -> dict[str, str]:
    """{cores, system}: RetroArch's cores and BIOS dirs, honouring retroarch.cfg."""
    base = ra_config_dir(home)
    cfg = _read_ra_cfg(os.path.join(base, "retroarch.cfg"))
    cores = cfg.get("libretro_directory") or ""
    system = cfg.get("system_directory") or ""
    return {
        "cores": _expand(cores, home, base) if cores and cores != "default" else os.path.join(base, "cores"),
        "system": _expand(system, home, base) if system and system != "default" else os.path.join(base, "system"),
    }


def core_path(home: str, core: str) -> str:
    if not _CORE_NAME.match(core):
        raise RommError(f"Bad core name {core!r}", code="bad_core")
    return os.path.join(ra_paths(home)["cores"], f"{core}_libretro.so")


def core_url(core: str) -> str:
    if not _CORE_NAME.match(core):
        raise RommError(f"Bad core name {core!r}", code="bad_core")
    return f"{BUILDBOT}{core}_libretro.so.zip"


# ---- detection -----------------------------------------------------------------


def _flatpak_installed(home: str, app: str) -> bool:
    return any(os.path.isdir(p) for p in (
        os.path.join(home, ".local", "share", "flatpak", "app", app),
        os.path.join("/var/lib/flatpak/app", app),
    ))


def _find_appimage(home: str, prefixes: tuple[str, ...]) -> str | None:
    apps = os.path.join(home, "Applications")
    try:
        names = os.listdir(apps)
    except OSError:
        return None
    for prefix in prefixes:
        # Newest by name, like EmuDeck's launchers ("sort -n | tail -n 1").
        hits = sorted(n for n in names if n.lower().startswith(prefix.lower()) and n.lower().endswith(".appimage"))
        if hits:
            return os.path.join(apps, hits[-1])
    return None


def _find_binary(home: str, rels: tuple[str, ...]) -> str | None:
    for rel in rels:
        p = os.path.join(home, "Applications", rel)
        if os.path.isfile(p):
            return p
    return None


def detect(home: str, emu_id: str) -> list[str] | None:
    """The executable argv prefix for an installed emulator, or None if it isn't installed."""
    e = EMULATORS[emu_id]
    flatpak = next((a for a in e.flatpaks if _flatpak_installed(home, a)), None)
    appimage = (_find_appimage(home, e.appimages) if e.appimages else None) or _find_binary(home, e.binaries)
    order = [("appimage", appimage), ("flatpak", flatpak)]
    if not e.prefer_appimage:
        order.reverse()
    for kind, hit in order:
        if hit and kind == "appimage":
            return [hit]
        if hit and kind == "flatpak":
            return [FLATPAK, "run", hit]
    return None


def detected(home: str) -> dict[str, list[str]]:
    """{emu_id: argv prefix} for every installed emulator."""
    return {i: argv for i in EMULATORS if (argv := detect(home, i))}


# ---- choosing --------------------------------------------------------------------


def candidates_for(slug: str, fs_slug: str = "") -> list[str]:
    for key in (slug, (fs_slug or "").lower()):
        if key and key in PLATFORMS:
            return PLATFORMS[key]
    return []


def platform_key(slug: str, fs_slug: str = "") -> str | None:
    for key in (slug, (fs_slug or "").lower()):
        if key and key in PLATFORMS:
            return key
    return None


def describe(home: str, cand: str, found: dict[str, list[str]] | None = None) -> dict:
    """{id, emulator, core?, name, status}. status: ready | core_missing | not_installed."""
    found = detected(home) if found is None else found
    emu_id, _, core = cand.partition(":")
    e = EMULATORS[emu_id]
    out = {"id": cand, "emulator": emu_id, "name": f"{e.name} ({core})" if core else e.name}
    if core:
        out["core"] = core
    if emu_id not in found:
        out["status"] = "not_installed"
    elif core and not os.path.isfile(core_path(home, core)):
        out["status"] = "core_missing"  # downloadable
    else:
        out["status"] = "ready"
    return out


def options(home: str, slug: str, fs_slug: str = "") -> list[dict]:
    found = detected(home)
    return [describe(home, c, found) for c in candidates_for(slug, fs_slug)]


def resolve(home: str, slug: str, fs_slug: str = "", override: str | None = None) -> dict:
    """The emulator to use: describe() of the chosen candidate. Raises if none is usable."""
    cands = candidates_for(slug, fs_slug)
    if not cands:
        raise RommError(f"No emulator is set up for this platform ({slug}) yet", code="unsupported_platform")
    opts = options(home, slug, fs_slug)
    usable = [o for o in opts if o["status"] != "not_installed"]
    if override:
        hit = next((o for o in usable if o["id"] == override), None)
        if hit:
            return hit
    # Prefer something ready to go over a core download, within the candidate order.
    ready = [o for o in usable if o["status"] == "ready"]
    if ready:
        return ready[0]
    if usable:
        return usable[0]
    names = ", ".join(dict.fromkeys(EMULATORS[c.partition(":")[0]].name for c in cands))
    raise RommError(f"No emulator installed for this platform. Install one of: {names}", code="no_emulator")


def argv(home: str, choice: dict, rom_path: str) -> list[str]:
    """Full command line for a resolved choice."""
    prefix = detect(home, choice["emulator"])
    if not prefix:
        raise RommError(f"{EMULATORS[choice['emulator']].name} isn't installed", code="no_emulator")
    if prefix[0] != FLATPAK and not os.access(prefix[0], os.X_OK):
        # AppImages lose their exec bit when copied around; EmuDeck's launchers chmod too.
        os.chmod(prefix[0], os.stat(prefix[0]).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    e = EMULATORS[choice["emulator"]]
    if prefix[0] == FLATPAK:
        prefix = prefix[:2] + _flatpak_access(home, choice["emulator"], prefix[2], rom_path) + prefix[2:]
    core = core_path(home, choice["core"]) if choice.get("core") else ""
    romdir = os.path.dirname(rom_path)
    romstem = os.path.splitext(os.path.basename(rom_path))[0]
    subs = {"{rom}": rom_path, "{romdir}": romdir, "{romstem}": romstem, "{core}": core}
    return prefix + [re.sub(r"\{(rom|romdir|romstem|core)\}", lambda m: subs[m.group(0)], a) for a in e.args]


def _flatpak_access(home: str, emu_id: str, app: str, rom_path: str) -> list[str]:
    """--filesystem grants so a sandboxed emulator can reach the ROM and its BIOS folder.

    Several Flathub builds can't see the home folder (Eden, DuckStation, PCSX2) or
    an SD card (melonDS, Ryujinx, RPCS3). Extra grants are harmless for the rest.
    The ROM folder is read-write, since some emulators save next to the ROM.
    """
    out = [f"--filesystem={os.path.dirname(rom_path)}"]
    bios = bios_dir(home, emu_id) if EMULATORS[emu_id].bios else None
    if bios and not bios.startswith(os.path.join(home, ".var", "app", app) + os.sep):
        out.append(f"--filesystem={bios}:ro")
    return out


# ---- BIOS folders ----------------------------------------------------------------


def _ini_value(path: str, section: str, key: str) -> str | None:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cp.read_file(f)
        return cp.get(section, key, fallback=None)
    except (OSError, configparser.Error):
        return None


def bios_dir(home: str, emu_id: str) -> str | None:
    """Where this emulator looks for BIOS/firmware files, or None if we don't manage its BIOS.

    Reads the config of the install that detect() would launch (AppImage and
    Flatpak builds keep separate configs).
    """
    kind = EMULATORS[emu_id].bios
    prefix = detect(home, emu_id) or []
    flatpak_first = bool(prefix) and prefix[0] == FLATPAK
    if kind == "retroarch":
        return ra_paths(home)["system"]
    if kind == "duckstation":
        bases = [os.path.join(home, ".local", "share", "duckstation"), os.path.join(home, ".config", "duckstation")]
        fp = [os.path.join(home, ".var", "app", "org.duckstation.DuckStation", "config", "duckstation")]
        for base in (fp + bases if flatpak_first else bases + fp):
            ini = os.path.join(base, "settings.ini")
            if os.path.isfile(ini):
                d = _ini_value(ini, "BIOS", "SearchDirectory")
                return _expand(d, home, base) if d else os.path.join(base, "bios")
        return None
    if kind == "pcsx2":
        bases = [os.path.join(home, ".config", "PCSX2")]
        fp = [os.path.join(home, ".var", "app", "net.pcsx2.PCSX2", "config", "PCSX2")]
        for base in (fp + bases if flatpak_first else bases + fp):
            ini = os.path.join(base, "inis", "PCSX2.ini")
            if os.path.isfile(ini):
                d = _ini_value(ini, "Folders", "Bios")
                return _expand(d, home, base) if d else os.path.join(base, "bios")
        return None
    return None


def supported(slug: str, fs_slug: str = "") -> bool:
    return bool(candidates_for(slug, fs_slug))

