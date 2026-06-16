// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { lazy, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { appToast } from "@/lib/toast";
import {
	Plus,
	Reply,
	X,
	Sparkles,
	Users,
	ChevronDown,
	FileText,
	Layers,
	Flame,
	Send,
	Clock,
	Eye,
	ShieldCheck,
	AlertTriangle,
	CheckCircle2,
	CalendarDays,
	SlidersHorizontal,
	Image as ImageIcon,
	Film,
	Play,
	UploadCloud,
	Wand2,
	Command as CommandIcon,
	History,
	Smartphone,
	BellRing,
	RotateCcw,
	Crop,
} from "lucide-react";
import { useComposer } from "@/contexts/ComposerContext";
import {
	useConnectedAccounts,
	type ConnectedAccount,
} from "@/hooks/useConnectedAccounts";
import { useAccountGroups, type AccountGroup } from "@/hooks/useAccountGroups";
import { useComposerDrafts } from "@/hooks/useComposerDrafts";
import { useTablistKeyboardNav } from "@/hooks/useTablistKeyboardNav";
import type { LatestDraft } from "@/hooks/useLatestDraft";
import {
	useBestPostingTimes,
	formatBestHours,
} from "@/hooks/useBestPostingTimes";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { uploadMedia } from "@/services/mediaService";
import {
	validateMedia,
	type Surface,
	type ValidationMode,
} from "@/utils/mediaValidation";
import { compressImage } from "@/utils/imageCompress";
import {
	createPost,
	resumePendingPublishJobs,
	type PublishStage,
} from "@/services/api/posts";
import { haptics } from "@/utils/haptics";
import { useDirtyGuard } from "@/hooks/useDirtyGuard";
import { usePostTemplates } from "@/hooks/usePostTemplates";
import { useUndoable } from "@/hooks/useUndoable";
import { cn } from "@/lib/utils";
import { randomUUID } from "@/lib/uuid";
import {
	runComposerAction,
	generateAiText,
	type ComposerAction,
	AiNotConfiguredError,
	AiRateLimitedError,
} from "@/services/ai";
import { ChannelHealthPills } from "@/components/composer/ChannelHealthPills";
import { SelectionActionBar } from "@/components/composer/SelectionActionBar";
import { SlashMenu, type SlashCommand } from "@/components/composer/SlashMenu";
import { VariantsLab } from "@/components/composer/VariantsLab";
import { CritiquePanel } from "@/components/composer/CritiquePanel";
import { CrossPostDiffResolver } from "@/components/composer/CrossPostDiffResolver";
import {
	critiqueComposerCaption,
	createComposerDiff,
	fetchComposerDiffs,
	generateComposerVariants,
	logComposerAiAction,
	promoteComposerVariant,
	updateComposerDiff,
	type ComposerCritique,
	type PostChannelDiff,
	type ComposerVariant,
} from "@/services/api/composer";
import { CounterPill } from "@/components/composer/ComposerFormControls";
import {
	ActivityPanel,
	BulkUploadQueuePanel,
	ComposerCommandPalette,
	ComposerIntelligencePanel,
	ComposerMobileButton,
	MediaOptimizationPanel,
	PhoneSetupPanel,
	SampleDraftPanel,
} from "@/components/composer/ComposerPanels";
import {
	ThreadsOptionsPanel,
	type ThreadsOptions,
} from "@/components/composer/ThreadsOptionsPanel";
import {
	InstagramOptionsPanel,
	type InstagramOptions,
} from "@/components/composer/InstagramOptionsPanel";
import {
	PreviewMock,
	type PreviewMode,
	type IGPostType,
	type ReplyControl,
	type MediaItem,
} from "@/components/composer/PreviewSection";
import {
	ScheduleModeRadio,
	ScheduleDateTimePickers,
	QueueModeHint,
	PublishModeRadio,
} from "@/components/composer/SchedulingOptions";
import { MediaGrid } from "@/components/composer/MediaGrid";
import {
	getPermissionState,
	isCurrentlySubscribed,
	isPushSupported,
	subscribeToPush,
} from "@/services/pushSubscriptionService";
import { trackClientEvent } from "@/services/clientTelemetry";
import { supabase } from "@/services/supabase";
import { getIdeas, type InspirationIdea } from "@/services/inspirationService";
import { UnifiedPublishingReadinessCard } from "@/components/publishing/UnifiedPublishingReadinessCard";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import {
	CommandDialog,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
	CommandShortcut,
} from "@/components/ui/Command";
import {
	NovaCard,
	NovaEmpty,
	NovaHeader,
	NovaSection,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { FormSection } from "@/components/ui/FormSection";
import { Input } from "@/components/ui/Input";
import { Kbd } from "@/components/ui/Kbd";
import { MatrixLoader } from "@/components/ui/MatrixLoader";
import { Select } from "@/components/ui/Select";
import { Sheet } from "@/components/ui/Sheet";
import { Textarea } from "@/components/ui/Textarea";
import {
	AccountChip,
	AccountPickerPopover,
	DraftsPopover,
	GroupPopover,
	type GroupPreset,
} from "@/components/composer/AccountSelector";
import { PublishingStartCard } from "@/components/publishing/PublishingStartCard";
import {
	buildPublishingReadinessIssues,
	summarizeReadinessState,
} from "@/lib/publishingReadiness";
import { deriveComposerPresentation } from "@/lib/composerPresentation";
import { detectPwaInstallState } from "@/lib/pwaSetup";
import type { PwaInstallState } from "@/types/publishingReadiness";

type Account = ConnectedAccount;
type AccountPlatform = ConnectedAccount["platform"];

const VoiceContextFile = lazy(() =>
	import("@/components/composer/VoiceContextFile").then((m) => ({
		default: m.VoiceContextFile,
	})),
);
const CustomPromptModal = lazy(() =>
	import("@/components/composer/CustomPromptModal").then((m) => ({
		default: m.CustomPromptModal,
	})),
);

/* =========================================================================
   Composer — full-surface post creator, modal target via `C` shortcut.
   Exposes the Threads + Instagram Graph API options so operators can target
   accounts, tune platform-specific behavior, and schedule in one place.
   ========================================================================= */

type WhoCanReply = "everyone" | "followers" | "mentioned" | "author_only";

// Composer uses short UI-facing labels; the `posts.publish` payload expects
// the canonical whoCanReply enum (types/index.ts PostSettings). Map once here
// so we don't leak UI strings into the API and silently mismatch.
function toWhoCanReply(control: ReplyControl): WhoCanReply {
	switch (control) {
		case "anyone":
			return "everyone";
		case "followed":
			return "followers";
		case "mentioned":
			return "mentioned";
		case "none":
			return "author_only";
	}
}

const publishStageLabels: Record<PublishStage, string> = {
	queued: "Queued for publish",
	preflight: "Checking account and media",
	publishing: "Sending to platform",
	scheduling: "Saving schedule",
	processing: "Waiting on Instagram",
	published: "Confirming publish",
	retrying: "Retrying publish",
	failed: "Publish failed",
};

const composerModeLabel: Record<
	ReturnType<typeof deriveComposerPresentation>["mode"],
	string
> = {
	threads: "Threads",
	"instagram-feed": "Instagram Feed",
	"instagram-reel": "Instagram Reel",
	"instagram-story": "Instagram Story",
	mixed: "Mixed",
	"notify-handoff": "Notify Me",
};

function getErrorRequestId(error: unknown): string | null {
	if (
		typeof error === "object" &&
		error !== null &&
		"requestId" in error &&
		typeof error.requestId === "string"
	) {
		return error.requestId;
	}
	return null;
}

function joinToastDetails(
	message: string | undefined,
	requestId: string | null,
): string | undefined {
	if (message && requestId) return `${message} Request ID: ${requestId}`;
	if (requestId) return `Request ID: ${requestId}`;
	return message;
}

type PersonaVoice = "default" | "aurora" | "meridian" | "harbor" | "vale";

interface ComposerTextHandoff {
	id: string;
	content: string;
	platform: "threads" | "instagram";
	label: string;
}

interface Draft {
	id: string;
	updatedAt: number;
	caption: string;
	targetIds: string[];
	media: MediaItem[];
	persona: PersonaVoice;
	isHero: boolean;
	preview: PreviewMode;
	replyControl: ReplyControl;
	threadChain: boolean;
	quoteUrl: string;
	tLocation: string;
	linkAttach: string;
	textSpoilerTerms: string;
	gifId: string;
	gifProvider: "GIPHY" | "TENOR";
	textAttachment: string;
	textAttachmentUrl: string;
	textAttachmentStyles: string;
	topicTag: string;
	geoGate: string;
	replyApprovalMode: "none" | "manual_approval";
	pollEnabled: boolean;
	pollOptions: string[];
	spoiler: boolean;
	ghostPost: boolean;
	ghostDuration: "24h" | "48h" | "7d";
	igType: IGPostType;
	firstComment: string;
	igLocation: string;
	collaborators: string[];
	crossFb: boolean;
	crossIgDarkMode: boolean;
	reelCover: number;
	coverUrl: string;
	audioName: string;
	igAudioId: string;
	igAudioTitle: string;
	igAudioArtist: string;
	igAudioType: "music" | "original_sound";
	trialReel: boolean;
	graduation: "MANUAL" | "SS_PERFORMANCE";
	shareToFeed: boolean;
	commentEnabled: boolean;
	userTags: string;
	productTags: string;
	isPaidPartnership: boolean;
	brandedContentSponsorIds: string;
	replyToId: string | null;
}

type ReadinessTone = "ready" | "warning" | "blocked";

interface ReadinessCheck {
	id: string;
	label: string;
	detail: string;
	tone: ReadinessTone;
	action?: (() => void) | undefined;
	actionLabel?: string | undefined;
}

interface BulkUploadQueueItem {
	id: string;
	file: File;
	previewUrl: string;
	name: string;
	kind: "image" | "video";
	caption: string;
	selected: boolean;
	postType: IGPostType;
	publishMode: "auto" | "notify";
	scheduleDate: string;
	scheduleTime: string;
	status: "queued" | "uploading" | "ready" | "saving" | "done" | "error";
	mediaUrl?: string | undefined;
	error?: string | undefined;
	warnings: string[];
}

interface ComposerActivity {
	id: string;
	label: string;
	detail: string;
	at: number;
	undo?: (() => void) | undefined;
}

interface PostHealth {
	score: number;
	label: string;
	tone: "ready" | "warning" | "blocked";
	issues: string[];
}

interface MediaOptimizationSuggestion {
	id: string;
	label: string;
	detail: string;
	actionLabel?: string | undefined;
	action?: (() => void) | undefined;
}

type PhoneSetupChecks = {
	openedOnPhone: boolean;
	homeScreen: boolean;
	instagramReady: boolean;
};

type PushHealthState =
	| "checking"
	| "unsupported"
	| "denied"
	| "permission-needed"
	| "not-subscribed"
	| "subscribed"
	| "unavailable";

interface ComposerMediaHandoff {
	id: string;
	name: string;
	type: "photo" | "video" | "reel";
	platforms: Array<"threads" | "instagram">;
	url?: string | undefined;
}

interface ComposerIdeaHandoff {
	id: string;
	content: string;
	accountId: string | null;
	groupId: string | null;
	linkUrl: string | null;
	imageUrl: string | null;
	imageName: string | null;
	label: string;
}

function localDateLabel(value: string): string {
	const date = /^\d{4}-\d{2}-\d{2}$/.test(value)
		? new Date(`${value}T00:00:00`)
		: new Date(value);
	if (Number.isNaN(date.getTime())) return "Slot";
	return date.toLocaleDateString(undefined, {
		weekday: "short",
		month: "short",
		day: "numeric",
	});
}

function isVerticalReelAspect(aspect: number | undefined): boolean {
	return typeof aspect === "number" && Math.abs(aspect - 9 / 16) < 0.04;
}

function labelForIgType(type: IGPostType): string {
	if (type === "reels") return "Reel";
	if (type === "story") return "Story";
	return "Feed";
}

function formatPushHealth(state: PushHealthState): {
	label: string;
	detail: string;
	tone: ReadinessTone;
} {
	switch (state) {
		case "subscribed":
			return {
				label: "Push notifications ready",
				detail: "This device can receive Notify Me reminders.",
				tone: "ready",
			};
		case "permission-needed":
			return {
				label: "Enable push notifications",
				detail:
					"Notify Me can schedule, but reminders need browser permission.",
				tone: "warning",
			};
		case "not-subscribed":
			return {
				label: "Subscribe this device",
				detail:
					"Permission is granted, but this browser is not subscribed yet.",
				tone: "warning",
			};
		case "denied":
			return {
				label: "Notifications blocked",
				detail:
					"Enable notifications in browser settings or use the in-app handoff fallback.",
				tone: "warning",
			};
		case "unsupported":
			return {
				label: "Push unsupported here",
				detail:
					"This browser cannot receive push reminders. Juno33 will still create the handoff.",
				tone: "warning",
			};
		case "unavailable":
			return {
				label: "Push status unavailable",
				detail: "Could not verify this browser subscription.",
				tone: "warning",
			};
		default:
			return {
				label: "Checking notifications",
				detail: "Juno33 is checking this browser before Notify Me scheduling.",
				tone: "warning",
			};
	}
}

function pushSetupState(state: PushHealthState): string {
	if (state === "subscribed") return "subscribed";
	if (state === "permission-needed") return "permission_needed";
	if (state === "not-subscribed") return "not_subscribed";
	if (state === "denied") return "denied";
	if (state === "unsupported") return "unsupported";
	return "unknown";
}

function postHealthLabel(score: number): PostHealth["label"] {
	if (score >= 90) return "Excellent";
	if (score >= 75) return "Ready";
	if (score >= 55) return "Needs review";
	return "Blocked";
}

function postHealthTone(score: number, blocked: number): PostHealth["tone"] {
	if (blocked > 0 || score < 55) return "blocked";
	if (score < 80) return "warning";
	return "ready";
}

function buildPostHealth({
	checks,
	media,
	caption,
	isInstagramNativeHandoff,
	pushHealth,
	preflightIssues,
}: {
	checks: ReadinessCheck[];
	media: MediaItem[];
	caption: string;
	isInstagramNativeHandoff: boolean;
	pushHealth: PushHealthState;
	preflightIssues: string[];
}): PostHealth {
	const blocked = checks.filter((check) => check.tone === "blocked").length;
	const warnings = checks.filter((check) => check.tone === "warning").length;
	let score = 100 - blocked * 22 - warnings * 8;
	if (caption.trim().length < 20) score -= 8;
	if (media.length === 0) score -= 10;
	if (media.some((item) => item.kind === "image" && !item.alt.trim()))
		score -= 6;
	if (isInstagramNativeHandoff && pushHealth !== "subscribed") score -= 6;
	if (preflightIssues.length > 0) score -= 12;
	score = Math.max(0, Math.min(100, Math.round(score)));

	const issues = [
		...checks
			.filter((check) => check.tone !== "ready")
			.map((check) => check.label),
		...(media.some((item) => item.kind === "image" && !item.alt.trim())
			? ["Add image alt text"]
			: []),
		...(caption.trim().length < 20 ? ["Strengthen the caption"] : []),
	].slice(0, 5);

	return {
		score,
		label: postHealthLabel(score),
		tone: postHealthTone(score, blocked),
		issues,
	};
}

function canOptimizeImage(file: File): boolean {
	return file.type.startsWith("image/") && file.size > 1_500_000;
}

function ComposerVisualPlanner({
	media,
	drafts,
	target,
	scheduleDate,
	scheduleTime,
	scheduleMode,
	onOpenMedia,
	onLoadDraft,
}: {
	media: MediaItem[];
	drafts: Draft[];
	target: Account | null;
	scheduleDate: string;
	scheduleTime: string;
	scheduleMode: "now" | "schedule" | "queue";
	onOpenMedia: () => void;
	onLoadDraft: (id: string) => void;
}) {
	const readyDrafts = drafts.slice(0, 3);
	const plannedSlots = Array.from({ length: 9 }).map((_, index) => {
		const attachment = media[index];
		const draft = readyDrafts[index - 3];
		const isScheduledSlot = index === 0 && scheduleMode !== "now";
		const isTargetSlot = index === 1 && target;
		return {
			id: `planner-${index}`,
			attachment,
			draft,
			isScheduledSlot,
			isTargetSlot,
			label: isScheduledSlot
				? scheduleMode === "queue"
					? "Queue"
					: `${localDateLabel(scheduleDate)} ${scheduleTime}`
				: isTargetSlot
					? target.handle
					: attachment
						? attachment.kind === "video"
							? "Video"
							: "Image"
						: draft
							? "Draft"
							: "+ slot",
		};
	});

	return (
		<NovaCard contentClassName="p-4">
			<div className="mb-3 flex items-start justify-between gap-3">
				<div>
					<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
						Visual planner
					</div>
					<div className="mt-1 text-[0.75rem] leading-snug text-muted-foreground">
						Preview the next grid before this draft ships.
					</div>
				</div>
				<Button
					type="button"
					onClick={onOpenMedia}
					variant="outline"
					size="sm"
					className="shrink-0"
				>
					Add media
				</Button>
			</div>

			<div className="grid grid-cols-3 gap-2">
				{plannedSlots.map((tile) => (
					<Button
						key={tile.id}
						type="button"
						variant="ghost"
						onClick={() => {
							if (tile.draft) onLoadDraft(tile.draft.id);
							else if (!tile.attachment) onOpenMedia();
						}}
						className={cn(
							"group relative h-auto aspect-square overflow-hidden rounded-lg border p-0 text-left",
							tile.attachment
								? "border-border bg-muted"
								: tile.isScheduledSlot || tile.isTargetSlot
									? "border-[color-mix(in_srgb,var(--color-oxblood)_24%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_7%,transparent)]"
									: tile.draft
										? "border-border bg-card"
										: "border-dashed border-border bg-background/35 hover:bg-muted/50",
						)}
					>
						{tile.attachment ? (
							<>
								{tile.attachment.url ? (
									<img
										src={tile.attachment.url}
										alt={tile.attachment.alt || tile.attachment.name}
										className="h-full w-full object-cover"
									/>
								) : (
									<div
										className="h-full w-full"
										style={{
											background: `linear-gradient(135deg, ${tile.attachment.from}, ${tile.attachment.to})`,
										}}
									/>
								)}
								<span className="absolute left-2 top-2 rounded bg-black/50 px-1.5 py-0.5 text-[0.625rem] font-bold uppercase tracking-[0.08em] text-white">
									{tile.attachment.kind}
								</span>
							</>
						) : (
							<div className="flex h-full flex-col justify-between p-2.5">
								<span
									className={cn(
										"text-[0.625rem] font-bold uppercase tracking-[0.12em]",
										tile.isScheduledSlot || tile.isTargetSlot
											? "text-[var(--color-oxblood)]"
											: "text-muted-foreground",
									)}
								>
									{tile.label}
								</span>
								{tile.draft ? (
									<span className="line-clamp-3 text-[0.6875rem] leading-snug text-muted-foreground">
										{tile.draft.caption || "Empty draft"}
									</span>
								) : (
									<span className="text-[0.6875rem] text-muted-foreground">
										{tile.isScheduledSlot
											? "Current draft"
											: tile.isTargetSlot
												? "Primary account"
												: "Open slot"}
									</span>
								)}
							</div>
						)}
					</Button>
				))}
			</div>

			<div className="mt-3 rounded-lg border border-border bg-background/35 p-3">
				<div className="mb-2 flex items-center gap-1.5 text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
					<CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
					Ready drafts
				</div>
				<div className="flex flex-col gap-1.5">
					{readyDrafts.length === 0 ? (
						<div className="text-[0.75rem] text-muted-foreground">
							Save drafts here, then stage them into open slots.
						</div>
					) : (
						readyDrafts.map((draft) => (
							<Button
								key={draft.id}
								type="button"
								variant="ghost"
								onClick={() => onLoadDraft(draft.id)}
								className="h-auto w-full justify-between gap-3 px-2 py-1.5 text-left text-[0.75rem]"
							>
								<span className="min-w-0 truncate text-muted-foreground">
									{draft.caption || "Empty draft"}
								</span>
								<span className="shrink-0 font-mono text-[0.625rem] text-muted-foreground">
									{new Date(draft.updatedAt).toLocaleDateString(undefined, {
										month: "short",
										day: "numeric",
									})}
								</span>
							</Button>
						))
					)}
				</div>
			</div>
		</NovaCard>
	);
}

const THREADS_LIMIT = 500;
const IG_LIMIT = 2200;

function utf8ByteLength(value: string): number {
	return new TextEncoder().encode(value).length;
}

const PERSONA_LABEL: Record<PersonaVoice, string> = {
	default: "Default voice",
	aurora: "Aurora — essayist, measured",
	meridian: "Meridian — sensory, playful",
	harbor: "Harbor — matter-of-fact, dry",
	vale: "Vale — editorial, moody",
};

function parseCsvTokens(value: string): string[] {
	return value
		.split(",")
		.map((token) => token.trim())
		.filter(Boolean);
}

function parseCountryCodes(value: string): string[] | undefined {
	const codes = parseCsvTokens(value)
		.map((code) => code.toUpperCase())
		.filter((code) => /^[A-Z]{2}$/.test(code));
	return codes.length > 0 ? codes : undefined;
}

function parseInstagramUserTags(
	value: string,
): Array<{ username: string; x: number; y: number }> | undefined {
	const tags = parseCsvTokens(value)
		.map((token) => {
			const [rawUsername, rawCoords] = token.split("@");
			const username = rawUsername!.replace(/^@/, "").trim();
			const [xRaw, yRaw] = (rawCoords ?? "").split(":");
			const x = Number.parseFloat(xRaw ?? "");
			const y = Number.parseFloat(yRaw ?? "");
			return {
				username,
				x: Number.isFinite(x) ? Math.min(1, Math.max(0, x)) : 0.5,
				y: Number.isFinite(y) ? Math.min(1, Math.max(0, y)) : 0.5,
			};
		})
		.filter((tag) => tag.username);
	return tags.length > 0 ? tags : undefined;
}

function parseInstagramProductTags(value: string):
	| Array<{
			product_id: string;
			x?: number | undefined;
			y?: number | undefined;
	  }>
	| undefined {
	const tags = parseCsvTokens(value)
		.map((token) => {
			const [product_id, rawCoords] = token.split("@");
			if (!product_id) return null;
			const [xRaw, yRaw] = (rawCoords ?? "").split(":");
			const x = Number.parseFloat(xRaw ?? "");
			const y = Number.parseFloat(yRaw ?? "");
			return {
				product_id,
				...(Number.isFinite(x) ? { x: Math.min(1, Math.max(0, x)) } : {}),
				...(Number.isFinite(y) ? { y: Math.min(1, Math.max(0, y)) } : {}),
			};
		})
		.filter((tag): tag is NonNullable<typeof tag> => tag != null);
	return tags.length > 0 ? tags : undefined;
}

function buildTextSpoilers(caption: string, terms: string) {
	const lower = caption.toLowerCase();
	return parseCsvTokens(terms)
		.map((term) => {
			const offset = lower.indexOf(term.toLowerCase());
			if (offset < 0) return null;
			return { entity_type: "SPOILER" as const, offset, length: term.length };
		})
		.filter(
			(
				entity,
			): entity is { entity_type: "SPOILER"; offset: number; length: number } =>
				Boolean(entity),
		);
}

type TextStyle =
	| "bold"
	| "italic"
	| "highlight"
	| "underline"
	| "strikethrough";

const TEXT_STYLE_SET = new Set<TextStyle>([
	"bold",
	"italic",
	"highlight",
	"underline",
	"strikethrough",
]);

function buildTextAttachmentStyles(plaintext: string, value: string) {
	const lower = plaintext.toLowerCase();
	return parseCsvTokens(value)
		.map((token) => {
			const [phraseRaw, stylesRaw] = token.split(":");
			const phrase = phraseRaw?.trim();
			const styles = (stylesRaw ?? "")
				.split("+")
				.map((style) => style.trim().toLowerCase())
				.filter((style): style is TextStyle =>
					TEXT_STYLE_SET.has(style as TextStyle),
				);
			if (!phrase || styles.length === 0) return null;
			const offset = lower.indexOf(phrase.toLowerCase());
			if (offset < 0) return null;
			return { offset, length: phrase.length, styling_info: styles };
		})
		.filter(
			(
				entity,
			): entity is {
				offset: number;
				length: number;
				styling_info: TextStyle[];
			} => Boolean(entity),
		);
}

function hasUnsupportedExtension(item: MediaItem, extensions: string[]) {
	const target = item.url || item.name;
	return extensions.some((extension) =>
		new RegExp(`\\.${extension}(\\?|$)`, "i").test(target),
	);
}

function collectComposerIssues({
	targets,
	media,
	igType,
	trialReel,
	brandedContentSponsorIds,
	collaborators,
	pollEnabled,
	pollOptions,
	linkAttach,
	gifId,
	textAttachment,
	textAttachmentStyles,
	textSpoilerTerms,
	caption,
	allowInstagramNativeHandoff = false,
}: {
	targets: ConnectedAccount[];
	media: MediaItem[];
	igType: IGPostType;
	trialReel: boolean;
	brandedContentSponsorIds: string;
	collaborators: string[];
	pollEnabled: boolean;
	pollOptions: string[];
	linkAttach: string;
	gifId: string;
	textAttachment: string;
	textAttachmentStyles: string;
	textSpoilerTerms: string;
	caption: string;
	allowInstagramNativeHandoff?: boolean;
}) {
	const issues: string[] = [];
	const hasInstagram = targets.some(
		(target) => target.platform === "instagram",
	);
	const hasThreads = targets.some((target) => target.platform === "threads");
	const hasVideo = media.some((item) => item.kind === "video");
	const hasImage = media.some((item) => item.kind === "image");

	if (media.some((item) => item.uploading)) {
		issues.push("Wait for all media uploads to finish before publishing.");
	}
	if (hasInstagram && media.length === 0) {
		issues.push("Instagram publishing requires at least one media item.");
	}
	if (hasInstagram && igType === "reels" && (media.length !== 1 || !hasVideo)) {
		issues.push("Instagram Reels require exactly one video.");
	}
	if (
		hasInstagram &&
		igType === "reels" &&
		trialReel &&
		collaborators.length > 0
	) {
		issues.push("Instagram Trial Reels cannot include collaborators.");
	}
	if (hasInstagram && parseCsvTokens(brandedContentSponsorIds).length > 2) {
		issues.push("Instagram paid partnership supports up to 2 brand partners.");
	}
	if (hasInstagram && igType === "story" && media.length !== 1) {
		issues.push("Instagram Stories require exactly one image or video.");
	}
	if (hasInstagram && igType === "feed" && media.length > 10) {
		issues.push("Instagram carousels support a maximum of 10 media items.");
	}
	if (
		hasInstagram &&
		!allowInstagramNativeHandoff &&
		hasImage &&
		media.some(
			(item) =>
				item.kind === "image" && hasUnsupportedExtension(item, ["gif", "webp"]),
		)
	) {
		issues.push(
			"Instagram image publishing supports JPEG/PNG URLs; GIF/WebP images need conversion first.",
		);
	}
	if (
		hasInstagram &&
		!allowInstagramNativeHandoff &&
		hasVideo &&
		media.some(
			(item) =>
				item.kind === "video" &&
				hasUnsupportedExtension(item, [
					"webm",
					"avi",
					"mkv",
					"wmv",
					"flv",
					"m4v",
					"ogv",
				]),
		)
	) {
		issues.push(
			"Instagram video publishing requires MP4/MOV-compatible video URLs.",
		);
	}
	if (hasThreads && utf8ByteLength(caption) > THREADS_LIMIT) {
		issues.push("Threads posts support a maximum of 500 UTF-8 bytes.");
	}
	if (hasInstagram && caption.length > IG_LIMIT) {
		issues.push("Instagram captions support a maximum of 2,200 characters.");
	}
	if (hasThreads && media.length > 20) {
		issues.push("Threads carousels support a maximum of 20 media items.");
	}
	if (
		hasThreads &&
		hasImage &&
		media.some(
			(item) =>
				item.kind === "image" && hasUnsupportedExtension(item, ["gif", "webp"]),
		)
	) {
		issues.push(
			"Threads image publishing supports JPEG/PNG URLs; GIF/WebP images need conversion or a GIF attachment.",
		);
	}
	if (
		hasThreads &&
		hasVideo &&
		media.some(
			(item) =>
				item.kind === "video" &&
				hasUnsupportedExtension(item, [
					"webm",
					"avi",
					"mkv",
					"wmv",
					"flv",
					"m4v",
					"ogv",
				]),
		)
	) {
		issues.push(
			"Threads video publishing requires MP4/MOV-compatible video URLs.",
		);
	}
	if (
		hasThreads &&
		pollEnabled &&
		pollOptions.filter((option) => option.trim()).length < 2
	) {
		issues.push("Threads polls need at least two options.");
	}
	if (
		hasThreads &&
		pollEnabled &&
		(linkAttach.trim() || gifId.trim() || textAttachment.trim())
	) {
		issues.push(
			"Threads polls cannot be combined with link, GIF, or text attachments.",
		);
	}
	if (hasThreads && linkAttach.trim() && media.length > 0) {
		issues.push("Threads link attachments only work on text-only posts.");
	}
	if (hasThreads && gifId.trim() && media.length > 0) {
		issues.push("Threads GIF attachments only work on text-only posts.");
	}
	if (hasThreads && textAttachment.trim() && media.length > 0) {
		issues.push("Threads text attachments only work on text-only posts.");
	}
	if (
		textSpoilerTerms.trim() &&
		buildTextSpoilers(caption, textSpoilerTerms).length === 0
	) {
		issues.push(
			"Text spoiler phrases must match text that exists in the caption.",
		);
	}
	if (textAttachmentStyles.trim() && !textAttachment.trim()) {
		issues.push("Attachment styling needs text attachment content.");
	}
	if (
		textAttachmentStyles.trim() &&
		buildTextAttachmentStyles(textAttachment, textAttachmentStyles).length === 0
	) {
		issues.push(
			"Attachment styling phrases must match text in the text attachment.",
		);
	}
	if (
		(hasInstagram || hasThreads) &&
		hasImage &&
		media.some((item) => item.kind === "image" && !item.alt.trim())
	) {
		issues.push("Add alt text to every image before publishing.");
	}

	return issues;
}

function groupsToPresets(groups: AccountGroup[]): GroupPreset[] {
	return groups.map((g) => ({
		id: g.id,
		label: g.name,
		description:
			g.accountIds.length === 0
				? "No accounts yet"
				: `${g.accountIds.length} ${g.accountIds.length === 1 ? "account" : "accounts"}`,
		color: g.color,
		accountIds: g.accountIds,
	}));
}

/* =========================================================================
   MAIN COMPONENT
   ========================================================================= */
export function Composer() {
	const location = useLocation();
	const [searchParams] = useSearchParams();
	const composer = useComposer();
	const { accounts: connectedAccounts } = useConnectedAccounts();
	const { groups: accountGroups, createGroup } = useAccountGroups();
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);

	const accountsById = useMemo(() => {
		const map = new Map<string, Account>();
		for (const a of connectedAccounts) map.set(a.id, a);
		return map;
	}, [connectedAccounts]);

	const groupPresets = useMemo(
		() => groupsToPresets(accountGroups),
		[accountGroups],
	);

	const [targetIds, setTargetIds] = useState<string[]>([]);
	const [activeGroup, setActiveGroup] = useState<string | null>(null);

	// Best-times heuristic: scope = single target when one selected, otherwise fleet-wide.
	// Derived from published post engagement × hour-of-day (cached 30 min in bestTimesCache).
	const bestTimesScope = targetIds.length === 1 ? targetIds[0] : null;
	const bestTimes = useBestPostingTimes(bestTimesScope!);
	const bestTimesLabel =
		bestTimes.hasEnoughData && bestTimes.topHours.length > 0
			? formatBestHours(bestTimes.topHours)
			: null;

	const [caption, setCaption] = useState("");
	const captionRef = useRef<HTMLTextAreaElement>(null);
	const [media, setMedia] = useState<MediaItem[]>([]);
	const [editingAltId, setEditingAltId] = useState<string | null>(null);
	const [altDraft, setAltDraft] = useState("");
	const [persona, setPersona] = useState<PersonaVoice>("default");
	const [isHero, setIsHero] = useState(false);
	const [preview, setPreview] = useState<PreviewMode>("threads");
	const [libraryMedia, setLibraryMedia] = useState<ComposerMediaHandoff | null>(
		null,
	);

	// Threads options
	const [replyControl, setReplyControl] = useState<ReplyControl>("anyone");
	const [threadChain, setThreadChain] = useState(false);
	const [quoteUrl, setQuoteUrl] = useState("");
	const [tLocation, setTLocation] = useState("");
	const [linkAttach, setLinkAttach] = useState("");
	const [textSpoilerTerms, setTextSpoilerTerms] = useState("");
	const [gifId, setGifId] = useState("");
	const [gifProvider, setGifProvider] = useState<"GIPHY" | "TENOR">("GIPHY");
	const [textAttachment, setTextAttachment] = useState("");
	const [textAttachmentUrl, setTextAttachmentUrl] = useState("");
	const [textAttachmentStyles, setTextAttachmentStyles] = useState("");
	const [topicTag, setTopicTag] = useState("");
	const [geoGate, setGeoGate] = useState("");
	const [replyApprovalMode, setReplyApprovalMode] = useState<
		"none" | "manual_approval"
	>("none");
	const [pollEnabled, setPollEnabled] = useState(false);
	const [pollOptions, setPollOptions] = useState<string[]>(["", ""]);
	const [spoiler, setSpoiler] = useState(false);
	const [ghostPost, setGhostPost] = useState(false);
	const [ghostDuration, setGhostDuration] = useState<"24h" | "48h" | "7d">(
		"24h",
	);

	// Instagram options
	const [igType, setIgType] = useState<IGPostType>("feed");
	const [firstComment, setFirstComment] = useState("");
	const [igLocation, setIgLocation] = useState("");
	const [collaborators, setCollaborators] = useState<string[]>([]);
	const [collaboratorDraft, setCollaboratorDraft] = useState("");
	const [crossFb, setCrossFb] = useState(false);
	const [crossIgDarkMode, setCrossIgDarkMode] = useState(false);
	const [reelCover, setReelCover] = useState(3);
	const [coverUrl, setCoverUrl] = useState("");
	const [audioName, setAudioName] = useState("");
	const [igAudioId, setIgAudioId] = useState("");
	const [igAudioTitle, setIgAudioTitle] = useState("");
	const [igAudioArtist, setIgAudioArtist] = useState("");
	const [igAudioType, setIgAudioType] = useState<"music" | "original_sound">(
		"music",
	);
	const [trialReel, setTrialReel] = useState(false);
	const [graduation, setGraduation] = useState<"MANUAL" | "SS_PERFORMANCE">(
		"SS_PERFORMANCE",
	);
	const [shareToFeed, setShareToFeed] = useState(true);
	const [commentEnabled, setCommentEnabled] = useState(true);
	const [userTags, setUserTags] = useState("");
	const [productTags, setProductTags] = useState("");
	const [isPaidPartnership, setIsPaidPartnership] = useState(false);
	const [brandedContentSponsorIds, setBrandedContentSponsorIds] = useState("");
	const [replyToId, setReplyToId] = useState<string | null>(null);

	const [scheduleMode, setScheduleMode] = useState<
		"now" | "schedule" | "queue"
	>("now");
	const [publishMode, setPublishMode] = useState<"auto" | "notify">("auto");
	const [scheduleDate, setScheduleDate] = useState(() => {
		const d = new Date();
		d.setDate(d.getDate() + 1);
		// Local YYYY-MM-DD — toISOString() would shift evening local times into tomorrow-UTC.
		const yyyy = d.getFullYear();
		const mm = String(d.getMonth() + 1).padStart(2, "0");
		const dd = String(d.getDate()).padStart(2, "0");
		return `${yyyy}-${mm}-${dd}`;
	});
	const [scheduleTime, setScheduleTime] = useState("09:00");
	const [bulkQueue, setBulkQueue] = useState<BulkUploadQueueItem[]>([]);
	const bulkQueueRef = useRef<BulkUploadQueueItem[]>([]);
	const [pushHealth, setPushHealth] = useState<PushHealthState>("checking");
	const [pushHealthBusy, setPushHealthBusy] = useState(false);
	const [pwaState, setPwaState] = useState<PwaInstallState>("desktop");
	const [trendIdeas, setTrendIdeas] = useState<InspirationIdea[]>([]);
	const [trendIdeasLoading, setTrendIdeasLoading] = useState(false);
	const [isSavingDraft, setIsSavingDraft] = useState(false);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [publishStage, setPublishStage] = useState<PublishStage | null>(null);
	const [commandOpen, setCommandOpen] = useState(false);
	const [activityOpen, setActivityOpen] = useState(false);
	const [activity, setActivity] = useState<ComposerActivity[]>([]);
	const [phoneChecks, setPhoneChecks] = useState({
		openedOnPhone: false,
		homeScreen: false,
		instagramReady: false,
	});

	useEffect(() => {
		setPwaState(detectPwaInstallState());
	}, []);

	const [pickerOpen, setPickerOpen] = useState(false);
	const [groupOpen, setGroupOpen] = useState(false);
	const [threadsOpen, setThreadsOpen] = useState(true);
	const [igOpen, setIgOpen] = useState(true);
	const [advancedOpen, setAdvancedOpen] = useState(false);
	const { undo } = useUndoable();

	const recordActivity = (
		label: string,
		detail: string,
		revert?: (() => void) | undefined,
	) => {
		const entry: ComposerActivity = {
			id: `act_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
			label,
			detail,
			at: Date.now(),
			undo: revert,
		};
		setActivity((current) => [entry, ...current].slice(0, 20));
		if (revert) {
			undo({ label, description: detail, revert });
		}
	};

	// Drafts — Supabase-backed (posts.status='draft' via useComposerDrafts) with
	// localStorage mirror, so they roam across devices and survive offline edits.
	const {
		drafts: remoteDrafts,
		saveDraft: persistDraftRemote,
		deleteDraft: deleteDraftRemote,
		restoreDraft: restoreDraftRemote,
	} = useComposerDrafts();
	const {
		forCategory: templatesForCategory,
		createTemplate: createContentKit,
		markUsed: markContentKitUsed,
	} = usePostTemplates();
	const drafts = remoteDrafts as unknown as Draft[];
	const contentKits = templatesForCategory("template").slice(0, 5);
	const captionKits = templatesForCategory("caption").slice(0, 5);
	const [currentDraftId, setCurrentDraftId] = useState<string | null>(null);
	const [draftsOpen, setDraftsOpen] = useState(false);

	// Mobile-only sheets
	const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false);
	const [mobileScheduleOpen, setMobileScheduleOpen] = useState(false);
	const [mobileReadinessOpen, setMobileReadinessOpen] = useState(false);
	const latestDraftSeedRef = useRef<string | null>(null);
	const libraryTextSeedRef = useRef<string | null>(null);
	const ideaHandoffSeedRef = useRef<string | null>(null);
	const querySeedRef = useRef<string | null>(null);
	const scopedTargetSeedRef = useRef<string | null>(null);
	const manualTargetScopeIdRef = useRef<string | null>(null);

	useEffect(() => {
		captionRef.current?.focus();
		trackClientEvent("composer_opened", { surface: "composer" });
	}, []);

	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (
				!(event.metaKey || event.ctrlKey) ||
				event.key.toLowerCase() !== "j"
			) {
				return;
			}
			event.preventDefault();
			setCommandOpen((open) => !open);
		};
		window.addEventListener("keydown", onKey);
		const onCommand = () => setCommandOpen(true);
		window.addEventListener("juno33:composer-command", onCommand);
		return () => {
			window.removeEventListener("keydown", onKey);
			window.removeEventListener("juno33:composer-command", onCommand);
		};
	}, []);

	useEffect(() => {
		let cancelled = false;
		const check = async () => {
			if (!isPushSupported()) {
				if (!cancelled) setPushHealth("unsupported");
				return;
			}
			const permission = getPermissionState();
			if (permission === "denied") {
				if (!cancelled) setPushHealth("denied");
				return;
			}
			if (permission === "default") {
				if (!cancelled) setPushHealth("permission-needed");
				return;
			}
			try {
				const subscribed = await isCurrentlySubscribed();
				if (!cancelled)
					setPushHealth(subscribed ? "subscribed" : "not-subscribed");
			} catch {
				if (!cancelled) setPushHealth("unavailable");
			}
		};
		void check();
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		if (pushHealth === "checking") return;
		trackClientEvent("composer_notify_push_state", {
			state: pushHealth,
			supported: isPushSupported(),
		});
	}, [pushHealth]);

	useEffect(() => {
		let cancelled = false;
		setTrendIdeasLoading(true);
		void getIdeas({ limit: 6, sortBy: "viral_score", sortOrder: "desc" })
			.then((ideas) => {
				if (!cancelled) setTrendIdeas(ideas.slice(0, 6));
			})
			.finally(() => {
				if (!cancelled) setTrendIdeasLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		let cancelled = false;
		void resumePendingPublishJobs((stage) => {
			if (!cancelled) setPublishStage(stage);
		}).then((results) => {
			if (cancelled || results.length === 0) return;
			setPublishStage(null);
			const failures = results.filter((result) => result.status === "rejected");
			const successes = results.length - failures.length;
			if (successes > 0 && failures.length === 0) {
				appToast.success(
					successes === 1
						? "Recovered publish completed"
						: `Recovered ${successes} completed publishes`,
				);
			} else if (successes > 0) {
				appToast.warn(
					`Recovered ${successes} publishes — ${failures.length} failed`,
				);
			} else {
				const first = failures[0];
				const reason = first?.status === "rejected" ? first.reason : null;
				appToast.error("Recovered publish failed", {
					description:
						reason instanceof Error
							? joinToastDetails(reason.message, getErrorRequestId(reason))
							: undefined,
				});
			}
		});
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				setSelectionBar(null);
				return;
			}
			if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k")
				return;
			const el = captionRef.current;
			if (!el || document.activeElement !== el) return;
			const start = el.selectionStart ?? 0;
			const end = el.selectionEnd ?? 0;
			if (end <= start) return;
			event.preventDefault();
			event.stopImmediatePropagation();
			const rect = el.getBoundingClientRect();
			setSelectionBar({
				start,
				end,
				x: rect.left + 24,
				y: Math.max(72, rect.top - 44),
			});
		};
		window.addEventListener("keydown", onKey, { capture: true });
		return () =>
			window.removeEventListener("keydown", onKey, { capture: true });
	}, []);

	useEffect(() => {
		const el = captionRef.current;
		if (!el) return;
		el.style.height = "auto";
		el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
	}, []);

	useEffect(() => {
		const stateMedia = (
			location.state as {
				libraryMedia?: ComposerMediaHandoff | undefined;
				latestDraft?: LatestDraft | undefined;
			} | null
		)?.libraryMedia;
		const storedMedia = window.sessionStorage.getItem("juno33:composer-media");
		let parsedStoredMedia: ComposerMediaHandoff | null = null;
		if (storedMedia) {
			try {
				parsedStoredMedia = JSON.parse(storedMedia) as ComposerMediaHandoff;
			} catch {
				window.sessionStorage.removeItem("juno33:composer-media");
			}
		}
		const incomingMedia = stateMedia ?? parsedStoredMedia;

		if (!incomingMedia) return;

		const mappedMedia: MediaItem = {
			id: incomingMedia.id,
			kind: incomingMedia.type === "photo" ? "image" : "video",
			name: incomingMedia.name,
			from:
				incomingMedia.type === "photo"
					? "var(--color-photo-gradient-start)"
					: "var(--color-video-gradient-start)",
			to:
				incomingMedia.type === "photo"
					? "var(--color-photo-gradient-end)"
					: "var(--color-video-gradient-end)",
			alt: "",
			url: incomingMedia.url,
		};

		setLibraryMedia(incomingMedia);
		setMedia((current) =>
			current.some((item) => item.id === mappedMedia.id)
				? current
				: [mappedMedia, ...current],
		);

		if (incomingMedia.platforms.includes("instagram")) {
			setPreview("ig-feed");
			setIgType(incomingMedia.type === "reel" ? "reels" : "feed");
		} else {
			setPreview("threads");
		}

		if (storedMedia) {
			window.sessionStorage.removeItem("juno33:composer-media");
		}
	}, [location.state]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: applyDraft is a plain function; ref guard prevents double-execution
	useEffect(() => {
		const latestDraft = (
			location.state as {
				libraryMedia?: ComposerMediaHandoff | undefined;
				latestDraft?: LatestDraft | undefined;
			} | null
		)?.latestDraft;

		if (!latestDraft) return;
		if (latestDraftSeedRef.current === latestDraft.id) return;

		const existingLocalDraft = drafts.find((d) => d.id === latestDraft.id);
		if (existingLocalDraft) {
			latestDraftSeedRef.current = latestDraft.id;
			applyDraft(existingLocalDraft);
			setDraftsOpen(false);
			appToast.success("Draft loaded", {
				description: existingLocalDraft.caption.slice(0, 80) || "Empty caption",
			});
			return;
		}

		latestDraftSeedRef.current = latestDraft.id;
		manualTargetScopeIdRef.current = null;
		scopedTargetSeedRef.current = null;
		setCaption(latestDraft.content);
		setTargetIds(
			latestDraft.targetAccountId ? [latestDraft.targetAccountId] : [],
		);
		setPreview(latestDraft.platform === "instagram" ? "ig-feed" : "threads");
		if (latestDraft.platform === "instagram") {
			setIgType("feed");
		}
		setActiveGroup(null);
		setCurrentDraftId(null);
		setDraftsOpen(false);
		appToast.success("Draft loaded", {
			description: latestDraft.content.slice(0, 80) || "Empty caption",
		});
	}, [location.state, drafts]);

	useEffect(() => {
		const libraryText = (
			location.state as {
				libraryMedia?: ComposerMediaHandoff | undefined;
				latestDraft?: LatestDraft | undefined;
				libraryText?: ComposerTextHandoff | undefined;
			} | null
		)?.libraryText;

		if (!libraryText) return;
		if (libraryTextSeedRef.current === libraryText.id) return;

		libraryTextSeedRef.current = libraryText.id;
		setCaption(libraryText.content);
		setPreview(libraryText.platform === "instagram" ? "ig-feed" : "threads");
		if (libraryText.platform === "instagram") {
			setIgType("feed");
		}
		setDraftsOpen(false);
		appToast.success(libraryText.label, {
			description: libraryText.content.slice(0, 80) || "Empty caption",
		});
	}, [location.state]);

	useEffect(() => {
		const stateIdea = (
			location.state as {
				ideaHandoff?: ComposerIdeaHandoff | undefined;
			} | null
		)?.ideaHandoff;
		const storedIdea = window.sessionStorage.getItem("juno33:composer-idea");
		let parsedStoredIdea: ComposerIdeaHandoff | null = null;
		if (storedIdea) {
			try {
				parsedStoredIdea = JSON.parse(storedIdea) as ComposerIdeaHandoff;
			} catch {
				window.sessionStorage.removeItem("juno33:composer-idea");
			}
		}
		const incomingIdea = stateIdea ?? parsedStoredIdea;

		if (!incomingIdea) return;
		if (ideaHandoffSeedRef.current === incomingIdea.id) return;
		ideaHandoffSeedRef.current = incomingIdea.id;

		manualTargetScopeIdRef.current = null;
		scopedTargetSeedRef.current = null;
		setCaption(incomingIdea.content);
		setCurrentDraftId(null);
		setLibraryMedia(null);
		setDraftsOpen(false);
		if (incomingIdea.linkUrl) setLinkAttach(incomingIdea.linkUrl);

		let ideaTargetIds: string[] = [];
		if (incomingIdea.groupId) {
			const preset = groupPresets.find((g) => g.id === incomingIdea.groupId);
			if (preset) {
				ideaTargetIds = preset.accountIds;
				setTargetIds(preset.accountIds);
				setActiveGroup(preset.id);
			}
		} else if (incomingIdea.accountId) {
			ideaTargetIds = [incomingIdea.accountId];
			setTargetIds([incomingIdea.accountId]);
			setActiveGroup(null);
		}

		if (incomingIdea.imageUrl) {
			const ideaMedia: MediaItem = {
				id: `idea_${incomingIdea.id}`,
				kind: "image",
				name: incomingIdea.imageName ?? "Idea screenshot",
				from: "var(--color-photo-gradient-start)",
				to: "var(--color-photo-gradient-end)",
				alt: "",
				url: incomingIdea.imageUrl,
			};
			setMedia((current) =>
				current.some((item) => item.id === ideaMedia.id)
					? current
					: [ideaMedia, ...current],
			);
		}

		const targetAccountId = incomingIdea.accountId ?? ideaTargetIds[0] ?? null;
		const targetAccount = targetAccountId
			? accountsById.get(targetAccountId)
			: null;
		if (targetAccount?.platform === "instagram") {
			setPreview("ig-feed");
			setIgType("feed");
		} else {
			setPreview("threads");
		}

		if (storedIdea) window.sessionStorage.removeItem("juno33:composer-idea");
		appToast.success(incomingIdea.label, {
			description: incomingIdea.content.slice(0, 80) || "Empty caption",
		});
	}, [accountsById, groupPresets, location.state]);

	useEffect(() => {
		if (!scopedAccount) {
			scopedTargetSeedRef.current = null;
			manualTargetScopeIdRef.current = null;
			return;
		}

		const scopedId = scopedAccount.id;
		if (
			manualTargetScopeIdRef.current &&
			manualTargetScopeIdRef.current !== scopedId
		) {
			manualTargetScopeIdRef.current = null;
		}
		if (manualTargetScopeIdRef.current === scopedId) return;

		const noDraftInFlight =
			!currentDraftId &&
			!caption.trim() &&
			media.length === 0 &&
			!isSavingDraft &&
			!isSubmitting;
		if (!noDraftInFlight) return;

		const isDefaultTarget =
			targetIds.length === 0 ||
			(scopedTargetSeedRef.current !== null &&
				targetIds.length === 1 &&
				targetIds[0] === scopedTargetSeedRef.current);
		if (!isDefaultTarget) return;
		if (targetIds.length === 1 && targetIds[0] === scopedId) {
			scopedTargetSeedRef.current = scopedId;
			return;
		}

		scopedTargetSeedRef.current = scopedId;
		setTargetIds([scopedId]);
		setActiveGroup(null);
	}, [
		scopedAccount,
		currentDraftId,
		caption,
		media.length,
		isSavingDraft,
		isSubmitting,
		targetIds,
	]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: applyDraft/applyGroup are plain functions; ref guard prevents double-execution
	useEffect(() => {
		const date = searchParams.get("date");
		const time = searchParams.get("time");
		const groupId = searchParams.get("group");
		const accountId = searchParams.get("accountId");
		const draftId = searchParams.get("draft");
		const replyTo = searchParams.get("reply-to");
		const fromWizard = searchParams.get("fromWizard") === "1";
		const sample = searchParams.get("sample") === "1";
		const requestedPlatform = searchParams.get("platform");
		const requestedPostType = searchParams.get("postType");
		const requestedPublishMode = searchParams.get("publishMode");

		if (
			!date &&
			!time &&
			!groupId &&
			!accountId &&
			!draftId &&
			!replyTo &&
			!fromWizard &&
			!sample &&
			!requestedPlatform &&
			!requestedPostType &&
			!requestedPublishMode
		)
			return;
		if (accountId && !accountsById.has(accountId)) return;

		const seedKey = `${date ?? ""}|${time ?? ""}|${groupId ?? ""}|${accountId ?? ""}|${draftId ?? ""}|${replyTo ?? ""}|${fromWizard ? "wizard" : ""}|${sample ? "sample" : ""}|${requestedPlatform ?? ""}|${requestedPostType ?? ""}|${requestedPublishMode ?? ""}`;
		if (querySeedRef.current === seedKey) return;
		querySeedRef.current = seedKey;

		if (fromWizard) {
			setScheduleMode("schedule");
			setIgOpen(true);
			setThreadsOpen(false);
			if (!caption.trim()) {
				setCaption(
					"Behind the scenes from today.\n\nWhat would you want to see next?",
				);
			}
			recordActivity(
				"First-post wizard opened",
				"Composer was prefilled for Instagram scheduling",
			);
		}
		if (requestedPublishMode === "notify" || requestedPublishMode === "auto") {
			setPublishMode(requestedPublishMode);
			if (requestedPublishMode === "notify") setPreview("ig-handoff");
		}
		if (
			requestedPostType === "feed" ||
			requestedPostType === "reels" ||
			requestedPostType === "story"
		) {
			setIgType(requestedPostType);
			setPreview(requestedPostType === "story" ? "ig-story" : "ig-feed");
		}
		if (requestedPlatform === "instagram" && !accountId) {
			const firstInstagram = connectedAccounts.find(
				(account) => account.platform === "instagram",
			);
			if (firstInstagram) {
				manualTargetScopeIdRef.current = null;
				scopedTargetSeedRef.current = firstInstagram.id;
				setTargetIds([firstInstagram.id]);
				setActiveGroup(null);
				setPreview(
					requestedPublishMode === "notify" ? "ig-handoff" : "ig-feed",
				);
			}
		}

		if (date) {
			setScheduleDate(date);
			setScheduleMode("schedule");
		}
		if (time) {
			setScheduleTime(time);
			setScheduleMode("schedule");
		}
		if (groupId) {
			const preset = groupPresets.find((g) => g.id === groupId);
			if (preset) {
				applyGroup(preset);
			}
		}
		if (accountId && accountsById.has(accountId)) {
			manualTargetScopeIdRef.current = null;
			scopedTargetSeedRef.current = accountId;
			setTargetIds([accountId]);
			setActiveGroup(null);
			const account = accountsById.get(accountId);
			if (account?.platform === "instagram") {
				setPreview("ig-feed");
				setIgType("feed");
			} else {
				setPreview("threads");
			}
		}
		if (draftId) {
			const d = drafts.find((x) => x.id === draftId);
			if (d) applyDraft(d);
		}
		if (replyTo) {
			setReplyToId(replyTo);
		}
	}, [searchParams, groupPresets, drafts, accountsById]);

	const targets = useMemo(
		() =>
			targetIds.map((id) => accountsById.get(id)).filter(Boolean) as Account[],
		[targetIds, accountsById],
	);

	const platformsInTargets = useMemo(() => {
		const set = new Set<AccountPlatform>();
		targets.forEach((a) => {
			set.add(a.platform);
		});
		return set;
	}, [targets]);
	const hasThreadsTarget = platformsInTargets.has("threads");
	const hasInstagramTarget = platformsInTargets.has("instagram");
	const composerPresentation = useMemo(
		() =>
			deriveComposerPresentation({
				targets,
				igType,
				scheduleMode,
				publishMode,
			}),
		[igType, publishMode, scheduleMode, targets],
	);
	const composerMode = composerPresentation.mode;
	const canShowThreadsOptions = composerPresentation.showThreadsOptions;
	const canShowInstagramOptions = composerPresentation.showInstagramOptions;
	const previewPlatform: AccountPlatform =
		preview === "threads" ? "threads" : "instagram";
	const previewTabs = useMemo(() => {
		const allTabs = [
			{ id: "threads" as PreviewMode, label: "Threads" },
			{ id: "ig-feed" as PreviewMode, label: "IG Feed" },
			{ id: "ig-story" as PreviewMode, label: "IG Story" },
			...(publishMode === "notify" || hasInstagramTarget
				? [{ id: "ig-handoff" as PreviewMode, label: "Handoff" }]
				: []),
		];

		if (targets.length === 0 || (hasThreadsTarget && hasInstagramTarget))
			return allTabs;
		if (hasInstagramTarget)
			return allTabs.filter((tab) => tab.id !== "threads");
		if (hasThreadsTarget) return allTabs.filter((tab) => tab.id === "threads");
		return allTabs;
	}, [hasInstagramTarget, hasThreadsTarget, publishMode, targets.length]);
	const previewIds = useMemo<PreviewMode[]>(
		() => previewTabs.map((tab) => tab.id),
		[previewTabs],
	);

	useEffect(() => {
		if (previewIds.includes(preview)) return;
		setPreview(previewIds[0] ?? "threads");
	}, [preview, previewIds]);

	useEffect(() => {
		if (canShowThreadsOptions && !canShowInstagramOptions) {
			setThreadsOpen(true);
			setIgOpen(false);
			return;
		}
		if (!canShowThreadsOptions && canShowInstagramOptions) {
			setThreadsOpen(false);
			setIgOpen(true);
			return;
		}
		if (!canShowThreadsOptions && !canShowInstagramOptions) return;

		if (previewPlatform === "instagram") {
			setThreadsOpen(false);
			setIgOpen(true);
		} else {
			setThreadsOpen(true);
			setIgOpen(false);
		}
	}, [canShowInstagramOptions, canShowThreadsOptions, previewPlatform]);

	const focusThreadsOptions = () => {
		if (!canShowThreadsOptions) return;
		setThreadsOpen(true);
		setIgOpen(false);
		if (preview !== "threads") setPreview("threads");
	};

	const focusInstagramOptions = () => {
		if (!canShowInstagramOptions) return;
		setThreadsOpen(false);
		setIgOpen(true);
		if (preview === "threads") setPreview("ig-feed");
	};

	const setInstagramPostType = (nextType: IGPostType) => {
		setIgType(nextType);
		if (canShowInstagramOptions) {
			setThreadsOpen(false);
			setIgOpen(true);
		}
		setPreview(nextType === "story" ? "ig-story" : "ig-feed");
	};

	const onPreviewKeyDesktop = useTablistKeyboardNav({
		ids: previewIds,
		activeId: preview,
		onNavigate: (id) => setPreview(id as PreviewMode),
		orientation: "horizontal",
		scopeSelector: '[data-tablist="composer-preview-desktop"]',
	});
	const onPreviewKeyMobile = useTablistKeyboardNav({
		ids: previewIds,
		activeId: preview,
		onNavigate: (id) => setPreview(id as PreviewMode),
		orientation: "horizontal",
		scopeSelector: '[data-tablist="composer-preview-mobile"]',
	});

	const groupsInTargets = useMemo(() => {
		const set = new Set<string>();
		// Real "networks" are user-defined groups; count distinct group ids.
		// Unassigned accounts (group_id null) collapse to a single "Unassigned" bucket.
		targets.forEach((a) => {
			set.add(a.groupId ?? "__unassigned");
		});
		return set;
	}, [targets]);
	const voiceGroupId = activeGroup ?? targets[0]?.groupId ?? null;

	const addAccount = (id: string) => {
		manualTargetScopeIdRef.current = scopedAccount?.id ?? null;
		scopedTargetSeedRef.current = null;
		setTargetIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
		setActiveGroup(null);
	};

	const removeAccount = (id: string) => {
		manualTargetScopeIdRef.current = scopedAccount?.id ?? null;
		scopedTargetSeedRef.current = null;
		setTargetIds((prev) => prev.filter((i) => i !== id));
		setActiveGroup(null);
	};

	const applyGroup = (g: GroupPreset) => {
		manualTargetScopeIdRef.current = scopedAccount?.id ?? null;
		scopedTargetSeedRef.current = null;
		const prevIds = targetIds;
		const prevGroup = activeGroup;
		setTargetIds(g.accountIds);
		setActiveGroup(g.id);
		setGroupOpen(false);
		if (prevIds.length > 0) {
			undo({
				label: `Selected group: ${g.label}`,
				description: `${g.accountIds.length} ${g.accountIds.length === 1 ? "account" : "accounts"} targeted.`,
				revert: () => {
					setTargetIds(prevIds);
					setActiveGroup(prevGroup);
				},
			});
		}
	};

	const clearTargets = () => {
		manualTargetScopeIdRef.current = scopedAccount?.id ?? null;
		scopedTargetSeedRef.current = null;
		const prevIds = targetIds;
		const prevGroup = activeGroup;
		setTargetIds([]);
		setActiveGroup(null);
		if (prevIds.length > 0) {
			undo({
				label: `Cleared ${prevIds.length} ${prevIds.length === 1 ? "target" : "targets"}`,
				revert: () => {
					setTargetIds(prevIds);
					setActiveGroup(prevGroup);
				},
			});
		}
	};

	const [aiRunning, setAiRunning] = useState<ComposerAction | null>(null);
	const [slashOpen, setSlashOpen] = useState(false);
	const [slashAnchor, setSlashAnchor] = useState<{
		x: number;
		y: number;
	} | null>(null);
	const [selectionBar, setSelectionBar] = useState<{
		start: number;
		end: number;
		x: number;
		y: number;
	} | null>(null);
	const [variants, setVariants] = useState<ComposerVariant[]>([]);
	const [, setActiveVariantId] = useState<string>("master");
	const [variantsRunning, setVariantsRunning] = useState(false);
	const [critique, setCritique] = useState<ComposerCritique | null>(null);
	const [critiqueLoading, setCritiqueLoading] = useState(false);
	const [diffs, setDiffs] = useState<PostChannelDiff[]>([]);
	const [voiceFileOpen, setVoiceFileOpen] = useState(false);
	const [customPromptOpen, setCustomPromptOpen] = useState(false);
	const [customPrompt, setCustomPrompt] = useState("");
	const [customPromptRunning, setCustomPromptRunning] = useState(false);
	const [customPromptSelection, setCustomPromptSelection] = useState<{
		start: number;
		end: number;
	} | null>(null);
	const masterCaptionRef = useRef("");

	const runAIAction = async (
		action: ComposerAction,
		selection?: { start: number; end: number },
	) => {
		if (aiRunning) return;
		const selectedText = selection
			? caption.slice(selection.start, selection.end)
			: "";
		if (!(selectedText || caption).trim()) {
			appToast.info("Write something first, then run an AI action.");
			return;
		}
		setAiRunning(action);
		const previousCaption = caption;
		const startedAt = Date.now();
		try {
			// accountId only flows when exactly one target is selected; the backend
			// then injects that account's voice_profile. With multi-target the AI
			// falls back to the generic system prompt.
			const scopedAccount = targetIds.length === 1 ? targets[0] : null;
			const rewritten = await runComposerAction({
				action,
				caption,
				selectedText: selectedText || undefined,
				accountId: scopedAccount?.id ?? null,
				platform: scopedAccount?.platform,
				isHeroPost: isHero,
			});
			if (selection && selectedText) {
				setCaption(
					`${caption.slice(0, selection.start)}${rewritten}${caption.slice(selection.end)}`,
				);
				setSelectionBar(null);
			} else {
				setCaption(rewritten);
			}
			const labels: Record<ComposerAction, string> = {
				rephrase: "Caption rewritten with AI",
				shorten: "Caption shortened",
				expand: "Caption expanded",
				spin: "Caption spun",
				translate: "Caption translated",
				matchVoice: "Voice matched",
			};
			undo({
				label: labels[action],
				description: scopedAccount
					? `Tuned to @${scopedAccount.handle.replace(/^@/, "")}'s voice.`
					: undefined,
				revert: () => setCaption(previousCaption),
			});
			void logComposerAiAction({
				accountId: scopedAccount?.id ?? null,
				actionType: action,
				inputText: selectedText || previousCaption,
				outputText: rewritten,
				latencyMs: Date.now() - startedAt,
				metadata: { selection: !!selection, isHero },
			});
		} catch (err) {
			if (err instanceof AiNotConfiguredError) {
				appToast.warn("AI is not configured for this workspace.");
			} else if (err instanceof AiRateLimitedError) {
				appToast.warn("AI rate limit hit — try again in a moment.");
			} else {
				const message =
					err instanceof Error ? err.message : "AI request failed.";
				appToast.error("AI action failed", { description: message });
			}
		} finally {
			setAiRunning(null);
		}
	};

	const runMatchVoice = () => {
		if (targetIds.length !== 1) {
			appToast.info(
				"Pick one target account first — voice matching needs a single account.",
			);
			return;
		}
		runAIAction("matchVoice");
	};

	useEffect(() => {
		if (!caption.trim()) {
			setCritique(null);
			return;
		}
		let cancelled = false;
		const timer = window.setTimeout(() => {
			setCritiqueLoading(true);
			void critiqueComposerCaption({ caption, accountId: targetIds[0] ?? null })
				.then((next) => {
					if (!cancelled) setCritique(next);
				})
				.catch(() => {
					if (!cancelled) setCritique(null);
				})
				.finally(() => {
					if (!cancelled) setCritiqueLoading(false);
				});
		}, 1500);
		return () => {
			cancelled = true;
			window.clearTimeout(timer);
		};
	}, [caption, targetIds]);

	const generateVariants = async () => {
		if (!caption.trim() || variantsRunning) return;
		setVariantsRunning(true);
		try {
			const next = await generateComposerVariants({
				caption,
				accountId: targetIds[0] ?? null,
				persona,
				draftId: currentDraftId,
			});
			setVariants(next);
			setActiveVariantId(next[0]?.id ?? "master");
		} catch (error) {
			appToast.error("Could not generate variants", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setVariantsRunning(false);
		}
	};

	const promoteVariant = async (variant: ComposerVariant) => {
		setCaption(variant.content);
		setActiveVariantId(variant.id);
		try {
			const promoted = await promoteComposerVariant(variant.id);
			setVariants((prev) =>
				prev.map((item) => (item.id === promoted.id ? promoted : item)),
			);
		} catch {
			appToast.error("Variant promoted locally, but persistence failed");
		}
	};

	const selectVariant = (variant: ComposerVariant) => {
		setCaption(variant.content);
		setActiveVariantId(variant.id);
	};

	const ghostSuggestion = useMemo(() => {
		const trimmed = caption.trim();
		if (trimmed.length < 24 || slashOpen || selectionBar) return "";
		if (trimmed.endsWith("?"))
			return " Turn the best answers into tomorrow’s follow-up post.";
		if (/threads/i.test(trimmed))
			return " The real edge is reply depth, not likes.";
		if (/reel|instagram/i.test(trimmed))
			return " Put the CTA before the viewer has time to drift.";
		return " Here’s the part most people miss.";
	}, [caption, selectionBar, slashOpen]);

	const acceptGhostSuggestion = () => {
		if (!ghostSuggestion) return;
		setCaption((value) => `${value}${ghostSuggestion}`);
		requestAnimationFrame(() => {
			captionRef.current?.focus();
			const next = caption.length + ghostSuggestion.length;
			captionRef.current?.setSelectionRange(next, next);
		});
	};

	const runCustomPrompt = async () => {
		const prompt = customPrompt.trim();
		if (!prompt || customPromptRunning) return;
		const previousCaption = caption;
		const selection = customPromptSelection;
		const selectedText = selection
			? caption.slice(selection.start, selection.end)
			: "";
		const sourceText = selectedText || caption;
		setCustomPromptRunning(true);
		const startedAt = Date.now();
		try {
			const output = await generateAiText(
				[
					"Edit this social post according to the operator instruction.",
					selectedText
						? "Return only the replacement text for the selected passage. Preserve handles, links, hashtags, and emoji unless instructed otherwise."
						: "Return only the final post text. Preserve handles, links, hashtags, and emoji unless instructed otherwise.",
					"",
					"INSTRUCTION:",
					prompt,
					"",
					selectedText ? "SELECTED PASSAGE:" : "POST:",
					sourceText,
				].join("\n"),
				{
					feature: "composer-custom-prompt",
					temperature: 0.55,
					maxTokens: 700,
					accountId: targetIds[0] ?? undefined,
					platform: platformsInTargets.has("instagram")
						? "instagram"
						: "threads",
					isHeroPost: isHero,
				},
			);
			const rewritten = output.trim();
			if (!rewritten) throw new Error("AI returned an empty response.");
			if (selection && selectedText) {
				setCaption(
					`${caption.slice(0, selection.start)}${rewritten}${caption.slice(selection.end)}`,
				);
				setSelectionBar(null);
			} else {
				setCaption(rewritten);
			}
			setCustomPromptOpen(false);
			setCustomPromptSelection(null);
			setCustomPrompt("");
			undo({
				label: "Custom AI prompt",
				revert: () => setCaption(previousCaption),
			});
			void logComposerAiAction({
				accountId: targetIds[0] ?? null,
				actionType: "customPrompt",
				inputText: sourceText,
				outputText: rewritten,
				latencyMs: Date.now() - startedAt,
				metadata: { prompt, isHero, selection: !!selectedText },
			});
		} catch (err) {
			appToast.error("Custom prompt failed", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		} finally {
			setCustomPromptRunning(false);
		}
	};

	const draftKey = currentDraftId ?? "composer-live-draft";
	useEffect(() => {
		let cancelled = false;
		fetchComposerDiffs(draftKey)
			.then((nextDiffs) => {
				if (!cancelled) setDiffs(nextDiffs);
			})
			.catch(() => {
				if (!cancelled) setDiffs([]);
			});
		return () => {
			cancelled = true;
		};
	}, [draftKey]);

	useEffect(() => {
		if (preview === "threads") {
			masterCaptionRef.current = caption;
			return;
		}
		if (
			!caption.trim() ||
			!masterCaptionRef.current ||
			caption === masterCaptionRef.current
		)
			return;
		const platform =
			preview === "ig-story" ? "instagram_story" : "instagram_feed";
		const timer = window.setTimeout(() => {
			createComposerDiff({
				draftId: draftKey,
				platform,
				masterCaption: masterCaptionRef.current,
				variantCaption: caption,
			})
				.then((diff) =>
					setDiffs((prev) => [
						diff,
						...prev.filter((item) => item.id !== diff.id),
					]),
				)
				.catch(() => {});
		}, 1800);
		return () => window.clearTimeout(timer);
	}, [caption, draftKey, preview]);

	const insertAtCursor = (text: string) => {
		const el = captionRef.current;
		const start = el?.selectionStart ?? caption.length;
		const end = el?.selectionEnd ?? caption.length;
		setCaption(`${caption.slice(0, start)}${text}${caption.slice(end)}`);
		requestAnimationFrame(() => {
			captionRef.current?.focus();
			const next = start + text.length;
			captionRef.current?.setSelectionRange(next, next);
		});
	};

	const slashTokenRange = () => {
		const el = captionRef.current;
		const cursor = el?.selectionStart ?? caption.length;
		const before = caption.slice(0, cursor);
		const match = before.match(/(^|\s)\/[\w-]*$/);
		if (!match || match.index === undefined) return null;
		const slashStart = match.index + match[1]!.length;
		return { start: slashStart, end: cursor };
	};

	const replaceSlashToken = (text: string) => {
		const range = slashTokenRange();
		if (!range) {
			insertAtCursor(text);
			return;
		}
		setCaption(
			`${caption.slice(0, range.start)}${text}${caption.slice(range.end)}`,
		);
		requestAnimationFrame(() => {
			captionRef.current?.focus();
			const next = range.start + text.length;
			captionRef.current?.setSelectionRange(next, next);
		});
	};

	const removeSlashToken = () => {
		const range = slashTokenRange();
		if (!range) return;
		setCaption(`${caption.slice(0, range.start)}${caption.slice(range.end)}`);
		requestAnimationFrame(() => {
			captionRef.current?.focus();
			captionRef.current?.setSelectionRange(range.start, range.start);
		});
	};

	const slashCommands: SlashCommand[] = [
		{
			id: "hook",
			label: "/hook",
			hint: "Insert a voice-pattern hook",
			run: () => replaceSlashToken("Here is the thing no one tells you: "),
		},
		{
			id: "threads",
			label: "/threads",
			hint: "Split caption into thread tail",
			run: () => {
				removeSlashToken();
				setThreadChain(true);
			},
		},
		{
			id: "shorten",
			label: "/shorten",
			hint: "Shorten with AI",
			run: () => {
				removeSlashToken();
				void runAIAction("shorten");
			},
		},
		{
			id: "cta",
			label: "/cta",
			hint: "Insert persona CTA",
			run: () => replaceSlashToken("\n\nWhat would you add?"),
		},
		{
			id: "poll",
			label: "/poll",
			hint: "Open poll fields",
			run: () => {
				removeSlashToken();
				focusThreadsOptions();
				setPollEnabled(true);
			},
		},
		{
			id: "quote",
			label: "/quote",
			hint: "Open quote field",
			run: () => {
				removeSlashToken();
				focusThreadsOptions();
				captionRef.current?.blur();
			},
		},
		{
			id: "topic",
			label: "/topic",
			hint: "Open topic picker",
			run: () => {
				removeSlashToken();
				focusThreadsOptions();
				setTopicTag(topicTag || "");
			},
		},
		{
			id: "ai",
			label: "/ai",
			hint: "Open selection AI bar",
			run: () => {
				removeSlashToken();
				setSelectionBar({ start: 0, end: caption.length, x: 220, y: 180 });
			},
		},
	];

	const onCaptionChange = (value: string) => {
		setCaption(value);
		const el = captionRef.current;
		if (!el) return;
		const pos = el.selectionStart ?? value.length;
		const prev = value[pos - 2] ?? " ";
		const char = value[pos - 1];
		if (char === "/" && /\s/.test(prev)) {
			const rect = el.getBoundingClientRect();
			setSlashAnchor({ x: rect.left + 16, y: rect.top + 36 });
			setSlashOpen(true);
		} else if (char === " ") {
			setSlashOpen(false);
		}
	};

	const fileInputRef = useRef<HTMLInputElement>(null);

	const surfacesFromTargets = (): Surface[] => {
		// Validate against every platform currently targeted so operators know instantly
		// if one file violates any surface constraint.
		const s = new Set<Surface>();
		if (platformsInTargets.has("threads")) s.add("threads");
		if (platformsInTargets.has("instagram")) {
			// Pick IG surfaces based on composer's igType toggle (Reels vs Feed vs Story).
			if (igType === "reels") s.add("ig-reel");
			else if (igType === "story") s.add("ig-story");
			else s.add("ig-feed");
		}
		if (s.size === 0) s.add("threads");
		return Array.from(s);
	};

	const mediaValidationMode = (): ValidationMode =>
		scheduleMode === "schedule" &&
		publishMode === "notify" &&
		platformsInTargets.has("instagram")
			? "native-handoff"
			: "api";

	const maybeUseReelValidation = async (
		file: File,
		surfaces: Surface[],
		check: Awaited<ReturnType<typeof validateMedia>>,
		mode: ValidationMode,
	): Promise<{
		check: Awaited<ReturnType<typeof validateMedia>>;
		surfaces: Surface[];
	}> => {
		const isInstagramFeedVideo =
			platformsInTargets.has("instagram") &&
			igType === "feed" &&
			file.type.startsWith("video/") &&
			surfaces.includes("ig-feed");
		const looksLikeReel =
			check.dimensions && Math.abs(check.dimensions.aspect - 9 / 16) < 0.04;

		if (isInstagramFeedVideo && looksLikeReel) {
			const reelSurfaces = surfaces.map((surface) =>
				surface === "ig-feed" ? "ig-reel" : surface,
			);
			const reelCheck = await validateMedia(file, reelSurfaces, { mode });
			setIgType("reels");
			appToast.info("Switched Instagram to Reels", {
				description: "Vertical 9:16 video is handled as a Reel.",
			});
			return { check: reelCheck, surfaces: reelSurfaces };
		}

		return { check, surfaces };
	};

	const buildBulkQueueItems = async (
		files: File[],
	): Promise<BulkUploadQueueItem[]> => {
		const surfaces = surfacesFromTargets();
		const mode = mediaValidationMode();
		const next: BulkUploadQueueItem[] = [];
		for (const file of files) {
			const check = await validateMedia(file, surfaces, { mode });
			const recommendedPostType =
				file.type.startsWith("video/") &&
				isVerticalReelAspect(check.dimensions?.aspect)
					? "reels"
					: igType;
			next.push({
				id: `bulk_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
				file,
				previewUrl: URL.createObjectURL(file),
				name: file.name,
				kind: file.type.startsWith("video/") ? "video" : "image",
				caption: caption.trim(),
				selected: true,
				postType: recommendedPostType,
				publishMode,
				scheduleDate,
				scheduleTime,
				status: check.ok ? "queued" : "error",
				error: check.ok ? undefined : check.errors.join("\n"),
				warnings: [
					...check.warnings,
					...(recommendedPostType !== igType
						? ["Vertical video detected. Recommended Instagram type: Reel."]
						: []),
				],
			});
		}
		return next;
	};

	const openFilePicker = () => {
		fileInputRef.current?.click();
	};

	const handleFilesSelected = async (files: FileList | null) => {
		if (!files || files.length === 0) return;
		const remaining = Math.max(0, 10 - media.length);
		const accepted = Array.from(files).slice(0, remaining);

		if (accepted.length < files.length) {
			appToast.warn(
				`Max 10 attachments — ${files.length - accepted.length} skipped.`,
			);
		}

		if (accepted.length > 1) {
			const queued = await buildBulkQueueItems(accepted);
			setBulkQueue((prev) => [...prev, ...queued]);
			recordActivity(
				"Bulk queue created",
				`${queued.length} files added for review`,
				() =>
					setBulkQueue((prev) =>
						prev.filter((item) => !queued.some((q) => q.id === item.id)),
					),
			);
			const errors = queued.filter((item) => item.status === "error").length;
			appToast.success(`${queued.length} files added to review queue`, {
				description:
					errors > 0
						? `${errors} need a format check before scheduling.`
						: "Review captions, post type, and schedule before creating posts.",
			});
			if (fileInputRef.current) fileInputRef.current.value = "";
			return;
		}

		let surfaces = surfacesFromTargets();

		for (const file of accepted) {
			const mode = mediaValidationMode();
			const initialCheck = await validateMedia(file, surfaces, { mode });
			const validation = await maybeUseReelValidation(
				file,
				surfaces,
				initialCheck,
				mode,
			);
			surfaces = validation.surfaces;
			const check = validation.check;
			if (!check.ok) {
				appToast.error(`${file.name} rejected`, {
					description: check.errors.join("\n"),
				});
				continue;
			}
			for (const w of check.warnings) appToast.warn(w);

			const localId = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
			const placeholder: MediaItem = {
				id: localId,
				kind: file.type.startsWith("video/") ? "video" : "image",
				name: file.name,
				from: "var(--color-upload-gradient-start)",
				to: "var(--color-upload-gradient-end)",
				alt: "",
				uploading: true,
			};
			setMedia((prev) => [...prev, placeholder]);

			try {
				// Compress images client-side (max 2048 edge, quality 0.85) + strip EXIF.
				// Videos pass through — they'd need ffmpeg.wasm for real transcoding.
				const prepared = file.type.startsWith("image/")
					? await compressImage(file)
					: file;
				const { publicUrl } = await uploadMedia({ file: prepared });
				setMedia((prev) =>
					prev.map((m) =>
						m.id === localId ? { ...m, url: publicUrl, uploading: false } : m,
					),
				);
				trackClientEvent("composer_media_upload_success", {
					kind: placeholder.kind,
					size_mb: Math.round((file.size / 1024 / 1024) * 10) / 10,
				});
				recordActivity("Media attached", file.name, () =>
					setMedia((prev) => prev.filter((m) => m.id !== localId)),
				);
			} catch (err) {
				appToast.error(`${file.name} failed to upload`, {
					description: err instanceof Error ? err.message : undefined,
				});
				trackClientEvent("composer_media_upload_failure", {
					kind: placeholder.kind,
					reason: err instanceof Error ? err.name || "upload_error" : "unknown",
				});
				setMedia((prev) => prev.filter((m) => m.id !== localId));
			}
		}

		if (fileInputRef.current) fileInputRef.current.value = "";
	};

	useEffect(() => {
		bulkQueueRef.current = bulkQueue;
	}, [bulkQueue]);

	useEffect(() => {
		return () => {
			for (const item of bulkQueueRef.current)
				URL.revokeObjectURL(item.previewUrl);
		};
	}, []);

	const openMediaPicker = openFilePicker;

	const applySampleDraft = () => {
		const beforeCaption = caption;
		const beforeIgType = igType;
		const beforeScheduleMode = scheduleMode;
		setCaption(
			"A simple behind-the-scenes clip showing how the new workflow comes together. Save this as a Reel, polish it in Instagram, then post natively.",
		);
		setIgType("reels");
		setScheduleMode("schedule");
		recordActivity("Sample draft loaded", "Client-only starter content", () => {
			setCaption(beforeCaption);
			setIgType(beforeIgType);
			setScheduleMode(beforeScheduleMode);
		});
	};

	const removeMedia = (id: string) => {
		const removed = media.find((item) => item.id === id);
		const before = media;
		setMedia((prev) => prev.filter((m) => m.id !== id));
		if (editingAltId === id) setEditingAltId(null);
		if (removed) {
			recordActivity("Media removed", removed.name, () => setMedia(before));
		}
	};

	const moveMedia = (id: string, direction: -1 | 1) => {
		const before = media;
		const index = media.findIndex((item) => item.id === id);
		const nextIndex = index + direction;
		if (index < 0 || nextIndex < 0 || nextIndex >= media.length) return;
		const next = [...media];
		const [item] = next.splice(index, 1);
		if (!item) return;
		next.splice(nextIndex, 0, item);
		setMedia(next);
		recordActivity("Media reordered", item.name, () => setMedia(before));
	};

	const beginEditAlt = (id: string) => {
		const item = media.find((m) => m.id === id);
		setAltDraft(item?.alt ?? "");
		setEditingAltId(id);
	};

	const saveAlt = () => {
		if (!editingAltId) return;
		const v = altDraft.trim();
		setMedia((prev) =>
			prev.map((m) => (m.id === editingAltId ? { ...m, alt: v } : m)),
		);
		setEditingAltId(null);
		setAltDraft("");
	};

	const cancelAlt = () => {
		setEditingAltId(null);
		setAltDraft("");
	};

	const setGeneratedAlt = (id: string, alt: string) => {
		setMedia((prev) => prev.map((m) => (m.id === id ? { ...m, alt } : m)));
		if (editingAltId === id) setAltDraft(alt);
	};

	const editingAltItem = editingAltId
		? (media.find((m) => m.id === editingAltId) ?? null)
		: null;

	const threadsCaptionBytes = utf8ByteLength(caption);
	const isInstagramNativeHandoff =
		scheduleMode === "schedule" &&
		publishMode === "notify" &&
		platformsInTargets.has("instagram");
	const captionCharsOK =
		(!platformsInTargets.has("threads") ||
			threadsCaptionBytes <= THREADS_LIMIT) &&
		(!platformsInTargets.has("instagram") || caption.length <= IG_LIMIT);

	const preflightIssues = useMemo(
		() =>
			collectComposerIssues({
				targets,
				media,
				igType,
				trialReel,
				brandedContentSponsorIds,
				collaborators,
				pollEnabled,
				pollOptions,
				linkAttach,
				gifId,
				textAttachment,
				textAttachmentStyles,
				textSpoilerTerms,
				caption,
				allowInstagramNativeHandoff: isInstagramNativeHandoff,
			}),
		[
			targets,
			media,
			igType,
			trialReel,
			brandedContentSponsorIds,
			collaborators,
			pollEnabled,
			pollOptions,
			linkAttach,
			gifId,
			textAttachment,
			textAttachmentStyles,
			textSpoilerTerms,
			caption,
			isInstagramNativeHandoff,
		],
	);
	const getSubmitBlockers = () => {
		const blockers: string[] = [];
		const hasCaption = caption.trim().length > 0;
		const hasMedia = media.length > 0;
		if (targets.length === 0) {
			blockers.push("Select at least one account.");
		}
		if (platformsInTargets.has("threads") && !hasCaption) {
			blockers.push("Threads posts need a caption.");
		}
		if (platformsInTargets.has("instagram") && !hasCaption && !hasMedia) {
			blockers.push("Instagram posts need media or a caption.");
		}
		if (
			!platformsInTargets.has("instagram") &&
			!platformsInTargets.has("threads") &&
			!hasCaption
		) {
			blockers.push(
				"Write a caption or select an Instagram account with media.",
			);
		}
		if (!captionCharsOK) {
			blockers.push(
				platformsInTargets.has("threads") && threadsCaptionBytes > THREADS_LIMIT
					? "Threads posts support a maximum of 500 UTF-8 bytes."
					: "Instagram captions support a maximum of 2,200 characters.",
			);
		}
		if (scheduleMode === "schedule") {
			const local = new Date(`${scheduleDate}T${scheduleTime}`);
			if (Number.isNaN(local.getTime())) {
				blockers.push("Choose a valid schedule date and time.");
			} else if (local.getTime() <= Date.now() + 2 * 60_000) {
				blockers.push("Choose a schedule time at least 2 minutes from now.");
			}
		}
		blockers.push(...preflightIssues);
		return blockers;
	};
	const submitBlockers = getSubmitBlockers();
	const canPublish = !isSubmitting;
	const pushHealthCopy = formatPushHealth(pushHealth);
	const readinessChecks: ReadinessCheck[] = [
		{
			id: "account",
			label: targets.length > 0 ? "Account selected" : "Choose an account",
			detail:
				targets.length > 0
					? `${targets.length} target${targets.length === 1 ? "" : "s"} ready.`
					: "Pick a Threads or Instagram account before publishing.",
			tone: targets.length > 0 ? "ready" : "blocked",
			action: () => setPickerOpen(true),
			actionLabel: "Pick account",
		},
		{
			id: "content",
			label:
				caption.trim() || media.length > 0
					? "Content present"
					: "Add caption or media",
			detail:
				caption.trim() || media.length > 0
					? `${caption.length} caption chars, ${media.length} media item${media.length === 1 ? "" : "s"}.`
					: "Posts need a caption, media, or both.",
			tone: caption.trim() || media.length > 0 ? "ready" : "blocked",
			action: () => captionRef.current?.focus(),
			actionLabel: "Edit",
		},
		{
			id: "uploads",
			label: media.some((item) => item.uploading)
				? "Uploads running"
				: "Media uploaded",
			detail: media.some((item) => item.uploading)
				? "Wait for all attached media to finish uploading."
				: media.length > 0
					? "Attached media has public URLs."
					: "No media attached.",
			tone: media.some((item) => item.uploading) ? "blocked" : "ready",
		},
		{
			id: "format",
			label:
				preflightIssues.length > 0
					? "Format needs review"
					: "Format compatible",
			detail:
				preflightIssues[0] ??
				`${platformsInTargets.has("instagram") ? labelForIgType(igType) : "Threads"} validation profile is clear.`,
			tone: preflightIssues.length > 0 ? "blocked" : "ready",
			action: () => setAdvancedOpen(true),
			actionLabel: "Review",
		},
		{
			id: "schedule",
			label:
				scheduleMode === "schedule"
					? "Schedule selected"
					: scheduleMode === "queue"
						? "Queue timing selected"
						: "Post now selected",
			detail:
				scheduleMode === "schedule"
					? `${scheduleDate} at ${scheduleTime}`
					: scheduleMode === "queue"
						? "Juno33 will use the next best available slot."
						: "This will publish immediately.",
			tone: submitBlockers.some((blocker) =>
				blocker.toLowerCase().includes("schedule"),
			)
				? "blocked"
				: "ready",
		},
		...(isInstagramNativeHandoff
			? [
					{
						id: "push",
						label: pushHealthCopy.label,
						detail: pushHealthCopy.detail,
						tone: pushHealthCopy.tone,
						action:
							pushHealth === "permission-needed" ||
							pushHealth === "not-subscribed"
								? () => void enablePushForNotifyMe()
								: undefined,
						actionLabel: pushHealthBusy ? "Enabling…" : "Enable",
					} satisfies ReadinessCheck,
				]
			: [
					{
						id: "publish-path",
						label: "Auto-publish checks",
						detail: platformsInTargets.has("instagram")
							? "Juno33 will use strict API publishing requirements."
							: "Threads publishing path is selected.",
						tone: "ready" as const,
					},
				]),
	];
	const readinessBlocked = readinessChecks.filter(
		(check) => check.tone === "blocked",
	).length;
	const readinessWarnings = readinessChecks.filter(
		(check) => check.tone === "warning",
	).length;
	const postHealth = buildPostHealth({
		checks: readinessChecks,
		media,
		caption,
		isInstagramNativeHandoff,
		pushHealth,
		preflightIssues,
	});
	const publishingReadinessIssues = (() => {
		const hasInstagramAccount = connectedAccounts.some(
			(account) => account.platform === "instagram",
		);
		const lastHandoffCompleted = drafts.some(
			(draft) => draft.preview === "ig-handoff",
		);
		return buildPublishingReadinessIssues({
			hasInstagramAccount,
			pushState: pushSetupState(pushHealth),
			pwaState,
			instagramReady: phoneChecks.instagramReady,
			lastHandoffCompleted,
		}).map((issue) => {
			if (issue.id === "instagram-account") {
				return { ...issue, action: () => setPickerOpen(true) };
			}
			if (issue.id === "notify-push") {
				return { ...issue, action: () => void enablePushForNotifyMe() };
			}
			if (issue.id === "pwa-install") {
				return { ...issue, action: () => setAdvancedOpen(true) };
			}
			if (issue.id === "instagram-app") {
				return {
					...issue,
					action: () =>
						setPhoneChecks((current) => ({
							...current,
							instagramReady: true,
						})),
				};
			}
			if (issue.id === "first-handoff") {
				return {
					...issue,
					action: () => {
						setPublishMode("notify");
						setScheduleMode("schedule");
						setPreview("ig-handoff");
					},
				};
			}
			return issue;
		});
	})();
	const publishingReadinessState = summarizeReadinessState(
		publishingReadinessIssues,
	);
	const readinessNeedsAttention =
		readinessBlocked > 0 ||
		readinessWarnings > 0 ||
		publishingReadinessState !== "ready" ||
		postHealth.tone !== "ready";
	const mediaOptimizationSuggestions: MediaOptimizationSuggestion[] = bulkQueue
		.filter((item) => canOptimizeImage(item.file))
		.slice(0, 3)
		.map((item) => ({
			id: item.id,
			label: "Large image queued",
			detail: `${item.name} will be compressed before upload.`,
			actionLabel: "Attach optimized",
			action: () => void attachBulkItemToCurrentPost(item),
		}));

	// Dirty = something worth warning about on tab close / hard refresh or in-app
	// modal close. Doesn't include target selection alone (cheap to re-pick) —
	// focus on content work that'd actually hurt to lose. currentDraftId means
	// the draft is already persisted, so tab close is safe.
	const hasUnsavedWork =
		!isSubmitting &&
		!currentDraftId &&
		(caption.trim().length > 0 || media.length > 0);
	useDirtyGuard(hasUnsavedWork);

	// Report dirty status + a save callback up to Layout so the Composer modal
	// close path can surface the three-button confirm dialog when needed.
	// biome-ignore lint/correctness/useExhaustiveDependencies: handleSaveDraft intentionally omitted — re-registering only on hasUnsavedWork keeps the confirm dialog operating on the current closure state
	useEffect(() => {
		composer.setDirtyState(hasUnsavedWork, async () => {
			await handleSaveDraft();
		});
		return () => composer.setDirtyState(false, null);
		// handleSaveDraft captures the latest state via closure — re-registering
		// it whenever unsaved-work changes keeps the confirm dialog's "Save draft"
		// button operating on the current caption/media.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [hasUnsavedWork]);

	const resetDraft = () => {
		manualTargetScopeIdRef.current = null;
		scopedTargetSeedRef.current = null;
		setTargetIds([]);
		setActiveGroup(null);
		setCaption("");
		setMedia([]);
		setPersona("default");
		setIsHero(false);
		setPreview("threads");
		setLibraryMedia(null);
		setReplyControl("anyone");
		setThreadChain(false);
		setQuoteUrl("");
		setTLocation("");
		setLinkAttach("");
		setTextSpoilerTerms("");
		setGifId("");
		setGifProvider("GIPHY");
		setTextAttachment("");
		setTextAttachmentUrl("");
		setTextAttachmentStyles("");
		setTopicTag("");
		setGeoGate("");
		setReplyApprovalMode("none");
		setPollEnabled(false);
		setPollOptions(["", ""]);
		setSpoiler(false);
		setGhostPost(false);
		setGhostDuration("24h");
		setIgType("feed");
		setFirstComment("");
		setIgLocation("");
		setCollaborators([]);
		setCollaboratorDraft("");
		setCrossFb(false);
		setCrossIgDarkMode(false);
		setReelCover(3);
		setCoverUrl("");
		setAudioName("");
		setTrialReel(false);
		setGraduation("SS_PERFORMANCE");
		setShareToFeed(true);
		setCommentEnabled(true);
		setUserTags("");
		setProductTags("");
		setIsPaidPartnership(false);
		setBrandedContentSponsorIds("");
		setReplyToId(null);
		setScheduleMode("now");
		setPublishMode("auto");
		const nextDate = new Date();
		nextDate.setDate(nextDate.getDate() + 1);
		const yyyy = nextDate.getFullYear();
		const mm = String(nextDate.getMonth() + 1).padStart(2, "0");
		const dd = String(nextDate.getDate()).padStart(2, "0");
		setScheduleDate(`${yyyy}-${mm}-${dd}`);
		setScheduleTime("09:00");
		setPickerOpen(false);
		setGroupOpen(false);
	};

	const collectDraft = (existingId?: string | null): Draft => ({
		id:
			existingId ??
			`dr_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
		updatedAt: Date.now(),
		caption,
		targetIds,
		media,
		persona,
		isHero,
		preview,
		replyControl,
		threadChain,
		quoteUrl,
		tLocation,
		linkAttach,
		textSpoilerTerms,
		gifId,
		gifProvider,
		textAttachment,
		textAttachmentUrl,
		textAttachmentStyles,
		topicTag,
		geoGate,
		replyApprovalMode,
		pollEnabled,
		pollOptions,
		spoiler,
		ghostPost,
		ghostDuration,
		igType,
		firstComment,
		igLocation,
		collaborators,
		crossFb,
		crossIgDarkMode,
		reelCover,
		coverUrl,
		audioName,
		igAudioId,
		igAudioTitle,
		igAudioArtist,
		igAudioType,
		trialReel,
		graduation,
		shareToFeed,
		commentEnabled,
		userTags,
		productTags,
		isPaidPartnership,
		brandedContentSponsorIds,
		replyToId,
	});

	const applyDraft = (d: Draft) => {
		manualTargetScopeIdRef.current = null;
		scopedTargetSeedRef.current = null;
		setCaption(d.caption);
		setTargetIds(d.targetIds);
		setMedia(d.media);
		setPersona(d.persona);
		setIsHero(d.isHero ?? false);
		setPreview(d.preview);
		setReplyControl(d.replyControl);
		setThreadChain(d.threadChain);
		setQuoteUrl(d.quoteUrl);
		setTLocation(d.tLocation);
		setLinkAttach(d.linkAttach);
		setTextSpoilerTerms(d.textSpoilerTerms ?? "");
		setGifId(d.gifId ?? "");
		setGifProvider(d.gifProvider ?? "GIPHY");
		setTextAttachment(d.textAttachment ?? "");
		setTextAttachmentUrl(d.textAttachmentUrl ?? "");
		setTextAttachmentStyles(d.textAttachmentStyles ?? "");
		setTopicTag(d.topicTag);
		setGeoGate(d.geoGate);
		setReplyApprovalMode(d.replyApprovalMode ?? "none");
		setPollEnabled(d.pollEnabled);
		setPollOptions(d.pollOptions);
		setSpoiler(d.spoiler);
		setGhostPost(d.ghostPost);
		setGhostDuration(d.ghostDuration);
		setIgType(d.igType);
		setFirstComment(d.firstComment);
		setIgLocation(d.igLocation);
		setCollaborators(d.collaborators);
		setCrossFb(d.crossFb);
		setCrossIgDarkMode(d.crossIgDarkMode ?? false);
		setReelCover(d.reelCover);
		setCoverUrl(d.coverUrl);
		setAudioName(d.audioName);
		setIgAudioId(d.igAudioId ?? "");
		setIgAudioTitle(d.igAudioTitle ?? "");
		setIgAudioArtist(d.igAudioArtist ?? "");
		setIgAudioType(d.igAudioType ?? "music");
		setTrialReel(d.trialReel);
		setGraduation(d.graduation);
		setShareToFeed(d.shareToFeed);
		setCommentEnabled(d.commentEnabled ?? true);
		setUserTags(d.userTags);
		setProductTags(d.productTags);
		setIsPaidPartnership(d.isPaidPartnership ?? false);
		setBrandedContentSponsorIds(d.brandedContentSponsorIds ?? "");
		setReplyToId(d.replyToId ?? null);
		setCurrentDraftId(d.id);
	};

	const deleteDraft = (id: string) => {
		const doomed = drafts.find((d) => d.id === id);
		if (!doomed) return;
		void deleteDraftRemote(id);
		if (currentDraftId === id) setCurrentDraftId(null);
		appToast.success("Draft deleted", {
			duration: 5000,
			description: doomed.caption.slice(0, 60) || "Empty caption",
			action: {
				label: "Undo",
				onClick: () => {
					void restoreDraftRemote(
						doomed as unknown as Parameters<typeof restoreDraftRemote>[0],
					);
				},
			},
		});
	};

	const loadDraft = (id: string) => {
		const d = drafts.find((x) => x.id === id);
		if (!d) return;
		applyDraft(d);
		setDraftsOpen(false);
		appToast.success("Draft loaded", {
			description: d.caption.slice(0, 80) || "Empty caption",
		});
	};

	const handleSaveDraft = async () => {
		if (isSavingDraft) return;
		setIsSavingDraft(true);
		const snap = collectDraft(currentDraftId);
		const existing = drafts.some((d) => d.id === snap.id);
		try {
			await persistDraftRemote(
				snap as unknown as Parameters<typeof persistDraftRemote>[0],
			);
			setCurrentDraftId(snap.id);
			haptics.light();
			appToast.success(existing ? "Draft updated" : "Draft saved", {
				description:
					targets.length > 0
						? `Saved for ${targets.length} ${targets.length === 1 ? "account" : "accounts"}.`
						: "Target accounts can be added later.",
			});
		} finally {
			setIsSavingDraft(false);
		}
	};

	const updateBulkQueueItem = (
		id: string,
		patch: Partial<BulkUploadQueueItem>,
	) => {
		setBulkQueue((prev) =>
			prev.map((item) => (item.id === id ? { ...item, ...patch } : item)),
		);
	};

	const removeBulkQueueItem = (id: string) => {
		setBulkQueue((prev) => {
			const item = prev.find((candidate) => candidate.id === id);
			if (item) URL.revokeObjectURL(item.previewUrl);
			return prev.filter((candidate) => candidate.id !== id);
		});
	};

	const moveBulkQueueItem = (id: string, direction: -1 | 1) => {
		setBulkQueue((prev) => {
			const index = prev.findIndex((item) => item.id === id);
			const nextIndex = index + direction;
			if (index < 0 || nextIndex < 0 || nextIndex >= prev.length) return prev;
			const next = [...prev];
			const [item] = next.splice(index, 1);
			if (!item) return prev;
			next.splice(nextIndex, 0, item);
			return next;
		});
	};

	const uploadBulkQueueItem = async (
		item: BulkUploadQueueItem,
	): Promise<string> => {
		if (item.mediaUrl) return item.mediaUrl;
		updateBulkQueueItem(item.id, { status: "uploading", error: undefined });
		const prepared = item.file.type.startsWith("image/")
			? await compressImage(item.file)
			: item.file;
		const { publicUrl } = await uploadMedia({ file: prepared });
		updateBulkQueueItem(item.id, { status: "ready", mediaUrl: publicUrl });
		return publicUrl;
	};

	const attachBulkItemToCurrentPost = async (item: BulkUploadQueueItem) => {
		try {
			const publicUrl = await uploadBulkQueueItem(item);
			const localId = `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
			setMedia((prev) => [
				...prev,
				{
					id: localId,
					kind: item.kind,
					name: item.name,
					from: "var(--color-upload-gradient-start)",
					to: "var(--color-upload-gradient-end)",
					alt: "",
					url: publicUrl,
					uploading: false,
				},
			]);
			removeBulkQueueItem(item.id);
			appToast.success("Attached to current post");
		} catch (err) {
			updateBulkQueueItem(item.id, {
				status: "error",
				error: err instanceof Error ? err.message : "Upload failed",
			});
			appToast.error("Could not attach media", {
				description: err instanceof Error ? err.message : undefined,
			});
		}
	};

	const createPostsFromBulkQueue = async (status: "draft" | "scheduled") => {
		const selected = bulkQueue.filter(
			(item) =>
				item.selected && item.status !== "error" && item.status !== "done",
		);
		if (selected.length === 0) {
			appToast.info("Select at least one queued item.");
			return;
		}
		if (targets.length === 0) {
			appToast.error("Select an account before creating queued posts.");
			return;
		}
		setIsSubmitting(true);
		try {
			let created = 0;
			const batchId = randomUUID();
			for (const item of selected) {
				updateBulkQueueItem(item.id, { status: "saving", error: undefined });
				const mediaUrl = await uploadBulkQueueItem(item);
				const scheduledDate =
					status === "scheduled"
						? new Date(
								`${item.scheduleDate}T${item.scheduleTime}`,
							).toISOString()
						: null;
				await Promise.all(
					targets.map((target, targetIndex) => {
						const igMediaType =
							target.platform === "instagram"
								? item.postType === "reels"
									? "REELS"
									: item.postType === "story"
										? "STORIES"
										: item.kind === "video"
											? "VIDEO"
											: "IMAGE"
								: undefined;
						return createPost({
							idempotencyKey: `composer-bulk:${batchId}:${item.id}:${target.id}:${targetIndex}`,
							content: item.caption || caption,
							mediaUrls: [mediaUrl],
							status,
							scheduledDate,
							publishMode:
								status === "scheduled" && target.platform === "instagram"
									? item.publishMode
									: "auto",
							platform: target.platform,
							accountId: target.platform === "threads" ? target.id : undefined,
							instagramAccountId:
								target.platform === "instagram" ? target.id : undefined,
							igMediaType,
							mediaType: igMediaType,
							topics: topicTag ? [topicTag] : [],
							metadata: {
								post_health_score: postHealth.score,
								post_health_issues: postHealth.issues,
								preview_surface: preview,
								manual_publish_setup_state:
									item.publishMode === "notify"
										? pushSetupState(pushHealth)
										: "not_applicable",
								first_post_wizard_step: "schedule",
								readiness_state: publishingReadinessState,
								readiness_issue_ids: publishingReadinessIssues
									.filter((issue) => issue.state !== "ready")
									.map((issue) => issue.id),
							},
						});
					}),
				);
				created += targets.length;
				updateBulkQueueItem(item.id, { status: "done" });
			}
			appToast.success(
				status === "scheduled" ? "Queued posts scheduled" : "Drafts created",
				{ description: `${created} post${created === 1 ? "" : "s"} created.` },
			);
			setBulkQueue((prev) => prev.filter((item) => item.status !== "done"));
		} catch (err) {
			appToast.error(
				status === "scheduled"
					? "Bulk schedule failed"
					: "Draft creation failed",
				{
					description: err instanceof Error ? err.message : undefined,
				},
			);
		} finally {
			setIsSubmitting(false);
		}
	};

	async function enablePushForNotifyMe() {
		setPushHealthBusy(true);
		try {
			const ok = await subscribeToPush();
			setPushHealth(
				ok
					? "subscribed"
					: getPermissionState() === "denied"
						? "denied"
						: "unavailable",
			);
			appToast[ok ? "success" : "warn"](
				ok ? "Notifications enabled" : "Could not enable notifications",
			);
		} finally {
			setPushHealthBusy(false);
		}
	}

	async function sendTestNotification() {
		setPushHealthBusy(true);
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session?.access_token)
				throw new Error("Sign in again to test notifications.");
			const response = await fetch("/api/notifications?action=test-push", {
				method: "POST",
				headers: {
					Authorization: `Bearer ${session.access_token}`,
					"Content-Type": "application/json",
				},
				body: JSON.stringify({ source: "composer" }),
			});
			const data = await response.json().catch(() => null);
			if (!response.ok)
				throw new Error(data?.error || "Test notification failed");
			appToast[data?.delivered ? "success" : "warn"](
				data?.delivered
					? "Test notification sent"
					: "No subscribed device found",
			);
		} catch (err) {
			appToast.error("Could not send test notification", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setPushHealthBusy(false);
		}
	}

	const applyContentKit = (kit: {
		id: string;
		textTemplate: string;
		hashtags: string[];
	}) => {
		const before = caption;
		const tags = kit.hashtags.length
			? `\n\n${kit.hashtags.map((tag) => (tag.startsWith("#") ? tag : `#${tag}`)).join(" ")}`
			: "";
		setCaption((prev) =>
			prev.trim()
				? `${prev.trim()}\n\n${kit.textTemplate}${tags}`
				: `${kit.textTemplate}${tags}`,
		);
		void markContentKitUsed(kit.id);
		recordActivity("Content kit applied", "Caption structure inserted", () =>
			setCaption(before),
		);
		appToast.success("Content kit applied");
	};

	const saveCurrentAsContentKit = async () => {
		if (!caption.trim()) {
			appToast.info("Write a caption before saving a content kit.");
			return;
		}
		const created = await createContentKit({
			name: `Composer kit ${new Date().toLocaleDateString()}`,
			category: "template",
			textTemplate: caption.trim(),
			platform: platformsInTargets.has("instagram") ? "instagram" : "threads",
			hashtags: topicTag ? [topicTag] : [],
			metadata: { postType: igType, publishMode },
		});
		appToast[created ? "success" : "error"](
			created ? "Content kit saved" : "Could not save content kit",
		);
	};

	const handleSubmit = async () => {
		if (isSubmitting) return;
		const blockers = getSubmitBlockers();
		if (blockers.length > 0) {
			const firstBlocked = readinessChecks.find(
				(check) => check.tone === "blocked",
			);
			if (firstBlocked?.action) {
				firstBlocked.action();
			} else {
				setAdvancedOpen(true);
			}
			appToast.error(blockers[0]!, {
				description:
					blockers.length > 1
						? `${blockers.length - 1} more composer checks need attention.`
						: undefined,
			});
			return;
		}
		const mediaUrls = media.map((m) => m.url).filter((u): u is string => !!u);
		setIsSubmitting(true);
		setPublishStage("preflight");
		const submitId = randomUUID();

		const firstAlt = media.find((m) => m.alt && m.alt.trim().length > 0)?.alt;
		const topicsList = topicTag ? [topicTag] : [];
		const allowlistedCountryCodes = parseCountryCodes(geoGate);
		const igUserTags = parseInstagramUserTags(userTags);
		const igProductTags = parseInstagramProductTags(productTags);
		const igBrandedContentSponsorIds = parseCsvTokens(
			brandedContentSponsorIds,
		).slice(0, 2);
		const textSpoilers = buildTextSpoilers(caption, textSpoilerTerms);
		const textAttachmentPayload =
			textAttachment.trim() && !pollEnabled
				? {
						plaintext: textAttachment.trim(),
						...(textAttachmentUrl.trim()
							? { link_attachment_url: textAttachmentUrl.trim() }
							: {}),
						...(textAttachmentStyles.trim()
							? {
									text_with_styling_info: buildTextAttachmentStyles(
										textAttachment,
										textAttachmentStyles,
									),
								}
							: {}),
					}
				: undefined;

		// `schedule` + `queue` both persist a scheduled post. Queue mode picks
		// the next best hour (from useBestPostingTimes) when the operator has
		// enough published history; otherwise falls back to a one-hour lookahead.
		const scheduledIso = (() => {
			if (scheduleMode === "schedule") {
				const local = new Date(`${scheduleDate}T${scheduleTime}`);
				return Number.isNaN(local.getTime()) ? null : local.toISOString();
			}
			if (scheduleMode === "queue") {
				const hasBest =
					bestTimes.hasEnoughData && bestTimes.topHours.length > 0;
				if (hasBest) {
					// Find the earliest upcoming occurrence of any topHour — prefer today
					// if one is still ahead, otherwise roll to tomorrow.
					const now = new Date();
					let candidate: Date | null = null;
					for (const hour of bestTimes.topHours) {
						const today = new Date(now);
						today.setHours(hour, 0, 0, 0);
						const chosen =
							today.getTime() > now.getTime() + 15 * 60_000
								? today
								: new Date(today.getTime() + 24 * 60 * 60 * 1000);
						if (!candidate || chosen.getTime() < candidate.getTime())
							candidate = chosen;
					}
					if (candidate) return candidate.toISOString();
				}
				const later = new Date();
				later.setHours(later.getHours() + 1, 0, 0, 0);
				return later.toISOString();
			}
			return null;
		})();

		if (scheduleMode === "schedule" && !scheduledIso) {
			setIsSubmitting(false);
			setPublishStage(null);
			appToast.error("Invalid schedule time");
			return;
		}

		const status = scheduleMode === "now" ? "published" : "scheduled";
		const composerMetadata = {
			post_health_score: postHealth.score,
			post_health_issues: postHealth.issues,
			preview_surface: preview,
			manual_publish_setup_state: isInstagramNativeHandoff
				? pushSetupState(pushHealth)
				: "not_applicable",
			first_post_wizard_step: "schedule",
			readiness_state: publishingReadinessState,
			readiness_issue_ids: publishingReadinessIssues
				.filter((issue) => issue.state !== "ready")
				.map((issue) => issue.id),
		};

		const results = await Promise.allSettled(
			targets.map((target, targetIndex) => {
				const igMediaType =
					target.platform === "instagram"
						? igType === "reels"
							? "REELS"
							: igType === "story"
								? "STORIES"
								: mediaUrls.length > 1
									? "CAROUSEL"
									: "IMAGE"
						: undefined;

				return createPost({
					idempotencyKey: `composer:${submitId}:${target.id}:${targetIndex}`,
					asyncPublish: scheduleMode === "now",
					onPublishStage: setPublishStage,
					content: caption,
					mediaUrls,
					mediaAltTexts: media.map((item) => item.alt),
					status,
					scheduledDate: scheduledIso,
					publishMode:
						scheduleMode === "schedule" && target.platform === "instagram"
							? publishMode
							: "auto",
					platform: target.platform,
					accountId: target.platform === "threads" ? target.id : undefined,
					instagramAccountId:
						target.platform === "instagram" ? target.id : undefined,
					igMediaType,
					altText:
						target.platform === "instagram" || target.platform === "threads"
							? (firstAlt ?? null)
							: undefined,
					topics: topicsList,
					linkUrl: linkAttach || undefined,
					locationId:
						target.platform === "instagram"
							? igLocation || undefined
							: tLocation || undefined,
					collaborators:
						target.platform === "instagram" && collaborators.length
							? collaborators
							: undefined,
					isSpoiler: spoiler || undefined,
					pollAttachment:
						pollEnabled && pollOptions.filter((o) => o.trim()).length >= 2
							? { options: pollOptions.filter((o) => o.trim()) }
							: undefined,
					textSpoilers:
						target.platform === "threads" && textSpoilers.length > 0
							? textSpoilers
							: undefined,
					gifAttachment:
						target.platform === "threads" && gifId.trim() && !pollEnabled
							? { gifId: gifId.trim(), provider: gifProvider }
							: undefined,
					textAttachment:
						target.platform === "threads" ? textAttachmentPayload : undefined,
					allowlistedCountryCodes,
					isGhostPost: ghostPost || undefined,
					ghostDuration:
						target.platform === "threads" && ghostPost
							? ghostDuration
							: undefined,
					isTrialReel:
						target.platform === "instagram" && igType === "reels" && trialReel
							? true
							: undefined,
					settings: {
						allowReplies: true,
						whoCanReply: toWhoCanReply(replyControl),
					},
					// Previously-dropped Composer fields — now plumbed through to posts
					persona: persona || undefined,
					crossreshareToIg:
						target.platform === "threads" ? crossFb || undefined : undefined,
					crossreshareToIgDarkMode:
						target.platform === "threads" && crossFb
							? crossIgDarkMode || undefined
							: undefined,
					firstComment: firstComment || undefined,
					userTags: target.platform === "instagram" ? igUserTags : undefined,
					productTags:
						target.platform === "instagram" ? igProductTags : undefined,
					isPaidPartnership:
						target.platform === "instagram" && isPaidPartnership
							? true
							: undefined,
					brandedContentSponsorIds:
						target.platform === "instagram" &&
						isPaidPartnership &&
						igBrandedContentSponsorIds.length
							? igBrandedContentSponsorIds
							: undefined,
					shareToFeed:
						target.platform === "instagram" && igType === "reels"
							? shareToFeed
							: undefined,
					graduation:
						target.platform === "instagram" && igType === "reels" && trialReel
							? graduation
							: undefined,
					thumbOffset:
						target.platform === "instagram" && igType === "reels"
							? reelCover
							: undefined,
					reelCover:
						target.platform === "instagram" && igType === "reels"
							? reelCover
							: undefined,
					coverUrl:
						target.platform === "instagram" && igType === "reels"
							? coverUrl || undefined
							: undefined,
					audioName:
						target.platform === "instagram" && igType === "reels"
							? audioName || undefined
							: undefined,
					igAudioId:
						target.platform === "instagram" && igType === "reels"
							? igAudioId || undefined
							: undefined,
					commentEnabled:
						target.platform === "instagram" && igType !== "story"
							? commentEnabled
							: undefined,
					threadChain:
						target.platform === "threads"
							? threadChain || undefined
							: undefined,
					quoteUrl:
						target.platform === "threads" ? quoteUrl || undefined : undefined,
					replyToId: replyToId || undefined,
					replyApprovalMode:
						target.platform === "threads" &&
						replyApprovalMode === "manual_approval"
							? replyApprovalMode
							: undefined,
					metadata: composerMetadata,
				});
			}),
		);

		const failures = results.filter((r) => r.status === "rejected");
		const successes = results.length - failures.length;
		setIsSubmitting(false);
		setPublishStage(null);

		if (successes === 0) {
			const firstError =
				failures[0]?.status === "rejected" &&
				failures[0].reason instanceof Error
					? failures[0].reason.message
					: undefined;
			const requestId =
				failures[0]?.status === "rejected"
					? getErrorRequestId(failures[0].reason)
					: null;
			haptics.error();
			trackClientEvent("composer_schedule_failure", {
				mode: scheduleMode,
				target_count: targets.length,
				post_health_score: postHealth.score,
			});
			appToast.error(
				scheduleMode === "now" ? "Publish failed" : "Schedule failed",
				{ description: joinToastDetails(firstError, requestId) },
			);
			return;
		}

		const label =
			scheduleMode === "now"
				? successes === 1
					? "Post published"
					: `Published to ${successes} accounts`
				: scheduleMode === "schedule"
					? successes === 1
						? "Post scheduled"
						: `Scheduled for ${successes} accounts`
					: `Added to queue for ${successes} ${successes === 1 ? "account" : "accounts"}`;

		const description =
			scheduleMode === "schedule"
				? publishMode === "notify" && platformsInTargets.has("instagram")
					? `Juno33 will remind you at ${scheduleTime}.`
					: `Scheduled for ${scheduleDate} at ${scheduleTime}.`
				: scheduleMode === "queue"
					? "Juno33 will place it in each account queue."
					: `Sent to ${successes} ${successes === 1 ? "account" : "accounts"}.`;

		if (failures.length > 0) {
			haptics.warning();
			trackClientEvent("composer_schedule_failure", {
				mode: scheduleMode,
				target_count: targets.length,
				success_count: successes,
				post_health_score: postHealth.score,
			});
			appToast.warn(`${label} — ${failures.length} failed`, {
				description: joinToastDetails(
					failures[0]?.status === "rejected" &&
						failures[0].reason instanceof Error
						? failures[0].reason.message
						: description,
					failures[0]?.status === "rejected"
						? getErrorRequestId(failures[0].reason)
						: null,
				),
			});
		} else {
			haptics.success();
			trackClientEvent("composer_schedule_success", {
				mode: scheduleMode,
				target_count: targets.length,
				post_health_score: postHealth.score,
				notify: isInstagramNativeHandoff,
			});
			recordActivity(
				scheduleMode === "now" ? "Post submitted" : "Post scheduled",
				`${successes} target${successes === 1 ? "" : "s"} · health ${postHealth.score}`,
			);
			appToast.success(label, { description });
		}

		resetDraft();
		if (composer.isOpen) {
			composer.close();
		}
		// Refresh the overview "latest draft" widget + any draft-count surfaces.
		// useLatestDraft listens on this event; saveLocal in useComposerDrafts
		// fires the same one. Fleet metrics / top posts refresh via the
		// in-memory hook cache's 30s freshness window + realtime subs.
		if (typeof window !== "undefined") {
			window.dispatchEvent(new CustomEvent("juno33:composer-drafts-updated"));
		}
	};

	const publishStatusLabel =
		isSubmitting && publishStage ? publishStageLabels[publishStage] : null;
	const composerCheckLabel =
		publishStatusLabel ??
		(submitBlockers.length
			? `${submitBlockers.length} check${submitBlockers.length === 1 ? "" : "s"}`
			: "Preflight ready");
	const composerCheckTitle =
		publishStatusLabel ??
		(submitBlockers.length
			? submitBlockers.slice(0, 3).join(" / ")
			: "Composer checks are clear. Server preflight also checks token health and media URLs before posting.");
	const submitCtaLabel =
		publishStatusLabel ??
		(scheduleMode === "now"
			? `Post to ${targets.length || 0}`
			: scheduleMode === "schedule"
				? "Schedule post"
				: "Add to queue");
	const mobileSubmitLabel =
		publishStatusLabel ??
		(scheduleMode === "now"
			? "Post"
			: scheduleMode === "schedule"
				? "Schedule"
				: "Queue");

	return (
		<NovaScreen width="full" density="compact" className="pb-28 lg:pb-8">
			<NovaHeader
				eyebrow="Composer"
				title="Compose"
				meta={
					targets.length
						? `${targets.length} target${targets.length === 1 ? "" : "s"}`
						: "Draft"
				}
				description={
					<>
						<strong className="font-semibold text-foreground">
							Write the post, add media, choose when it ships.
						</strong>{" "}
						Preview and scheduling stay visible; deeper tuning lives under
						advanced controls.
					</>
				}
				filters={
					<>
						<Badge tone="oxblood">Targets {targets.length}</Badge>
						<Badge tone="secondary">
							{[
								platformsInTargets.has("threads") ? "Threads" : null,
								platformsInTargets.has("instagram")
									? igType === "reels"
										? "Reels"
										: igType === "story"
											? "Stories"
											: "IG feed"
									: null,
							]
								.filter(Boolean)
								.join(" + ") || "No surfaces"}
						</Badge>
						<Badge tone={scheduleMode === "now" ? "secondary" : "oxblood"}>
							{scheduleMode === "now"
								? "Now"
								: scheduleMode === "schedule"
									? "Scheduled"
									: "Queue"}
						</Badge>
					</>
				}
				actions={
					<NovaToolbar className="hidden text-[0.6875rem] text-muted-foreground md:flex">
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => setCommandOpen(true)}
						>
							<CommandIcon data-icon="inline-start" aria-hidden="true" />
							Composer
						</Button>
						<Kbd>C</Kbd>
						<span>new post</span>
						<span className="mx-1 h-3 w-px bg-border" aria-hidden="true" />
						<Kbd>⌘J</Kbd>
						<span>composer</span>
						<span className="mx-1 h-3 w-px bg-border" aria-hidden="true" />
						<Kbd>⌘K</Kbd>
						<span>commands</span>
					</NovaToolbar>
				}
			/>
			<div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-6">
				{/* ==================================================================
             EDITOR PANEL
             ================================================================== */}
				<NovaSection className="gap-5">
					{targets.length === 0 && !caption.trim() && media.length === 0 && (
						<>
							<PublishingStartCard surface="composer_empty" />
							<SampleDraftPanel
								hasAccounts={connectedAccounts.length > 0}
								onUseSample={applySampleDraft}
								onPickAccount={() => setPickerOpen(true)}
							/>
						</>
					)}
					{/* --- Targeting ---------------------------------------------- */}
					<NovaCard contentClassName="p-4">
						<div className="flex items-center justify-between mb-3">
							<div className="flex items-center gap-1.5">
								<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
									Platform & accounts
								</span>
								{targets.length > 0 && (
									<span className="text-[0.65625rem] text-muted-foreground tabular-nums">
										· {targets.length}{" "}
										{targets.length === 1 ? "account" : "accounts"} ·{" "}
										{groupsInTargets.size}{" "}
										{groupsInTargets.size === 1 ? "group" : "groups"}
									</span>
								)}
							</div>
							{targets.length > 0 && (
								<Button
									type="button"
									variant="ghost"
									size="sm"
									onClick={clearTargets}
									className="h-7 px-2 text-[0.6875rem]"
								>
									Clear
								</Button>
							)}
						</div>

						<div className="flex items-start flex-wrap gap-1.5">
							{targets.map((a) => (
								<AccountChip
									key={a.id}
									account={a}
									onRemove={() => removeAccount(a.id)}
								/>
							))}

							<AccountPickerPopover
								open={pickerOpen}
								onOpenChange={setPickerOpen}
								trigger={
									<Button
										type="button"
										variant="outline"
										size="sm"
										className="h-7 rounded-full px-2.5 text-[0.75rem]"
									>
										<Plus data-icon="inline-start" aria-hidden="true" />
										Add accounts
									</Button>
								}
								selectedIds={targetIds}
								accounts={connectedAccounts}
								onToggle={(id) =>
									targetIds.includes(id) ? removeAccount(id) : addAccount(id)
								}
							/>
							<GroupPopover
								open={groupOpen}
								onOpenChange={setGroupOpen}
								trigger={
									<Button
										type="button"
										variant={activeGroup ? "secondary" : "outline"}
										size="sm"
										className={cn(
											"h-7 rounded-full px-2.5 text-[0.75rem]",
											activeGroup && "text-[color:var(--color-oxblood)]",
										)}
									>
										<Users data-icon="inline-start" aria-hidden="true" />
										{activeGroup
											? (groupPresets.find((g) => g.id === activeGroup)
													?.label ?? "Groups")
											: "Groups"}
										<ChevronDown data-icon="inline-end" aria-hidden="true" />
									</Button>
								}
								activeGroup={activeGroup}
								presets={groupPresets}
								selectedAccountIds={targetIds}
								onSelect={applyGroup}
								onCreate={async (name, color) => {
									if (targetIds.length === 0) return null;
									const g = await createGroup({
										name,
										color,
										accountIds: targetIds,
									});
									if (g) setActiveGroup(g.id);
									return g;
								}}
							/>
						</div>

						{canShowInstagramOptions && (
							<div className="mt-4 grid grid-cols-1 gap-3 border-t border-border pt-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,0.8fr)]">
								<div>
									<div className="mb-1.5 flex items-center justify-between gap-2">
										<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
											Instagram type
										</span>
										<span className="text-[0.6875rem] text-muted-foreground">
											Sets validation + preview
										</span>
									</div>
									<div
										className="grid grid-cols-3 gap-1.5"
										role="radiogroup"
										aria-label="Instagram post type"
									>
										{[
											{
												value: "feed" as IGPostType,
												label: "Feed",
												Icon: ImageIcon,
											},
											{
												value: "reels" as IGPostType,
												label: "Reel",
												Icon: Film,
											},
											{
												value: "story" as IGPostType,
												label: "Story",
												Icon: Play,
											},
										].map(({ value, label, Icon }) => {
											const active = igType === value;
											return (
												<Button
													key={value}
													type="button"
													role="radio"
													aria-checked={active}
													onClick={() => setInstagramPostType(value)}
													variant={active ? "secondary" : "outline"}
													size="sm"
													className="h-9 justify-center"
												>
													<Icon data-icon="inline-start" aria-hidden="true" />
													{label}
												</Button>
											);
										})}
									</div>
								</div>

								<div>
									<div className="mb-1.5 flex items-center justify-between gap-2">
										<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
											Publish mode
										</span>
										<span className="text-[0.6875rem] text-muted-foreground">
											Instagram schedule
										</span>
									</div>
									{scheduleMode === "schedule" ? (
										<PublishModeRadio
											publishMode={publishMode}
											onPublishModeChange={setPublishMode}
										/>
									) : (
										<Button
											type="button"
											onClick={() => setScheduleMode("schedule")}
											variant="outline"
											size="sm"
											className="h-9 w-full justify-center"
										>
											<Send data-icon="inline-start" aria-hidden="true" />
											Auto-publish
											<span className="hidden text-muted-foreground sm:inline">
												· schedule for Notify me
											</span>
										</Button>
									)}
								</div>
							</div>
						)}

						{targets.length === 0 &&
							(connectedAccounts.length === 0 ? (
								<div
									className="mt-3 rounded-md border px-3 py-2.5 text-[0.78125rem] leading-[1.45]"
									style={{
										backgroundColor:
											"color-mix(in srgb, var(--color-oxblood) 6%, transparent)",
										borderColor:
											"color-mix(in srgb, var(--color-oxblood) 20%, transparent)",
									}}
								>
									<div className="font-medium text-foreground">
										Connect an account before composing.
									</div>
									<Link
										to="/accounts"
										className="mt-1 inline-flex items-center gap-1 font-semibold text-[color:var(--color-oxblood)]"
									>
										Connect account →
									</Link>
								</div>
							) : (
								<div className="mt-3 text-[0.71875rem] text-muted-foreground">
									Pick at least one account to publish. You can add a whole
									group.
								</div>
							))}
					</NovaCard>

					{/* --- Caption + AI ----------------------------------------- */}
					<NovaCard contentClassName="p-4">
						<div className="flex items-center justify-between mb-3">
							<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
								Caption
							</span>
							<div className="flex items-center gap-3 text-[0.65625rem] tabular-nums">
								<Button
									type="button"
									onClick={() => setVoiceFileOpen(true)}
									disabled={!voiceGroupId}
									variant="ghost"
									size="sm"
									className="h-7 px-2 text-[0.6875rem]"
								>
									Voice file
								</Button>
								{platformsInTargets.has("threads") && (
									<CounterPill
										current={threadsCaptionBytes}
										max={THREADS_LIMIT}
										label="Threads"
									/>
								)}
								{platformsInTargets.has("instagram") && (
									<CounterPill
										current={caption.length}
										max={IG_LIMIT}
										label="Instagram"
									/>
								)}
							</div>
						</div>

						{replyToId && (
							<div className="flex items-center gap-2 mb-2 px-2.5 py-1.5 rounded-md bg-[color-mix(in_srgb,var(--color-oxblood)_6%,transparent)] border border-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)] text-[0.71875rem] text-oxblood">
								<Reply className="w-3 h-3 shrink-0" aria-hidden="true" />
								<span className="flex-1 truncate">
									Replying to post{" "}
									<span className="font-mono opacity-70">
										{replyToId.slice(-8)}
									</span>
								</span>
								<Button
									type="button"
									aria-label="Clear reply context"
									onClick={() => setReplyToId(null)}
									variant="ghost"
									size="icon"
									className="size-6 shrink-0"
								>
									<X data-icon="inline-start" aria-hidden="true" />
								</Button>
							</div>
						)}

						<Textarea
							ref={captionRef}
							value={caption}
							onChange={(e) => onCaptionChange(e.target.value)}
							onKeyDown={(event) => {
								if (event.key === "Tab" && ghostSuggestion) {
									event.preventDefault();
									acceptGhostSuggestion();
								}
							}}
							placeholder="What's the post?"
							rows={4}
							className="min-h-[142px] resize-none text-base leading-[1.55] md:text-[0.9375rem]"
						/>
						{ghostSuggestion && (
							<Button
								type="button"
								onClick={acceptGhostSuggestion}
								variant="outline"
								size="sm"
								className="mt-1 max-w-full justify-start border-dashed text-left text-[0.75rem]"
							>
								<span className="truncate">{ghostSuggestion.trim()}</span>
								<Kbd className="shrink-0">Tab</Kbd>
							</Button>
						)}
						<ChannelHealthPills accounts={targets} />

						<div className="mt-3 flex items-center flex-wrap gap-1.5 border-t border-border pt-3">
							<span className="inline-flex items-center gap-1 text-[0.65625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground mr-1">
								<Sparkles
									className="w-3 h-3"
									style={{ color: "var(--color-oxblood)" }}
									aria-hidden="true"
								/>
								AI
							</span>
							{[
								{ label: "Rephrase", action: "rephrase" as const },
								{ label: "Spin", action: "spin" as const },
								{ label: "Shorten", action: "shorten" as const },
								{ label: "Expand", action: "expand" as const },
								{ label: "Translate", action: "translate" as const },
							].map(({ label, action }) => {
								const busy = aiRunning === action;
								return (
									<Button
										key={label}
										type="button"
										onClick={() => runAIAction(action)}
										disabled={aiRunning !== null || !caption.trim()}
										variant="outline"
										size="sm"
										className="h-7 rounded-full px-2.5 text-[0.71875rem]"
									>
										{busy ? (
											<>
												<MatrixLoader
													label={`${label} AI action running`}
													size="sm"
													className="-ml-1 -mr-0.5 scale-75"
												/>
												{label}…
											</>
										) : (
											label
										)}
									</Button>
								);
							})}
							<Button
								type="button"
								onClick={runMatchVoice}
								disabled={
									aiRunning !== null ||
									!caption.trim() ||
									targetIds.length !== 1
								}
								title={
									targetIds.length !== 1
										? "Pick exactly one target account to match its voice"
										: `Match @${targets[0]?.handle.replace(/^@/, "")}'s voice`
								}
								variant={targetIds.length === 1 ? "secondary" : "outline"}
								size="sm"
								className="h-7 rounded-full px-2.5 text-[0.71875rem]"
							>
								<Sparkles data-icon="inline-start" aria-hidden="true" />
								{aiRunning === "matchVoice" ? (
									<>
										<MatrixLoader
											label="Matching voice"
											size="sm"
											className="-ml-1 -mr-0.5 scale-75"
										/>
										Matching voice…
									</>
								) : targetIds.length === 1 ? (
									`Match voice: @${targets[0]?.handle.replace(/^@/, "")}`
								) : (
									"Match voice"
								)}
							</Button>
							<div className="mx-1 w-px h-4 bg-border" aria-hidden="true" />
							<Button
								type="button"
								role="switch"
								aria-checked={isHero}
								aria-label="Mark as hero post — routes AI to Claude Haiku 4.5"
								onClick={() => setIsHero((v) => !v)}
								title={
									isHero
										? "Hero on — tone-critical AI routing (Claude Haiku 4.5)"
										: "Mark hero — route AI to tone-critical model for this draft"
								}
								variant={isHero ? "secondary" : "outline"}
								size="sm"
								className="h-7 rounded-full px-2.5 text-[0.71875rem]"
							>
								<Flame data-icon="inline-start" aria-hidden="true" />
								Hero
							</Button>
							<div className="mx-1 w-px h-4 bg-border" aria-hidden="true" />
							<div className="relative inline-flex items-center">
								<Select
									aria-label="Composer persona"
									value={persona}
									onChange={(event) =>
										setPersona(event.target.value as PersonaVoice)
									}
									sizeVariant="sm"
									className="h-7 rounded-full pr-7 text-[0.71875rem]"
									options={(Object.keys(PERSONA_LABEL) as PersonaVoice[]).map(
										(v) => ({
											value: v,
											label: PERSONA_LABEL[v],
										}),
									)}
								/>
								<ChevronDown
									className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none"
									aria-hidden="true"
								/>
							</div>
						</div>
					</NovaCard>

					{/* --- Media ------------------------------------------------ */}
					<MediaGrid
						media={media}
						onReorder={setMedia}
						libraryMedia={libraryMedia}
						editingAltId={editingAltId}
						editingAltItem={editingAltItem}
						altDraft={altDraft}
						onAltDraftChange={setAltDraft}
						onBeginEditAlt={beginEditAlt}
						onSaveAlt={saveAlt}
						onCancelAlt={cancelAlt}
						onAltGenerated={setGeneratedAlt}
						onRemoveMedia={removeMedia}
						onMoveMedia={moveMedia}
						onOpenPicker={openMediaPicker}
						onFilesSelected={handleFilesSelected}
						fileInputRef={fileInputRef}
					/>

					{bulkQueue.length > 0 && (
						<BulkUploadQueuePanel
							items={bulkQueue}
							onUpdate={updateBulkQueueItem}
							onRemove={removeBulkQueueItem}
							onMove={moveBulkQueueItem}
							onAttach={attachBulkItemToCurrentPost}
							onCreateDrafts={() => void createPostsFromBulkQueue("draft")}
							onScheduleSelected={() =>
								void createPostsFromBulkQueue("scheduled")
							}
							disabled={isSubmitting}
						/>
					)}

					<div className="flex items-center justify-between gap-3 border-t border-border pt-3">
						<Button
							type="button"
							onClick={() => setAdvancedOpen((open) => !open)}
							aria-expanded={advancedOpen}
							variant="outline"
							size="sm"
							className="h-9"
						>
							<SlidersHorizontal data-icon="inline-start" aria-hidden="true" />
							Advanced controls
							<span className="text-muted-foreground">
								{advancedOpen ? "Hide" : "Show"}
							</span>
						</Button>
						<Badge tone="outline">{composerModeLabel[composerMode]}</Badge>
					</div>

					{advancedOpen && (
						<div className="flex flex-col gap-4">
							<VariantsLab
								variants={variants}
								generating={variantsRunning}
								onGenerate={generateVariants}
								onSelect={selectVariant}
								onPromote={promoteVariant}
							/>

							<CrossPostDiffResolver
								diffs={diffs}
								onAccept={(diff) => {
									setCaption(diff.variant_caption);
									void updateComposerDiff(diff.id, "accepted").then((next) =>
										setDiffs((prev) =>
											prev.map((item) => (item.id === next.id ? next : item)),
										),
									);
								}}
								onRevert={(diff) => {
									setCaption(diff.master_caption);
									void updateComposerDiff(diff.id, "reverted").then((next) =>
										setDiffs((prev) =>
											prev.map((item) => (item.id === next.id ? next : item)),
										),
									);
								}}
							/>

							{canShowThreadsOptions && (
								<ThreadsOptionsPanel
									targets={targets}
									open={threadsOpen}
									onToggle={focusThreadsOptions}
									options={{
										replyControl,
										topicTag,
										location: tLocation,
										quoteUrl,
										linkAttach,
										textSpoilerTerms,
										gifId,
										gifProvider,
										textAttachment,
										textAttachmentUrl,
										textAttachmentStyles,
										geoGate,
										replyApprovalMode,
										threadChain,
										spoiler,
										ghostPost,
										ghostDuration,
										pollEnabled,
										pollOptions,
										crossFb,
										crossIgDarkMode,
									}}
									onChange={(patch: Partial<ThreadsOptions>) => {
										if (patch.replyControl !== undefined)
											setReplyControl(patch.replyControl);
										if (patch.topicTag !== undefined)
											setTopicTag(patch.topicTag);
										if (patch.location !== undefined)
											setTLocation(patch.location);
										if (patch.quoteUrl !== undefined)
											setQuoteUrl(patch.quoteUrl);
										if (patch.linkAttach !== undefined)
											setLinkAttach(patch.linkAttach);
										if (patch.textSpoilerTerms !== undefined)
											setTextSpoilerTerms(patch.textSpoilerTerms);
										if (patch.gifId !== undefined) setGifId(patch.gifId);
										if (patch.gifProvider !== undefined)
											setGifProvider(patch.gifProvider);
										if (patch.textAttachment !== undefined)
											setTextAttachment(patch.textAttachment);
										if (patch.textAttachmentUrl !== undefined)
											setTextAttachmentUrl(patch.textAttachmentUrl);
										if (patch.textAttachmentStyles !== undefined)
											setTextAttachmentStyles(patch.textAttachmentStyles);
										if (patch.geoGate !== undefined) setGeoGate(patch.geoGate);
										if (patch.replyApprovalMode !== undefined)
											setReplyApprovalMode(patch.replyApprovalMode);
										if (patch.threadChain !== undefined)
											setThreadChain(patch.threadChain);
										if (patch.spoiler !== undefined) setSpoiler(patch.spoiler);
										if (patch.ghostPost !== undefined)
											setGhostPost(patch.ghostPost);
										if (patch.ghostDuration !== undefined)
											setGhostDuration(patch.ghostDuration);
										if (patch.pollEnabled !== undefined)
											setPollEnabled(patch.pollEnabled);
										if (patch.pollOptions !== undefined)
											setPollOptions(patch.pollOptions);
										if (patch.crossFb !== undefined) setCrossFb(patch.crossFb);
										if (patch.crossIgDarkMode !== undefined)
											setCrossIgDarkMode(patch.crossIgDarkMode);
									}}
								/>
							)}

							{canShowInstagramOptions && (
								<InstagramOptionsPanel
									targets={targets}
									open={igOpen}
									onToggle={focusInstagramOptions}
									showPostType={false}
									options={{
										igType,
										firstComment,
										location: igLocation,
										collaborators,
										collaboratorDraft,
										userTags,
										productTags,
										isPaidPartnership,
										brandedContentSponsorIds,
										reelCover,
										coverUrl,
										audioName,
										igAudioId,
										igAudioTitle,
										igAudioArtist,
										igAudioType,
										shareToFeed,
										trialReel,
										graduation,
										commentEnabled,
									}}
									onChange={(patch: Partial<InstagramOptions>) => {
										if (patch.igType !== undefined) setIgType(patch.igType);
										if (patch.firstComment !== undefined)
											setFirstComment(patch.firstComment);
										if (patch.location !== undefined)
											setIgLocation(patch.location);
										if (patch.collaborators !== undefined)
											setCollaborators(patch.collaborators);
										if (patch.collaboratorDraft !== undefined)
											setCollaboratorDraft(patch.collaboratorDraft);
										if (patch.userTags !== undefined)
											setUserTags(patch.userTags);
										if (patch.productTags !== undefined)
											setProductTags(patch.productTags);
										if (patch.isPaidPartnership !== undefined)
											setIsPaidPartnership(patch.isPaidPartnership);
										if (patch.brandedContentSponsorIds !== undefined)
											setBrandedContentSponsorIds(
												patch.brandedContentSponsorIds,
											);
										if (patch.reelCover !== undefined)
											setReelCover(patch.reelCover);
										if (patch.coverUrl !== undefined)
											setCoverUrl(patch.coverUrl);
										if (patch.audioName !== undefined)
											setAudioName(patch.audioName);
										if (patch.igAudioId !== undefined)
											setIgAudioId(patch.igAudioId);
										if (patch.igAudioTitle !== undefined)
											setIgAudioTitle(patch.igAudioTitle);
										if (patch.igAudioArtist !== undefined)
											setIgAudioArtist(patch.igAudioArtist);
										if (patch.igAudioType !== undefined)
											setIgAudioType(patch.igAudioType);
										if (patch.shareToFeed !== undefined)
											setShareToFeed(patch.shareToFeed);
										if (patch.trialReel !== undefined)
											setTrialReel(patch.trialReel);
										if (patch.graduation !== undefined)
											setGraduation(patch.graduation);
										if (patch.commentEnabled !== undefined)
											setCommentEnabled(patch.commentEnabled);
									}}
								/>
							)}
						</div>
					)}
				</NovaSection>

				{/* ==================================================================
             PREVIEW + SCHEDULE PANEL — hidden on mobile (accessible via sheets)
             ================================================================== */}
				<NovaSection className="hidden gap-5 lg:flex">
					<NovaCard className="overflow-hidden" contentClassName="p-0">
						<header className="px-4 pt-3 pb-0 border-b border-border">
							<div
								role="tablist"
								aria-label="Preview mode"
								data-tablist="composer-preview-desktop"
								onKeyDown={onPreviewKeyDesktop}
								className="flex items-center gap-0"
							>
								{previewTabs.map((t) => {
									const active = preview === t.id;
									return (
										<Button
											key={t.id}
											type="button"
											variant="ghost"
											role="tab"
											aria-selected={active}
											data-tab-id={t.id}
											tabIndex={active ? 0 : -1}
											onClick={() => setPreview(t.id)}
											className={cn(
												"h-9 rounded-t-md px-3 text-[0.78125rem]",
												active
													? "bg-muted text-foreground shadow-sm"
													: "text-muted-foreground hover:text-foreground",
											)}
										>
											{t.label}
										</Button>
									);
								})}
							</div>
						</header>
						<div className="p-4">
							<PreviewMock
								mode={preview}
								caption={caption}
								media={media}
								account={targets[0] ?? null}
								replyControl={replyControl}
								igType={igType}
								firstComment={firstComment}
								trialReel={trialReel}
								pollOptions={pollEnabled ? pollOptions : null}
								spoiler={spoiler}
								topicTag={topicTag}
								collaborators={collaborators}
							/>
						</div>
					</NovaCard>

					<UnifiedPublishingReadinessCard
						checks={readinessChecks}
						setupIssues={publishingReadinessIssues}
						postHealth={postHealth}
						onCheckAction={(check) =>
							trackClientEvent("composer_readiness_fix_clicked", {
								check_id: check.id,
								tone: check.tone,
							})
						}
						onSetupIssueAction={(issue) =>
							trackClientEvent("account_readiness_action_clicked", {
								issue_id: issue.id,
								state: issue.state,
								surface: "composer",
							})
						}
					/>

					{isInstagramNativeHandoff && (
						<PhoneSetupPanel
							pushHealth={pushHealth}
							pushHealthBusy={pushHealthBusy}
							checks={phoneChecks}
							onToggle={(key) =>
								setPhoneChecks((current) => ({
									...current,
									[key]: !current[key],
								}))
							}
							onEnablePush={() => void enablePushForNotifyMe()}
							onTestPush={() => void sendTestNotification()}
						/>
					)}

					{mediaOptimizationSuggestions.length > 0 && (
						<MediaOptimizationPanel
							suggestions={mediaOptimizationSuggestions}
						/>
					)}

					<ActivityPanel
						activity={activity}
						open={activityOpen}
						onOpenChange={setActivityOpen}
					/>

					<ComposerIntelligencePanel
						contentKits={contentKits}
						captionKits={captionKits}
						trendIdeas={trendIdeas}
						loadingTrends={trendIdeasLoading}
						onApplyKit={applyContentKit}
						onSaveCurrent={saveCurrentAsContentKit}
						onUseTrend={(idea) => {
							const before = caption;
							setCaption(
								idea.adaptedContent || idea.originalPost.content || caption,
							);
							if (idea.topicTags?.[0]) setTopicTag(idea.topicTags[0]);
							recordActivity(
								"Trend draft loaded",
								idea.topicTags?.[0] || idea.competitorUsername || "Inspiration",
								() => setCaption(before),
							);
							appToast.success("Trend draft loaded");
						}}
					/>

					{advancedOpen && (
						<>
							<CritiquePanel critique={critique} loading={critiqueLoading} />

							<ComposerVisualPlanner
								media={media}
								drafts={drafts}
								target={targets[0] ?? null}
								scheduleDate={scheduleDate}
								scheduleTime={scheduleTime}
								scheduleMode={scheduleMode}
								onOpenMedia={openMediaPicker}
								onLoadDraft={loadDraft}
							/>
						</>
					)}

					<NovaCard contentClassName="p-4">
						<div className="flex items-center justify-between mb-3">
							<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
								Schedule
							</span>
							{bestTimesLabel ? (
								<span className="text-[0.65625rem] text-muted-foreground">
									Best time: {bestTimesLabel}
								</span>
							) : (
								<span className="text-[0.65625rem] text-muted-foreground">
									{bestTimes.isLoading
										? "Learning best times…"
										: "Best times need 5+ posts"}
								</span>
							)}
						</div>

						<div className="mb-3">
							<ScheduleModeRadio
								scheduleMode={scheduleMode}
								onScheduleModeChange={setScheduleMode}
							/>
						</div>

						{scheduleMode === "schedule" && (
							<div className="mb-3">
								<ScheduleDateTimePickers
									scheduleDate={scheduleDate}
									onScheduleDateChange={setScheduleDate}
									scheduleTime={scheduleTime}
									onScheduleTimeChange={setScheduleTime}
								/>
							</div>
						)}

						{scheduleMode === "queue" && (
							<div className="mb-3">
								<QueueModeHint />
							</div>
						)}

						<div className="flex items-center gap-2">
							<DraftsPopover
								open={draftsOpen}
								onOpenChange={setDraftsOpen}
								drafts={drafts}
								currentDraftId={currentDraftId}
								onLoad={loadDraft}
								onDelete={deleteDraft}
								trigger={
									<Button
										type="button"
										aria-haspopup="listbox"
										variant="outline"
										size="sm"
										className="h-9"
									>
										<Layers data-icon="inline-start" aria-hidden="true" />
										Drafts
										{drafts.length > 0 && (
											<Badge
												tone="oxblood"
												className="h-5 px-1.5 text-[0.625rem]"
											>
												{drafts.length}
											</Badge>
										)}
									</Button>
								}
							/>
							<Button
								type="button"
								onClick={handleSaveDraft}
								variant="outline"
								size="sm"
								className="h-9"
							>
								<FileText data-icon="inline-start" aria-hidden="true" />
								{isSavingDraft
									? "Saving…"
									: currentDraftId
										? "Update draft"
										: "Save draft"}
							</Button>

							<div
								className={cn(
									"hidden xl:inline-flex h-9 min-w-[168px] items-center gap-2 rounded-md border px-2.5 text-[0.75rem]",
									isSubmitting && publishStage
										? "border-[color-mix(in_srgb,var(--color-oxblood)_32%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_7%,transparent)] text-muted-foreground"
										: submitBlockers.length
											? "border-[color-mix(in_srgb,var(--color-gold)_36%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-gold)_8%,transparent)] text-muted-foreground"
											: "border-border bg-card text-muted-foreground",
								)}
								title={composerCheckTitle}
							>
								{submitBlockers.length ? (
									<AlertTriangle
										className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-gold)]"
										aria-hidden="true"
									/>
								) : isSubmitting ? (
									<Clock
										className="h-3.5 w-3.5 shrink-0 animate-pulse text-[color:var(--color-oxblood)]"
										aria-hidden="true"
									/>
								) : (
									<ShieldCheck
										className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-positive)]"
										aria-hidden="true"
									/>
								)}
								<span className="truncate">{composerCheckLabel}</span>
							</div>

							<Button
								type="button"
								disabled={!canPublish}
								onClick={handleSubmit}
								title={composerCheckTitle}
								size="sm"
								className="h-9 flex-1"
							>
								<Send data-icon="inline-start" aria-hidden="true" />
								{submitCtaLabel}
							</Button>
						</div>
					</NovaCard>
				</NovaSection>
			</div>

			<div className="fixed inset-x-0 bottom-0 z-[70] border-t border-border bg-card/95 px-3 pb-[calc(10px+env(safe-area-inset-bottom))] pt-2.5 shadow-lg backdrop-blur-md lg:hidden">
				<div className="mx-auto flex max-w-[720px] items-center gap-1.5">
					<ComposerMobileButton
						onClick={() => setMobilePreviewOpen(true)}
						label="Preview"
						icon={<Eye data-icon="inline-start" aria-hidden="true" />}
					/>
					<ComposerMobileButton
						onClick={() => setMobileScheduleOpen(true)}
						label={
							scheduleMode === "now"
								? "Now"
								: scheduleMode === "schedule"
									? "Scheduled"
									: "Queue"
						}
						icon={<Clock data-icon="inline-start" aria-hidden="true" />}
						highlighted={scheduleMode !== "now"}
					/>
					<ComposerMobileButton
						onClick={handleSaveDraft}
						label={isSavingDraft ? "…" : currentDraftId ? "Update" : "Save"}
						icon={<FileText data-icon="inline-start" aria-hidden="true" />}
					/>
					{readinessNeedsAttention && (
						<ComposerMobileButton
							onClick={() => setMobileReadinessOpen(true)}
							label="Checks"
							icon={<ShieldCheck data-icon="inline-start" aria-hidden="true" />}
							highlighted
						/>
					)}
					<Button
						type="button"
						disabled={!canPublish}
						onClick={handleSubmit}
						title={composerCheckTitle}
						className="h-11 shrink-0 flex-1 max-w-[130px] gap-1.5 text-[0.84375rem]"
					>
						<Send data-icon="inline-start" aria-hidden="true" />
						{mobileSubmitLabel}
					</Button>
				</div>
			</div>

			{/* Mobile PREVIEW sheet */}
			<Sheet
				open={mobilePreviewOpen}
				onClose={() => setMobilePreviewOpen(false)}
				title="Preview"
				side="bottom"
				widthClass="w-full lg:hidden"
				ariaLabel="Composer preview"
				panelClassName="max-h-[90dvh]"
			>
				<div className="p-4 pb-6 flex flex-col gap-4">
					<div
						role="tablist"
						aria-label="Preview mode"
						data-tablist="composer-preview-mobile"
						onKeyDown={onPreviewKeyMobile}
						className="inline-flex items-center p-[3px] bg-muted border border-border rounded-md self-start"
					>
						{previewTabs.map((t) => {
							const active = preview === t.id;
							return (
								<Button
									key={t.id}
									type="button"
									variant={active ? "secondary" : "ghost"}
									role="tab"
									aria-selected={active}
									data-tab-id={t.id}
									tabIndex={active ? 0 : -1}
									onClick={() => setPreview(t.id)}
									className={cn(
										"h-8 px-3.5 text-[0.78125rem]",
										active && "shadow-sm",
									)}
								>
									{t.label}
								</Button>
							);
						})}
					</div>
					<PreviewMock
						mode={preview}
						caption={caption}
						media={media}
						account={targets[0] ?? null}
						replyControl={replyControl}
						igType={igType}
						firstComment={firstComment}
						trialReel={trialReel}
						pollOptions={pollEnabled ? pollOptions : null}
						spoiler={spoiler}
						topicTag={topicTag}
						collaborators={collaborators}
					/>
				</div>
			</Sheet>

			{/* Mobile READINESS sheet */}
			<Sheet
				open={mobileReadinessOpen}
				onClose={() => setMobileReadinessOpen(false)}
				title="Readiness"
				side="bottom"
				widthClass="w-full lg:hidden"
				ariaLabel="Composer readiness"
				panelClassName="max-h-[90dvh]"
			>
				<div className="p-4 pb-6">
					<UnifiedPublishingReadinessCard
						checks={readinessChecks}
						setupIssues={publishingReadinessIssues}
						postHealth={postHealth}
						onCheckAction={(check) =>
							trackClientEvent("composer_readiness_fix_clicked", {
								check_id: check.id,
								tone: check.tone,
							})
						}
						onSetupIssueAction={(issue) =>
							trackClientEvent("account_readiness_action_clicked", {
								issue_id: issue.id,
								state: issue.state,
								surface: "composer_mobile",
							})
						}
					/>
				</div>
			</Sheet>

			{/* Mobile SCHEDULE sheet */}
			<Sheet
				open={mobileScheduleOpen}
				onClose={() => setMobileScheduleOpen(false)}
				title="Schedule"
				side="bottom"
				widthClass="w-full lg:hidden"
				ariaLabel="Composer schedule"
				panelClassName="max-h-[90dvh]"
			>
				<div className="p-4 pb-6 flex flex-col gap-4">
					<ScheduleModeRadio
						scheduleMode={scheduleMode}
						onScheduleModeChange={setScheduleMode}
						size="mobile"
					/>

					{scheduleMode === "schedule" && (
						<ScheduleDateTimePickers
							scheduleDate={scheduleDate}
							onScheduleDateChange={setScheduleDate}
							scheduleTime={scheduleTime}
							onScheduleTimeChange={setScheduleTime}
							size="mobile"
						/>
					)}

					{scheduleMode === "schedule" &&
						platformsInTargets.has("instagram") && (
							<PublishModeRadio
								publishMode={publishMode}
								onPublishModeChange={setPublishMode}
								size="mobile"
							/>
						)}

					{scheduleMode === "queue" && <QueueModeHint size="mobile" />}

					<div className="flex items-center justify-between text-[0.71875rem] text-muted-foreground">
						<span className="inline-flex items-center gap-1.5">
							<span
								className="w-1.5 h-1.5 rounded-full"
								style={{ background: "var(--color-oxblood)" }}
								aria-hidden="true"
							/>
							{bestTimesLabel ? (
								<>Best time for your audience: {bestTimesLabel}</>
							) : bestTimes.isLoading ? (
								"Learning best times from your history…"
							) : (
								"Publish 5+ posts to unlock audience best-time suggestions"
							)}
						</span>
					</div>

					<Button
						type="button"
						onClick={() => setMobileScheduleOpen(false)}
						className="h-11 text-[0.875rem]"
					>
						Done
					</Button>
				</div>
			</Sheet>
			<ComposerCommandPalette
				open={commandOpen}
				onOpenChange={setCommandOpen}
				commands={[
					{
						id: "upload",
						label: "Upload media",
						detail: "Open the file picker",
						run: openMediaPicker,
					},
					{
						id: "feed",
						label: "Switch to Instagram Feed",
						detail: "Use Feed validation and preview",
						run: () => {
							const before = igType;
							setIgType("feed");
							recordActivity("Post type changed", "Instagram Feed", () =>
								setIgType(before),
							);
						},
					},
					{
						id: "reel",
						label: "Switch to Instagram Reel",
						detail: "Use 9:16 Reel validation and preview",
						run: () => {
							const before = igType;
							setIgType("reels");
							recordActivity("Post type changed", "Instagram Reel", () =>
								setIgType(before),
							);
						},
					},
					{
						id: "story",
						label: "Switch to Instagram Story",
						detail: "Use Story preview and handoff-friendly framing",
						run: () => {
							const before = igType;
							setIgType("story");
							recordActivity("Post type changed", "Instagram Story", () =>
								setIgType(before),
							);
						},
					},
					{
						id: "notify",
						label: "Use Notify Me",
						detail: "Schedule native phone handoff",
						run: () => {
							const beforeMode = publishMode;
							const beforeSchedule = scheduleMode;
							setScheduleMode("schedule");
							setPublishMode("notify");
							recordActivity("Publish mode changed", "Notify Me", () => {
								setPublishMode(beforeMode);
								setScheduleMode(beforeSchedule);
							});
						},
					},
					{
						id: "auto",
						label: "Use Auto-publish",
						detail: "Use strict API publishing checks",
						run: () => {
							const before = publishMode;
							setPublishMode("auto");
							recordActivity("Publish mode changed", "Auto-publish", () =>
								setPublishMode(before),
							);
						},
					},
					{
						id: "schedule",
						label: "Open schedule controls",
						detail: "Review date, time, and queue mode",
						run: () => setMobileScheduleOpen(true),
					},
					{
						id: "draft",
						label: "Save draft",
						detail: "Persist this composer state",
						run: () => void handleSaveDraft(),
					},
					{
						id: "readiness",
						label: "Review readiness",
						detail: `${postHealth.score}/100 · ${postHealth.label}`,
						run: () => setAdvancedOpen(true),
					},
				]}
			/>
			<SlashMenu
				open={slashOpen}
				anchor={slashAnchor}
				commands={slashCommands}
				onClose={() => setSlashOpen(false)}
			/>
			<SelectionActionBar
				open={!!selectionBar}
				anchor={selectionBar ? { x: selectionBar.x, y: selectionBar.y } : null}
				onClose={() => setSelectionBar(null)}
				onRun={(action) => {
					if (action === "custom") {
						setCustomPromptSelection(
							selectionBar
								? { start: selectionBar.start, end: selectionBar.end }
								: null,
						);
						setCustomPromptOpen(true);
						return;
					}
					if (selectionBar) void runAIAction(action, selectionBar);
				}}
			/>
			<VoiceContextFile
				open={voiceFileOpen}
				groupId={voiceGroupId}
				onClose={() => setVoiceFileOpen(false)}
			/>
			<CustomPromptModal
				open={customPromptOpen}
				value={customPrompt}
				running={customPromptRunning}
				onChange={setCustomPrompt}
				onClose={() => {
					setCustomPromptOpen(false);
					setCustomPromptSelection(null);
				}}
				onRun={() => void runCustomPrompt()}
			/>
		</NovaScreen>
	);
}
