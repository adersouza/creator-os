import type { AccountGroup } from "@/hooks/useAccountGroups";

export type Tab = "media";
export type MediaType = "photo" | "video";
export type PlatformKind = "threads" | "instagram";

export interface MediaItem {
  id: string;
  name: string;
  type: MediaType;
  platforms: PlatformKind[];
  used: number;
  addedDaysAgo: number;
  size: string;
  from: string;
  to: string;
  thumbnailUrl?: string | undefined;
  url?: string | undefined;
  groupId: string | null;
  groupName: string;
  accountId: string | null;
  accountPlatform: PlatformKind | null;
  accountName: string;
  accent: string;
}

export type AnyLibraryItem = MediaItem;
export type LibraryGroup = Pick<AccountGroup, "id" | "name" | "color">;
export interface LibraryAccount {
  id: string;
  handle: string;
  platform: PlatformKind;
  groupId: string | null;
}
