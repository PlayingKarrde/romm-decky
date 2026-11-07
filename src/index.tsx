import { PanelSection, PanelSectionRow, SteamSpinner, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";
import { PublicSettings, getSettings } from "./backend";
import { ConnectionPanel } from "./components/ConnectionPanel";

function Content() {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [loaded, setLoaded] = useState(false);

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
  return <ConnectionPanel settings={settings} onChange={setSettings} />;
}

export default definePlugin(() => ({
  name: "RomM",
  titleView: <div className={staticClasses.Title}>RomM</div>,
  content: <Content />,
  icon: <FaGamepad />,
}));
