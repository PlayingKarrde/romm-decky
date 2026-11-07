import { DialogButton, Focusable, Navigation, SteamSpinner, TextField, showModal } from "@decky/ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Collection,
  CollectionGroup,
  InstalledRom,
  Platform,
  RomScope,
  RomSummary,
  formatBytes,
  listCollections,
  listPlatforms,
  listRoms,
} from "../backend";
import { activeJobFor, healthOf, installedFor, statusFor, useInstallState } from "../installs";
import { Cover } from "./Cover";
import { RomModal } from "./RomModal";

export const LIBRARY_ROUTE = "/romm";
const PAGE_SIZE = 50;

export type LibraryTab = "platforms" | "collections" | "installed";
let nextTab: LibraryTab = "platforms";

/** Open the full-screen library, optionally on a given tab. */
export function openLibrary(tab: LibraryTab = "platforms") {
  nextTab = tab;
  Navigation.Navigate(LIBRARY_ROUTE);
  Navigation.CloseSideMenus();
}

const GROUPS: [CollectionGroup, string][] = [
  ["mine", "Mine"],
  ["collection", "Series"],
  ["franchise", "Franchises"],
  ["genre", "Genres"],
  ["company", "Companies"],
  ["mode", "Modes"],
];

// Steam's footer (button hints) overlays the bottom ~50px of the screen.
const FOOTER = 56;
const css = `
.rm-card { border-radius: 6px; padding: 4px; transition: transform 80ms ease-out, background 80ms;
  scroll-margin: 16px 0 ${FOOTER + 16}px; }
.rm-card.rm-focus { background: rgba(255,255,255,0.12); transform: scale(1.04); outline: 2px solid #1a9fff; }
.rm-tile { border-radius: 6px; padding: 14px; min-height: 64px; background: rgba(255,255,255,0.06);
  display: flex; flex-direction: column; justify-content: space-between; gap: 6px;
  transition: transform 80ms ease-out, background 80ms; scroll-margin: 16px 0 ${FOOTER + 16}px; }
.rm-tile.rm-focus { background: rgba(26,159,255,0.25); transform: scale(1.03); outline: 2px solid #1a9fff; }
`;

/** What the ROM grid is showing: everything (search), or one platform/collection. */
type Scope = { scope: RomScope; id: number | string | null; name: string };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const ellipsis = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } as const;

/** An install record shaped like a list item, for the Installed tab and the modal. */
function installedAsRom(i: InstalledRom): RomSummary {
  return {
    id: Number(i.rom_id),
    name: i.title,
    platform_id: i.platform_id,
    platform_slug: i.platform_slug,
    platform_fs_slug: i.platform_fs_slug,
    platform_name: i.platform_name,
    fs_name: "",
    size: i.size,
    cover: i.cover,
    multi_file: i.files.length > 1,
    regions: [],
    missing: false,
  };
}

function RomCard({ rom, showPlatform }: { rom: RomSummary; showPlatform: boolean }) {
  const snap = useInstallState();
  const job = activeJobFor(snap, rom.id);
  const inst = installedFor(snap, rom.id);
  const badge = job
    ? { text: job.total ? `${Math.floor((100 * job.done) / job.total)}%` : "Installing", color: "#1a9fff" }
    : inst
      ? healthOf(inst, statusFor(snap, rom.id)) !== "ok"
        ? { text: "Needs attention", color: "#ffb84d" }
        : statusFor(snap, rom.id)?.update_available
          ? { text: "Update", color: "#1a9fff" }
          : { text: "Installed", color: "#59bf40" }
      : null;
  const open = () => showModal(<RomModal rom={rom} />);
  return (
    <Focusable className="rm-card" focusClassName="rm-focus" noFocusRing onActivate={open} onClick={open}>
      <Cover url={rom.cover} title={rom.name} />
      <div style={{ marginTop: "6px", fontSize: "13px", ...ellipsis }}>{rom.name}</div>
      <div style={{ fontSize: "11px", color: "#8b929a", ...ellipsis }}>
        {[showPlatform ? rom.platform_name : null, formatBytes(rom.size)].filter(Boolean).join(" · ")}
        {badge && <span style={{ color: badge.color }}> · {badge.text}</span>}
      </div>
    </Focusable>
  );
}

function InstalledGrid({ query }: { query: string }) {
  const { installed } = useInstallState();
  const q = query.toLowerCase();
  const roms = installed
    .filter((i) => !q || i.title.toLowerCase().includes(q))
    .sort((a, b) => a.title.localeCompare(b.title))
    .map(installedAsRom);
  return (
    <>
      <div style={{ fontSize: "12px", color: "#8b929a", padding: "0 4px" }}>{plural(roms.length, "game")}</div>
      <Focusable
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: "14px",
          padding: "8px 4px",
        }}
      >
        {roms.map((r) => (
          <RomCard key={r.id} rom={r} showPlatform />
        ))}
      </Focusable>
      {!roms.length && (
        <div style={{ color: "#8b929a", padding: "24px 0" }}>
          {query ? `No installed games match “${query}”.` : "Nothing installed yet."}
        </div>
      )}
    </>
  );
}

