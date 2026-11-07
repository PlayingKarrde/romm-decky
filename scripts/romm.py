#!/usr/bin/env python3
"""Dev CLI for the RomM client, using credentials from ./.env.

  scripts/romm.py test
  scripts/romm.py platforms
  scripts/romm.py roms [search] [--platform ID] [--collection ID] [--smart ID] [--virtual ID] [--offset N] [--limit N]
  scripts/romm.py rom <id>
  scripts/romm.py collections [--virtual-kind collection|franchise|genre|company|mode]
  scripts/romm.py firmware <platform_id>
  scripts/romm.py fetch <rom_id> --dest DIR [--stop-after BYTES]   # per-file download with Range resume

.env keys (CRLF tolerated): ROMM_URL, and ROMM_TOKEN or ROMM_USER + ROMM_PASS.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))

from romm.client import RommClient, RommError  # noqa: E402
from romm import library  # noqa: E402


def load_env(path: str) -> dict:
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def make_client() -> RommClient:
    env = {**load_env(os.path.join(ROOT, ".env")), **os.environ}
    url = env.get("ROMM_URL")
    if not url:
        sys.exit("Set ROMM_URL (and ROMM_TOKEN or ROMM_USER/ROMM_PASS) in .env")
    c = RommClient(url, token=env.get("ROMM_TOKEN"), username=env.get("ROMM_USER"), password=env.get("ROMM_PASS"))
    if not c.has_auth:
        sys.exit("Set ROMM_TOKEN or ROMM_USER/ROMM_PASS in .env")
    return c


def fmt(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def collections(c: RommClient, virtual_kind: str | None) -> list[dict]:
    out = [library.collection_summary(x, "user") for x in c.list_collections()]
    out += [library.collection_summary(x, "smart") for x in c.list_smart_collections()]
    for kind in ([virtual_kind] if virtual_kind else []):
        out += [library.collection_summary(x, f"virtual:{kind}") for x in c.list_virtual_collections(kind)]
    return out


def fetch(c: RommClient, rom_id: int, dest: str, stop_after: int | None) -> dict:
    """Throwaway downloader to exercise per-file Range resume (the worker gets the real one)."""
    rom = library.rom_detail(c.get_rom(rom_id))
    os.makedirs(dest, exist_ok=True)
    results = []
    for f in rom["files"]:
        path = os.path.join(dest, f["name"])
        part = path + ".part"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if os.path.exists(path) and os.path.getsize(path) == f["size"]:
            results.append({"file": f["name"], "status": "already"})
            continue
        with c.open_rom_file(rom_id, f["id"], f["name"], offset=have) as resp:
            resumed = have > 0 and resp.status == 206
            mode = "ab" if resumed else "wb"
            done = have if resumed else 0
            with open(part, mode) as out:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    print(f"\r{f['name'][:40]:40} {fmt(done)} / {fmt(f['size'])}", end="", file=sys.stderr)
                    if stop_after and done >= stop_after and done < f["size"]:
                        print(file=sys.stderr)
                        return {"stopped_at": done, "file": f["name"], "rerun_to_resume": True}
        print(file=sys.stderr)
        if os.path.getsize(part) != f["size"]:
            raise RommError(f"size mismatch for {f['name']}: {os.path.getsize(part)} != {f['size']}")
        os.replace(part, path)
        results.append({"file": f["name"], "status": "resumed" if resumed else "downloaded", "size": f["size"]})
    return {"rom": rom["name"], "files": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    sub.add_parser("platforms")
    r = sub.add_parser("roms")
    r.add_argument("search", nargs="?", default="")
    r.add_argument("--platform", type=int)
    r.add_argument("--collection", type=int)
    r.add_argument("--smart", type=int)
    r.add_argument("--virtual")
    r.add_argument("--offset", type=int, default=0)
    r.add_argument("--limit", type=int, default=20)
    g = sub.add_parser("rom")
    g.add_argument("id", type=int)
    co = sub.add_parser("collections")
    co.add_argument("--virtual-kind", choices=library.VIRTUAL_KINDS)
    fw = sub.add_parser("firmware")
    fw.add_argument("platform_id", type=int)
    fe = sub.add_parser("fetch")
    fe.add_argument("id", type=int)
    fe.add_argument("--dest", required=True)
    fe.add_argument("--stop-after", type=int)
    args = ap.parse_args()

    c = make_client()
    try:
        if args.cmd == "test":
            out = c.test_connection()
        elif args.cmd == "platforms":
            out = library.platforms_summary(c.list_platforms())
        elif args.cmd == "roms":
            out = library.page_summary(c.list_roms(
                platform_id=args.platform, collection_id=args.collection, smart_collection_id=args.smart,
                virtual_collection_id=args.virtual, search=args.search or None,
                offset=args.offset, limit=args.limit))
        elif args.cmd == "rom":
            out = library.rom_detail(c.get_rom(args.id))
        elif args.cmd == "collections":
            out = collections(c, args.virtual_kind)
        elif args.cmd == "firmware":
            out = [{k: f.get(k) for k in ("id", "file_name", "file_size_bytes", "md5_hash", "is_verified")}
                   for f in c.list_firmware(args.platform_id)]
        else:
            out = fetch(c, args.id, args.dest, args.stop_after)
    except RommError as e:
        sys.exit(f"error: {e} (status={e.status}, code={e.code})")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
