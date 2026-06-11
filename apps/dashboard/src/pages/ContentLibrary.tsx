import {
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type ReactNode,
} from "react";
import { Grid2x2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Button } from "@/components/ui/Button";
import { NovaDataPanel, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { ContentLibrarySkeleton } from "@/components/skeletons/PageSkeletons";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useAccountGroups } from "@/hooks/useAccountGroups";
import {
	assignMediaToGroup,
	assignMediaToAccount,
	bulkAssignMediaToAccount,
	bulkAssignMediaToGroup,
	getAllMedia,
} from "@/services/mediaService";
import { ContentHero } from "@/components/content-library/ContentHero";
import { MediaUploadZone } from "@/components/content-library/MediaUploadZone";
import { MediaView } from "@/components/content-library/MediaView";
import { adaptMediaAsset } from "@/components/content-library/adapters";
import type {
	LibraryAccount,
	MediaItem,
} from "@/components/content-library/types";

export function ContentLibrary() {
	const navigate = useNavigate();
	const {
		accounts,
		isLoading: accountsLoading,
		hasError: accountsError,
	} = useConnectedAccounts();
	const { groups } = useAccountGroups();
	const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
	const [mediaLoading, setMediaLoading] = useState(true);
	const [uploadOpen, setUploadOpen] = useState(false);
	const mediaRequestRef = useRef(0);

	const groupsById = useMemo(
		() =>
			new Map(
				groups.map((group) => [
					group.id,
					{ name: group.name, color: group.color },
				]),
			),
		[groups],
	);
	const libraryAccounts = useMemo<LibraryAccount[]>(
		() =>
			accounts.map((account) => ({
				id: account.id,
				handle: account.handle,
				platform: account.platform,
				groupId: account.groupId,
			})),
		[accounts],
	);
	const accountsByKey = useMemo(
		() =>
			new Map(
				libraryAccounts.map((account) => [
					`${account.platform}:${account.id}`,
					account,
				]),
			),
		[libraryAccounts],
	);

	const counts = { media: mediaItems.length, groups: groups.length };
	const hasAccounts = !accountsError && accounts.length > 0;

	const loadMedia = useCallback(async () => {
		const requestId = mediaRequestRef.current + 1;
		mediaRequestRef.current = requestId;
		setMediaLoading(true);
		try {
			const rows = await getAllMedia();
			if (mediaRequestRef.current !== requestId) return;
			setMediaItems(
				rows.map((asset) => adaptMediaAsset(asset, groupsById, accountsByKey)),
			);
		} catch {
			if (mediaRequestRef.current !== requestId) return;
			setMediaItems([]);
		} finally {
			if (mediaRequestRef.current === requestId) setMediaLoading(false);
		}
	}, [accountsByKey, groupsById]);

	useEffect(() => {
		void loadMedia();
		return () => {
			mediaRequestRef.current += 1;
		};
	}, [loadMedia]);

	const recentMedia = useMemo(() => mediaItems.slice(0, 10), [mediaItems]);

	const handleUseMedia = (item: MediaItem) => {
		const handoff = {
			id: item.id,
			name: item.name,
			type: item.type,
			platforms: item.platforms,
			url: item.url,
		};
		window.sessionStorage.setItem(
			"juno33:composer-media",
			JSON.stringify(handoff),
		);
		navigate("/composer", {
			state: { libraryMedia: handoff, requestMediaUpload: false },
		});
	};

	const applyGroupToItems = useCallback(
		(mediaIds: string[], groupId: string | null) => {
			const group = groupId ? groupsById.get(groupId) : null;
			setMediaItems((prev) =>
				prev.map((item) =>
					mediaIds.includes(item.id)
						? {
								...item,
								groupId,
								groupName: group?.name ?? "Unassigned",
								accent: group?.color ?? "#6B6B70",
							}
						: item,
				),
			);
		},
		[groupsById],
	);
	const applyAccountToItems = useCallback(
		(
			mediaIds: string[],
			accountId: string | null,
			accountPlatform: "threads" | "instagram" | null,
		) => {
			const account =
				accountId && accountPlatform
					? accountsByKey.get(`${accountPlatform}:${accountId}`)
					: null;
			setMediaItems((prev) =>
				prev.map((item) =>
					mediaIds.includes(item.id)
						? {
								...item,
								accountId,
								accountPlatform,
								accountName: account?.handle ?? "Unassigned",
								platforms: accountPlatform
									? [accountPlatform]
									: (["instagram", "threads"] as MediaItem["platforms"]),
							}
						: item,
				),
			);
		},
		[accountsByKey],
	);

	const handleAssignGroup = async (mediaId: string, groupId: string | null) => {
		applyGroupToItems([mediaId], groupId);
		const ok = await assignMediaToGroup(mediaId, groupId);
		if (!ok) void loadMedia();
	};

	const handleBulkAssignGroup = async (
		mediaIds: string[],
		groupId: string | null,
	) => {
		if (mediaIds.length === 0) return 0;
		applyGroupToItems(mediaIds, groupId);
		const updated = await bulkAssignMediaToGroup(mediaIds, groupId);
		if (updated !== mediaIds.length) void loadMedia();
		return updated;
	};
	const handleAssignAccount = async (
		mediaId: string,
		accountId: string | null,
		accountPlatform: "threads" | "instagram" | null,
	) => {
		applyAccountToItems([mediaId], accountId, accountPlatform);
		const ok = await assignMediaToAccount(mediaId, accountId, accountPlatform);
		if (!ok) void loadMedia();
	};
	const handleBulkAssignAccount = async (
		mediaIds: string[],
		accountId: string | null,
		accountPlatform: "threads" | "instagram" | null,
	) => {
		if (mediaIds.length === 0) return 0;
		applyAccountToItems(mediaIds, accountId, accountPlatform);
		const updated = await bulkAssignMediaToAccount(
			mediaIds,
			accountId,
			accountPlatform,
		);
		if (updated !== mediaIds.length) void loadMedia();
		return updated;
	};

	if (mediaLoading && mediaItems.length === 0 && accountsLoading) {
		return <ContentLibrarySkeleton />;
	}

	return (
		<NovaScreen width="full" density="compact">
			<ContentHero counts={counts} onPrimary={() => setUploadOpen(true)} />
			{!accountsLoading && accountsError ? (
				<LibraryEmpty
					title="Could not load connected accounts"
					description="Refresh the page to retry."
					action={
						<Button onClick={() => window.location.reload()}>Refresh</Button>
					}
				/>
			) : !accountsLoading && !hasAccounts ? (
				<LibraryEmpty
					title="Upload media to build a library"
					description="Connect an account first so uploads have somewhere to publish to."
					action={
						<Button onClick={() => navigate("/accounts")}>
							Connect your first account
						</Button>
					}
				/>
			) : (
				<main>
					{mediaLoading ? (
						<LibraryContentLoading label="Loading media library" />
					) : (
						<MediaView
							items={mediaItems}
							recentItems={recentMedia}
							groups={groups}
							accounts={libraryAccounts}
							onUseInComposer={handleUseMedia}
							onAssignGroup={handleAssignGroup}
							onBulkAssignGroup={handleBulkAssignGroup}
							onAssignAccount={handleAssignAccount}
							onBulkAssignAccount={handleBulkAssignAccount}
						/>
					)}
				</main>
			)}
			<MediaUploadZone
				open={uploadOpen}
				onClose={() => setUploadOpen(false)}
				onComplete={() => void loadMedia()}
				groups={groups}
				accounts={libraryAccounts}
			/>
		</NovaScreen>
	);
}

