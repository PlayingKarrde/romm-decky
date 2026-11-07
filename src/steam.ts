// Thin wrappers over SteamClient.Apps.* and Steam's collectionStore (both undocumented).
// Keep every Steam call in this file. Verified on the Deck with scripts/cdp.py.
import { getArtwork, getImageChunk } from "./backend";

const ASSET = { capsule: 0, hero: 1, logo: 2, header: 3, icon: 4 } as const;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function appStore(): any {
  return (window as any).appStore ?? null;
}

function collectionStore(): any {
  return (window as any).collectionStore ?? null;
}

export function shortcutExists(appId: number): boolean {
  try {
    return !!appStore()?.GetAppOverviewByAppID(appId);
  } catch {
    return false;
  }
}

/** Resolve once app details satisfy pred, or false after timeoutMs. */
function waitForDetails(appId: number, pred: (d: any) => boolean, timeoutMs = 3000): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    let reg: { unregister(): void } | undefined;
    const finish = (v: boolean) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => reg?.unregister(), 0);
      resolve(v);
    };
    const timer = setTimeout(() => finish(false), timeoutMs);
    try {
      reg = SteamClient.Apps.RegisterForAppDetails(appId, (d: any) => {
        if (pred(d && Object.keys(d).length ? d : null)) finish(true);
      });
    } catch {
      finish(false);
    }
  });
}

const quote = (p: string) => `"${p}"`;

export type ShortcutSpec = { name: string; exe: string; startDir: string };

/**
 * Create a shortcut (or update an existing one). Returns the appid.
 * Launch options are never touched: the launch script takes the user's options as "$@".
 */
export async function upsertShortcut(spec: ShortcutSpec, existing?: number | null): Promise<number> {
  let appId = existing && shortcutExists(existing) ? existing : null;
  if (appId == null) {
    const id = await SteamClient.Apps.AddShortcut(spec.name, spec.exe, spec.startDir, "");
    if (typeof id !== "number") throw new Error("Steam did not create the shortcut");
    appId = id;
    await waitForDetails(appId, (d) => d != null);
  }
  SteamClient.Apps.SetShortcutName(appId, spec.name);
  SteamClient.Apps.SetShortcutExe(appId, quote(spec.exe));
  SteamClient.Apps.SetShortcutStartDir(appId, quote(spec.startDir));
  // Emulators are native Linux: make sure no Proton is set (e.g. by a global default).
  SteamClient.Apps.SpecifyCompatTool(appId, "");
  await waitForDetails(appId, (d) => d?.strDisplayName === spec.name, 2000);
  return appId;
}

export async function removeShortcut(appId: number): Promise<void> {
  if (!shortcutExists(appId)) return;
  SteamClient.Apps.RemoveShortcut(appId);
  await waitForDetails(appId, (d) => d == null, 2000);
}

// ---- collections -----------------------------------------------------------

async function overviewOf(appId: number): Promise<any> {
  for (let i = 0; i < 30; i++) {
    const ov = appStore()?.GetAppOverviewByAppID(appId);
    if (ov) return ov;
    await sleep(100);
  }
  throw new Error("Steam doesn't know the new shortcut yet");
}

/**
 * Add the app to the user collection with this name, creating it if needed.
 * Removing the shortcut later drops it from the collection automatically.
 */
export async function addToCollection(appId: number, name: string): Promise<void> {
  const cs = collectionStore();
  if (!cs) throw new Error("Steam's collection store isn't available");
  const ov = await overviewOf(appId);
  const existing = cs.GetUserCollectionsByName(name)?.[0];
  if (existing) {
    if (existing.apps?.has(appId)) return;
    const dd = existing.AsDragDropCollection?.();
    if (!dd) throw new Error(`The "${name}" collection can't be edited (it's a dynamic collection)`);
    dd.AddApps([ov]);
    await existing.Save();
  } else {
    const created = cs.NewUnsavedCollection(name, undefined, [ov]);
    await created.Save();
  }
}

// ---- artwork ---------------------------------------------------------------

async function fetchOriginal(url: string): Promise<string | null> {
  const info = await getArtwork(url);
  if (!info.ok) return null;
  const parts: string[] = [];
  for (let i = 0; i < info.data.chunks; i++) {
    const c = await getImageChunk(url, i);
    if (!c.ok) return null;
    parts.push(c.data);
  }
  return `data:${info.data.content_type};base64,${parts.join("")}`;
}

/** Re-encode via canvas so Steam always gets PNG (covers webp etc.). Returns bare base64. */
async function toPngBase64(dataUrl: string): Promise<string> {
  if (dataUrl.startsWith("data:image/png;")) return dataUrl.slice(dataUrl.indexOf(",") + 1);
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error("decode failed"));
    i.src = dataUrl;
  });
  const c = document.createElement("canvas");
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  c.getContext("2d")!.drawImage(img, 0, 0);
  const out = c.toDataURL("image/png");
  return out.slice(out.indexOf(",") + 1);
}

/** Best effort: the RomM cover becomes the portrait capsule. Failures are logged, never thrown. */
export async function applyCover(appId: number, url: string | null | undefined): Promise<void> {
  if (!url) return;
  try {
    const src = await fetchOriginal(url);
    if (!src) return;
    const b64 = await toPngBase64(src);
    await SteamClient.Apps.ClearCustomArtworkForApp(appId, ASSET.capsule as any).catch(() => undefined);
    await sleep(300); // Clear resolves before it's actually cleared
    await SteamClient.Apps.SetCustomArtworkForApp(appId, b64, "png", ASSET.capsule as any);
  } catch (e) {
    console.warn("[romm] artwork failed", url, e);
  }
}
