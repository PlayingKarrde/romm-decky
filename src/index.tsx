import { ButtonItem, PanelSection, PanelSectionRow, SteamSpinner, staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";
import { PublicSettings, getSettings } from "./backend";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { DownloadsPanel } from "./components/DownloadsPanel";
import { InstallLocationPanel } from "./components/InstallLocationPanel";
import { LIBRARY_ROUTE, LibraryPage, openLibrary } from "./components/LibraryPage";
import { startPolling, stopPolling, useInstallState } from "./installs";

function Content() {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const { installed } = useInstallState(); // before any early return: hooks must run every render

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
        </PanelSection>
      )}
      <DownloadsPanel />
      <ConnectionPanel settings={settings} onChange={setSettings} />
      {paired && <InstallLocationPanel />}
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(LIBRARY_ROUTE, LibraryPage, { exact: true });
  startPolling();
  return {
    name: "RomM",
    titleView: <div className={staticClasses.Title}>RomM</div>,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount() {
      routerHook.removeRoute(LIBRARY_ROUTE);
      stopPolling();
    },
  };
});
