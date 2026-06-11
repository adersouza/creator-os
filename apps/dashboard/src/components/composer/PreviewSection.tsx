// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import {
	Hash,
	Play,
	MessageCircle,
	Send,
	EyeOff,
	FlaskConical,
	Check,
	Clipboard,
	Download,
	Camera,
	Share2,
} from "lucide-react";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import { cn } from "@/lib/utils";

/* =========================================================================
   Preview mockups + shared Composer types.
   Renders platform-accurate post previews for Threads, IG Feed, IG Story.
   ========================================================================= */

export type PreviewMode = "threads" | "ig-feed" | "ig-story" | "ig-handoff";
export type IGPostType = "feed" | "reels" | "story";
export type ReplyControl = "anyone" | "followed" | "mentioned" | "none";

type Account = ConnectedAccount;

export interface MediaItem {
	id: string;
	kind: "image" | "video";
	name: string;
	from: string;
	to: string;
	alt: string;
	/** Public URL for uploaded media. Mock/library items leave this undefined and render via from/to gradient. */
	url?: string | undefined;
	/** True while the real upload is in flight. */
	uploading?: boolean | undefined;
}

export function avatarGradient(seed: string): {
	from: string;
	to: string;
	initial: string;
} {
	let hash = 0;
	for (let i = 0; i < seed.length; i++)
		hash = (hash * 31 + seed.charCodeAt(i)) % 10_000;
	const palette: Array<readonly [string, string]> = [
		["#F1F1EF", "#8A8D94"],
		["#E8E6E2", "#B8B5AF"],
		["#DFE1E5", "#5F6670"],
		["#E5E5E2", "#6F7078"],
		["#EEEAE4", "#9B948C"],
		["#E8E3DC", "#A67C2D"],
		["#F1E3E4", "#E5484D"],
		["#E2E3E7", "#8A8D94"],
	];
	const [from, to] = palette[hash % palette.length]!;
	return { from, to, initial: seed[0]?.toUpperCase() ?? "?" };
}

export function PreviewMock({
	mode,
	caption,
	media,
	account,
	replyControl,
	igType,
	firstComment,
	trialReel,
	pollOptions,
	spoiler,
	topicTag,
	collaborators,
}: {
	mode: PreviewMode;
	caption: string;
	media: MediaItem[];
	account: Account | null;
	replyControl: ReplyControl;
	igType: IGPostType;
	firstComment: string;
	trialReel: boolean;
	pollOptions: string[] | null;
	spoiler: boolean;
	topicTag: string;
	collaborators: string[];
}) {
	if (mode === "ig-story") {
		return (
			<IgStoryMock
				media={media[0] ?? null}
				account={account}
				caption={caption}
			/>
		);
	}
	if (mode === "ig-handoff") {
		return (
			<IgHandoffMock
				media={media[0] ?? null}
				account={account}
				caption={caption}
				igType={igType}
			/>
		);
	}
	if (mode === "ig-feed") {
		return (
			<IgFeedMock
				media={media}
				account={account}
				caption={caption}
				igType={igType}
				firstComment={firstComment}
				trialReel={trialReel}
				collaborators={collaborators}
			/>
		);
	}
	return (
		<ThreadsMock
			caption={caption}
			media={media}
			account={account}
			replyControl={replyControl}
			pollOptions={pollOptions}
			spoiler={spoiler}
			topicTag={topicTag}
		/>
	);
}

