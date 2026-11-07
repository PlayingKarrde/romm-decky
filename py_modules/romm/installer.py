"""Download a RomM ROM into a platform folder (EmuDeck-style layout).

Layout under the install root (default ~/Emulation/roms):
  single file:  <root>/<platform>/<file>
  multi file:   <root>/<platform>/<fs_name>/<subdir>/<file>  (+ <fs_name>.m3u for discs)

There's no per-game marker folder in this flat layout, so ownership is tracked
per file: files we download are "owned" (uninstall may delete them); files that
were already there with a matching MD5 are "adopted" and never deleted.

Each file downloads to "<target>.romm-part" next to its target, resumes with
HTTP Range, is MD5-checked, then renamed into place.
"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from typing import Callable

from .client import RommClient, RommError

PART_SUFFIX = ".romm-part"
CHUNK = 1 << 20
SPACE_MARGIN = 256 * 1024 * 1024

# Disc images that make up a multi-disc game, in launch preference order.
DISC_EXT = (".m3u", ".cue", ".gdi", ".chd", ".cso", ".iso", ".pbp", ".ccd", ".mds", ".rvz", ".gcz", ".wbfs")
_UNSAFE = re.compile(r'[\x00-\x1f/\\]')

# For archives, RomM's md5_hash is the hash of the ROM *inside* (it identifies games
# by content), not of the archive file. Verified on RomM 5.4.1 with a .zip.
ARCHIVE_EXT = (".zip", ".7z", ".rar")


class Cancelled(Exception):
    pass


def safe_name(name: str) -> str:
    """One path component from server data: no separators, no '..', no control chars."""
    n = _UNSAFE.sub("_", (name or "").strip()).strip(". ")
    if not n:
        raise RommError(f"Unusable file name from server: {name!r}", code="bad_name")
    return n


def platform_dir(root: str, fs_slug: str) -> str:
    """<root>/<platform>, reusing an existing folder that differs only in case (MAME vs mame)."""
    want = safe_name(fs_slug)
    try:
        for entry in os.listdir(root):
            if entry.lower() == want.lower() and os.path.isdir(os.path.join(root, entry)):
                return os.path.join(root, entry)
    except OSError:
        pass
    return os.path.join(root, want.lower())


def plan(rom: dict) -> dict:
    """From library.rom_detail(): {game_dir_rel, files: [{id, name, size, md5, rel}]}.

    ``rel`` is relative to the platform dir.
    """
    files = rom.get("files") or []
    if not files:
        raise RommError("RomM lists no downloadable files for this ROM", code="no_files")
    multi = bool(rom.get("multi_file")) or len(files) > 1
    game_dir_rel = safe_name(rom.get("fs_name") or rom.get("name") or str(rom.get("id"))) if multi else ""
    out = []
    for f in files:
        parts = [game_dir_rel] if game_dir_rel else []
        parts += [safe_name(p) for p in (f.get("subdir") or "").split("/") if p]
        parts.append(safe_name(f["name"]))
        out.append({**f, "rel": os.path.join(*parts)})
    return {"game_dir_rel": game_dir_rel, "files": out}


def free_bytes(path: str) -> int:
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    st = os.statvfs(path or "/")
    return st.f_bavail * st.f_frsize


def check_space(path: str, need: int) -> None:
    free = free_bytes(path)
    if need + SPACE_MARGIN > free:
        raise RommError(f"Not enough space: need {need // (1 << 20)} MiB, {free // (1 << 20)} MiB free",
                        code="no_space")


def md5_file(path: str, cancelled: Callable[[], bool] | None = None) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            if cancelled and cancelled():
                raise Cancelled()
            b = f.read(CHUNK)
            if not b:
                return h.hexdigest()
            h.update(b)


def _zip_member_md5(path: str) -> str | None:
    """MD5 of the only file in a zip, or None if it isn't a one-file zip."""
    try:
        with zipfile.ZipFile(path) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if len(members) != 1:
                return None
            h = hashlib.md5()
            with z.open(members[0]) as m:
                for b in iter(lambda: m.read(CHUNK), b""):
                    h.update(b)
            return h.hexdigest()
    except (OSError, zipfile.BadZipFile):
        return None


