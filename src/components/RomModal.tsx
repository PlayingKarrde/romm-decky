import { ConfirmModal, DialogButton, Focusable, ModalRoot, Navigation, SteamSpinner, showModal } from "@decky/ui";
import { ReactElement, useEffect, useState } from "react";
import { EmulatorInfo, InstalledRom, RomDetail, RomSummary, formatBytes, getEmulator, getRom } from "../backend";
import {
  activeJobFor,
  appIdOf,
  forget,
  healthOf,
  install,
  installedFor,
  readdToSteam,
  refreshStatus,
  startUpdate,
  statusFor,
  uninstall,
  useInstallState,
} from "../installs";
import { Cover } from "./Cover";

type Props = { rom: RomSummary; closeModal?: () => void };

/**
 * Confirm, then uninstall. The dialog's handlers only record the choice: Steam's
 * ConfirmModal doesn't close on an async onOK, so the work runs after it has closed.
 */
export async function confirmUninstall(inst: InstalledRom, onDone?: () => void): Promise<void> {
  const adopted = inst.files.filter((f) => !f.owned).length;
  const owned = inst.files.length - adopted;
  const choice = await new Promise<"keep" | "delete" | null>((resolve) => {
    if (!adopted) {
      showModal(
        <ConfirmModal
          strTitle={`Uninstall ${inst.title}?`}
          strDescription={`This removes ${inst.title} from Steam and deletes its ROM files (${formatBytes(inst.size)}). Saves are kept.`}
          strOKButtonText="Uninstall"
          onOK={() => resolve("keep")}
          onCancel={() => resolve(null)}
        />,
      );
      return;
    }
    const what = owned
      ? `${adopted} of its files were already on the Deck before it was installed.`
      : "Its ROM files were already on the Deck before it was installed.";
    showModal(
      <ConfirmModal
        strTitle={`Uninstall ${inst.title}?`}
        strDescription={`This removes ${inst.title} from Steam${owned ? " and deletes the files it downloaded" : ""}. ${what} Keep them, or delete them too? Saves are kept either way.`}
        strOKButtonText="Keep files"
        strMiddleButtonText="Delete files too"
        onOK={() => resolve("keep")}
        onMiddleButton={() => resolve("delete")}
        onCancel={() => resolve(null)}
      />,
    );
  });
  if (!choice) return;
  if (await uninstall(inst, choice === "delete")) onDone?.();
}

