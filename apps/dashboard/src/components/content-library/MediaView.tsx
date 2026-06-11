import { useEffect, useMemo, useState } from "react";
import { Check, Image as ImageIcon, Play, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Select } from "@/components/ui/Select";
import { RecentStrip } from "./RecentStrip";
import {
	InlineEmpty,
	MetaDot,
	PlatformIcon,
	StatCell,
	TypePill,
} from "./shared";
import type {
	LibraryAccount,
	LibraryGroup,
	MediaItem,
	MediaType,
	PlatformKind,
} from "./types";

const MEDIA_PAGE_SIZE = 32;

const getAccountOptionLabel = (account: LibraryAccount) =>
	`${account.handle} · ${account.platform === "instagram" ? "IG" : "Threads"}`;

export function MediaView({
	items: mediaItems,
	recentItems,
	groups,
	accounts,
	onUseInComposer,
	onAssignGroup,
	onBulkAssignGroup,
	onAssignAccount,
	onBulkAssignAccount,
}: {
	items: MediaItem[];
	recentItems: MediaItem[];
	groups: LibraryGroup[];
	accounts: LibraryAccount[];
	onUseInComposer: (item: MediaItem) => void;
	onAssignGroup: (mediaId: string, groupId: string | null) => Promise<void>;
	onBulkAssignGroup: (
		mediaIds: string[],
		groupId: string | null,
	) => Promise<number>;
	onAssignAccount: (
		mediaId: string,
		accountId: string | null,
		accountPlatform: PlatformKind | null,
	) => Promise<void>;
	onBulkAssignAccount: (
		mediaIds: string[],
		accountId: string | null,
		accountPlatform: PlatformKind | null,
	) => Promise<number>;
}) {
	const [type, setType] = useState<"all" | MediaType>("all");
	const [platform, setPlatform] = useState<"all" | PlatformKind>("all");
	const [groupId, setGroupId] = useState<string>("all");
	const [sort, setSort] = useState<"recent" | "used">("recent");
	const [visibleCount, setVisibleCount] = useState(MEDIA_PAGE_SIZE);
	const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
	const [bulkGroupId, setBulkGroupId] = useState<string>("unassigned");
	const [bulkAccountKey, setBulkAccountKey] = useState<string>("unassigned");
	const [bulkSaving, setBulkSaving] = useState(false);
	const resetKey = `${platform}:${sort}:${type}:${groupId}`;

	const items = useMemo(() => {
		let rows = mediaItems.filter((m) => {
			if (type !== "all" && m.type !== type) return false;
			if (platform !== "all" && !m.platforms.includes(platform)) return false;
			if (groupId === "unassigned" && m.groupId !== null) return false;
			if (
				groupId !== "all" &&
				groupId !== "unassigned" &&
				m.groupId !== groupId
			) {
				return false;
			}
			return true;
		});
		rows = rows.sort((a, b) =>
			sort === "used" ? b.used - a.used : a.addedDaysAgo - b.addedDaysAgo,
		);
		return rows;
	}, [groupId, mediaItems, platform, sort, type]);

	useEffect(() => {
		void resetKey;
		setVisibleCount(MEDIA_PAGE_SIZE);
		setSelectedIds(new Set());
	}, [resetKey]);

	const visibleItems = useMemo(
		() => items.slice(0, visibleCount),
		[items, visibleCount],
	);

	const totalSize = useMemo(
		() => mediaItems.reduce((acc, m) => acc + parseFloat(m.size), 0).toFixed(1),
		[mediaItems],
	);
	const assignedCount = useMemo(
		() => mediaItems.filter((m) => m.groupId !== null).length,
		[mediaItems],
	);
	const mostUsed = useMemo(
		() => [...mediaItems].sort((a, b) => b.used - a.used)[0],
		[mediaItems],
	);

	const selectedVisibleCount = visibleItems.filter((item) =>
		selectedIds.has(item.id),
	).length;
	const allVisibleSelected =
		visibleItems.length > 0 && selectedVisibleCount === visibleItems.length;

	const toggleSelected = (id: string) => {
		setSelectedIds((prev) => {
			const next = new Set(prev);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			return next;
		});
	};

	const toggleVisible = () => {
		setSelectedIds((prev) => {
			const next = new Set(prev);
			if (allVisibleSelected) {
				visibleItems.forEach((item) => {
					next.delete(item.id);
				});
			} else {
				visibleItems.forEach((item) => {
					next.add(item.id);
				});
			}
			return next;
		});
	};

	const applyBulkGroup = async () => {
		if (selectedIds.size === 0) return;
		setBulkSaving(true);
		const nextGroupId = bulkGroupId === "unassigned" ? null : bulkGroupId;
		const updated = await onBulkAssignGroup([...selectedIds], nextGroupId);
		if (updated > 0) setSelectedIds(new Set());
		setBulkSaving(false);
	};
	const applyBulkAccount = async () => {
		if (selectedIds.size === 0) return;
		setBulkSaving(true);
		const [accountPlatform, accountId] =
			bulkAccountKey === "unassigned"
				? [null, null]
				: (bulkAccountKey.split(":") as [PlatformKind, string]);
		const updated = await onBulkAssignAccount(
			[...selectedIds],
			accountId,
			accountPlatform,
		);
		if (updated > 0) setSelectedIds(new Set());
		setBulkSaving(false);
	};

	return (
		<div className="flex flex-col gap-6">
			<RecentStrip
				items={recentItems}
				renderItem={(m) => (
					<RecentMediaCard
						key={m.id}
						item={m}
						onUseInComposer={onUseInComposer}
					/>
				)}
			/>
			<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
				<StatCell label="Assigned" value={assignedCount.toString()} />
				<StatCell label="Storage used" value={`${totalSize} MB`} />
				<StatCell
					label="Most reused"
					value={mostUsed ? `${mostUsed.used}x` : "-"}
					detail={mostUsed?.name ?? "Upload to start tracking reuse"}
				/>
			</div>
			<NovaCard contentClassName="p-3 md:p-4">
				<div className="flex items-center flex-wrap gap-2">
					<FilterSelect<"all" | MediaType>
						value={type}
						onChange={setType}
						options={[
							{ value: "all", label: "All types" },
							{ value: "photo", label: "Photo" },
							{ value: "video", label: "Video" },
						]}
					/>
					<FilterSelect<"all" | PlatformKind>
						value={platform}
						onChange={setPlatform}
						options={[
							{ value: "all", label: "All platforms" },
							{ value: "threads", label: "Threads" },
							{ value: "instagram", label: "Instagram" },
						]}
					/>
					<FilterSelect<string>
						value={groupId}
						onChange={setGroupId}
						options={[
							{ value: "all", label: "All groups" },
							{ value: "unassigned", label: "Unassigned" },
							...groups.map((group) => ({
								value: group.id,
								label: group.name,
							})),
						]}
					/>
					<FilterSelect<"recent" | "used">
						value={sort}
						onChange={setSort}
						options={[
							{ value: "recent", label: "Recent" },
							{ value: "used", label: "Most used" },
						]}
					/>
					<div className="ml-auto text-xs text-muted-foreground tabular-nums">
						{items.length} of {mediaItems.length}
					</div>
				</div>
				{items.length > 0 && (
					<div className="mt-3 flex items-center flex-wrap gap-2 border-t border-border pt-3">
						<Button
							type="button"
							onClick={toggleVisible}
							variant="outline"
							size="sm"
							className="gap-1.5"
						>
							{allVisibleSelected ? (
								<X data-icon="inline-start" aria-hidden="true" />
							) : (
								<Check data-icon="inline-start" aria-hidden="true" />
							)}
							{allVisibleSelected ? "Clear visible" : "Select visible"}
						</Button>
						{selectedIds.size > 0 && (
							<>
								<span className="text-sm text-muted-foreground tabular-nums">
									{selectedIds.size} selected
								</span>
								<FilterSelect<string>
									value={bulkGroupId}
									onChange={setBulkGroupId}
									options={[
										{ value: "unassigned", label: "Unassigned" },
										...groups.map((group) => ({
											value: group.id,
											label: group.name,
										})),
									]}
								/>
								<Button
									type="button"
									disabled={bulkSaving}
									onClick={() => void applyBulkGroup()}
									size="sm"
								>
									{bulkSaving ? "Assigning..." : "Assign group"}
								</Button>
								<FilterSelect<string>
									value={bulkAccountKey}
									onChange={setBulkAccountKey}
									options={[
										{ value: "unassigned", label: "No creator" },
										...accounts.map((account) => ({
											value: `${account.platform}:${account.id}`,
											label: getAccountOptionLabel(account),
										})),
									]}
								/>
								<Button
									type="button"
									disabled={bulkSaving}
									onClick={() => void applyBulkAccount()}
									variant="outline"
									size="sm"
								>
									{bulkSaving ? "Assigning..." : "Assign creator"}
								</Button>
							</>
						)}
					</div>
				)}
			</NovaCard>
			{items.length === 0 ? (
				<InlineEmpty
					title={
						mediaItems.length === 0
							? "Upload media to build a library"
							: "No matching media"
					}
					detail={
						mediaItems.length === 0
							? "Drop in a photo or video and it will appear here for Composer."
							: "Try widening the filter or choosing another group."
					}
				/>
			) : (
				<>
					<div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
						{visibleItems.map((m) => (
							<MediaCard
								key={m.id}
								item={m}
								groups={groups}
								accounts={accounts}
								selected={selectedIds.has(m.id)}
								onToggleSelected={toggleSelected}
								onUseInComposer={onUseInComposer}
								onAssignGroup={onAssignGroup}
								onAssignAccount={onAssignAccount}
							/>
						))}
					</div>
					{visibleItems.length < items.length && (
						<div className="flex justify-center pt-1">
							<Button
								type="button"
								variant="outline"
								onClick={() =>
									setVisibleCount((count) => count + MEDIA_PAGE_SIZE)
								}
							>
								Show{" "}
								{Math.min(MEDIA_PAGE_SIZE, items.length - visibleItems.length)}{" "}
								more
							</Button>
						</div>
					)}
				</>
			)}
		</div>
	);
}