function IgHandoffMock({
	media,
	account,
	caption,
	igType,
}: {
	media: MediaItem | null;
	account: Account | null;
	caption: string;
	igType: IGPostType;
}) {
	const handle = account?.handle ?? "@your.account";
	const steps = [
		{
			label: "Copy caption",
			detail: caption
				? "Caption is ready to paste in Instagram."
				: "Add caption before handoff.",
			icon: Clipboard,
		},
		{
			label: "Share or download media",
			detail: media
				? `${media.kind === "video" ? "Video" : "Image"} prepared for phone handoff.`
				: "Attach media before scheduling.",
			icon: media ? Share2 : Download,
		},
		{
			label: "Open Instagram",
			detail: `${igType === "reels" ? "Reel" : igType === "story" ? "Story" : "Feed"} flow opens for final edits.`,
			icon: Camera,
		},
		{
			label: "Mark posted",
			detail: "Confirm after publishing so Juno33 can close the loop.",
			icon: Check,
		},
	];
	return (
		<div className="mx-auto max-w-[280px] rounded-[28px] border border-border bg-background p-2 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.75)]">
			<div className="rounded-[22px] border border-border bg-card p-3">
				<div className="flex items-center justify-between gap-3 border-b border-border pb-2">
					<div className="min-w-0">
						<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Notify Me handoff
						</div>
						<div className="mt-0.5 truncate text-[0.8125rem] font-medium text-foreground">
							{handle}
						</div>
					</div>
					<span className="rounded-full bg-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)] px-2 py-1 text-[0.625rem] font-semibold text-[color:var(--color-oxblood)]">
						{igType === "reels"
							? "Reel"
							: igType === "story"
								? "Story"
								: "Feed"}
					</span>
				</div>
				<div
					className="mt-3 aspect-[9/16] overflow-hidden rounded-xl border border-border bg-muted"
					style={
						media
							? {
									background: `linear-gradient(135deg, ${media.from}, ${media.to})`,
								}
							: { background: "linear-gradient(135deg, #202124, #5F6670)" }
					}
				>
					{media && <MediaFill item={media} fit="contain" />}
				</div>
				<div className="mt-3 flex flex-col gap-2">
					{steps.map((step, index) => {
						const Icon = step.icon;
						return (
							<div
								key={step.label}
								className="flex gap-2 rounded-lg border border-border bg-background/60 px-2.5 py-2"
							>
								<span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-foreground text-[0.625rem] font-semibold text-background">
									{index + 1}
								</span>
								<div className="min-w-0 flex-1">
									<div className="flex items-center gap-1.5 text-[0.75rem] font-semibold text-foreground">
										<Icon
											className="h-3.5 w-3.5 text-muted-foreground"
											aria-hidden="true"
										/>
										{step.label}
									</div>
									<div className="mt-0.5 text-[0.6875rem] leading-snug text-muted-foreground">
										{step.detail}
									</div>
								</div>
							</div>
						);
					})}
				</div>
			</div>
		</div>
	);
}

