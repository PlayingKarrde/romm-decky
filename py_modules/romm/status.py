"""Health and update status of installed ROMs.

Files are checked locally against the install record. Updates compare RomM's
current file list (name, size, md5) with the one saved at install time
(record["server_files"]). Records from before that field existed get the
current server state as their baseline, so they're never flagged spuriously.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .client import RommError


def files_state(rec: dict) -> str:
    """'ok' | 'missing': every recorded file exists at its recorded size."""
    plat = rec.get("platform_dir") or ""
    files = rec.get("files") or []
    if not files:
        return "missing"
    for f in files:
        p = os.path.join(plat, f.get("rel", ""))
        if not os.path.isfile(p) or os.path.getsize(p) != f.get("size"):
            return "missing"
    return "ok"


def server_signature(rom: dict) -> list[list]:
    """[[name, size, md5], ...] of a library.rom_detail(), sorted, for comparison."""
    return sorted([f.get("name"), f.get("size"), (f.get("md5") or "").lower()] for f in rom.get("files") or [])


def check_one(get_rom: Callable[[int], dict] | None, rec: dict) -> dict:
    """{rom_id, files, update_available, server_missing, server_size, error, baseline?}

    ``baseline`` is set when the record had no server_files: the caller should store it.
    """
    rid = str(rec["rom_id"])
    out = {"rom_id": rid, "files": files_state(rec), "update_available": False, "server_missing": False,
           "server_size": None, "error": None}
    if get_rom is None:
        return out
    try:
        rom = get_rom(int(rid))
    except RommError as e:
        if e.status == 404:
            out["server_missing"] = True
        else:
            out["error"] = str(e)
        return out
    sig = server_signature(rom)
    out["server_size"] = sum(f.get("size") or 0 for f in rom.get("files") or [])
    have = rec.get("server_files")
    if have is None:
        out["baseline"] = sig
    else:
        out["update_available"] = sig != have
    return out


def check_all(get_rom: Callable[[int], dict] | None, records: list[dict]) -> list[dict]:
    if not records:
        return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda r: check_one(get_rom, r), records))
