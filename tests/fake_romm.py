"""A tiny fake RomM server for installer tests: ROM detail + per-file content with Range."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeRomm:
    """roms: {rom_id: {"rom": DetailedRom-ish dict, "content": {file_id: bytes}}}"""

    def __init__(self):
        self.roms: dict[int, dict] = {}
        self.requests: list[tuple[str, str | None]] = []  # (path, Range header)
        self.honour_range = True

    def add_rom(self, rom_id: int, platform: str, fs_name: str, files: dict[str, bytes], multi: bool = False,
                fs_slug: str | None = None) -> None:
        entries, content = [], {}
        for i, (name, data) in enumerate(files.items()):
            fid = rom_id * 100 + i
            content[fid] = data
            entries.append({"id": fid, "file_name": name, "file_size_bytes": len(data),
                            "md5_hash": hashlib.md5(data).hexdigest(), "category": "game", "is_top_level": True,
                            "file_path": f"roms/{platform}/{fs_name}" if multi else f"roms/{platform}"})
        self.roms[rom_id] = {"content": content, "rom": {
            "id": rom_id, "name": fs_name, "fs_name": fs_name, "fs_path": f"roms/{platform}",
            "platform_id": 1, "platform_slug": platform, "platform_fs_slug": fs_slug or platform,
            "platform_display_name": platform.upper(), "fs_size_bytes": sum(map(len, files.values())),
            "has_multiple_files": multi, "files": entries, "path_cover_small": None, "path_cover_large": None,
        }}

    def start(self) -> str:
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                rng = self.headers.get("Range")
                fake.requests.append((u.path, rng))
                m = re.fullmatch(r"/api/roms/(\d+)", u.path)
                if m and int(m.group(1)) in fake.roms:
                    body = json.dumps(fake.roms[int(m.group(1))]["rom"]).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                m = re.fullmatch(r"/api/roms/(\d+)/content/.+", u.path)
                if m and int(m.group(1)) in fake.roms:
                    fid = int(urllib.parse.parse_qs(u.query)["file_ids"][0])
                    data = fake.roms[int(m.group(1))]["content"][fid]
                    start = 0
                    if rng and fake.honour_range:
                        start = int(re.match(r"bytes=(\d+)-", rng).group(1))
                    chunk = data[start:]
                    self.send_response(206 if start else 200)
                    if start:
                        self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.end_headers()
                    self.wfile.write(chunk)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
