// Polls the worker's job states and turns finished downloads into Steam shortcuts.
// Lives for the whole plugin lifetime (started in definePlugin), not per page.
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  ACTIVE_PHASES,
  InstalledRom,
  JobState,
  dismissJob,
  finalizeInstall,
  getInstalled,
  getJobs,
  setInstalledAppid,
  startInstall,
  uninstallRom,
} from "./backend";
import { addToCollection, applyCover, removeShortcut, shortcutExists, upsertShortcut } from "./steam";

type Snapshot = { jobs: JobState[]; installed: InstalledRom[] };

let snapshot: Snapshot = { jobs: [], installed: [] };
const listeners = new Set<(s: Snapshot) => void>();
const finishing = new Set<string>();
const failed = new Map<string, string>(); // job_id -> why adding to Steam failed
let timer: ReturnType<typeof setTimeout> | null = null;
let stopped = true;
let ticking = false; // a tick is awaiting refresh()
let rerun = false; // kick() arrived mid-tick: tick again right after

const toast = (body: string) => toaster.toast({ title: "RomM", body });

function emit() {
  listeners.forEach((l) => l(snapshot));
}

export async function refresh(): Promise<Snapshot> {
  const [j, i] = await Promise.all([getJobs(), getInstalled()]);
  snapshot = { jobs: j.ok ? j.data : snapshot.jobs, installed: i.ok ? i.data : snapshot.installed };
  emit();
  for (const job of snapshot.jobs) {
    if (job.phase === "done" && !finishing.has(job.job_id)) void finishInstall(job);
  }
  return snapshot;
}

async function tick() {
  if (stopped) return;
  if (ticking) {
    rerun = true;
    return;
  }
  ticking = true;
  timer = null;
  try {
    await refresh();
  } catch (e) {
    console.warn("[romm] poll failed", e);
  } finally {
    ticking = false;
  }
  if (stopped) return;
  const busy = snapshot.jobs.some((j) => ACTIVE_PHASES.includes(j.phase));
  const delay = rerun ? 0 : busy ? 1000 : 5000;
  rerun = false;
  if (timer) clearTimeout(timer);
  timer = setTimeout(tick, delay);
}

export function startPolling() {
  if (!stopped) return;
  stopped = false;
  void tick();
}

export function stopPolling() {
  stopped = true;
  if (timer) clearTimeout(timer);
  timer = null;
}

/** Poke the poller now (e.g. right after starting an install). */
export function kick() {
  if (timer) clearTimeout(timer);
  if (!stopped) void tick();
}

export function useInstallState(): Snapshot {
  const [s, setS] = useState(snapshot);
  useEffect(() => {
    listeners.add(setS);
    setS(snapshot);
    return () => void listeners.delete(setS);
  }, []);
  return s;
}

export const installedFor = (s: Snapshot, romId: number | string) =>
  s.installed.find((r) => r.rom_id === String(romId));

export const activeJobFor = (s: Snapshot, romId: number | string) =>
  s.jobs.find((j) => String(j.rom_id) === String(romId) && (ACTIVE_PHASES.includes(j.phase) || j.phase === "done"));

export const finishFailed = (jobId: string) => failed.get(jobId);

/** The Steam shortcut for an install, if it still exists. */
export const appIdOf = (inst?: InstalledRom) =>
  inst?.appid && shortcutExists(inst.appid) ? inst.appid : null;

// ---- actions -------------------------------------------------------------------

export async function install(romId: number, name: string): Promise<boolean> {
  const r = await startInstall(romId);
  if (!r.ok) {
    toast(`Can't install ${name}: ${r.error.message}`);
    return false;
  }
  toast(`Downloading ${name}`);
  kick();
  return true;
}

/** Turn a finished job into a Steam shortcut (+ collection, artwork) and record it. */
export async function finishInstall(job: JobState, manual = false): Promise<void> {
  if (manual) {
    failed.delete(job.job_id);
    finishing.delete(job.job_id);
  }
  if (finishing.has(job.job_id) || failed.has(job.job_id)) return;
  finishing.add(job.job_id);
  const title = job.title ?? `ROM ${job.rom_id}`;
  try {
    const info = await finalizeInstall(job.job_id);
    if (!info.ok) throw new Error(info.error.message);
    const f = info.data;
    const hadShortcut = !!f.appid && shortcutExists(f.appid);
    const appId = await upsertShortcut({ name: f.name, exe: f.exe, startDir: f.start_dir }, f.appid);
    let collection: string | null = null;
    if (f.collection) {
      try {
        await addToCollection(appId, f.collection);
        collection = f.collection;
      } catch (e) {
        console.warn("[romm] collection failed", e);
      }
    }
    const saved = await setInstalledAppid(f.rom_id, appId, collection);
    if (!saved.ok) throw new Error(saved.error.message);
    await dismissJob(job.job_id);
    toast(`${f.name} is ready to play`);
    // A reinstall keeps the existing shortcut's artwork (which the user may have customised).
    if (!hadShortcut) await applyCover(appId, f.cover);
  } catch (e) {
    console.error("[romm] finishing install failed", e);
    failed.set(job.job_id, (e as Error).message);
    toast(`Couldn't add ${title} to Steam: ${(e as Error).message}`);
  } finally {
    void refresh();
  }
}

const uninstalling = new Set<string>();

/**
 * Remove the Steam shortcut, then the files we downloaded and the record.
 * deleteExisting also deletes files that were already on the Deck before the install.
 */
export async function uninstall(inst: InstalledRom, deleteExisting = false): Promise<boolean> {
  if (uninstalling.has(inst.rom_id)) return false; // a second press while the first is running
  uninstalling.add(inst.rom_id);
  try {
    if (inst.appid) await removeShortcut(inst.appid);
    const r = await uninstallRom(inst.rom_id, deleteExisting);
    if (!r.ok) throw new Error(r.error.message);
    toast(
      r.data.kept
        ? `${inst.title} removed from Steam. Its existing ROM files were kept.`
        : `${inst.title} uninstalled`,
    );
    return true;
  } catch (e) {
    toast(`Couldn't uninstall ${inst.title}: ${(e as Error).message}`);
    return false;
  } finally {
    uninstalling.delete(inst.rom_id);
    void refresh();
  }
}