def content_matches(path: str, f: dict, file_md5: str | None = None, cancelled=None) -> bool:
    """Does the file at path match RomM's hash? Size must already match.

    Plain files: the file's MD5. One-file zips: the member's MD5. Other archives
    (7z, multi-file zips): RomM's hash can't be checked without unpacking, so the
    size match has to do.
    """
    want = (f.get("md5") or "").lower()
    if not want:
        return True
    if f["name"].lower().endswith(ARCHIVE_EXT):
        if f["name"].lower().endswith(".zip"):
            inner = _zip_member_md5(path)
            if inner is not None:
                return inner == want
        return True
    return (file_md5 or md5_file(path, cancelled)) == want


def existing_matches(path: str, f: dict, cancelled=None) -> bool | None:
    """True: same file already there. False: a different file is there. None: nothing there."""
    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) != f["size"]:
        return False
    return content_matches(path, f, cancelled=cancelled)


def download_file(client: RommClient, rom_id: int, f: dict, target: str,
                  on_bytes: Callable[[int], None], cancelled: Callable[[], bool]) -> None:
    """Download one file to target via target.romm-part, resuming and verifying MD5."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + PART_SUFFIX
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have > f["size"]:
        os.remove(part)
        have = 0
    h = hashlib.md5()
    if have:
        with open(part, "rb") as p:
            while True:
                b = p.read(CHUNK)
                if not b:
                    break
                h.update(b)
        on_bytes(have)
    if have < f["size"] or f["size"] == 0:
        with client.open_rom_file(rom_id, f["id"], f["name"], offset=have) as resp:
            if have and resp.status != 206:  # server ignored Range: start over
                on_bytes(-have)
                have, h = 0, hashlib.md5()
            with open(part, "ab" if have else "wb") as out:
                while True:
                    if cancelled():
                        raise Cancelled()
                    b = resp.read(CHUNK)
                    if not b:
                        break
                    out.write(b)
                    h.update(b)
                    on_bytes(len(b))
    size = os.path.getsize(part)
    if size != f["size"]:
        raise RommError(f"Download of {f['name']} is incomplete ({size} of {f['size']} bytes); retry to resume",
                        code="incomplete")
    if not content_matches(part, {**f, "name": f["name"]}, file_md5=h.hexdigest()):
        os.remove(part)
        raise RommError(f"Checksum mismatch for {f['name']}; the partial file was removed", code="bad_checksum")
    os.replace(part, target)


def write_m3u(plat_dir: str, game_dir_rel: str, files: list[dict]) -> str | None:
    """For a multi-disc game without its own .m3u, write one. Returns its rel path or None."""
    if not game_dir_rel or any(f["rel"].lower().endswith(".m3u") for f in files):
        return None
    discs = [f for f in files if f["rel"].lower().endswith((".cue", ".gdi"))] or \
            [f for f in files if f["rel"].lower().endswith(DISC_EXT[3:])]
    if len(discs) < 2:
        return None
    discs.sort(key=lambda f: f["rel"].lower())
    rel = os.path.join(game_dir_rel, game_dir_rel + ".m3u")
    path = os.path.join(plat_dir, rel)
    if os.path.exists(path):
        return rel  # someone (EmuDeck tooling, a previous install) already made one
    with open(path, "w", encoding="utf-8") as m:
        for d in discs:
            m.write(os.path.relpath(os.path.join(plat_dir, d["rel"]), os.path.dirname(path)) + "\n")
    return rel


def launch_target(files: list[dict], m3u_rel: str | None) -> str:
    """The file the emulator should open (rel to the platform dir)."""
    if m3u_rel:
        return m3u_rel
    for ext in DISC_EXT:
        for f in files:
            if f["rel"].lower().endswith(ext):
                return f["rel"]
    return max(files, key=lambda f: f["size"])["rel"]


def install(client: RommClient, rom: dict, root: str, platform_fs_slug: str,
            progress: Callable[[str, int, int | None], None], cancelled: Callable[[], bool],
            replace: set[str] | frozenset[str] = frozenset()) -> dict:
    """Download (or adopt) every file of a ROM. Returns the install record fields.

    replace: rel paths this install may overwrite when they differ (an update of
    files the previous install recorded). Anything else that differs is a conflict.
    """
    p = plan(rom)
    plat = platform_dir(root, platform_fs_slug)
    total = sum(f["size"] for f in p["files"])

    # Adopt files that are already there; refuse to overwrite different ones.
    progress("checking", 0, total)
    todo, result = [], []
    for f in p["files"]:
        target = os.path.join(plat, f["rel"])
        same = existing_matches(target, f, cancelled)
        if same is True:
            result.append({"rel": f["rel"], "size": f["size"], "owned": False})
        elif same is False and f["rel"] in replace:
            todo.append((f, target))
        elif same is False:
            raise RommError(f"A different file already exists at {target}. Move it away to install this ROM.",
                            code="conflict")
        else:
            todo.append((f, target))
    need = sum(f["size"] - (os.path.getsize(t + PART_SUFFIX) if os.path.isfile(t + PART_SUFFIX) else 0)
               for f, t in todo)
    if need:
        os.makedirs(plat, exist_ok=True)
        check_space(plat, need)

    done = total - sum(f["size"] for f, _ in todo)
    counter = {"done": done}

    def on_bytes(n: int) -> None:
        counter["done"] += n
        progress("downloading", counter["done"], total)

    for f, target in todo:
        download_file(client, rom["id"], f, target, on_bytes, cancelled)
        result.append({"rel": f["rel"], "size": f["size"], "owned": True})

    progress("finalizing", total, total)
    m3u = write_m3u(plat, p["game_dir_rel"], p["files"])
    if m3u and not any(r["rel"] == m3u for r in result):
        result.append({"rel": m3u, "size": os.path.getsize(os.path.join(plat, m3u)), "owned": True})
    order = {f["rel"]: i for i, f in enumerate(p["files"])}
    result.sort(key=lambda r: order.get(r["rel"], len(order)))
    return {
        "platform_dir": plat,
        "game_dir_rel": p["game_dir_rel"],
        # The game folder is ours to remove only if nothing in it was adopted.
        "game_dir_owned": bool(p["game_dir_rel"]) and all(r["owned"] for r in result),
        "files": result,
        "launch_target": launch_target(p["files"], m3u),
        "size": total,
        "downloaded": sum(r["size"] for r in result if r["owned"]),
    }


def cleanup_parts(plat_dir: str, rom: dict) -> None:
    """Remove partial downloads after a cancel (they'd otherwise sit in the ROM folder)."""
    try:
        p = plan(rom)
    except RommError:
        return
    for f in p["files"]:
        part = os.path.join(plat_dir, f["rel"]) + PART_SUFFIX
        if os.path.isfile(part):
            os.remove(part)
    if p["game_dir_rel"]:
        d = os.path.join(plat_dir, p["game_dir_rel"])
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)


def delete_owned(record: dict, include_adopted: bool = False) -> list[str]:
    """Delete the files we downloaded (only if still the size we wrote). Returns what was removed.

    include_adopted: also delete files that were already there before the install
    (only when the user explicitly asks for it).
    """
    plat = record.get("platform_dir") or ""
    removed = []
    for f in record.get("files") or []:
        if not f.get("owned") and not include_adopted:
            continue
        path = os.path.normpath(os.path.join(plat, f["rel"]))
        if not path.startswith(os.path.normpath(plat) + os.sep):
            continue  # never escape the platform dir
        if os.path.isfile(path) and os.path.getsize(path) == f.get("size"):
            os.remove(path)
            removed.append(path)
    gd = record.get("game_dir_rel")
    if gd and (record.get("game_dir_owned") or include_adopted):
        # Bottom-up rmdir only succeeds on empty folders, so anything the user added stays.
        for sub, _, _ in os.walk(os.path.join(plat, gd), topdown=False):
            try:
                os.rmdir(sub)
            except OSError:
                pass
    return removed

