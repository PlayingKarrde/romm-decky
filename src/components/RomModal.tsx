import { DialogButton, Focusable, ModalRoot, SteamSpinner } from "@decky/ui";
import { useEffect, useState } from "react";
import { RomDetail, RomSummary, formatBytes, getRom } from "../backend";
import { Cover } from "./Cover";

type Props = { rom: RomSummary; closeModal?: () => void };

/** ROM detail. Install/uninstall arrive with the emulator layer (plan step 3). */
export function RomModal({ rom, closeModal }: Props) {
  const [detail, setDetail] = useState<RomDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRom(rom.id).then((r) => (r.ok ? setDetail(r.data) : setError(r.error.message)));
  }, [rom.id]);

  const files = detail?.files ?? [];
  const discs = files.length > 1 ? `${files.length} files` : null;
  const meta = [rom.platform_name, formatBytes(rom.size), discs, ...(rom.regions ?? []).slice(0, 2)].filter(Boolean);

  const GAP = "20px";
  const COVER_W = "180px";
  const wide = { flex: 1, minWidth: 0 };

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

        <Focusable style={{ display: "flex", gap: GAP }} flow-children="horizontal">
          <div style={{ width: COVER_W, flexShrink: 0 }} />
          <DialogButton style={wide} disabled>
            Install (coming soon)
          </DialogButton>
          <DialogButton style={wide} onClick={closeModal}>
            Close
          </DialogButton>
        </Focusable>
      </div>
    </ModalRoot>
  );
}
