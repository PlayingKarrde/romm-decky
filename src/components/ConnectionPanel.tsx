import { ButtonItem, Field, PanelSection, PanelSectionRow, TextField, ToggleField, showModal } from "@decky/ui";
import { useState } from "react";
import { ConnectionInfo, PublicSettings, setPlatformCollections, signOut, testConnection } from "../backend";
import { PairingModal } from "./PairingModal";

type Props = { settings: PublicSettings | null; onChange: (s: PublicSettings) => void };

/** Unpaired: server URL + "Pair with RomM". Paired: who/where, test, sign out, and options. */
export function ConnectionPanel({ settings, onChange }: Props) {
  const [url, setUrl] = useState(settings?.server_url ?? "");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const paired = !!settings?.has_token;

  const describe = (c: ConnectionInfo) =>
    `Connected to RomM ${c.server_version ?? ""} as ${c.username ?? "?"} · ${c.rom_count} ROMs on ${c.platform_count} platforms`;

  const onTest = async () => {
    setBusy(true);
    setStatus(null);
    try {
      const r = await testConnection();
      setStatus(r.ok ? { ok: true, text: describe(r.data) } : { ok: false, text: r.error.message });
    } finally {
      setBusy(false);
    }
  };

  const onPair = () =>
    showModal(
      <PairingModal
        serverUrl={url}
        onPaired={(s) => {
          setStatus(null);
          onChange(s);
        }}
      />,
    );

  const onSignOut = async () => {
    const r = await signOut();
    if (r.ok) {
      setStatus(null);
      onChange(r.data);
    }
  };

  const statusRow = status && (
    <PanelSectionRow>
      <Field
        focusable={false}
        childrenLayout="below"
        description={
          <span style={{ color: status.ok ? "#59bf40" : "#ff6b6b", wordBreak: "break-word" }}>{status.text}</span>
        }
      />
    </PanelSectionRow>
  );

  if (!paired) {
    return (
      <PanelSection title="Connection">
        <PanelSectionRow>
          <TextField
            label="RomM server URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            description="e.g. https://romm.example.com"
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!url.trim()}
            description="Approve this Deck from RomM on your phone. No password needed."
            onClick={onPair}
          >
            Pair with RomM
          </ButtonItem>
        </PanelSectionRow>
        {statusRow}
      </PanelSection>
    );
  }

  return (
    <PanelSection title="Connection">
      <PanelSectionRow>
        <Field
          focusable={false}
          childrenLayout="below"
          label={settings!.username ? `Signed in as ${settings!.username}` : "Paired"}
          description={<span style={{ wordBreak: "break-all" }}>{settings!.server_url}</span>}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={onTest}>
          Test connection
        </ButtonItem>
      </PanelSectionRow>
      {statusRow}
      <PanelSectionRow>
        <ToggleField
          label="Platform collections"
          description="Put installed games in a Steam collection per platform"
          checked={settings!.steam_platform_collections}
          onChange={async (v) => {
            const r = await setPlatformCollections(v);
            if (r.ok) onChange(r.data);
          }}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={onSignOut} description="You can also remove the device in RomM.">
          Sign out
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
