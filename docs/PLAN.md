# romm-decky — implementation plan

## Context
We want a Decky plugin that browses a self-hosted RomM server from Gaming Mode, installs ROMs on demand as non-Steam shortcuts that launch the right emulator, and uninstalls them. It copies the plumbing of `../gameyfin-decky` (shipped, verified on a Deck). The real differences from Gameyfin are:
- **Emulators instead of Proton.** Each platform maps to an emulator, plus cores, BIOS files, multi-disc games and archives.
- **Browsing by platform and collection**, not one flat library.
- **Different auth and API.**

Decisions made with the user (2026-11-06):
- **Emulators: a mix.** RetroArch (Flatpak) is the default; the plugin can install it and its cores. Standalone emulators it detects (Flatpak or EmuDeck AppImages) are preferred where they're better. Settings has a per-platform override. **No RetroDECK.**
- **What went wrong with Tender:** it syncs the whole library into Steam. → **Install on demand only.** A shortcut exists only for a ROM the user installed, and uninstalling removes it.
- **Browsing:** a Platforms tab and a RomM Collections tab, plus Installed.
- **Steam collections:** each installed game goes into a per-platform Steam collection (e.g. "SNES"). RomM collections are **not** mirrored into Steam, by the user's decision; they are browse-only in the plugin.
- **Auth:** RomM 5.4.1 has a device-auth flow. The Deck shows a QR code, you approve it in RomM, and the Deck gets a client token. No password is stored on the Deck. (Updated after checking the API.)

## Step 0 — record decisions, get server access
1. Update `CLAUDE.md`: set the status, add the decisions above, and drop the open questions they settle.
2. Get the server URL and credentials from the user, and put them in a git-ignored `.env`. Strip `\r` from it, and never print it.
3. Pull `<server>/openapi.json` into `docs/openapi.json`. From it, confirm:
   - the auth schemes, and whether the server has API or client tokens;
   - the endpoints for platforms, ROMs (paging shape, filters, search), ROM detail, content download, collections (regular, smart, virtual), firmware and covers.
4. Find out whether `/api/roms/{id}/content/...` honours `Range`, and what a multi-file ROM download looks like (a zip?).
5. Write `py_modules/romm/client.py`:
   - Copy `ssl_context()`/`urlopen` and the error class from `gameyfin-decky/py_modules/gameyfin/client.py:34-58`.
   - Add a `RommClient` with `test_connection`, `list_platforms`, `list_roms(platform_id|collection_id, search, offset, limit)`, `list_collections`, `get_rom`, `open_download`, `fetch_image` and `list_firmware`.
   - Auth: prefer a long-lived token if the server offers one. Otherwise use the password grant at `/api/token` and refresh it, with Basic as the fallback. The password is stored only in `settings.json` (mode 0600).
6. Write `scripts/romm.py test|platforms|roms|rom|collections|firmware|install`, modelled on `scripts/gf.py`.

## Step 1 — scaffold and a hello panel
- **Copy and rename** from gameyfin-decky:
  - `package.json`, `rollup.config.js`, `tsconfig.json`, `plugin.json` (name "RomM"), `decky.pyi`, `.gitignore`, `LICENSE` and `.github/workflows/`;
  - `scripts/{deploy,package,logs}.sh`, with `NAME=romm-decky` and no innoextract;
  - `scripts/cdp.py`, changing the plugin name inside its `gf()` helper.
- **Generic backend, copied mostly verbatim** into `py_modules/romm/`: `jobs.py`, `settings.py` (fields `server_url`, `token`, `device_id`, `custom_install_dir`, `platform_overrides`, `steam_collections_platform`), `installed.py`, `images.py`, and `status.py`. **Skip `pairing.py`:** RomM's device-auth flow replaces it, with a QR code of `verification_path_complete` and the Deck polling for the token.
- **Renames:** `.romm.json` marker, `.romm-tmp`, the `romm-install-<job>` unit name, and `~/Games/RomM`.
- **`main.py`:** copy the `_ok`/`_err`/`_call` envelope (`gameyfin-decky/main.py:25-52`). Start with `ping`, `get_settings`, `save_settings` and `test_connection`.
- **Deploy loop:** the user adds the sudoers line from CLAUDE.md. Then run `deploy.sh` and confirm the QAM panel loads and Test connection works.

## Step 2 — browsing
- **`library.py`:** slim summaries. A platform has `{id, slug, name, rom_count}`. A ROM has `{id, name, platform_slug, cover, size, multi_disc}`. Collections are tagged by kind.
- **Callables:** `list_platforms`, `list_collections`, `list_roms(scope, id, search, page)`, `get_rom`, plus the existing image callables.
- **`LibraryPage.tsx`** keeps the tabs, the debounced search, `IntersectionObserver` infinite scroll and the focusable grid. Tabs:
  - **Platforms:** a grid of platform tiles. Opening one shows a paged ROM grid with search.
  - **Collections:** the same, over RomM collections.
  - **Installed:** built locally from `installed.json`.
