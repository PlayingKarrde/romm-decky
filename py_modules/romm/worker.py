"""Install worker: ``python3 -m romm.worker <job_dir>``.

Runs outside Decky (system python, own systemd --user unit). Reads job.json,
reports progress to state.json, honours the cancel flag and SIGTERM. The token
is read from the plugin's settings.json, never from job.json.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback

from . import jobs, library
from .client import RommClient, RommError
from .installer import Cancelled, cleanup_parts, install, platform_dir


class Reporter:
    """Throttled state writer with a smoothed speed estimate."""

    def __init__(self, job_dir: str, base: dict):
        self.job_dir = job_dir
        self.state = dict(base)
        self._last_t = time.monotonic()
        self._last_done = 0
        self._last_phase = None
        self._last_write = 0.0
        self._speed = 0.0

    def update(self, **fields) -> None:
        self.state.update(fields)
        jobs.write_state(self.job_dir, self.state)
        self._last_write = time.monotonic()

    def progress(self, phase: str, done: int, total: int | None) -> None:
        now = time.monotonic()
        if phase != self._last_phase:
            self._last_phase, self._last_done, self._last_t, self._speed = phase, done, now, 0.0
            return self.update(phase=phase, done=done, total=total, speed=0)
        dt = now - self._last_t
        if dt >= 0.5:
            inst = (done - self._last_done) / dt
            self._speed = inst if self._speed == 0 else 0.7 * self._speed + 0.3 * inst
            self._last_t, self._last_done = now, done
        if now - self._last_write >= 0.25:
            self.update(phase=phase, done=done, total=total, speed=max(0, round(self._speed)))


def _client(spec: dict) -> RommClient:
    token = ""
    if spec.get("settings_path"):
        with open(spec["settings_path"], encoding="utf-8") as f:
            token = json.load(f).get("token", "")
    token = token or os.environ.get("ROMM_TOKEN", "")
    return RommClient(spec["server_url"], token=token, username=os.environ.get("ROMM_USER"),
                      password=os.environ.get("ROMM_PASS"))


def run(job_dir: str) -> int:
    spec = jobs.read_spec(job_dir)
    rep = Reporter(job_dir, {
        "job_id": spec["job_id"], "rom_id": spec["rom_id"], "title": spec.get("title"),
        "root": spec["root"], "pid": os.getpid(), "started_at": time.time(),
        "phase": "starting", "done": 0, "total": spec.get("total_bytes"), "kind": spec.get("kind", "install"),
    })
    rep.update()

    cancel = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: cancel.__setitem__("flag", True))
    cancelled = lambda: cancel["flag"] or jobs.cancel_requested(job_dir)  # noqa: E731

    rom = None
    try:
        client = _client(spec)
        rom = library.rom_detail(client.get_rom(int(spec["rom_id"])))
        rep.update(title=rom["name"])
        res = install(client, rom, spec["root"], rom["platform_fs_slug"], rep.progress, cancelled)
        res["rom"] = {k: rom.get(k) for k in ("name", "platform_id", "platform_slug", "platform_fs_slug",
                                              "platform_name", "cover", "cover_large")}
        rep.update(phase="done", result=res, done=res["size"], total=res["size"], speed=0, finished_at=time.time())
        return 0
    except Cancelled:
        if rom:
            cleanup_parts(platform_dir(spec["root"], rom["platform_fs_slug"]), rom)
        rep.update(phase="cancelled", speed=0, finished_at=time.time())
        return 2
    except RommError as e:
        rep.update(phase="error", error=str(e), error_code=e.code, speed=0, finished_at=time.time())
        return 1
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        rep.update(phase="error", error=f"{type(e).__name__}: {e}", error_code="internal", speed=0,
                   finished_at=time.time())
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 -m romm.worker <job_dir>")
    sys.exit(run(sys.argv[1]))
