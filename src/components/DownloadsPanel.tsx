import { ButtonItem, PanelSection, PanelSectionRow, ProgressBarWithInfo } from "@decky/ui";
import { ACTIVE_PHASES, JobState, cancelInstall, dismissJob, formatBytes } from "../backend";
import { finishFailed, finishInstall, refresh, useInstallState } from "../installs";

const PHASE_TEXT: Record<string, string> = {
  queued: "Queued",
  starting: "Starting",
  core: "Downloading emulator core",
  checking: "Checking existing files",
  downloading: "Downloading",
  finalizing: "Finishing",
  bios: "Copying BIOS files",
  done: "Adding to Steam",
  error: "Failed",
  cancelled: "Cancelled",
};

function eta(job: JobState): string | undefined {
  if (!job.speed || !job.total || job.phase !== "downloading") return undefined;
  const s = Math.max(0, Math.round((job.total - job.done) / job.speed));
  return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function JobRow({ job }: { job: JobState }) {
  const active = ACTIVE_PHASES.includes(job.phase);
  const pct = job.total ? Math.min(100, (100 * job.done) / job.total) : undefined;
  const steamError = job.phase === "done" ? finishFailed(job.job_id) : undefined;
  const op =
    job.phase === "error"
      ? (job.error ?? "Failed")
      : steamError
        ? `Couldn't add to Steam: ${steamError}`
        : `${PHASE_TEXT[job.phase] ?? job.phase}${job.total ? ` · ${formatBytes(job.done)} / ${formatBytes(job.total)}` : ""}${
            job.speed ? ` · ${formatBytes(job.speed)}/s` : ""
          }`;

  return (
    <>
      <PanelSectionRow>
        <ProgressBarWithInfo
          label={job.title ?? `ROM ${job.rom_id}`}
          nProgress={job.phase === "done" ? 100 : pct}
          indeterminate={active && pct == null}
          sOperationText={op}
          sTimeRemaining={eta(job)}
        />
      </PanelSectionRow>
      {active && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => cancelInstall(job.job_id).then(() => refresh())}>
            Cancel
          </ButtonItem>
        </PanelSectionRow>
      )}
      {steamError && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void finishInstall(job, true)}>
            Retry adding to Steam
          </ButtonItem>
        </PanelSectionRow>
      )}
      {(job.phase === "error" || job.phase === "cancelled" || steamError) && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => dismissJob(job.job_id).then(() => refresh())}>
            Dismiss
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

export function DownloadsPanel() {
  const { jobs } = useInstallState();
  if (!jobs.length) return null;
  return (
    <PanelSection title="Downloads">
      {jobs.map((j) => (
        <JobRow key={j.job_id} job={j} />
      ))}
    </PanelSection>
  );
}
