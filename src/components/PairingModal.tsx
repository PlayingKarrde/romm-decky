import { DialogButton, Focusable, ModalRoot, SteamSpinner } from "@decky/ui";
import { toaster } from "@decky/api";
import qrcode from "qrcode-generator";
import { useEffect, useMemo, useState } from "react";
import { PairingStatus, PublicSettings, getPairingStatus, startPairing, stopPairing } from "../backend";

function qrSvg(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
}

type Props = { serverUrl: string; onPaired?: (s: PublicSettings) => void; closeModal?: () => void };

/** RomM device auth: show RomM's approval link as a QR code, poll until the user approves it. */
export function PairingModal({ serverUrl, onPaired, closeModal }: Props) {
  const [st, setSt] = useState<PairingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    let paired = false;
    const poll = async () => {
      const r = await getPairingStatus();
      if (!alive) return;
      if (r.ok) {
        setSt(r.data);
        if (r.data.state === "done") {
          paired = true;
          toaster.toast({ title: "RomM", body: `Paired${r.data.settings?.username ? ` as ${r.data.settings.username}` : ""}` });
          if (r.data.settings) onPaired?.(r.data.settings);
          closeModal?.();
          return;
        }
        if (r.data.state !== "waiting") return;
      }
      timer = setTimeout(poll, 2000);
    };
    startPairing(serverUrl).then((r) => {
      if (!alive) return;
      if (!r.ok) return setError(r.error.message);
      setSt(r.data);
      timer = setTimeout(poll, 2000);
    });
    return () => {
      alive = false;
      clearTimeout(timer);
      if (!paired) void stopPairing();
    };
  }, []);

  const svg = useMemo(() => (st?.url ? qrSvg(st.url) : null), [st?.url]);
  const closed = st && st.state !== "waiting" && st.state !== "done" && st.state !== "starting";

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
        <div
          style={{
            width: "220px",
            height: "220px",
            flexShrink: 0,
            background: "#fff",
            borderRadius: "8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            opacity: closed ? 0.25 : 1,
          }}
        >
          {svg ? (
            <div style={{ width: "100%", height: "100%" }} dangerouslySetInnerHTML={{ __html: svg }} />
          ) : (
            !error && <SteamSpinner />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "10px" }}>
          <div style={{ fontSize: "22px", fontWeight: "bold" }}>Pair with RomM</div>
          <div style={{ fontSize: "14px", color: "#b8bcbf", lineHeight: 1.4 }}>
            Scan the code with a phone that's signed in to RomM, or open RomM on any device and enter this code
            under device pairing. Then approve the Deck.
          </div>
          {st?.user_code && (
            <div
              style={{
                fontFamily: "monospace",
                fontSize: "28px",
                letterSpacing: "4px",
                padding: "8px 12px",
                background: "rgba(255,255,255,0.08)",
                borderRadius: "6px",
                textAlign: "center",
              }}
            >
              {st.user_code}
            </div>
          )}
          <div style={{ fontSize: "13px", color: error || closed ? "#ff6b6b" : "#8b929a", wordBreak: "break-word" }}>
            {error ??
              (closed
                ? st!.error || "Pairing stopped."
                : st?.state === "waiting"
                  ? `Waiting for approval… (expires in ${Math.ceil((st.expires_in ?? 0) / 60)} min)` +
                    (st.error ? ` · ${st.error}` : "")
                  : "Starting…")}
          </div>
          <Focusable style={{ marginTop: "6px" }}>
            <DialogButton onClick={closeModal}>Cancel</DialogButton>
          </Focusable>
        </div>
      </div>
    </ModalRoot>
  );
}
