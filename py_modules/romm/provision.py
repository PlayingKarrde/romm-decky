"""Get an emulator ready: RetroArch cores from the libretro buildbot, BIOS files from RomM.

Both run in the install worker (cores before the ROM, BIOS after) and from the
plugin when the user switches a platform to a core that isn't downloaded yet.
"""

from __future__ import annotations

import hashlib
import io
import os
import urllib.error
import urllib.request
import zipfile
from typing import Callable

from . import emulators
from .client import USER_AGENT, RommClient, RommError, urlopen
from .installer import Cancelled, safe_name

MAX_CORE_ZIP = 200 * 1024 * 1024


def download_core(home: str, core: str, cancelled: Callable[[], bool] = lambda: False) -> str:
    """Fetch <core>_libretro.so into RetroArch's cores dir. Returns its path."""
    target = emulators.core_path(home, core)
    if os.path.isfile(target):
        return target
    url = emulators.core_url(core)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=60) as resp:
            buf = io.BytesIO()
            while True:
                if cancelled():
                    raise Cancelled()
                b = resp.read(1 << 20)
                if not b:
                    break
                buf.write(b)
                if buf.tell() > MAX_CORE_ZIP:
                    raise RommError(f"Core download for {core} is unexpectedly large", code="core_failed")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RommError(f"The libretro buildbot has no '{core}' core", code="core_failed") from None
        raise RommError(f"Couldn't download the {core} core (HTTP {e.code})", code="core_failed") from None
    except (urllib.error.URLError, OSError) as e:
        raise RommError(f"Couldn't download the {core} core: {e}", code="core_failed") from None
    want = f"{core}_libretro.so"
    try:
        with zipfile.ZipFile(buf) as z:
            member = next((i for i in z.infolist() if os.path.basename(i.filename) == want), None)
            if not member:
                raise RommError(f"The {core} core download didn't contain {want}", code="core_failed")
            data = z.read(member)
    except zipfile.BadZipFile:
        raise RommError(f"The {core} core download wasn't a zip", code="core_failed") from None
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    return target


def fetch_bios(client: RommClient, platform_id: int, bios_dir: str,
               cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Copy the platform's firmware from RomM into bios_dir.

    Files already there (by name) are left alone, whatever their content: the
    user's own BIOS setup wins. Returns {added: [names], present: [names]}.
    BIOS files are never deleted by uninstall.
    """
    added, present = [], []
    for fw in client.list_firmware(int(platform_id)):
        name = safe_name(fw.get("file_name") or "")
        target = os.path.join(bios_dir, name)
        if os.path.exists(target):
            present.append(name)
            continue
        if cancelled():
            raise Cancelled()
        os.makedirs(bios_dir, exist_ok=True)
        tmp = f"{target}.romm-part"
        h = hashlib.md5()
        with client.open_firmware(fw["id"], fw["file_name"]) as resp, open(tmp, "wb") as out:
            while True:
                b = resp.read(1 << 20)
                if not b:
                    break
                out.write(b)
                h.update(b)
        want = (fw.get("md5_hash") or "").lower()
        if want and h.hexdigest() != want and not name.lower().endswith((".zip", ".7z")):
            os.remove(tmp)
            raise RommError(f"Checksum mismatch for BIOS file {name}", code="bad_checksum")
        os.replace(tmp, target)
        added.append(name)
    return {"added": added, "present": present}
