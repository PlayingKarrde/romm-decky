import { callable } from "@decky/api";

export type ApiError = { message: string; status: number | null; code: string | null };
export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export type PublicSettings = {
  server_url: string;
  has_token: boolean;
  username: string;
  custom_install_dir: string;
  steam_platform_collections: boolean;
  platform_overrides: Record<string, string>;
};

export type ConnectionInfo = {
  ok: boolean;
  server_version: string | null;
  username: string | null;
  platform_count: number;
  rom_count: number;
};

export type PairingState = "starting" | "waiting" | "done" | "expired" | "denied" | "error" | "stopped";
export type PairingStatus = {
  state: PairingState;
  user_code?: string;
  url?: string;
  expires_in?: number | null;
  error?: string | null;
  settings?: PublicSettings;
};

export const getSettings = callable<[], Result<PublicSettings>>("get_settings");
export const setPlatformCollections = callable<[enabled: boolean], Result<PublicSettings>>(
  "set_platform_collections",
);
export const testConnection = callable<[], Result<ConnectionInfo>>("test_connection");
export const signOut = callable<[], Result<PublicSettings>>("sign_out");
export const startPairing = callable<[server_url: string], Result<PairingStatus>>("start_pairing");
export const getPairingStatus = callable<[], Result<PairingStatus>>("get_pairing_status");
export const stopPairing = callable<[], Result<null>>("stop_pairing");

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}