export function RomModal({ rom, closeModal }: Props) {
  const [detail, setDetail] = useState<RomDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emu, setEmu] = useState<{ ok: true; data: EmulatorInfo } | { ok: false; message: string } | null>(null);
  const [starting, setStarting] = useState(false);
  const snap = useInstallState();
  const job = activeJobFor(snap, rom.id);
  const inst = installedFor(snap, rom.id);
  const appId = appIdOf(inst);

  useEffect(() => {
    getRom(rom.id).then((r) => (r.ok ? setDetail(r.data) : setError(r.error.message)));
    getEmulator(rom.platform_slug, rom.platform_fs_slug).then((r) =>
      setEmu(r.ok ? { ok: true, data: r.data } : { ok: false, message: r.error.message }),
    );
    if (inst) void refreshStatus(); // fresh health/update info for the game being looked at
  }, [rom.id]);

  const st = inst ? statusFor(snap, rom.id) : undefined;
  const health = inst ? healthOf(inst, st) : "ok";

  const files = detail?.files ?? [];
  const discs = files.length > 1 ? `${files.length} files` : null;
  const meta = [rom.platform_name, formatBytes(rom.size), discs, ...(rom.regions ?? []).slice(0, 2)].filter(Boolean);

  const GAP = "20px";
  const COVER_W = "180px";
  const wide = { flex: 1, minWidth: 0 };

  let actions: ReactElement[];
  if (job) {
    const pct = job.total ? ` ${Math.floor((100 * job.done) / job.total)}%` : "";
    actions = [
      <DialogButton key="busy" disabled style={wide}>
        {job.phase === "done" ? "Adding to Steam…" : `${job.kind === "update" ? "Updating" : "Installing"}…${pct}`}
      </DialogButton>,
    ];
  } else if (inst && health === "files_missing") {
    actions = [
      <DialogButton key="reinstall" style={wide} disabled={st?.server_missing} onClick={() => void install(rom.id, rom.name)}>
        Reinstall
      </DialogButton>,
      <DialogButton key="forget" style={wide} onClick={() => void forget(inst).then(() => closeModal?.())}>
        Remove from list
      </DialogButton>,
    ];
  } else if (inst) {
    actions = [];
    if (health === "shortcut_missing")
      actions.push(
        <DialogButton key="readd" style={wide} onClick={() => void readdToSteam(inst)}>
          Re-add to Steam
        </DialogButton>,
      );
    if (st?.update_available)
      actions.push(
        <DialogButton key="update" style={wide} onClick={() => void startUpdate(inst)}>
          Update
        </DialogButton>,
      );
    actions.push(
      <DialogButton key="uninstall" style={wide} onClick={() => void confirmUninstall(inst, closeModal)}>
        Uninstall
      </DialogButton>,
    );
  } else {
    actions = [
      <DialogButton
        key="install"
        style={wide}
        disabled={starting || !emu?.ok || rom.missing || !!detail?.playlist_for}
        onClick={async () => {
          setStarting(true);
          await install(rom.id, rom.name);
          setStarting(false);
        }}
      >
        Install
      </DialogButton>,
    ];
  }

  const emuLine = inst
    ? `Installed · ${inst.emulator}`
    : emu == null
      ? null
      : emu.ok
        ? `Runs with ${emu.data.name}${emu.data.status === "core_missing" ? " (the core downloads on install)" : ""}`
        : emu.message;

  const notice = !inst
    ? null
    : health === "files_missing"
      ? { text: `Its files are missing or changed in ${inst.platform_dir}. Reinstall, or remove it from the list.`, color: "#ffb84d" }
      : health === "shortcut_missing"
        ? { text: "Its Steam shortcut was removed. The ROM files are still installed.", color: "#ffb84d" }
        : st?.update_available
          ? { text: "RomM has a different version of this ROM.", color: "#1a9fff" }
          : st?.server_missing
            ? { text: "This ROM is no longer on the RomM server. The installed copy still works.", color: "#8b929a" }
            : null;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ display: "flex", flexDirection: "column", gap: GAP }}>
        <div style={{ display: "flex", gap: GAP, minHeight: "270px" }}>
          <div style={{ width: COVER_W, flexShrink: 0 }}>
            <Cover url={rom.cover} title={rom.name} />
          </div>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "10px" }}>
            <div style={{ fontSize: "24px", fontWeight: "bold" }}>{rom.name}</div>
            <div style={{ color: "#8b929a", fontSize: "14px" }}>{meta.join(" · ")}</div>
            {emuLine && (
              <div style={{ fontSize: "13px", color: inst ? "#59bf40" : emu?.ok ? "#b8bcbf" : "#ffb84d" }}>
                {emuLine}
              </div>
            )}
            {notice && (
              <div style={{ fontSize: "13px", color: notice.color, wordBreak: "break-word" }}>{notice.text}</div>
            )}
            {detail?.playlist_for && (
              <div style={{ fontSize: "13px", color: "#ffb84d" }}>
                This is only a disc playlist.{" "}
                {detail.playlist_for.length
                  ? `Install ${detail.playlist_for.map((s) => s.name).join(" or ")} instead.`
                  : "Install the game it belongs to instead."}
              </div>
            )}
            {rom.missing && (
              <div style={{ fontSize: "13px", color: "#ffb84d" }}>RomM reports this ROM's files as missing.</div>
            )}
            <div style={{ fontSize: "13px", lineHeight: 1.4, maxHeight: "150px", overflowY: "auto", color: "#dcdedf" }}>
              {error ? (
                <span style={{ color: "#ff6b6b" }}>{error}</span>
              ) : detail ? (
                detail.summary || "No description."
              ) : (
                <SteamSpinner />
              )}
            </div>
            {files.length > 1 && (
              <div style={{ fontSize: "12px", color: "#8b929a", lineHeight: 1.5 }}>
                {files.map((f) => (
                  <div key={f.id} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {f.name} · {formatBytes(f.size)}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* First slot sits under the poster, the rest under the text. */}
        <Focusable style={{ display: "flex", gap: GAP }} flow-children="horizontal">
          {appId ? (
            <DialogButton
              style={{ width: COVER_W, minWidth: 0, flexShrink: 0 }}
              onClick={() => {
                closeModal?.();
                Navigation.Navigate(`/library/app/${appId}`);
              }}
            >
              Open in library
            </DialogButton>
          ) : (
            <div style={{ width: COVER_W, flexShrink: 0 }} />
          )}
          {actions}
          <DialogButton style={wide} onClick={closeModal}>
            Close
          </DialogButton>
        </Focusable>
      </div>
    </ModalRoot>
  );
}
