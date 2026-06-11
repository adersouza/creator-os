import type { MediaAsset } from "@/services/mediaService";
import type {
  LibraryAccount,
  MediaItem,
  MediaType,
} from "@/components/content-library/types";

const UNASSIGNED_COLOR = "#6B6B70";

function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function gradientForId(id: string) {
  const hueA = hashString(id) % 360;
  return {
    from: `hsl(${hueA} 42% 62%)`,
    to: `hsl(${(hueA + 42) % 360} 34% 38%)`,
  };
}

function daysSince(iso: string | null): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.round((Date.now() - t) / 86_400_000));
}

export function adaptMediaAsset(
  asset: MediaAsset,
  groupsById: Map<string, { name: string; color: string }>,
  accountsByKey: Map<string, LibraryAccount> = new Map(),
): MediaItem {
  const createdDays = asset.date === "Recently" ? 0 : daysSince(asset.date);
  const mediaType: MediaType = asset.fileType === "video" ? "video" : "photo";
  const group = asset.groupId ? groupsById.get(asset.groupId) : null;
  const account =
    asset.accountId && asset.accountPlatform
      ? accountsByKey.get(`${asset.accountPlatform}:${asset.accountId}`)
      : null;
  const { from, to } = gradientForId(asset.id);
  return {
    id: asset.id,
    name: asset.name || "Untitled asset",
    type: mediaType,
    platforms: asset.accountPlatform ? [asset.accountPlatform] : ["instagram", "threads"],
    used: 0,
    addedDaysAgo: createdDays,
    size: asset.size,
    from,
    to,
    thumbnailUrl:
      mediaType === "photo" && /^https?:\/\//.test(asset.url)
        ? asset.url
        : undefined,
    url: /^https?:\/\//.test(asset.url) ? asset.url : undefined,
    groupId: asset.groupId,
    groupName: group?.name || "Unassigned",
    accountId: asset.accountId,
    accountPlatform: asset.accountPlatform,
    accountName: account?.handle || "Unassigned",
    accent: group?.color || UNASSIGNED_COLOR,
  };
}