function ThreadsMock({
	caption,
	media,
	account,
	replyControl,
	pollOptions,
	spoiler,
	topicTag,
}: {
	caption: string;
	media: MediaItem[];
	account: Account | null;
	replyControl: ReplyControl;
	pollOptions: string[] | null;
	spoiler: boolean;
	topicTag: string;
}) {
	const hasAccount = account !== null;
	const handleWithAt = account?.handle ?? "@your.account";
	const handleBare = handleWithAt.replace(/^@/, "");
	const { from, to, initial } = avatarGradient(account?.handle ?? handleBare);
	return (
		<div className="rounded-xl border border-border bg-card p-4">
			<div className="flex items-start gap-3">
				<div
					className="w-10 h-10 rounded-full inline-flex items-center justify-center text-[0.875rem] font-semibold text-white shrink-0"
					style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}
					aria-hidden="true"
				>
					{initial}
				</div>
				<div className="flex-1 min-w-0">
					<div className="flex items-baseline gap-1.5">
						<span
							className={`text-[0.8125rem] font-semibold truncate ${hasAccount ? "text-foreground" : "text-muted-foreground italic"}`}
						>
							{handleWithAt}
						</span>
						<span className="text-[0.6875rem] text-muted-foreground">
							just now
						</span>
					</div>
					{topicTag && (
						<div
							className="mt-1 inline-flex items-center gap-1 text-[0.65625rem] font-medium uppercase tracking-[0.08em]"
							style={{ color: "var(--color-oxblood)" }}
						>
							<Hash className="w-2.5 h-2.5" aria-hidden="true" />
							{topicTag}
						</div>
					)}
					<p className="mt-1 text-[0.84375rem] leading-[1.45] text-foreground whitespace-pre-wrap">
						{caption || (
							<span className="text-muted-foreground italic">
								Your caption will appear here…
							</span>
						)}
					</p>
					{media.length > 0 && (
						<div className="mt-2 grid grid-cols-2 gap-1.5 relative">
							{media.slice(0, 4).map((m) => (
								<div
									key={m.id}
									className="aspect-[4/3] rounded-md overflow-hidden relative"
									style={{
										background: `linear-gradient(135deg, ${m.from}, ${m.to})`,
									}}
								>
									<MediaFill item={m} fit="cover" />
									{m.kind === "video" && !spoiler && (
										<div className="absolute inset-0 flex items-center justify-center">
											<div className="w-7 h-7 rounded-full bg-[color-mix(in_srgb,var(--color-foreground)_85%,transparent)] inline-flex items-center justify-center">
												<Play
													className="w-3 h-3 text-foreground fill-foreground"
													aria-hidden="true"
												/>
											</div>
										</div>
									)}
								</div>
							))}
							{spoiler && (
								<div className="absolute inset-0 rounded-md bg-[color-mix(in_srgb,var(--color-foreground)_82%,transparent)] backdrop-blur-md flex items-center justify-center">
									<div className="inline-flex items-center gap-1.5 text-white text-[0.71875rem] font-semibold">
										<EyeOff className="w-3.5 h-3.5" aria-hidden="true" />
										Spoiler — tap to reveal
									</div>
								</div>
							)}
						</div>
					)}
					{pollOptions?.some((o) => o.trim().length > 0) && (
						<div className="mt-2 flex flex-col gap-1.5">
							{pollOptions.map((opt, i) => (
								<div
									key={i}
									className="h-8 px-3 rounded-md border border-border bg-[color-mix(in_srgb,var(--color-foreground)_2%,transparent)] dark:bg-[color-mix(in_srgb,var(--color-foreground)_2%,transparent)] inline-flex items-center text-[0.78125rem] text-foreground"
								>
									{opt.trim() || (
										<span className="text-muted-foreground">
											Option {String.fromCharCode(65 + i)}
										</span>
									)}
								</div>
							))}
							<div className="text-[0.65625rem] text-muted-foreground">
								0 votes · ends in 24h
							</div>
						</div>
					)}
					<div className="mt-3 flex items-center gap-4 text-[0.6875rem] text-muted-foreground">
						<span className="inline-flex items-center gap-1">
							<MessageCircle className="w-3 h-3" aria-hidden="true" />
							{replyControl === "anyone"
								? "Anyone"
								: replyControl === "followed"
									? "Followed"
									: replyControl === "mentioned"
										? "Mentioned"
										: "No one"}
						</span>
						<span className="inline-flex items-center gap-1">
							<Hash className="w-3 h-3" aria-hidden="true" />0
						</span>
						<span className="inline-flex items-center gap-1">
							<Send className="w-3 h-3" aria-hidden="true" />0
						</span>
					</div>
				</div>
			</div>
		</div>
	);
}

