# romm-decky

A Decky Loader plugin that browses a self-hosted **RomM** server from Steam Gaming Mode, installs ROMs as non-Steam shortcuts that launch the right emulator, and uninstalls them. It is a sibling of `../gameyfin-decky` (the same author's Gameyfin plugin). That plugin is shipped, has been verified on a Deck, and is the template for this one.

**Status (2026-11-06): v0.1.0 released.** Release page: https://github.com/PlayingKarrde/romm-decky/releases/tag/v0.1.0
- Steps 0 to 5 are done, and every step was verified by the user on the Deck.
- **Pushing from WSL:** git uses Windows Git Credential Manager (`credential.helper` in the global config).
  - Pushes succeed, but GCM prints `Failed to write item to store. [0x8]` because it can't save the token, so it may ask for a browser sign-in again.
  - The repo is public, so CI and release status can be read without auth at `api.github.com/repos/PlayingKarrde/romm-decky/actions/runs`.
- **Next (v2 ideas):** save/state sync (RomM `/api/saves`, `/api/states`, `/api/sync`), banner/logo art from SteamGridDB, and "send to Deck" install requests (`/api/devices/{id}/installs`).
- The repo uses a repo-local git identity (PlayingKarrde, with the GitHub no-reply email).
- The plan is in `docs/PLAN.md`.

## Why a separate plugin
- RomM and Gameyfin share almost nothing past the plumbing:
  - different auth and APIs,
  - emulators rather than Proton,
  - platform→emulator mapping, BIOS files, multi-disc games,
  - RomM has save/state APIs that will matter later.
- Merging them would mean a source abstraction that touches every layer. Copy the plumbing instead. Don't build a shared library until both plugins are stable and the duplication actually hurts.
- `gameyfin-decky` stays Gameyfin-only; its CLAUDE.md says "No RomM code". Don't add RomM code there.

## Why not Tender
Tender (github.com/danielcopper/decky-romm-sync) already exists. The user tried it and rejected it for two reasons:
- **The way it integrates with Steam: it syncs the whole RomM library into Steam as shortcuts.** romm-decky installs on demand only. A shortcut exists only for a ROM the user installed, and uninstalling removes it.
- **It requires RetroDECK.**

**Hard requirement: no RetroDECK dependency.** Tender is still worth reading as a RomM API reference. It's a poor model for how the plugin should behave.

## Hard constraints (inherited from gameyfin-decky; they still apply)
- **Stay a Decky plugin**, not a standalone service.
- **Long downloads run in a separate worker process** that survives Decky restarts:
  - started by `systemd-run --user` with `/usr/bin/python3`,
  - writes progress to a `state.json`, which a frontend poller reads.
  - Small ROMs could download inline, but use one code path unless that proves painful.
- **Decky's bridge payload cap is about 1 MiB.** Send small JSON only. Images go through an on-disk cache and are sent as data URLs.
- **Everything the plugin runs must ship with it or come with SteamOS.** The root filesystem is read-only. User-level Flatpaks (`flatpak install --user`) are available on SteamOS and are the likely way to get emulators.
- **The plugin runs as `deck`**, without the `_root` flag.
- **Backend callables return an envelope:** `{ok, data}` or `{ok: false, error: {message, status, code}}`. Credentials never go to the frontend.
- **Save sync is out of scope for v1.** It's a likely v2 feature, because RomM has save and state endpoints.

## Decisions (2026-11-06)
- **Emulators: a mix.**
  - RetroArch (the Flatpak `org.libretro.RetroArch`) is the default. The plugin offers to install it (`flatpak install --user`) and fetches cores on demand from the libretro buildbot into the Flatpak's `cores/` dir.
  - Detected standalone emulators win where they're better: Flatpaks such as `org.duckstation.DuckStation`, `net.pcsx2.PCSX2`, `org.DolphinEmu.dolphin-emu`, `org.ppsspp.PPSSPP` and `info.cemu.Cemu`, EmuDeck AppImages in `~/Applications`, and Steam RetroArch.
  - Settings has a per-platform override.
  - A `PLATFORMS` table in `emulators.py` maps each RomM slug to an ordered list of candidates.
- **Shortcut target: a launch wrapper the plugin ships** (`bin/romm-launch`, which calls `py_modules/romm/launch.py <rom_id>`). The emulator is resolved at launch time, so changing the emulator choice never means editing shortcuts, and save sync gets a hook later.
  - Not yet decided: pass the ROM id through a per-game stub in the install dir, so the user's launch options are never touched. Check on the Deck.
- **Compat tool:** always cleared, with `SpecifyCompatTool(appid, "")`.
- **Emulator layer (`emulators.py`), decided with the user on 2026-11-06:**
  - **Emulators are launched directly** (`flatpak run …` or the AppImage), **never through EmuDeck's launcher scripts.** Those also run EmuDeck init and cloud-sync upload. Arguments follow EmuDeck's Steam ROM Manager parsers, as recorded in `~/.config/steam-rom-manager/userData/userConfigurations.json` on the Deck.
  - **Platforms map to candidates:** `PLATFORMS[slug]` is an ordered list of `retroarch:<core>` or standalone emulator ids.
  - **Choosing:** `resolve()` takes the user's override (`settings.platform_overrides[key]`) if it's installed, else the first ready candidate, else the first whose core can be downloaded.
  - **Detection:** Flatpak app dirs (user and system) and `~/Applications/<Prefix>*.AppImage`. EmuDeck's AppImage wins over a Flatpak for DuckStation, PCSX2, Cemu and RPCS3, because that's the build EmuDeck configured.
  - **Core downloads:** a missing RetroArch core comes from `buildbot.libretro.com/nightly/linux/x86_64/latest/<core>_libretro.so.zip`, in the worker (phase `core`) or when the user switches.
  - **BIOS:** each emulator's BIOS folder is read from its own config (`retroarch.cfg` `system_directory`, DuckStation `settings.ini` `[BIOS] SearchDirectory`, PCSX2 `inis/PCSX2.ini` `[Folders] Bios`). On the Deck all three point at `~/Emulation/bios`. RomM firmware for the platform is copied there after the ROM (phase `bios`). Existing names are never overwritten, and BIOS files are never deleted.
  - **Keeping launchers current:** at plugin load, `_refresh_launchers` rewrites any launch script whose resolved command changed. It never downloads cores, so "Automatic" follows newly installed emulators. Changing an override rewrites that platform's scripts, downloading the core if needed.
- **Updates and health (`status.py`):** a ROM counts as updated when RomM's `[name, size, md5]` list differs from `record["server_files"]`, saved at install.
  - Records without a baseline adopt the current state, so they're never flagged spuriously.
  - `update_rom` reinstalls into the same root. The worker may overwrite only files the record lists (`replace`), and owned files the server dropped are deleted.
  - Ownership persists across reinstalls: a previously owned file that's unchanged stays owned.
- **Playlist-only ROMs:** RomM indexes a loose `Game.m3u` as its own ROM, separate from the folder holding the discs (PSX Chrono Cross: 5269 is the `.m3u`, 5268 the discs). `rom_detail()["playlist_for"]` lists the `sibling_roms`, and installing one is refused, naming the real game.
- **BIOS:** fetched from RomM's firmware endpoint into the chosen emulator's BIOS dir (RetroArch `system/`, DuckStation and PCSX2 `bios/`). Files already present with the same hash are skipped.
- **Multi-disc:** generate an `.m3u`. **Archives:** extract only when the platform's map entry says so.
- **Install layout (2026-11-06, the user's choice):** EmuDeck style, `<root>/<platform>/<file>`. A multi-file game gets `<root>/<platform>/<fs_name>/` plus an `.m3u`.
  - The default root is `~/Emulation/roms` when it exists, otherwise `~/Games/RomM`. It can be changed in the QAM "Install location" panel (an SD card, or any folder).
  - The platform folder is RomM's `fs_slug`; an existing folder whose name differs only in case is reused (MAME vs mame).
  - **There are no marker files.** `installed.json` records each file with `owned` set to true (we downloaded it) or false (adopted).
  - **Adoption:** a file already present with a matching size and MD5 is adopted instead of downloaded, also the user's choice. Uninstall deletes only owned files whose size is unchanged. Adopted files are kept unless the user picks "Delete files too" in the uninstall dialog, which the user asked for on 2026-11-06.
  - A different file already at the target path stops the install with a `conflict` error. It is never overwritten.
- **Launching:** each shortcut runs `~/.local/share/romm-decky/launch/<rom_id>.sh`, which execs the resolved emulator command with `"$@"`.
  - Steam's launch options stay empty, and the user's own options pass through.
  - Changing the emulator means rewriting the script, never the shortcut.
- **Browsing:** tabs for Platforms, RomM Collections and Installed. Platforms and Collections each drill into a paged ROM grid with search.
- **Steam collections:** each installed game goes into a per-platform Steam collection (for example "SNES"). The names come from `library.COLLECTION_NAMES`, falling back to RomM's display name.
  - **Verified on the Deck:**
    - `collectionStore.NewUnsavedCollection(name, undefined, [overview])` followed by `.Save()` creates a collection.
    - For an existing one, `GetUserCollectionsByName(name)[0].AsDragDropCollection().AddApps([ov])` followed by `.Save()` adds the app.
    - Removing the shortcut drops it from the collection.
  - **RomM collections are never mirrored into Steam.** The user rejected this on 2026-11-06. RomM collections, including the virtual ones, can only be browsed in the plugin.
  - Verify the `collectionStore` calls with `cdp.py` before building on them.
- **Auth:** pair through RomM's device-auth flow (see RomM API below). The plugin stores only the client token, in `settings.json` (mode 0600). Username and password exist only in the dev `.env`.

## Steam UI gotchas (verified on the Deck)
- **B on a page with drill-down:** once a Focusable has `onCancelButton`, Steam treats B as handled and skips its default back action. The handler must call `Navigation.NavigateBack()` itself at the top level. See `LibraryPage`.
- **`ConfirmModal` doesn't close when `onOK` is async.** The work ran, the dialog stayed open, and a second press errored. In the handlers, only resolve a promise; do the work after the dialog closes. See `confirmUninstall`. `strMiddleButtonText`/`onMiddleButton` add a third button.
- **After `systemctl restart plugin_loader`,** `DeckyBackend` takes a few seconds to appear. `cdp.py` scripts should wait for it before calling `rm(...)`.

## RomM API (verified 2026-11-06 against the user's server, RomM 5.4.1)
The schema is saved at `docs/openapi.json`. The client is `py_modules/romm/client.py`, and `scripts/romm.py test|platforms|roms|rom|collections|firmware|fetch` exercises it using `.env` (`ROMM_URL`, and either `ROMM_TOKEN` or `ROMM_USER`/`ROMM_PASS`).
- **Auth:** HTTP Basic and OAuth2 `Bearer` both work. The dev CLI uses Basic.
- **The server sits behind Cloudflare.** A request without a `User-Agent` (Python's urllib default) gets `403 error code: 1010`. `RommClient` always sends `romm-decky/<ver>`; keep that header on every request, including in the worker.
- **Pairing: use RomM's device-auth flow instead of gameyfin-decky's homemade phone pairing.**
  1. `POST /api/auth/device/init` (no auth) with `{client_device_identifier, name, client, platform, client_version, requested_scopes}` returns `{device_code, user_code, verification_path, verification_path_complete, expires_in, interval}`.
  2. The Deck shows `verification_path_complete` as a QR code, and the user approves it in the RomM web UI.
  3. The Deck polls `POST /api/auth/device/token {device_code}`, which returns `{access_token, device_id, scopes, expires_at}`: a client token tied to a RomM Device.
  - Polling returns RFC 8628 errors as HTTP 400 with `detail` set to `authorization_pending`, `slow_down`, `expired_token` or `access_denied`. This was verified live.
  - No password is ever stored on the Deck. Scopes are in `client.DEVICE_SCOPES`.
- **Devices and install requests:** `/api/devices/{id}/installs` lets the RomM web UI queue "install on this device" requests, which the device claims. This could be a later feature ("send to Deck").
- **Platforms:** `GET /api/platforms` returns all 178 known platforms; only about 36 have ROMs, so filter on `rom_count > 0`. Slugs aren't unique (two `arcade` platforms with fs_slugs `MAME` and `arcade`; `genesis` with fs_slug `megadrive`), so key on the platform `id` and map emulators by `slug`.
- **ROMs:** `GET /api/roms?platform_ids=&collection_id=&smart_collection_id=&virtual_collection_id=&search_term=&limit=&offset=&order_by=name&order_dir=asc` returns `{items, total, limit, offset}`.
  - Each item is about 9 KB, so slim it down with `library.py` before sending it to the frontend.
  - **List items have `files: []`;** only `GET /api/roms/{id}` returns `files[]`.
  - Multi-disc games (for example PSX `.chd` per disc) are `has_multiple_files`, and their files can include 0-byte placeholders such as `noload.txt`, which `library._game_files` filters out.
  - Single-file ROMs are often `.7z` or `.zip`. RetroArch opens archives itself; standalone emulators may need them extracted.
- **Downloads:**
  - Use `GET /api/roms/{id}/content/{file_name}?file_ids={file_id}`, one file at a time. It serves the raw file, supports `Range` (206), and has an ETag. Resume has been tested and the MD5 matched.
  - Without `file_ids`, a multi-file ROM comes back as a zip (with an `.m3u` if applicable). **Don't use that path:** download per file and write our own `.m3u`. That gives resumable downloads, no extraction, and no need for double the disk space.
  - `/api/roms/{id}/files/content/{name}` returned 404 when given a ROM id; avoid it.
  - Every file has an `md5_hash`, but **for archives (`.zip`, `.7z`) it's the MD5 of the ROM inside**, because RomM identifies games by content. Verified with a `.zip`.
    - `installer.content_matches` checks the member's MD5 for a one-file zip, and only the size for 7z and multi-file zips.
- **Covers:** `path_cover_small`/`path_cover_large`, such as `/assets/romm/resources/roms/<pid>/<rid>/cover/small.png?ts=...`. These are PNGs of about 55 KB and are served without auth on this server; the client sends auth anyway.
- **Collections:**
  - `/api/collections` holds the user collections; this server has only "Favorites".
  - `/api/collections/smart` is empty here.
  - `/api/collections/virtual?type=collection|franchise|genre|company|mode` returns auto-generated collections with opaque base64 string ids. These are well populated (149 franchises).
- **Firmware:** `GET /api/firmware?platform_id=` returns `{id, file_name, file_size_bytes, md5_hash, is_verified}`. Download with `/api/firmware/{id}/content/{file_name}`. PS2 has 35 files and Amiga 6.
- **Saves and states:** `/api/saves`, `/api/states`, `/api/sync/*`, `/api/play-sessions`, all for v2.

## What to copy from ../gameyfin-decky
Copy the files and adapt them. Read each one before copying; don't assume its behaviour.
- **Scaffolding:**
  - `package.json`, `rollup.config.js`, `tsconfig.json`, `plugin.json`, `decky.pyi`, `.gitignore`, `LICENSE`, `.github/workflows/` (CI and release).
  - The release workflow creates a GitHub release when a `v*` tag is pushed and refuses tags that don't match `package.json`.
  - Push the tag **after** the first commit is on GitHub. gameyfin-decky's v0.1.0 tag went up with the repo's first push and never produced a release.
- **Scripts:** `deploy.sh` and `package.sh` (change `NAME`), `logs.sh`, and `cdp.py` (runs JS in Steam's SharedJSContext over an SSH tunnel; good for trying SteamClient calls).
- **Backend:**
  - `jobs.py` and `worker.py`: worker launch and the job/state pattern.
  - `installer.py`: streaming download, cancellation, safe folder names, the install marker.
  - `installed.py`: an installed.json record with a lock, install targets (internal, SD or custom), and safe delete.
  - `settings.py`: corrupt files load as defaults; use `dataclasses.replace` for updates.
  - `images.py`: the disk cache, unique temp names, data URLs.
  - `status.py`: drift checks (missing files or a missing shortcut).
  - `client.py`: `ssl_context()` with the system CA bundle. **Decky's PyInstaller Python has no CA store**, so HTTPS fails without it.
- **Frontend:**
  - `src/steam.ts`: every `SteamClient.Apps.*` call. Paths are quoted. `SetAppLaunchOptions` is only called when options are set, because otherwise it wipes the user's options.
  - `src/installs.ts`: the poller with its re-entrancy guard; finished jobs become shortcuts.
  - `src/contextMenu.tsx`: patches Steam's library context menu to add Uninstall.
  - `src/components/`: the library page with tabs and infinite scroll, the Downloads panel, the install location picker (`openFilePicker`), and the confirm modals.
- **Tests:** the `unittest` pattern and a fake server for streaming downloads (`tests/fake_gameyfin.py`).

## Dev environment (same machines as gameyfin-decky)
- **The PC is WSL.** Node and pnpm are in `~/.local/bin`. Never use the Windows npm on PATH.
- **The Deck is SSH alias `deck`** and stays in Gaming Mode. Deploy with rsync to a staging dir, then one exact-args `sudo rsync` into `~/homebrew/plugins/<name>/` (Decky re-chowns plugin dirs to root on every start).
  - **The sudoers whitelist is per plugin dir.** Before the first deploy, the user must add a line to `/etc/sudoers.d/zz-decky-dev` on the Deck:
    `deck ALL=(root) NOPASSWD: /usr/bin/rsync -a --delete /home/deck/.cache/romm-decky-stage/ /home/deck/homebrew/plugins/romm-decky/`
  - The `systemctl restart plugin_loader` rule already exists.
  - The file name must sort after `wheel`.
- **The user edits some files from Windows.** Strip `\r` from `.env` and similar files.
- **Not on the Decky store.** It rejects LLM-written plugins. Users install from the GitHub release zip URL.

## Conventions
- Commit or push only when the user asks. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Verify Steam integration on the Deck (through `cdp.py`) before building UI around it. `SteamClient` is undocumented and changes often.

## Suggested first session
1. Discuss the emulator strategy and what the user disliked about Tender's Steam integration. Record the decisions here.
2. Get the RomM server URL, version and credentials. Pull `/openapi.json` and write `client.py` plus a `scripts/romm.py test|platforms|roms` CLI, as `scripts/gf.py` does.
3. Scaffold from gameyfin-decky: build, deploy a hello panel, and confirm the loop works (after the sudoers line above is added).
4. Do one platform end to end, for example SNES through RetroArch: download a ROM, create a shortcut, launch it from Gaming Mode.