function LibraryEmpty({
	title,
	description,
	action,
}: {
	title: string;
	description: string;
	action: ReactNode;
}) {
	return (
		<NovaEmpty
			title={title}
			description={description}
			action={action}
			icon={<Grid2x2 data-icon="inline-start" aria-hidden="true" />}
		/>
	);
}

function LibraryContentLoading({ label }: { label: string }) {
	return (
		<NovaDataPanel
			title="Media library"
			description="Loading uploaded assets, assignments, and reusable media."
			contentClassName="p-5"
			role="status"
			aria-live="polite"
			aria-label={label}
		>
			<div className="mb-4 grid gap-2 sm:grid-cols-3">
				<Skeleton className="h-16 rounded-lg" />
				<Skeleton className="h-16 rounded-lg" />
				<Skeleton className="h-16 rounded-lg" />
			</div>
			<div className="mb-5 flex gap-3 overflow-hidden">
				{[0, 1, 2, 3].map((item) => (
					<div
						key={item}
						className="min-w-[160px] rounded-lg border border-border bg-muted/35 p-3"
					>
						<Skeleton className="aspect-[4/3] w-full rounded-md" />
						<Skeleton className="mt-3 h-3 w-24 rounded-full" />
						<Skeleton className="mt-2 h-2.5 w-16 rounded-full opacity-60" />
					</div>
				))}
			</div>
			<div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
				{Array.from({ length: 8 }).map((_, index) => (
					<div key={index} className="rounded-lg border border-border bg-muted/35 p-3">
						<Skeleton className="aspect-square w-full rounded-md" />
						<Skeleton className="mt-3 h-3 w-[70%] rounded-full" />
						<Skeleton className="mt-2 h-2.5 w-[46%] rounded-full opacity-60" />
					</div>
				))}
			</div>
		</NovaDataPanel>
	);
}
