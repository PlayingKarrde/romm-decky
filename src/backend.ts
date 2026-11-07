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

// ---- library ---------------------------------------------------------------

export type Platform = {
  id: number;
  slug: string;
  fs_slug: string;
  name: string;
  rom_count: number;
  firmware_count: number;
};

export type CollectionGroup = "mine" | "collection" | "franchise" | "genre" | "company" | "mode";
export type Collection = {
  id: number | string;
  kind: "user" | "smart" | "virtual";
  name: string;
  rom_count: number;
  cover: string | null;
  is_favorite: boolean;
};

export type RomScope = "all" | "platform" | "collection" | "smart" | "virtual";

export type RomSummary = {
  id: number;
  name: string;
  platform_id: number;
  platform_slug: string;
  platform_fs_slug: string;
  platform_name: string;
  fs_name: string;
  size: number;
  cover: string | null;
  multi_file: boolean;
  regions: string[];
  missing: boolean;
};

export type RomFile = { id: number; name: string; size: number; md5: string | null; subdir: string };
export type RomDetail = RomSummary & {
  summary: string;
  cover_large: string | null;
  files: RomFile[];
  updated_at: string;
  collections: { id: number; name: string }[];
};

export type RomPage = { items: RomSummary[]; total: number | null; offset: number; limit: number };

export const listPlatforms = callable<[], Result<Platform[]>>("list_platforms");
export const listCollections = callable<[group: CollectionGroup], Result<Collection[]>>("list_collections");
export const listRoms = callable<
  [scope: RomScope, scope_id: number | string | null, query: string, offset: number, limit: number],
  Result<RomPage>
>("list_roms");
export const getRom = callable<[rom_id: number], Result<RomDetail>>("get_rom");

export type ImageInfo = { thumb: string } | { content_type: string; size: number; chunks: number };
export const getImage = callable<[image_url: string], Result<ImageInfo>>("get_image");
export const getImageChunk = callable<[image_url: string, index: number], Result<string>>("get_image_chunk");
export const saveThumbnail = callable<[image_url: string, data_url: string], Result<null>>("save_thumbnail");

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