const fail = (e: unknown) => ({ ok: false as const, error: { message: String(e), status: null, code: null } });

/** Paged ROM list with infinite scroll; stale responses are dropped. */
function useRomPages(scope: Scope | null, query: string) {
  const [items, setItems] = useState<RomSummary[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);

  const load = useCallback(
    async (from: number) => {
      if (!scope) return;
      const id = ++reqId.current;
      setLoading(true);
      setError(null);
      const r = await listRoms(scope.scope, scope.id, query, from, PAGE_SIZE).catch(fail);
      if (id !== reqId.current) return; // superseded by a newer search/scope
      setLoading(false);
      if (!r.ok) return setError(r.error.message);
      setItems((prev) => (from === 0 ? r.data.items : [...prev, ...r.data.items]));
      setTotal(r.data.total);
      setOffset(from);
    },
    [scope, query],
  );

  useEffect(() => {
    reqId.current++;
    setItems([]);
    setTotal(null);
    setError(null);
    setLoading(false);
    if (scope) void load(0);
  }, [load]);

  const hasMore = total != null && items.length < total;
  const next = useCallback(() => load(offset + PAGE_SIZE), [load, offset]);
  const retry = () => load(items.length ? offset + PAGE_SIZE : 0);
  return { items, total, loading, error, hasMore, next, retry };
}

function useLoaded<T>(fetch: () => Promise<{ ok: true; data: T } | { ok: false; error: { message: string } }>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    fetch()
      .catch(fail)
      .then((r) => {
        if (!alive) return;
        if (r.ok) setData(r.data);
        else setError(r.error.message);
      });
    return () => {
      alive = false;
    };
  }, [...deps, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

function ErrorRow({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div style={{ color: "#ff6b6b", padding: "16px 0" }}>
      {error}
      {error.includes("Not paired") ? (
        " — pair with RomM in the quick-access panel."
      ) : (
        <DialogButton style={{ width: "120px", minWidth: 0, marginTop: "10px" }} onClick={onRetry}>
          Retry
        </DialogButton>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
      <SteamSpinner />
    </div>
  );
}

function PlatformTiles({ onOpen }: { onOpen: (p: Platform) => void }) {
  const { data, error, reload } = useLoaded(() => listPlatforms(), []);
  if (error) return <ErrorRow error={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <Focusable
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        gap: "12px",
        padding: "8px 4px",
      }}
    >
      {data.map((p) => (
        <Focusable
          key={p.id}
          className="rm-tile"
          focusClassName="rm-focus"
          noFocusRing
          onActivate={() => onOpen(p)}
          onClick={() => onOpen(p)}
        >
          <div style={{ fontSize: "15px", fontWeight: "bold", ...ellipsis }}>{p.name}</div>
          <div style={{ fontSize: "12px", color: "#8b929a" }}>{plural(p.rom_count, "game")}</div>
        </Focusable>
      ))}
    </Focusable>
  );
}

function CollectionTiles({ group, onOpen }: { group: CollectionGroup; onOpen: (c: Collection) => void }) {
  const { data, error, reload } = useLoaded(() => listCollections(group), [group]);
  if (error) return <ErrorRow error={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  if (!data.length)
    return (
      <div style={{ color: "#8b929a", padding: "24px 0" }}>
        {group === "mine" ? "You haven't made any collections in RomM yet." : "Nothing here."}
      </div>
    );
  return (
    <Focusable
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
        gap: "14px",
        padding: "8px 4px",
      }}
    >
      {data.map((c) => (
        <Focusable
          key={`${c.kind}:${c.id}`}
          className="rm-card"
          focusClassName="rm-focus"
          noFocusRing
          onActivate={() => onOpen(c)}
          onClick={() => onOpen(c)}
        >
          <Cover url={c.cover} title={c.name} />
          <div style={{ marginTop: "6px", fontSize: "13px", ...ellipsis }}>{c.name}</div>
          <div style={{ fontSize: "11px", color: "#8b929a" }}>{plural(c.rom_count, "game")}</div>
        </Focusable>
      ))}
    </Focusable>
  );
}

function RomGrid({ scope, query }: { scope: Scope; query: string }) {
  const pages = useRomPages(scope, query);
  const sentinel = useRef<HTMLDivElement>(null);
  const showPlatform = scope.scope !== "platform";

  // Infinite scroll: fetch the next page when the sentinel nears the viewport.
  useEffect(() => {
    const el = sentinel.current;
    // Stop on error: otherwise each failed page flips `loading` and immediately retries, forever.
    if (!el || !pages.hasMore || pages.loading || pages.error) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && pages.next(), { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, [pages.hasMore, pages.loading, pages.error, pages.next]);

  return (
    <>
      <div style={{ fontSize: "12px", color: "#8b929a", padding: "0 4px" }}>
        {pages.total != null ? plural(pages.total, "game") : " "}
      </div>
      {pages.error && <ErrorRow error={pages.error} onRetry={pages.retry} />}
      <Focusable
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: "14px",
          padding: "8px 4px",
        }}
      >
        {pages.items.map((r) => (
          <RomCard key={r.id} rom={r} showPlatform={showPlatform} />
        ))}
      </Focusable>
      <div ref={sentinel} style={{ height: "1px" }} />
      {pages.loading && <Spinner />}
      {pages.total === 0 && !pages.loading && !pages.error && (
        <div style={{ color: "#8b929a", padding: "24px 0" }}>
          {query ? `No games match “${query}”.` : "No games here."}
        </div>
      )}
    </>
  );
}

