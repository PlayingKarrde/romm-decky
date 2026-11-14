import {
  ButtonItem,
  DialogButton,
  Focusable,
  PanelSection,
  PanelSectionRow,
  SteamSpinner,
  showModal,
  staticClasses,
} from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaCog, FaGamepad, FaTimes } from "react-icons/fa";
import {
  PluginUpdate,
  PublicSettings,
  checkPluginUpdate,
  getSettings,
  getSgdbPhoneStatus,
  startSgdbPhone,
  stopSgdbPhone,
} from "./backend";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { ArtworkPanel } from "./common/ArtworkPanel";
import { PhoneModal } from "./common/PhoneModal";
import { LIBRARY_ROUTE, LibraryPage, openLibrary } from "./components/LibraryPage";
import { patchContextMenu } from "./contextMenu";
import { attentionCounts, startPolling, stopPolling, useInstallState } from "./installs";
import { setPanelView, usePanelView } from "./view";

const sgdbPhoneApi = { start: startSgdbPhone, status: getSgdbPhoneStatus, stop: stopSgdbPhone };

/** Decky's own "Install plugin from URL" flow: it asks for confirmation, then replaces this
 *  plugin with the release zip. The store isn't an option (it rejects LLM-written plugins). */
function installUpdate(u: PluginUpdate) {
  const backend = (window as any).DeckyBackend;
  if (!u.url || !backend?.call) {
    toaster.toast({ title: "RomM", body: `Install ${u.latest} from ${u.page ?? "the GitHub releases page"}` });
    return;
  }
  // utilities/install_plugin(artifact, name, version, hash, install_type); 2 = InstallType.UPDATE.
  // The name must match plugin.json. hash false skips Decky's check when GitHub has no digest.
  void backend.call("utilities/install_plugin", u.url, "RomM", u.latest, u.sha256 ?? false, 2);
}

function PluginUpdateSection() {
  const [update, setUpdate] = useState<PluginUpdate | null>(null);
  useEffect(() => {
    checkPluginUpdate(false).then((r) => r.ok && setUpdate(r.data));
  }, []);
  if (!update?.newer) return null;
  return (
    <PanelSection title="Plugin update">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description={`RomM for Decky ${update.latest} is available (you have ${update.current}).`}
          onClick={() => installUpdate(update)}
        >
          Update to {update.latest}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

/** Settings: ask GitHub now instead of waiting for the 6-hour cache. */
function UpdateCheckPanel() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ update?: PluginUpdate; error?: string } | null>(null);
  const update = result?.update;

  const onCheck = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await checkPluginUpdate(true);
      setResult(r.ok ? { update: r.data } : { error: r.error.message });
    } finally {
      setBusy(false);
    }
  };

  const description = busy
    ? "Checking…"
    : result?.error
      ? `Couldn't check: ${result.error}`
      : update
        ? update.newer
          ? `${update.latest} is available (you have ${update.current}).`
          : `You're on the latest version (${update.current}).`
        : undefined;

  return (
    <PanelSection title="Plugin">
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} description={description} onClick={onCheck}>
          Check for updates
        </ButtonItem>
      </PanelSectionRow>
      {update?.newer && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => installUpdate(update)}>
            Update to {update.latest}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

/** Mention a new release once per version, shortly after Steam starts. */
async function announceUpdate() {
  const r = await checkPluginUpdate(false);
  if (!r.ok || !r.data.newer) return;
  const KEY = "romm-decky:announced-version";
  if (localStorage.getItem(KEY) === r.data.latest) return;
  localStorage.setItem(KEY, r.data.latest);
  toaster.toast({ title: "RomM", body: `Version ${r.data.latest} is available. Update it from the RomM panel.` });
}

function Content() {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const snap = useInstallState(); // before any early return: hooks must run every render
  const { installed } = snap;
  const { attention, updates } = attentionCounts(snap);
  const view = usePanelView();

  // Leaving the plugin (B / Decky's back arrow) unmounts this; start on the main page next time.
  useEffect(() => () => setPanelView("main"), []);

  useEffect(() => {
    getSettings().then((r) => {
      if (r.ok) setSettings(r.data);
      setLoaded(true);
    });
  }, []);

  if (!loaded) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <SteamSpinner />
        </PanelSectionRow>
      </PanelSection>
    );
  }
  const paired = !!settings?.has_token;

  if (view === "settings") {
    return (
      <>
        <ConnectionPanel settings={settings} onChange={setSettings} />
        {paired && <InstallLocationPanel />}
        {paired && (
          <ArtworkPanel
            title="RomM"
            settings={settings}
            onSaved={setSettings}
            phone={(done) =>
              showModal(
                <PhoneModal
                  api={sgdbPhoneApi}
                  title="RomM"
                  description="Sign in to SteamGridDB there and paste its API key."
                  onDone={done}
                />,
              )
            }
          />
        )}
        <UpdateCheckPanel />
      </>
    );
  }

  return (
    <>
      <PluginUpdateSection />
      {paired && (
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openLibrary("platforms")}>
              Browse platforms
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openLibrary("collections")}>
              Browse collections
            </ButtonItem>
          </PanelSectionRow>
          {installed.length > 0 && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => openLibrary("installed")}>
                Installed ({installed.length})
              </ButtonItem>
            </PanelSectionRow>
          )}
          {attention > 0 && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                description="Missing files or a removed Steam shortcut"
                onClick={() => openLibrary("installed")}
              >
                {attention === 1 ? "1 game needs attention" : `${attention} games need attention`}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {updates > 0 && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => openLibrary("installed")}>
                {updates === 1 ? "1 update available" : `${updates} updates available`}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}
      <DownloadsPanel />
      {!paired && <ConnectionPanel settings={settings} onChange={setSettings} />}
    </>
  );
}

const iconButton = { height: "28px", width: "40px", minWidth: 0, padding: "10px 12px" };

/** Title bar: "RomM" plus a cog that opens settings; in settings it becomes a close button.
 *  (Decky draws its own back arrow on the left, which leaves the plugin.) */
function TitleView() {
  const view = usePanelView();
  const inSettings = view === "settings";
  return (
    <Focusable
      className={staticClasses.Title}
      style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%", padding: 0, boxShadow: "none" }}
    >
      <div style={{ marginRight: "auto" }}>{inSettings ? "RomM settings" : "RomM"}</div>
      <DialogButton style={iconButton} onClick={() => setPanelView(inSettings ? "main" : "settings")}>
        {inSettings ? (
          <FaTimes style={{ marginTop: "-4px", display: "block" }} />
        ) : (
          <FaCog style={{ marginTop: "-4px", display: "block" }} />
        )}
      </DialogButton>
    </Focusable>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(LIBRARY_ROUTE, LibraryPage, { exact: true });
  startPolling();
  const announce = setTimeout(() => void announceUpdate().catch(() => undefined), 30_000);
  let unpatchMenu = () => {};
  try {
    unpatchMenu = patchContextMenu();
  } catch (e) {
    console.warn("[romm] context menu patch failed", e);
  }
  return {
    name: "RomM",
    titleView: <TitleView />,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount() {
      routerHook.removeRoute(LIBRARY_ROUTE);
      stopPolling();
      clearTimeout(announce);
      setPanelView("main");
      unpatchMenu();
    },
  };
});
