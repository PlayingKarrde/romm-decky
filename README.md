# romm-decky

A [Decky Loader](https://decky.xyz) plugin that browses a self-hosted [RomM](https://romm.app) server from Steam Gaming Mode. It installs ROMs one at a time as Steam shortcuts that launch the right emulator.

- **Installs on demand.** Nothing is added to Steam until you install a game, and uninstalling removes it again.
- **No password on the Deck.** You pair with RomM's own device approval: scan a QR code on your phone and approve the Deck in RomM.
- **Uses the emulators you already have.** It runs RetroArch (Flatpak) with the right core for most platforms, and prefers standalone emulators it finds where they're better:
  - DuckStation, PCSX2, Dolphin, PPSSPP, melonDS, Cemu, Citra/Azahar, RPCS3, xemu, Supermodel, Ryujinx/Eden/yuzu.
  - It finds them as Flatpaks or as AppImages in `~/Applications`.
  - It doesn't need RetroDECK or EmuDeck, but works alongside EmuDeck.
- **Gets the emulator ready.** Missing RetroArch cores download automatically. BIOS files stored in RomM are copied to the folder each emulator actually reads.

## Features
- **Browsing:** by platform or by collection (yours, plus RomM's series, franchise, genre, company and mode collections), with search and cover art.
- **Installing:**
  - Downloads are resumable and checksum-verified, and run in the background, surviving Decky restarts.
  - Multi-disc games get an `.m3u` playlist.
  - ROMs go into an EmuDeck-style layout, `<folder>/<platform>/`. By default that's `~/Emulation/roms` when it exists, otherwise `~/Games/RomM`; you can choose the internal drive, an SD card or any folder.
  - A ROM file that's already there with a matching checksum is reused instead of downloaded. It's only deleted if you ask for that when uninstalling.
- **In Steam:**
  - Each installed game gets a shortcut with its RomM cover, in a per-platform collection such as "SNES" (you can turn that off).
  - Launch options stay yours.
  - The game's context menu gets a **RomM ›** submenu with Uninstall, and Update when RomM has a newer version.
- **Health checks:** missing files, removed shortcuts and server-side changes are flagged, with one-press fixes.
- **Emulators… settings:** choose the emulator for each platform. Installed games switch over without touching their shortcuts.

## Requirements
- A Steam Deck (or other SteamOS device) with [Decky Loader](https://decky.xyz).
- A RomM server, version 5.x, with device pairing. The plugin was built against RomM 5.4.1.
- At least one emulator. RetroArch can be installed from the plugin's Emulators… screen.

## Install
The plugin isn't on the Decky store. Download `romm-decky-<version>.zip` from the [latest release](../../releases/latest). Then, in Decky's settings, enable Developer mode, and under Developer choose **Install Plugin from ZIP** (or from URL, using the release asset's link).

## Setup
1. Open the Quick Access menu (`…`), then **RomM**.
2. Enter your RomM server URL and choose **Pair with RomM**.
3. Scan the QR code with a phone that's signed in to RomM, or enter the code in RomM's device pairing page, and approve the Deck.
4. Choose **Browse platforms** or **Browse collections**, pick a game, and choose **Install**.

## How launching works
Each game's Steam shortcut runs a small script in `~/.local/share/romm-decky/launch/<rom id>.sh` that starts the chosen emulator with the ROM. When you change a platform's emulator, or install a better one, the plugin rewrites these scripts; the shortcuts stay the same.

## Not yet
- Save and state sync with RomM.
- Banner and logo artwork. Only the RomM cover is used.

## Development
See `CLAUDE.md` for the architecture, the decisions behind it, and the dev loop (`scripts/deploy.sh`, `scripts/cdp.py`, `scripts/romm.py`). Run the tests with `python3 -m unittest discover -s tests`.

## License
BSD-3-Clause
