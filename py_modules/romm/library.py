"""Slim RomM payloads for the frontend.

A raw SimpleRom is ~9 KB (every metadata provider's blob), and Decky's bridge
caps payloads at ~1 MiB, so everything sent to the UI goes through here.
"""

from __future__ import annotations

from typing import Any

# Virtual collection kinds RomM generates from metadata (ids are opaque strings).
VIRTUAL_KINDS = ("collection", "franchise", "genre", "company", "mode")

# Collection browse groups -> how to list them. "mine" = user + smart collections.
COLLECTION_GROUPS = ("mine",) + VIRTUAL_KINDS


def platform_summary(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "slug": p.get("slug"),
        "fs_slug": p.get("fs_slug"),
        "name": p.get("display_name") or p.get("custom_name") or p.get("name"),
        "rom_count": p.get("rom_count") or 0,
        "firmware_count": p.get("firmware_count") or 0,
        "logo": p.get("url_logo"),
    }


def platforms_summary(platforms: list[dict]) -> list[dict]:
    """Only platforms that have ROMs, sorted by name.

    RomM can have two platforms with the same display name (e.g. 'Arcade' for the
    MAME/ and arcade/ folders); those get their folder name appended.
    """
    out = [platform_summary(p) for p in platforms if p.get("rom_count")]
    names = [p["name"] for p in out]
    for p in out:
        if names.count(p["name"]) > 1 and p["fs_slug"]:
            p["name"] = f'{p["name"]} ({p["fs_slug"]})'
    out.sort(key=lambda p: (p["name"] or "").lower())
    return out


def collection_summary(c: dict, kind: str) -> dict:
    """kind: 'user' | 'smart' | 'virtual:<type>'. ``id`` is str for virtual ones."""
    return {
        "id": c.get("id"),
        "kind": kind,
        "name": c.get("name"),
        "rom_count": c.get("rom_count") or 0,
        "cover": c.get("path_cover_small") or next(iter(c.get("path_covers_small") or []), None),
        "is_favorite": bool(c.get("is_favorite")),
    }


def rom_summary(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name") or r.get("fs_name_no_ext") or r.get("fs_name"),
        "platform_id": r.get("platform_id"),
        "platform_slug": r.get("platform_slug"),
        "platform_fs_slug": r.get("platform_fs_slug"),
        "platform_name": r.get("platform_display_name"),
        "fs_name": r.get("fs_name"),
        "size": r.get("fs_size_bytes") or 0,
        "cover": r.get("path_cover_small"),
        "multi_file": bool(r.get("has_multiple_files")),
        "regions": r.get("regions") or [],
        "missing": bool(r.get("missing_from_fs")),
    }


def page_summary(page: dict) -> dict:
    return {
        "items": [rom_summary(r) for r in page.get("items") or []],
        "total": page.get("total"),
        "offset": page.get("offset"),
        "limit": page.get("limit"),
    }


def _game_files(r: dict) -> list[dict]:
    """Downloadable game files: drop RomM placeholders like 0-byte 'noload.txt'."""
    out = []
    for f in r.get("files") or []:
        if not f.get("file_size_bytes"):
            continue
        cat = f.get("category")
        if cat not in (None, "game"):
            continue
        out.append({
            "id": f.get("id"),
            "name": f.get("file_name"),
            "size": f.get("file_size_bytes") or 0,
            "md5": f.get("md5_hash"),
            # Path inside the ROM's folder, for nested multi-file ROMs.
            "subdir": _subdir(r, f),
        })
    return out


def _subdir(r: dict, f: dict) -> str:
    if f.get("is_top_level", True):
        return ""
    base = (r.get("fs_path") or "").rstrip("/") + "/" + (r.get("fs_name") or "")
    fp = (f.get("file_path") or "").rstrip("/")
    return fp[len(base):].strip("/") if fp.startswith(base) else ""


def rom_detail(r: dict) -> dict[str, Any]:
    d = rom_summary(r)
    d.update({
        "summary": (r.get("summary") or "")[:1500],
        "cover_large": r.get("path_cover_large"),
        "files": _game_files(r),
        "updated_at": r.get("updated_at"),
        "collections": [{"id": c.get("id"), "name": c.get("name")} for c in r.get("user_collections") or []],
    })
    return d


def collections_summary(user: list[dict], smart: list[dict]) -> list[dict]:
    """The user's own collections (Favorites first), then smart ones."""
    out = [collection_summary(c, "user") for c in user]
    out.sort(key=lambda c: (not c["is_favorite"], (c["name"] or "").lower()))
    out += sorted((collection_summary(c, "smart") for c in smart), key=lambda c: (c["name"] or "").lower())
    return [c for c in out if c["rom_count"]]


def virtual_summary(kind: str, items: list[dict]) -> list[dict]:
    out = [collection_summary(c, "virtual") for c in items if c.get("rom_count")]
    out.sort(key=lambda c: (c["name"] or "").lower())
    return out