function IgFeedMock({
	media,
	account,
	caption,
	igType,
	firstComment,
	trialReel,
	collaborators,
}: {
	media: MediaItem[];
	account: Account | null;
	caption: string;
	igType: IGPostType;
	firstComment: string;
	trialReel: boolean;
	collaborators: string[];
}) {
	const hasAccount = account !== null;
	const handle = (account?.handle ?? "@your.account").replace(/^@/, "");
	const { from, to, initial } = avatarGradient(account?.handle ?? handle);
	const cover = media[0];
	return (
		<div className="rounded-xl border border-border bg-card overflow-hidden">
			<div className="flex items-center gap-2.5 px-3 py-2.5 border-b border-[color-mix(in_srgb,var(--color-foreground)_5%,transparent)]">
				<div
					className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[0.6875rem] font-semibold text-white"
					style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}
					aria-hidden="true"
				>
					{initial}
				</div>
				<div className="flex-1 min-w-0">
					<div className="flex items-center gap-1.5 min-w-0">
						<span
							className={`text-[0.78125rem] font-semibold truncate ${hasAccount ? "text-foreground" : "text-muted-foreground italic"}`}
						>
							{handle}
						</span>
						{collaborators.length > 0 && (
							<span className="text-[0.6875rem] text-muted-foreground truncate">
								with {collaborators.map((c) => `@${c}`).join(", ")}
							</span>
						)}
					</div>
				</div>
				<div className="flex items-center gap-1.5 shrink-0">
					{trialReel && igType === "reels" && (
						<span
							className="inline-flex items-center gap-1 h-[18px] px-1.5 rounded-[4px] text-[0.59375rem] font-semibold uppercase tracking-[0.08em]"
							style={{
								color: "var(--color-oxblood)",
								backgroundColor:
									"color-mix(in srgb, var(--color-oxblood) 8%, transparent)",
							}}
						>
							<FlaskConical className="w-2.5 h-2.5" aria-hidden="true" />
							Trial
						</span>
					)}
					<span className="text-[0.65625rem] text-muted-foreground capitalize">
						{igType}
					</span>
				</div>
			</div>
			<div
				className={cn(
					"relative w-full overflow-hidden",
					igType === "reels" || igType === "story"
						? "aspect-[9/16]"
						: "aspect-square",
				)}
				style={
					cover
						? {
								background: `linear-gradient(135deg, ${cover.from}, ${cover.to})`,
							}
						: { background: "linear-gradient(135deg, #E8E6E2, #8A8D94)" }
				}
			>
				{cover && (
					<MediaFill
						item={cover}
						fit={igType === "feed" ? "cover" : "contain"}
					/>
				)}
				{igType === "feed" && (
					<div
						className="pointer-events-none absolute inset-[10%] rounded-[6px] border border-white/35"
						aria-hidden="true"
					/>
				)}
				{igType !== "feed" && (
					<>
						<div
							className="pointer-events-none absolute inset-x-[8%] top-[7%] bottom-[14%] rounded-[10px] border border-white/30"
							aria-hidden="true"
						/>
						<div
							className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-[linear-gradient(to_top,color-mix(in_srgb,var(--color-foreground)_52%,transparent),transparent)]"
							aria-hidden="true"
						/>
						<span className="absolute bottom-3 left-3 rounded-[4px] bg-black/35 px-1.5 py-0.5 text-[0.625rem] font-medium text-white backdrop-blur-sm">
							safe caption zone
						</span>
					</>
				)}
				{igType === "reels" && (
					<div className="absolute inset-0 flex items-center justify-center">
						<div className="w-12 h-12 rounded-full bg-[color-mix(in_srgb,var(--color-foreground)_85%,transparent)] inline-flex items-center justify-center">
							<Play
								className="w-5 h-5 text-foreground fill-foreground"
								aria-hidden="true"
							/>
						</div>
					</div>
				)}
				{media.length > 1 && (
					<span className="absolute top-2 right-2 px-1.5 py-0.5 rounded text-[0.625rem] font-semibold text-white bg-[color-mix(in_srgb,var(--color-foreground)_50%,transparent)] backdrop-blur-sm tabular-nums">
						1 / {media.length}
					</span>
				)}
			</div>
			<div className="p-3">
				<p className="text-[0.78125rem] leading-[1.45] text-foreground whitespace-pre-wrap">
					<span className="font-semibold mr-1.5">{handle}</span>
					{caption || (
						<span className="text-muted-foreground italic">
							Caption preview…
						</span>
					)}
				</p>
				{firstComment && (
					<div className="mt-2 pt-2 border-t border-[color-mix(in_srgb,var(--color-foreground)_5%,transparent)]">
						<p className="text-[0.71875rem] text-muted-foreground">
							<span className="font-semibold text-foreground mr-1.5">
								{handle}
							</span>
							<span
								className="inline-flex items-center gap-1 text-[0.625rem] uppercase tracking-[0.08em]"
								style={{ color: "var(--color-oxblood)" }}
							>
								<Check className="w-2.5 h-2.5" aria-hidden="true" />
								Pinned
							</span>
							<br />
							{firstComment}
						</p>
					</div>
				)}
			</div>
		</div>
	);
}

