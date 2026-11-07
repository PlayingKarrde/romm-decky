import { ButtonItem, Dropdown, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { openFilePicker, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { InstallRoot, formatBytes, getInstallRoots, getSettings, setInstallRoot } from "../backend";

// FileSelectionType is a `const enum` in @decky/api's types and isn't exported at runtime.
const FOLDER = 1;
const AUTO = "";

/** Where installs go. Each ROM lands in <folder>/<platform>/, like EmuDeck's layout. */
export function InstallLocationPanel() {
  const [roots, setRoots] = useState<InstallRoot[]>([]);
  const [selected, setSelected] = useState("");
  const [saved, setSaved] = useState(AUTO);

  const load = () =>
    Promise.all([getInstallRoots(), getSettings()]).then(([r, s]) => {
      if (s.ok) setSaved(s.data.install_root);
      if (!r.ok) return;
      setRoots(r.data.roots);
      setSelected(r.data.selected);
    });

  useEffect(() => {
    void load();
  }, []);

  const save = async (path: string) => {
    const r = await setInstallRoot(path);
    if (!r.ok) {
      toaster.toast({ title: "RomM", body: r.error.message });
      return;
    }
    await load();
  };

  const browse = async () => {
    try {
      const res = await openFilePicker(FOLDER as any, selected || "/home/deck", false, true);
      if (res?.path) await save(res.path);
    } catch {
      // picker closed without a choice
    }
  };

  const current = roots.find((r) => r.path === selected);
  const options = [
    { data: AUTO, label: "Automatic" },
    ...roots.map((r) => ({ data: r.path, label: r.label })),
  ];

  return (
    <PanelSection title="Install location">
      <PanelSectionRow>
        <Field
          label="ROMs go to"
          description={
            <span style={{ wordBreak: "break-all" }}>
              {selected}/&lt;platform&gt;
              {current?.free != null ? ` · ${formatBytes(current.free)} free` : ""}
            </span>
          }
          childrenLayout="below"
          focusable={false}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <Dropdown rgOptions={options} selectedOption={saved || AUTO} onChange={(o) => void save(o.data)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={browse}>
          Choose another folder…
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
