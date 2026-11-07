import { DialogButton, Dropdown, Focusable, ModalRoot, SteamSpinner } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  EmulatorOption,
  EmulatorSettings,
  PlatformEmulators,
  getEmulatorSettings,
  installRetroarch,
  setPlatformEmulator,
} from "../backend";

const AUTO = "";
const muted = { color: "#8b929a", fontSize: "12px" } as const;

function label(o: EmulatorOption): string {
  return o.status === "core_missing" ? `${o.name} · downloads core` : o.name;
}

function PlatformRow({ p, onChanged }: { p: PlatformEmulators; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const usable = p.options.filter((o) => o.status !== "not_installed");
  const missing = p.options.filter((o) => o.status === "not_installed");
  const chosen = p.options.find((o) => o.id === p.chosen);
  const rgOptions = [
    { data: AUTO, label: `Automatic${chosen && !p.override ? ` (${chosen.name})` : ""}` },
    ...usable.map((o) => ({ data: o.id, label: label(o) })),
  ];

  const pick = async (candidate: string) => {
    setBusy(true);
    const r = await setPlatformEmulator(p.key, candidate);
    setBusy(false);
    if (!r.ok) toaster.toast({ title: "RomM", body: r.error.message });
    else if (r.data.updated)
      toaster.toast({ title: "RomM", body: `${p.name}: updated ${r.data.updated} installed game(s)` });
    onChanged();
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "16px", padding: "6px 0" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "15px" }}>{p.name}</div>
        <div style={muted}>
          {chosen ? `Uses ${chosen.name}` : "No emulator installed"}
          {missing.length ? ` · not installed: ${missing.map((o) => o.name).join(", ")}` : ""}
        </div>
      </div>
      <div style={{ width: "300px", flexShrink: 0 }}>
        {usable.length ? (
          <Dropdown
            disabled={busy}
            rgOptions={rgOptions}
            selectedOption={p.override ?? AUTO}
            onChange={(o) => void pick(o.data)}
          />
        ) : (
          <div style={{ ...muted, textAlign: "right" }}>Nothing to choose</div>
        )}
      </div>
    </div>
  );
}

/** Per-platform emulator choice for the platforms on the RomM server. */
export function EmulatorsModal({ closeModal }: { closeModal?: () => void }) {
  const [data, setData] = useState<EmulatorSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);

  const load = () =>
    getEmulatorSettings().then((r) => (r.ok ? (setData(r.data), setError(null)) : setError(r.error.message)));

  useEffect(() => {
    void load();
  }, []);

  // While RetroArch installs, re-check every few seconds.
  useEffect(() => {
    if (!installing || data?.retroarch) return;
    const t = setInterval(() => void load(), 4000);
    return () => clearInterval(t);
  }, [installing, data?.retroarch]);

  const startRa = async () => {
    const r = await installRetroarch();
    if (!r.ok) return void toaster.toast({ title: "RomM", body: r.error.message });
    setInstalling(true);
    toaster.toast({ title: "RomM", body: "Installing RetroArch from Flathub…" });
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "22px", fontWeight: "bold", marginBottom: "4px" }}>Emulators</div>
      <div style={{ ...muted, fontSize: "13px", marginBottom: "12px" }}>
        Automatic uses the best installed emulator for each platform. Installed games switch when you change this.
        {data?.emulators.length ? ` Found: ${data.emulators.map((e) => e.name).join(", ")}.` : ""}
      </div>
      {error && <div style={{ color: "#ff6b6b", marginBottom: "10px" }}>{error}</div>}
      {data && !data.retroarch && (
        <Focusable style={{ marginBottom: "12px" }}>
          <DialogButton disabled={installing} onClick={startRa}>
            {installing ? "Installing RetroArch…" : "Install RetroArch (Flatpak)"}
          </DialogButton>
        </Focusable>
      )}
      {!data && !error ? (
        <SteamSpinner />
      ) : (
        <Focusable style={{ maxHeight: "60vh", overflowY: "auto", paddingRight: "8px" }}>
          {data?.platforms.map((p) => <PlatformRow key={p.key} p={p} onChanged={() => void load()} />)}
        </Focusable>
      )}
      <Focusable style={{ marginTop: "12px" }}>
        <DialogButton onClick={closeModal}>Close</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