function MediaCard({
	item,
	groups,
	accounts,
	selected,
	onToggleSelected,
	onUseInComposer,
	onAssignGroup,
	onAssignAccount,
}: {
	item: MediaItem;
	groups: LibraryGroup[];
	accounts: LibraryAccount[];
	selected: boolean;
	onToggleSelected: (id: string) => void;
	onUseInComposer: (item: MediaItem) => void;
	onAssignGroup: (mediaId: string, groupId: string | null) => Promise<void>;
	onAssignAccount: (
		mediaId: string,
		accountId: string | null,
		accountPlatform: PlatformKind | null,
	) => Promise<void>;
}) {
	const typeIcon = item.type === "photo" ? ImageIcon : Play;
	const typeTone = item.type === "video" ? "gold" : "ink";
	const scopedAccounts = item.groupId
		? accounts.filter((account) => account.groupId === item.groupId)
		: accounts;
	const accountOptions =
		item.accountId &&
		item.accountPlatform &&
		!scopedAccounts.some(
			(account) =>
				account.id === item.accountId &&
				account.platform === item.accountPlatform,
		)
			? accounts
			: scopedAccounts;
	return (
		<NovaCard
			className="group"
			contentClassName="p-0"
			draggable
			onDragStart={(e) => e.dataTransfer.setData("text/plain", item.id)}
		>
			<div
				className="relative aspect-square w-full"
				style={{
					background: `linear-gradient(135deg, ${item.from}, ${item.to})`,
				}}
			>
				{item.thumbnailUrl && (
					<img
						src={item.thumbnailUrl}
						alt={item.name}
						loading="lazy"
						decoding="async"
						className="absolute inset-0 w-full h-full object-cover"
					/>
				)}
				<label
					htmlFor={`media-select-${item.id}`}
					className="absolute top-2 left-2 z-20 inline-flex items-center justify-center"
				>
					<span className="sr-only">Select {item.name}</span>
					<Checkbox
						id={`media-select-${item.id}`}
						checked={selected}
						onCheckedChange={() => onToggleSelected(item.id)}
						className="size-7 border-white/35 bg-black/35 text-white backdrop-blur-sm data-[state=checked]:border-primary data-[state=checked]:bg-primary"
					/>
				</label>
				<div className="absolute top-2 right-2 flex items-center gap-1">
					{item.platforms.map((p) => (
						<span
							key={p}
							className="inline-flex size-5 items-center justify-center rounded-full border border-border bg-background/90 text-[0.59375rem] text-foreground shadow-sm backdrop-blur-sm"
						>
							<PlatformIcon platform={p} className="w-3 h-3" />
						</span>
					))}
				</div>
				<div className="absolute bottom-2 left-2">
					<TypePill label={item.type} icon={typeIcon} tone={typeTone} />
				</div>
				{item.type !== "photo" && (
					<div className="absolute inset-0 flex items-center justify-center pointer-events-none">
						<div className="inline-flex size-10 items-center justify-center rounded-full border border-border bg-background/90 text-foreground shadow-sm backdrop-blur-sm">
							<Play className="size-4 fill-current" />
						</div>
					</div>
				)}
				<div
					className="absolute top-0 left-0 right-0 h-[2px]"
					style={{ background: item.accent }}
				/>
				<div className="absolute inset-0 bg-[color-mix(in_srgb,var(--color-foreground)_38%,transparent)] backdrop-blur-[2px] opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-200 flex items-center justify-center">
					<Button
						type="button"
						variant="secondary"
						size="sm"
						className="gap-1"
						onClick={() => onUseInComposer(item)}
					>
						<Sparkles data-icon="inline-start" aria-hidden="true" /> Use in
						Composer
					</Button>
				</div>
			</div>
			<div className="flex flex-col gap-2.5 px-3.5 py-3">
				<div className="min-w-0">
					<div className="text-[0.78125rem] font-medium text-foreground truncate tracking-[-0.005em]">
						{item.name}
					</div>
					<div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
						<span>{item.size}</span>
						<MetaDot />
						<span>{item.used}x used</span>
						<MetaDot />
						<span>{item.addedDaysAgo}d ago</span>
					</div>
				</div>
				<label htmlFor={`media-group-${item.id}`} className="block">
					<span className="sr-only">Assign group for {item.name}</span>
					<Select
						id={`media-group-${item.id}`}
						value={item.groupId ?? "unassigned"}
						onChange={(event) =>
							void onAssignGroup(
								item.id,
								event.target.value === "unassigned" ? null : event.target.value,
							)
						}
						sizeVariant="sm"
					>
						<option value="unassigned">Unassigned</option>
						{groups.map((group) => (
							<option key={group.id} value={group.id}>
								{group.name}
							</option>
						))}
					</Select>
				</label>
				<label htmlFor={`media-creator-${item.id}`} className="block">
					<span className="sr-only">Assign creator for {item.name}</span>
					<Select
						id={`media-creator-${item.id}`}
						value={
							item.accountId && item.accountPlatform
								? `${item.accountPlatform}:${item.accountId}`
								: "unassigned"
						}
						onChange={(event) => {
							const value = event.target.value;
							if (value === "unassigned") {
								void onAssignAccount(item.id, null, null);
								return;
							}
							const [platform, accountId] = value.split(":") as [
								PlatformKind,
								string,
							];
							void onAssignAccount(item.id, accountId, platform);
						}}
						sizeVariant="sm"
					>
						<option value="unassigned">No creator</option>
						{accountOptions.map((account) => (
							<option
								key={`${account.platform}:${account.id}`}
								value={`${account.platform}:${account.id}`}
							>
								{getAccountOptionLabel(account)}
							</option>
						))}
					</Select>
				</label>
			</div>
		</NovaCard>
	);
}

function RecentMediaCard({
	item,
	onUseInComposer,
}: {
	item: MediaItem;
	onUseInComposer: (item: MediaItem) => void;
}) {
	return (
		<Button
			type="button"
			title={item.name}
			onClick={() => onUseInComposer(item)}
			variant="ghost"
			className="group relative h-auto w-[112px] shrink-0 overflow-hidden rounded-md border border-border p-0 text-left hover:border-input"
		>
			<div
				className="relative aspect-square w-full"
				style={{
					background: `linear-gradient(135deg, ${item.from}, ${item.to})`,
				}}
			>
				{item.thumbnailUrl && (
					<img
						src={item.thumbnailUrl}
						alt={item.name}
						loading="lazy"
						decoding="async"
						className="absolute inset-0 w-full h-full object-cover"
					/>
				)}
				<div
					className="absolute top-0 left-0 right-0 h-[2px]"
					style={{ background: item.accent }}
				/>
			</div>
			<div className="px-2 py-1.5 bg-card">
				<div className="text-[0.6875rem] font-medium text-foreground truncate tracking-[-0.005em]">
					{item.name}
				</div>
				<div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
					{item.groupName} · {item.addedDaysAgo}d
				</div>
			</div>
		</Button>
	);
}