- **`GameModal`:** cover, platform, size, disc count, which emulator will be used (and whether it's missing), and Install/Play/Uninstall.

## Step 3 — one platform end to end (SNES → RetroArch)
- **Install layout:** `<target>/RomM/<platform_slug>/<safe name>/` holds the ROM files and the `.romm.json` marker.
- **Worker:** reuse `jobs.launch_worker` (systemd-run) and the `Reporter`/cancel skeleton from `worker.py`. Replace the Gameyfin parts:
  - **Download:** fetch each file separately (`content/{name}?file_ids=`) with `Range` resume from `.part` (verified), then check the MD5.
  - **Unpack:** extract `.7z`/`.zip` only when the chosen emulator can't read archives.
  - **Multi-disc:** generate an `.m3u`.
  - **Launch file:** write `launch_target` (a relative path) into the state.
- **Launcher (stable shortcut target):**
  - Ship `bin/romm-launch` (POSIX sh) in the plugin. Each shortcut's exe is that script, and the ROM id is passed through it.
  - At launch it runs a small Python resolver, `py_modules/romm/launch.py <rom_id>`. The resolver reads `installed.json`, the settings overrides and the detected emulators, then `exec`s `flatpak run org.libretro.RetroArch -L <core> <file>` (or a standalone emulator).
  - So changing the emulator choice never means editing shortcuts, and save sync gets a hook later.
  - The user's launch options are left alone. To check on the Deck: whether to put the ROM id in a per-game stub script inside the install dir rather than in launch options, so `SetAppLaunchOptions` is never touched.
- **`steam.ts`:**
  - Reuse `upsertShortcut`, `removeShortcut` and `applyArtwork`.
  - Always clear the compat tool with `SpecifyCompatTool(appid, "")`.
  - Add `addToCollection(appid, name)` and `removeFromCollections(appid)` via `collectionStore`. Verify these on the Deck with `cdp.py` first: create, add, then confirm they persist across a Steam restart.
- **`installs.ts`:** `finishInstall` creates the shortcut (named after the game), applies artwork, adds the game to its platform's Steam collection (if the setting is on), calls `register_installed` (the record gains `platform_slug`, `rom_id`, `files`, and `launch_target`), then dismisses the job.
- **Done when:** a SNES ROM installs from the Deck UI, appears in Steam inside the "SNES" collection with art, and launches in RetroArch from Gaming Mode.

## Step 4 — the emulator layer
- **`emulators.py`:**
  - **Detection:** `flatpak list --app --columns=application` (user and system), EmuDeck AppImages under `~/Applications`, and Steam RetroArch.
  - **`PLATFORMS` table:** RomM slug → ordered candidates `{emulator, core?, args, extensions, extract, bios_dir}`. Start with NES, SNES, GB/GBC/GBA, N64, Genesis/MD, Master System, Game Gear, PSX, PSP, NDS, PS2, GameCube, Wii and arcade.
  - **`resolve(slug, overrides, detected)`** returns the emulator to use, or what's missing.
- **RetroArch management:**
  - "Install RetroArch" runs `flatpak install --user -y flathub org.libretro.RetroArch` in a worker job.
  - Cores are fetched on demand from `buildbot.libretro.com/nightly/linux/x86_64/latest/<core>_libretro.so.zip` into `~/.var/app/org.libretro.RetroArch/config/retroarch/cores/`.
- **BIOS:** on install, if the platform needs firmware, fetch it from RomM's firmware endpoint into the chosen emulator's BIOS dir (RetroArch `system/`, DuckStation `bios/`, PCSX2 `bios/`). Skip files that already exist with the same hash.
- **Settings UI:** an "Emulators" section that lists the detected emulators, offers to install RetroArch, and has a per-platform dropdown override.

## Step 5 — finishing the parity work
- **Uninstall:** copy the confirm modal and the context-menu patch from `gameyfin-decky/src/contextMenu.tsx:331-356` (relabelled "(RomM)"). Remove the shortcut (Steam drops it from collections) and delete the files with the marker check (`installed.delete_game_dir`). Leave BIOS and saves alone.
- **Status and drift:** `status.py` reports missing files or a missing shortcut. Its update signal is the server's file size or hash, instead of Gameyfin's `fileSize`.
- **Downloads panel:** copied as is.
- **Standalone emulators:** add DuckStation, PCSX2, Dolphin, PPSSPP and melonDS/Cemu launch arguments, then verify a few on the Deck.

## Step 6 — release
CI (typecheck, unittest, package), then `v0.1.0`. Push the tag only after the first commit is on GitHub.

## Out of scope for v1
Save and state sync (v2; RomM has the endpoints). Bulk "install the whole platform". Achievements.

## Critical files
- **New:**
  - `py_modules/romm/{client,library,emulators,launch,worker,installer}.py`
  - `bin/romm-launch`
  - `src/{steam,installs,contextMenu}.ts(x)`
  - `src/components/{LibraryPage,GameModal,SettingsPanel,EmulatorsPanel}.tsx`
- **Copied with renames:** `py_modules/romm/{jobs,settings,installed,images,pairing,status}.py`, `main.py`, and the scripts.
- **Reference:**
  - `gameyfin-decky/src/steam.ts:138-226`
  - `gameyfin-decky/src/installs.ts:281-487`
  - `gameyfin-decky/py_modules/gameyfin/jobs.py:117-129`
  - `gameyfin-decky/py_modules/gameyfin/installer.py:141-251`

## Verification
- **Unit tests** (`python3 -m unittest discover -s tests`):
  - the client against `tests/fake_romm.py`, which serves the platforms/roms/collections JSON and a streaming download with `Range`;
  - the installer (single file, zip, multi-disc → m3u);
  - `emulators.resolve` with fake detection output;
  - the launcher resolver building the command;
  - the stores and pairing tests carried over.
- **Live:** `scripts/romm.py` against the real server (platforms, roms, one download).
- **On the Deck:**
  - `cdp.py` checks of `AddShortcut`, `SpecifyCompatTool(appid,"")` and the `collectionStore` add/remove calls before building UI on them;
  - then the full SNES flow (step 3), a PSX multi-disc game with BIOS, and uninstall from the library context menu.