export function LibraryPage() {
  const [tab, setTab] = useState<LibraryTab>(() => {
    const t = nextTab;
    nextTab = "platforms";
    return t;
  });
  const [group, setGroup] = useState<CollectionGroup>("mine");
  const [scope, setScope] = useState<Scope | null>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  // Typing at the top level searches every ROM; inside a platform/collection it searches that.
  // Memoised: a fresh object each render would re-trigger the page loader forever.
  // The Installed tab filters locally instead of searching the server.
  const gridScope = useMemo<Scope | null>(
    () => scope ?? (debounced && tab !== "installed" ? { scope: "all", id: null, name: "All games" } : null),
    [scope, debounced, tab],
  );
  const { installed } = useInstallState();

  const drill = (s: Scope) => {
    setScope(s);
    setQuery("");
    setDebounced("");
  };
  const up = () => {
    setScope(null);
    setQuery("");
    setDebounced("");
  };

  const crumb = scope
    ? scope.name
    : tab === "installed"
      ? "Installed"
      : debounced
        ? "Search"
        : tab === "platforms"
          ? "Platforms"
          : "Collections";

  return (
    <Focusable
      // B goes up one level from a platform/collection, else leaves the page. Once a
      // Focusable has onCancelButton, Steam treats B as handled and skips its default
      // "back", so the top level must navigate back itself (verified on the Deck).
      onCancelButton={(e) => {
        e.stopPropagation();
        if (scope) up();
        else Navigation.NavigateBack();
      }}
      onCancelActionDescription={scope ? "Up" : "Back"}
      style={{
        marginTop: "40px",
        height: "calc(100vh - 40px)",
        boxSizing: "border-box",
        overflowY: "auto",
        padding: `0 24px ${FOOTER + 24}px`,
      }}
    >
      <style>{css}</style>
      <div style={{ padding: "12px 0 6px", fontSize: "14px", color: "#b8bcbf" }}>RomM · {crumb}</div>
      <Focusable style={{ display: "flex", alignItems: "center", gap: "16px", paddingBottom: "12px" }}>
        <div style={{ flex: 1 }}>
          <TextField value={query} onChange={(e) => setQuery(e.target.value)} bShowClearAction />
        </div>
        <DialogButton
          style={{ width: "120px", minWidth: 0 }}
          onClick={() => (scope ? up() : Navigation.NavigateBack())}
        >
          Back
        </DialogButton>
      </Focusable>

      {!scope && (
        <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", paddingBottom: "12px", flexWrap: "wrap" }}>
          {(
            [
              ["platforms", "Platforms"],
              ["collections", "Collections"],
              ["installed", `Installed (${installed.length})`],
            ] as [LibraryTab, string][]
          ).map(([id, label]) => (
            <DialogButton
              key={id}
              onClick={() => setTab(id)}
              style={{
                width: "auto",
                minWidth: 0,
                padding: "6px 16px",
                background: tab === id ? "#1a9fff" : undefined,
                color: tab === id ? "#fff" : undefined,
              }}
            >
              {label}
            </DialogButton>
          ))}
          {tab === "collections" && !debounced && (
            <>
              <div style={{ width: "1px", height: "24px", background: "rgba(255,255,255,0.2)", margin: "0 6px" }} />
              {GROUPS.map(([id, label]) => (
                <DialogButton
                  key={id}
                  onClick={() => setGroup(id)}
                  style={{
                    width: "auto",
                    minWidth: 0,
                    padding: "6px 12px",
                    fontSize: "13px",
                    background: group === id ? "rgba(26,159,255,0.6)" : undefined,
                    color: group === id ? "#fff" : undefined,
                  }}
                >
                  {label}
                </DialogButton>
              ))}
            </>
          )}
        </Focusable>
      )}

      {gridScope ? (
        <RomGrid scope={gridScope} query={debounced} />
      ) : tab === "installed" ? (
        <InstalledGrid query={debounced} />
      ) : tab === "platforms" ? (
        <PlatformTiles onOpen={(p) => drill({ scope: "platform", id: p.id, name: p.name })} />
      ) : (
        <CollectionTiles
          group={group}
          onOpen={(c) =>
            drill({ scope: c.kind === "user" ? "collection" : c.kind, id: c.id, name: c.name })
          }
        />
      )}
    </Focusable>
  );
}
