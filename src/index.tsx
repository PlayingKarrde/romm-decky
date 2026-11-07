import { ButtonItem, PanelSection, PanelSectionRow, SteamSpinner, staticClasses } from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";
import { PluginUpdate, PublicSettings, checkPluginUpdate, getSettings } from "./backend";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { ArtworkPanel } from "./common/ArtworkPanel";
import { LIBRARY_ROUTE, LibraryPage, openLibrary } from "./components/LibraryPage";
import { patchContextMenu } from "./contextMenu";
import { attentionCounts, startPolling, stopPolling, useInstallState } from "./installs";

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
      <ConnectionPanel settings={settings} onChange={setSettings} />
      {paired && <InstallLocationPanel />}
      {paired && <ArtworkPanel title="RomM" settings={settings} onSaved={setSettings} />}
    </>
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
    titleView: <div className={staticClasses.Title}>RomM</div>,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount() {
      routerHook.removeRoute(LIBRARY_ROUTE);
      stopPolling();
      clearTimeout(announce);
      unpatchMenu();
    },
  };
});