function IgStoryMock({
	media,
	account,
	caption,
}: {
	media: MediaItem | null;
	account: Account | null;
	caption: string;
}) {
	const hasAccount = account !== null;
	const handle = (account?.handle ?? "@your.account").replace(/^@/, "");
	const { from, to, initial } = avatarGradient(account?.handle ?? handle);
	return (
		<div className="flex justify-center">
			<div
				className="relative w-[220px] aspect-[9/16] rounded-xl overflow-hidden"
				style={
					media
						? {
								background: `linear-gradient(135deg, ${media.from}, ${media.to})`,
							}
						: { background: "linear-gradient(135deg, #1A1A1C, #2A2B2F)" }
				}
			>
				{media && <MediaFill item={media} fit="contain" />}
				<div className="absolute inset-0 bg-[linear-gradient(to_bottom,color-mix(in_srgb,var(--color-foreground)_35%,transparent),transparent_30%,transparent_70%,color-mix(in_srgb,var(--color-foreground)_35%,transparent))]" />
				<div
					className="pointer-events-none absolute inset-x-[8%] top-[9%] bottom-[15%] rounded-[10px] border border-white/30"
					aria-hidden="true"
				/>
				<div className="absolute top-0 left-0 right-0 p-2.5 flex items-center gap-2">
					<div className="h-0.5 flex-1 bg-[color-mix(in_srgb,var(--color-foreground)_40%,transparent)] rounded-full overflow-hidden">
						<div className="h-full w-1/2 bg-white rounded-full" />
					</div>
				</div>
				<div className="absolute top-5 left-2.5 right-2.5 flex items-center gap-2">
					<div
						className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[0.6875rem] font-semibold text-white"
						style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}
						aria-hidden="true"
					>
						{initial}
					</div>
					<span
						className={`text-[0.71875rem] font-semibold text-white truncate ${hasAccount ? "" : "italic opacity-75"}`}
					>
						{handle}
					</span>
					<span className="text-[0.625rem] text-white/70 ml-auto">now</span>
				</div>
				<div className="absolute bottom-8 left-3 right-3 text-center">
					<p className="text-[0.78125rem] font-semibold text-white leading-[1.35] line-clamp-3 drop-shadow-[0_1px_2px_color-mix(in_srgb,var(--color-foreground)_50%,transparent)]">
						{caption || "Your story caption…"}
					</p>
				</div>
			</div>
		</div>
	);
}

function MediaFill({
	item,
	fit,
}: {
	item: MediaItem;
	fit: "cover" | "contain";
}) {
	if (!item.url) return null;
	const className = cn(
		"absolute inset-0 h-full w-full",
		fit === "cover" ? "object-cover" : "object-contain bg-black",
	);
	if (item.kind === "video") {
		return (
			<video
				src={item.url}
				className={className}
				muted
				playsInline
				preload="metadata"
			/>
		);
	}
	return (
		<img
			src={item.url}
			alt={item.alt || ""}
			loading="lazy"
			decoding="async"
			className={className}
		/>
	);
}
