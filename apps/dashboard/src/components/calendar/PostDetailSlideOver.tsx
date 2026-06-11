// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Clock, Copy, PenSquare, Repeat2, Trash2, X } from "lucide-react";

const FOCUSABLE_SELECTOR = [
	"a[href]",
	"button:not([disabled])",
	"input:not([disabled])",
	"textarea:not([disabled])",
	"select:not([disabled])",
	'[tabindex]:not([tabindex="-1"])',
].join(",");
import { retryFailedPost } from "@/services/autopilotService";
import {
	fetchCampaignFactoryAudioEvents,
	formatCampaignFactoryAudioEventLine,
	updateCampaignFactoryAudioState,
	type CampaignFactoryAudioEvent,
} from "@/services/api/posts";
import { appToast } from "@/lib/toast";
import {
	formatCampaignFactoryReuseLabels,
	formatCampaignFactoryAudioStatus,
	formatCampaignFactoryScheduleMode,
	formatCampaignFactorySurface,
	getCampaignFactoryDailyProductionRows,
	getCampaignFactoryDetailRows,
	getCampaignFactoryLongDetailRows,
	getCampaignFactoryPerformanceLineage,
	getCampaignFactoryPerformancePayload,
	campaignFactoryAudioAllowsLive,
	isCampaignFactoryDraft,
	getCampaignFactoryMetadata,
} from "@/lib/campaignFactory";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Z } from "@/components/ui/overlayZ";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { labelFor, maxBodyChars } from "@/lib/socialPlatform";
import {
	DAY_NAMES_LONG,
	STATUS_STYLE,
	formatHour,
	type Post,
	type Status,
} from "./shared";

type AutopsyResult = {
	performance?: "above" | "below" | undefined;
	factors?:
		| Array<{ title?: string | undefined; explanation?: string | undefined }>
		| undefined;
	recommendation?: string | undefined;
};
type AutopsyState =
	| { status: "idle" }
	| { status: "loading" }
	| { status: "loaded"; result: AutopsyResult }
	| { status: "error"; message: string };

type SentimentVerdict =
	| "hype"
	| "drama"
	| "positive"
	| "neutral"
	| "negative"
	| "mixed";

type SentimentResult = {
	totalComments: number;
	sentimentScore: number;
	verdict: string;
	breakdown: {
		positive: number;
		negative: number;
		neutral: number;
		question: number;
	};
	llm?:
		| {
				overall_verdict: SentimentVerdict;
				summary: string;
				hype_score: number;
				drama_score: number;
				top_themes: string[];
				concerning_count: number;
		  }
		| undefined;
	llmSkipped?: boolean | undefined;
	degraded?: boolean | undefined;
};
type SentimentState =
	| { status: "idle" }
	| { status: "loading" }
	| { status: "loaded"; result: SentimentResult }
	| { status: "error"; message: string };
type AudioHistoryState =
	| { status: "idle" }
	| { status: "loading" }
	| { status: "loaded"; events: CampaignFactoryAudioEvent[] }
	| { status: "error"; message: string };

const VERDICT_COLORS: Record<SentimentVerdict, string> = {
	hype: "var(--color-health-good)",
	positive: "var(--color-health-good)",
	drama: "var(--color-oxblood)",
	negative: "var(--color-oxblood)",
	mixed: "var(--color-gold)",
	neutral: "var(--color-muted-foreground)",
};

/* =========================================================================
   POST DETAIL SLIDE-OVER — extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
export function PostDetailSlideOver({
	post,
	onClose,
	onSave,
	onDelete,
	onDuplicate,
	onRepost,
	onRetry,
	deleteDisabledReason,
}: {
	post: Post;
	onClose: () => void;
	onSave: (updated: Post) => Promise<void>;
	onDelete: (id: string) => Promise<void>;
	onDuplicate: (id: string) => void;
	onRepost?: ((post: Post) => Promise<void>) | undefined;
	onRetry: (id: string) => void;
	deleteDisabledReason?: string | null | undefined;
}) {
	const status = STATUS_STYLE[post.status];
	const platformLabel = labelFor(post.platform);
	const charLimit = maxBodyChars(post.platform);
	const campaignFactory = post.campaignFactory ?? null;
	const campaignFactorySurface = campaignFactory
		? formatCampaignFactorySurface(campaignFactory)
		: null;
	const campaignFactoryScheduleMode = campaignFactory
		? formatCampaignFactoryScheduleMode(campaignFactory)
		: null;
	const campaignFactoryAudioStatus = campaignFactory
		? formatCampaignFactoryAudioStatus(campaignFactory)
		: null;
	const campaignFactoryAudioReady = campaignFactory
		? campaignFactoryAudioAllowsLive(campaignFactory)
		: true;
	const campaignFactoryAudioDecision =
		campaignFactory?.audio_intent?.decision &&
		typeof campaignFactory.audio_intent.decision === "object"
			? campaignFactory.audio_intent.decision
			: null;
	const campaignFactoryPrimaryAudio =
		campaignFactoryAudioDecision?.primaryAudio &&
		typeof campaignFactoryAudioDecision.primaryAudio === "object"
			? (campaignFactoryAudioDecision.primaryAudio as Record<string, unknown>)
			: null;
	const campaignFactoryBackupAudios = Array.isArray(
		campaignFactoryAudioDecision?.backupAudios,
	)
		? (campaignFactoryAudioDecision.backupAudios.filter(
				(item) => item && typeof item === "object",
			) as Record<string, unknown>[])
		: [];
	const campaignFactoryAudioRecommendations =
		campaignFactory?.audio_intent?.recommendations || [];
	const isCampaignDraft = isCampaignFactoryDraft(post);
	const reuseLabels = post.campaignFactoryReuse
		? formatCampaignFactoryReuseLabels(post.campaignFactoryReuse)
		: [];
	const performanceLineage = getCampaignFactoryPerformanceLineage(post);
	const campaignFactoryDetailRows = campaignFactory
		? getCampaignFactoryDetailRows(campaignFactory)
		: [];
	const campaignFactoryDailyRows = campaignFactory
		? getCampaignFactoryDailyProductionRows(campaignFactory)
		: [];
	const campaignFactoryLongRows = campaignFactory
		? getCampaignFactoryLongDetailRows(campaignFactory)
		: [];
	const campaignFactoryPerformance = campaignFactory
		? getCampaignFactoryPerformancePayload({
				id: post.id,
				status: post.status,
				instagramAccountId: post.accountId,
				mediaUrls: post.mediaUrls,
				publishedAt: post.publishedAt,
				permalink: post.permalink,
				views_count: post.viewsCount,
				likes_count: post.likesCount,
				replies_count: post.repliesCount,
				shares_count: post.sharesCount,
				ig_views: post.igViews,
				ig_comment_count: post.igCommentCount,
				ig_reach: post.igReach,
				ig_saved: post.igSaved,
				ig_shares: post.igShares,
				campaignFactory,
			})
		: null;

	const [editing, setEditing] = useState(false);
	const [confirmDelete, setConfirmDelete] = useState(false);
	const [retrying, setRetrying] = useState(false);
	const [reposting, setReposting] = useState(false);
	const [saving, setSaving] = useState(false);
	const [deleting, setDeleting] = useState(false);
	const [draft, setDraft] = useState<Post>(post);
	const [autopsy, setAutopsy] = useState<AutopsyState>({ status: "idle" });
	const [sentiment, setSentiment] = useState<SentimentState>({
		status: "idle",
	});
	const [audioHistory, setAudioHistory] = useState<AudioHistoryState>({
		status: "idle",
	});
	const [audioProofAction, setAudioProofAction] = useState<
		"attached" | "verified" | null
	>(null);
	const [audioProofUrl, setAudioProofUrl] = useState("");
	const [audioProofNote, setAudioProofNote] = useState("");
	const [audioUpdating, setAudioUpdating] = useState(false);
	const panelRef = useRef<HTMLElement>(null);
	const cancelDeleteRef = useRef<HTMLButtonElement>(null);
	const returnFocusRef = useRef<HTMLElement | null>(null);

	const loadAudioHistory = useCallback(async () => {
		if (!campaignFactory) {
			setAudioHistory({ status: "idle" });
			return;
		}
		setAudioHistory({ status: "loading" });
		try {
			const events = await fetchCampaignFactoryAudioEvents({
				postId: post.id,
				campaignId: campaignFactory.campaign_id,
				renderedAssetId: campaignFactory.rendered_asset_id,
				limit: 5,
			});
			setAudioHistory({ status: "loaded", events });
		} catch (err) {
			setAudioHistory({
				status: "error",
				message: err instanceof Error ? err.message : "Audio history failed",
			});
		}
	}, [campaignFactory, post.id]);

	const updateNativeAudioStatus = async (
		status: "selected" | "attached" | "verified" | "skipped" | "blocked",
		proof: {
			url?: string | undefined;
			note?: string | undefined;
			selectedAudioId?: string | undefined;
		} = {},
	) => {
		if (!campaignFactory) return;
		const notes =
			status === "skipped" || status === "blocked"
				? window.prompt(
						status === "skipped"
							? "Why are we skipping native audio?"
							: "Why is this audio blocked?",
					) || ""
				: "";
		setAudioUpdating(true);
		try {
			const proofUrl = proof.url?.trim() || "";
			const proofNote = proof.note?.trim() || "";
			const result = await updateCampaignFactoryAudioState([post.id], status, {
				note: notes || undefined,
				proofUrl: proofUrl || undefined,
				proofType: proofUrl
					? "native_post_link"
					: proofNote
						? "operator_note"
						: undefined,
				proofNote: proofNote || undefined,
				selectedAudioId: proof.selectedAudioId || undefined,
			});
			const row = result.posts[0];
			if (!row) {
				appToast.info("No Campaign Factory audio state was updated.");
				return;
			}
			const nextMetadata = (
				row.metadata && typeof row.metadata === "object" ? row.metadata : {}
			) as Record<string, unknown>;
			const nextPost = {
				...post,
				metadata: nextMetadata,
				campaignFactory:
					getCampaignFactoryMetadata({ metadata: nextMetadata }) ??
					campaignFactory,
			};
			await onSave(nextPost);
			setDraft(nextPost);
			setAudioProofAction(null);
			setAudioProofUrl("");
			setAudioProofNote("");
			void loadAudioHistory();
		} finally {
			setAudioUpdating(false);
		}
	};

	// Lock body scroll while the slide-over is mounted. Without this the
	// calendar grid behind the panel scrolls freely on iOS Safari.
	useBodyScrollLock(true);

	// Auto-focus the first focusable inside the panel on mount. The Tab
	// handler below cycles within the panel, but without this the user
	// arrives with focus still on the calendar card they clicked, so
	// Tab walks into the panel from outside. Re-fires on post.id change
	// because the calendar swaps the post under the open panel; the dep
	// is intentional and not closure-derived.
	// biome-ignore lint/correctness/useExhaustiveDependencies: re-focus when a different post is opened
	useEffect(() => {
		const panel = panelRef.current;
		if (!panel) return;
		const first = panel.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
		first?.focus();
	}, [post.id]);

	// Reset draft + edit/delete state whenever a new post is opened
	useEffect(() => {
		setDraft(post);
		setEditing(false);
		setConfirmDelete(false);
		setRetrying(false);
		setSaving(false);
		setDeleting(false);
		setAutopsy({ status: "idle" });
		setSentiment({ status: "idle" });
		setAudioHistory({ status: "idle" });
		setAudioProofAction(null);
		setAudioProofUrl("");
		setAudioProofNote("");
		setAudioUpdating(false);
	}, [post.id, post]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		void loadAudioHistory();
	}, [loadAudioHistory]);

	// Tab-cycle focus trap + return-focus on close.
	useEffect(() => {
		returnFocusRef.current = document.activeElement as HTMLElement | null;
		const onKey = (e: KeyboardEvent) => {
			if (e.key !== "Tab") return;
			const panel = panelRef.current;
			if (!panel) return;
			const focusables = Array.from(
				panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
			).filter(
				(el) => !el.hasAttribute("disabled") && el.offsetParent !== null,
			);
			if (focusables.length === 0) return;
			const first = focusables[0];
			const last = focusables[focusables.length - 1];
			const active = document.activeElement as HTMLElement | null;
			if (e.shiftKey && (active === first || !panel.contains(active))) {
				e.preventDefault();
				last!.focus();
			} else if (!e.shiftKey && active === last) {
				e.preventDefault();
				first!.focus();
			}
		};
		window.addEventListener("keydown", onKey);
		return () => {
			window.removeEventListener("keydown", onKey);
			returnFocusRef.current?.focus?.();
		};
	}, []);

	// When the user enters delete-confirm mode, move focus to Cancel (HIG:
	// destructive confirms focus Cancel by default so Enter doesn't delete).
	useEffect(() => {
		if (confirmDelete) cancelDeleteRef.current?.focus();
	}, [confirmDelete]);

	const handleAnalyze = async () => {
		if (autopsy.status === "loading") return;
		setAutopsy({ status: "loading" });
		try {
			const response = await fetch("/api/posts?action=autopsy", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({ postId: post.id }),
			});
			if (!response.ok) {
				const errBody = await response.json().catch(() => ({}));
				throw new Error(errBody.error || `HTTP ${response.status}`);
			}
			const data = await response.json();
			if (!data?.analysis) {
				throw new Error("No analysis returned");
			}
			setAutopsy({ status: "loaded", result: data.analysis });
		} catch (err) {
			setAutopsy({
				status: "error",
				message: err instanceof Error ? err.message : "Analysis failed",
			});
		}
	};

	const handleScanSentiment = async () => {
		if (sentiment.status === "loading") return;
		setSentiment({ status: "loading" });
		try {
			const response = await fetch(
				`/api/posts?action=sentiment-scan&postId=${encodeURIComponent(
					post.id,
				)}&platform=${encodeURIComponent(post.platform)}`,
			);
			if (!response.ok) {
				const errBody = await response.json().catch(() => ({}));
				throw new Error(errBody.error || `HTTP ${response.status}`);
			}
			const body = (await response.json()) as SentimentResult & {
				success?: boolean | undefined;
			};
			if (typeof body?.totalComments !== "number") {
				throw new Error("Malformed sentiment response");
			}
			setSentiment({ status: "loaded", result: body });
		} catch (err) {
			setSentiment({
				status: "error",
				message: err instanceof Error ? err.message : "Sentiment scan failed",
			});
		}
	};

	const handleRetry = async () => {
		if (retrying) return;
		setRetrying(true);
		try {
			await retryFailedPost(post.id);
			appToast.success("Queued for retry", {
				description: "Publishing again in ~1 minute.",
			});
			onRetry(post.id);
			onClose();
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Could not queue retry.";
			appToast.error("Retry failed", { description });
			setRetrying(false);
		}
	};

	const handleRepost = async () => {
		if (!onRepost || reposting) return;
		setReposting(true);
		try {
			await onRepost(post);
		} finally {
			setReposting(false);
		}
	};

	const handleSave = async () => {
		if (saving) return;
		setSaving(true);
		try {
			await onSave(isCampaignDraft ? { ...draft, status: "draft" } : draft);
			setEditing(false);
		} finally {
			setSaving(false);
		}
	};
	const handleCancel = () => {
		setDraft(post);
		setEditing(false);
	};
	const handleConfirmDelete = async () => {
		if (deleting || deleteDisabledReason) return;
		setDeleting(true);
		try {
			await onDelete(post.id);
			onClose();
		} finally {
			setDeleting(false);
		}
	};
	const timeToString = (h: number, m: number) =>
		`${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`;
	const timestampLabel = (iso: string | null | undefined) => {
		if (!iso) return null;
		const date = new Date(iso);
		if (Number.isNaN(date.getTime())) return iso;
		return date.toLocaleString(undefined, {
			month: "short",
			day: "numeric",
			hour: "numeric",
			minute: "2-digit",
		});
	};
	const firstMediaUrl = post.mediaUrls?.[0] ?? post.thumbnailUrl;
	const firstMediaIsVideo = /\.(mp4|mov|webm|m4v)(\?|$)/i.test(
		firstMediaUrl ?? "",
	);

	const charCount = draft.title.length;
	const charPct = charCount / charLimit;
	const charColor =
		charPct >= 1
			? "var(--color-oxblood)"
			: charPct >= 0.9
				? "var(--color-gold)"
				: "var(--color-muted-foreground)";

	if (typeof document === "undefined") return null;
	return createPortal(
		<>
			<div
				onClick={onClose}
				// Stronger scrim in dark mode — without it the glass calendar cards
				// underneath bleed through the detail panel and make text hard to read.
				className="fixed inset-0 bg-foreground/30 dark:bg-black/70"
				style={{
					zIndex: Z.modalBackdrop,
					backdropFilter: "blur(6px)",
					WebkitBackdropFilter: "blur(6px)",
				}}
			/>
			<aside
				ref={panelRef}
				role="dialog"
				aria-modal="true"
				aria-label={`Post detail — ${post.account}`}
				style={{
					position: "fixed",
					right: 0,
					top: 0,
					bottom: 0,
					width: "100%",
					maxWidth: 420,
					zIndex: Z.modal,
				}}
				// Opaque shadcn/Nova surface so calendar cards do not bleed through.
				className="bg-card border-l border-border overflow-y-auto shadow-[-20px_0_40px_-20px_color-mix(in_srgb,var(--color-foreground)_15%,transparent)] dark:shadow-[-20px_0_40px_-20px_color-mix(in_srgb,var(--color-foreground)_60%,transparent)]"
			>
				<div className="sticky top-0 bg-card border-b border-border flex items-center justify-between px-5 py-4">
					<div className="flex items-center gap-2.5">
						<span
							className="w-2 h-2 rounded-full"
							style={{ backgroundColor: post.groupColor }}
						/>
						<span className="text-[0.8125rem] font-medium text-foreground">
							{post.account}
						</span>
					</div>
					<IconTooltipButton
						label="Close post details"
						onClick={onClose}
						className="text-muted-foreground hover:text-foreground"
					>
						<span className="h-8 w-8 rounded-md inline-flex items-center justify-center hover:bg-foreground/[0.05]">
							<X className="w-4 h-4" />
						</span>
					</IconTooltipButton>
				</div>

				<div className="flex flex-col gap-5 p-5">
					{/* Scheduled */}
					<div>
						<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
							{post.isUnscheduledDraft ? "Review state" : "Scheduled for"}
						</div>
						{editing && !isCampaignDraft ? (
							<div className="flex items-center gap-2">
								<Clock className="w-4 h-4 text-muted-foreground flex-shrink-0" />
								<Select
									value={draft.day}
									onChange={(e) =>
										setDraft({ ...draft, day: parseInt(e.target.value, 10) })
									}
									className="h-9 px-3 rounded-md bg-card border border-border text-[0.8125rem] text-foreground"
									options={DAY_NAMES_LONG.map((d, i) => ({
										value: String(i),
										label: d,
									}))}
								/>
								<Input
									type="time"
									value={timeToString(draft.hour, draft.minute)}
									onChange={(e) => {
										const [h, m] = e.target.value.split(":").map(Number);
										if (!Number.isNaN(h) && !Number.isNaN(m)) {
											setDraft({ ...draft, hour: h!, minute: m! });
										}
									}}
									className="h-9 px-2 rounded-md bg-card border border-border text-[0.8125rem] text-foreground tabular-nums"
								/>
							</div>
						) : (
							<div className="flex items-baseline gap-2">
								<Clock className="w-4 h-4 text-muted-foreground" />
								<span className="text-[1.125rem] font-medium text-foreground tabular-nums tracking-[-0.02em]">
									{post.isUnscheduledDraft
										? "Unscheduled draft"
										: `${DAY_NAMES_LONG[post.day]} · ${formatHour(post.hour, post.minute)}`}
								</span>
							</div>
						)}
					</div>

					{/* Caption */}
					<div>
						<div className="flex items-baseline justify-between mb-1.5">
							<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
								Caption
							</div>
							{editing && (
								<div
									className="text-[0.6875rem] tabular-nums font-medium"
									style={{ color: charColor }}
								>
									{charCount} / {charLimit}
								</div>
							)}
						</div>
						{editing ? (
							<Textarea
								value={draft.title}
								onChange={(e) => setDraft({ ...draft, title: e.target.value })}
								rows={4}
								maxLength={charLimit}
								className="w-full p-3 text-[0.875rem] leading-relaxed focus:border-input"
								placeholder="Write your caption…"
							/>
						) : (
							<p className="text-[0.875rem] text-foreground leading-relaxed whitespace-pre-wrap">
								{post.title}
							</p>
						)}
					</div>

					{/* Platform (read-only, never editable) + Status */}
					<div className="grid grid-cols-2 gap-3">
						<div>
							<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
								Platform
							</div>
							<div className="text-[0.8125rem] text-foreground inline-flex items-center gap-1.5">
								<span
									className="w-1.5 h-1.5 rounded-full bg-foreground/60"
									aria-hidden="true"
								/>
								{platformLabel}
							</div>
						</div>
						<div>
							<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
								Status
							</div>
							{editing && !isCampaignDraft ? (
								<Select
									value={draft.status}
									onChange={(e) =>
										setDraft({ ...draft, status: e.target.value as Status })
									}
									className="h-9 w-full px-3 rounded-md bg-card border border-border text-[0.8125rem] text-foreground"
									options={[
										{ value: "draft", label: "Draft" },
										{ value: "scheduled", label: "Scheduled" },
										{ value: "review", label: "In Review" },
										{ value: "published", label: "Published" },
										{ value: "failed", label: "Failed" },
									]}
								/>
							) : (
								<span
									className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] px-2 h-5 rounded inline-flex items-center"
									style={{ color: status.color, backgroundColor: status.bg }}
								>
									{status.label}
								</span>
							)}
						</div>
					</div>

					{/* Group */}
					<div>
						<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
							Group
						</div>
						<div className="text-[0.8125rem] text-foreground inline-flex items-center gap-1.5 tabular-nums">
							<span
								className="w-1.5 h-1.5 rounded-full flex-shrink-0"
								style={{ backgroundColor: post.groupColor }}
							/>
							{post.groupName}
						</div>
					</div>

					{campaignFactory && (
						<div className="rounded-md border border-border bg-foreground/[0.02] p-3">
							<div className="mb-2 flex items-center justify-between gap-2">
								<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
									Campaign Factory
								</div>
								<div className="flex items-center gap-1">
									<span
										className="rounded px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-[0.08em]"
										style={{
											color: "var(--color-oxblood)",
											backgroundColor:
												"color-mix(in srgb, var(--color-oxblood) 9%, transparent)",
										}}
									>
										{campaignFactorySurface}
									</span>
									{campaignFactoryScheduleMode && (
										<span
											className="rounded px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-[0.08em]"
											style={{
												color: "var(--color-warning)",
												backgroundColor:
													"color-mix(in srgb, var(--color-warning) 13%, transparent)",
											}}
										>
											{campaignFactoryScheduleMode}
										</span>
									)}
								</div>
							</div>
							<div className="grid grid-cols-2 gap-2 text-[0.75rem]">
								{campaignFactoryDetailRows.map(({ label, value, kind }) => (
									<div key={label} className="min-w-0">
										<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
											{label}
										</div>
										<div
											className={
												kind === "id"
													? "truncate font-mono text-foreground"
													: "truncate text-foreground"
											}
										>
											{(kind === "timestamp" ? timestampLabel(value) : value) ||
												"—"}
										</div>
									</div>
								))}
							</div>

							{campaignFactoryDailyRows.length > 0 && (
								<div className="mt-3 rounded border border-border bg-card px-2.5 py-2">
									<div className="mb-2 text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
										Daily 10 base videos
									</div>
									<div className="grid grid-cols-2 gap-2 text-[0.75rem]">
										{campaignFactoryDailyRows.map(({ label, value }) => (
											<div key={label} className="min-w-0">
												<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
													{label}
												</div>
												<div className="truncate text-foreground">
													{value ?? "—"}
												</div>
											</div>
										))}
									</div>
								</div>
							)}

							{campaignFactory.assignment_notes && (
								<div className="mt-3 rounded border border-border bg-card px-2.5 py-2 text-[0.75rem] leading-snug text-muted-foreground">
									{campaignFactory.assignment_notes}
								</div>
							)}

							{campaignFactoryAudioStatus && (
								<div className="mt-3 rounded border border-border bg-card px-2.5 py-2">
									<div className="mb-2 flex items-center justify-between gap-2">
										<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
											Native audio
										</div>
										<span
											className="rounded px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-[0.08em]"
											style={{
												color: campaignFactoryAudioReady
													? "var(--color-health-good)"
													: "var(--color-critical)",
												backgroundColor: campaignFactoryAudioReady
													? "color-mix(in srgb, var(--color-health-good) 12%, transparent)"
													: "color-mix(in srgb, var(--color-critical) 10%, transparent)",
											}}
										>
											{campaignFactoryAudioStatus}
										</span>
									</div>
									{campaignFactoryPrimaryAudio && (
										<div className="mb-2 rounded border border-[color-mix(in_srgb,var(--color-health-good)_35%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-health-good)_8%,var(--color-card))] px-2 py-1.5 text-[0.75rem] text-muted-foreground">
											<div className="mb-1 text-[0.59375rem] font-bold uppercase tracking-[0.1em] text-muted-foreground">
												Primary audio ·{" "}
												{String(
													campaignFactoryAudioDecision?.decisionConfidence ||
														"directional",
												)}
											</div>
											<div className="font-semibold text-foreground">
												{String(
													campaignFactoryPrimaryAudio.audio_title ||
														campaignFactoryPrimaryAudio.audioTitle ||
														campaignFactoryPrimaryAudio.strategy ||
														"Native audio recommendation",
												)}
												{campaignFactoryPrimaryAudio.artist_name ||
												campaignFactoryPrimaryAudio.artistName
													? ` · ${String(campaignFactoryPrimaryAudio.artist_name || campaignFactoryPrimaryAudio.artistName)}`
													: ""}
											</div>
											<div className="mt-1 flex flex-wrap gap-1">
												{[
													campaignFactoryPrimaryAudio.platform,
													campaignFactoryPrimaryAudio.freshness ||
														campaignFactoryPrimaryAudio.trendStatus,
													campaignFactoryPrimaryAudio.decisionScore
														? `score ${Math.round(Number(campaignFactoryPrimaryAudio.decisionScore))}`
														: null,
												]
													.filter(Boolean)
													.map((value) => (
														<span
															key={String(value)}
															className="rounded bg-background px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
														>
															{String(value)}
														</span>
													))}
											</div>
											{Array.isArray(campaignFactoryAudioDecision?.riskFlags) &&
												campaignFactoryAudioDecision.riskFlags.length > 0 && (
													<div className="mt-1 flex flex-wrap gap-1">
														{campaignFactoryAudioDecision.riskFlags
															.slice(0, 4)
															.map((risk) => (
																<span
																	key={String(risk)}
																	className="rounded bg-[color-mix(in_srgb,var(--color-critical)_10%,transparent)] px-1.5 py-0.5 text-[0.625rem] text-muted-foreground"
																>
																	{String(risk)}
																</span>
															))}
													</div>
												)}
											{campaignFactoryPrimaryAudio.platform_url ||
											campaignFactoryPrimaryAudio.platformUrl ||
											campaignFactoryPrimaryAudio.platform_audio_id ? (
												<div className="mt-1 break-all font-mono text-[0.6875rem] text-muted-foreground">
													{campaignFactoryPrimaryAudio.platform_url ||
													campaignFactoryPrimaryAudio.platformUrl ? (
														<a
															href={String(
																campaignFactoryPrimaryAudio.platform_url ||
																	campaignFactoryPrimaryAudio.platformUrl,
															)}
															target="_blank"
															rel="noreferrer"
															className="underline decoration-dotted underline-offset-2"
														>
															{String(
																campaignFactoryPrimaryAudio.platform_url ||
																	campaignFactoryPrimaryAudio.platformUrl,
															)}
														</a>
													) : (
														`ID: ${String(campaignFactoryPrimaryAudio.platform_audio_id)}`
													)}
												</div>
											) : null}
											{campaignFactoryAudioDecision?.operatorInstruction ? (
												<div>
													{String(
														campaignFactoryAudioDecision.operatorInstruction,
													)}
												</div>
											) : null}
											{campaignFactoryAudioDecision?.whenNotToUse ? (
												<div className="mt-1 text-muted-foreground">
													{String(campaignFactoryAudioDecision.whenNotToUse)}
												</div>
											) : null}
											<Button
												type="button"
												disabled={audioUpdating}
												onClick={() => {
													const selectedAudioId = String(
														campaignFactoryPrimaryAudio.catalog_audio_id ||
															campaignFactoryPrimaryAudio.catalogAudioId ||
															campaignFactoryPrimaryAudio.audioMemoryGraphId ||
															campaignFactoryPrimaryAudio.platform_audio_id ||
															campaignFactoryPrimaryAudio.platformAudioId ||
															campaignFactoryPrimaryAudio.audioId ||
															campaignFactoryPrimaryAudio.platform_url ||
															campaignFactoryPrimaryAudio.platformUrl ||
															"",
													);
													void updateNativeAudioStatus("selected", {
														selectedAudioId,
													});
												}}
												variant="outline"
												size="sm"
												className="mt-2"
											>
												Use primary audio
											</Button>
										</div>
									)}
									{(campaignFactoryPrimaryAudio
										? campaignFactoryBackupAudios
										: campaignFactoryAudioRecommendations
									)
										.slice(0, 3)
										.map((rec, index) => (
											<div
												key={`${String(rec.platform_audio_id || rec.audio_title || index)}`}
												className="mb-2 rounded bg-foreground/[0.04] px-2 py-1.5 text-[0.75rem] text-muted-foreground"
											>
												{campaignFactoryPrimaryAudio && index === 0 ? (
													<div className="mb-1 text-[0.59375rem] font-bold uppercase tracking-[0.1em] text-muted-foreground">
														Backup audio
													</div>
												) : null}
												<div className="font-semibold text-foreground">
													{String(
														rec.audio_title ||
															rec.strategy ||
															"Native audio recommendation",
													)}
													{rec.artist_name
														? ` · ${String(rec.artist_name)}`
														: ""}
												</div>
												<div className="mt-1 flex flex-wrap gap-1">
													{[
														rec.platform,
														rec.freshness || rec.trendStatus,
														rec.confidence
															? `conf ${Math.round(Number(rec.confidence) * 100)}%`
															: null,
													]
														.filter(Boolean)
														.map((value) => (
															<span
																key={String(value)}
																className="rounded bg-background px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
															>
																{String(value)}
															</span>
														))}
												</div>
												{(Array.isArray(rec.vibe_tags)
													? rec.vibe_tags
													: Array.isArray(rec.vibeTags)
														? rec.vibeTags
														: []
												).length > 0 && (
													<div className="mt-1 flex flex-wrap gap-1">
														{(Array.isArray(rec.vibe_tags)
															? rec.vibe_tags
															: (rec.vibeTags as unknown[])
														)
															.slice(0, 5)
															.map((tag) => (
																<span
																	key={String(tag)}
																	className="rounded bg-foreground/[0.05] px-1.5 py-0.5 text-[0.625rem] text-muted-foreground"
																>
																	{String(tag)}
																</span>
															))}
													</div>
												)}
												{rec.platform_url ||
												rec.platformUrl ||
												rec.platform_audio_id ? (
													<div className="mt-1 break-all font-mono text-[0.6875rem] text-muted-foreground">
														{rec.platform_url || rec.platformUrl ? (
															<a
																href={String(
																	rec.platform_url || rec.platformUrl,
																)}
																target="_blank"
																rel="noreferrer"
																className="underline decoration-dotted underline-offset-2"
															>
																{String(rec.platform_url || rec.platformUrl)}
															</a>
														) : (
															`ID: ${String(rec.platform_audio_id)}`
														)}
													</div>
												) : null}
												{rec.instruction ? (
													<div>{String(rec.instruction)}</div>
												) : null}
												{rec.rationale ? (
													<div>{String(rec.rationale)}</div>
												) : null}
												{rec.safe_usage_notes || rec.safeUsageNotes ? (
													<div className="mt-1 text-muted-foreground">
														{String(rec.safe_usage_notes || rec.safeUsageNotes)}
													</div>
												) : null}
												<Button
													type="button"
													disabled={audioUpdating}
													onClick={() => {
														const selectedAudioId = String(
															rec.catalog_audio_id ||
																rec.catalogAudioId ||
																rec.audioMemoryGraphId ||
																rec.platform_audio_id ||
																rec.platformAudioId ||
																rec.audioId ||
																rec.platform_url ||
																rec.platformUrl ||
																"",
														);
														void updateNativeAudioStatus("selected", {
															selectedAudioId,
														});
													}}
													variant="outline"
													size="sm"
													className="mt-2"
												>
													Use this audio
												</Button>
											</div>
										))}
									<div className="flex flex-wrap gap-1.5">
										{(
											[
												"selected",
												"attached",
												"verified",
												"skipped",
												"blocked",
											] as const
										).map((status) => (
											<Button
												key={status}
												type="button"
												onClick={() => {
													if (status === "attached" || status === "verified") {
														setAudioProofAction(status);
														return;
													}
													void updateNativeAudioStatus(status);
												}}
												disabled={audioUpdating}
												variant="outline"
												size="sm"
											>
												{status === "selected"
													? "Mark selected"
													: status === "attached"
														? "Mark attached"
														: status === "verified"
															? "Verify"
															: status === "skipped"
																? "Skip"
																: "Block"}
											</Button>
										))}
									</div>
									{audioProofAction && (
										<form
											className="mt-3 rounded border border-border bg-background px-2.5 py-2"
											onSubmit={(event) => {
												event.preventDefault();
												void updateNativeAudioStatus(audioProofAction, {
													url: audioProofUrl,
													note: audioProofNote,
												});
											}}
										>
											<div className="mb-2 text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
												{audioProofAction === "attached"
													? "Attachment proof"
													: "Verification proof"}
											</div>
											<label
												htmlFor="native-audio-proof-url"
												className="mb-2 block text-[0.6875rem] font-semibold text-muted-foreground"
											>
												Native post or audio proof URL
												<Input
													id="native-audio-proof-url"
													value={audioProofUrl}
													onChange={(event) =>
														setAudioProofUrl(event.target.value)
													}
													placeholder="https://instagram.com/..."
													className="mt-1 w-full rounded border border-border bg-card px-2 py-1.5 font-mono text-[0.75rem] text-foreground outline-none transition-colors focus:border-input"
												/>
											</label>
											<label
												htmlFor="native-audio-proof-note"
												className="block text-[0.6875rem] font-semibold text-muted-foreground"
											>
												Proof note
												<Textarea
													id="native-audio-proof-note"
													value={audioProofNote}
													onChange={(event) =>
														setAudioProofNote(event.target.value)
													}
													placeholder="Audio attached natively in app, checked before publish."
													rows={2}
													className="mt-1 min-h-16 w-full resize-none rounded border border-border bg-card px-2 py-1.5 text-[0.75rem] focus:border-input"
												/>
											</label>
											<div className="mt-2 flex flex-wrap gap-1.5">
												<Button
													type="submit"
													disabled={audioUpdating}
													size="sm"
												>
													{audioUpdating
														? "Saving…"
														: audioProofAction === "attached"
															? "Save attached proof"
															: "Save verification"}
												</Button>
												<Button
													type="button"
													disabled={audioUpdating}
													onClick={() => {
														setAudioProofAction(null);
														setAudioProofUrl("");
														setAudioProofNote("");
													}}
													variant="outline"
													size="sm"
												>
													Cancel
												</Button>
											</div>
										</form>
									)}
									<div className="mt-3 border-t border-border pt-3">
										<div className="mb-2 text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
											Recent events
										</div>
										{audioHistory.status === "loading" && (
											<div className="text-[0.75rem] text-muted-foreground">
												Loading audio history…
											</div>
										)}
										{audioHistory.status === "error" && (
											<div className="text-[0.75rem] text-muted-foreground">
												Audio history unavailable: {audioHistory.message}
											</div>
										)}
										{audioHistory.status === "loaded" &&
											audioHistory.events.length === 0 && (
												<div className="text-[0.75rem] text-muted-foreground">
													No audio events recorded yet.
												</div>
											)}
										{audioHistory.status === "loaded" &&
											audioHistory.events.length > 0 && (
												<div className="flex flex-col gap-2">
													{audioHistory.events.map((event, index) => (
														<div
															key={
																event.id ||
																`${event.timestamp || "event"}-${index}`
															}
															className="rounded bg-foreground/[0.04] px-2 py-1.5 text-[0.75rem] text-muted-foreground"
														>
															<div className="flex items-start justify-between gap-2">
																<div className="font-semibold text-foreground">
																	{formatCampaignFactoryAudioEventLine(event)}
																</div>
																<div className="shrink-0 text-[0.625rem] tabular-nums text-muted-foreground">
																	{timestampLabel(event.timestamp)}
																</div>
															</div>
															<div className="mt-1 flex flex-wrap gap-1">
																{event.proofComplete !== null && (
																	<span className="rounded bg-background px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
																		Proof{" "}
																		{event.proofComplete
																			? "complete"
																			: "incomplete"}
																	</span>
																)}
																{event.nativeAudioLocator && (
																	<span className="rounded bg-background px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
																		Locator saved
																	</span>
																)}
															</div>
															{event.nativeAudioLocator && (
																<div className="mt-1 break-all font-mono text-[0.6875rem] text-muted-foreground">
																	{event.platformUrl ? (
																		<a
																			href={event.platformUrl}
																			target="_blank"
																			rel="noreferrer"
																			className="underline decoration-dotted underline-offset-2"
																		>
																			{event.platformUrl}
																		</a>
																	) : (
																		event.nativeAudioLocator
																	)}
																</div>
															)}
															{(event.note || event.reason) && (
																<div className="mt-1 text-muted-foreground">
																	{event.note || event.reason}
																</div>
															)}
														</div>
													))}
												</div>
											)}
									</div>
								</div>
							)}

							<div className="mt-3 border-t border-border pt-3">
								<div className="mb-1 text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
									Reuse indicators
								</div>
								{reuseLabels.length > 0 ? (
									<div className="flex flex-wrap gap-1">
										{reuseLabels.map((label) => (
											<span
												key={label}
												className="rounded bg-foreground/[0.05] px-2 py-0.5 text-[0.6875rem] font-medium text-muted-foreground"
											>
												{label}
											</span>
										))}
									</div>
								) : (
									<div className="text-[0.75rem] text-muted-foreground">
										No reuse found in draft, scheduled, or published Campaign
										Factory posts.
									</div>
								)}
							</div>

							<div className="mt-3 border-t border-border pt-3">
								<div className="grid grid-cols-1 gap-1.5 text-[0.75rem]">
									<div>
										<span className="text-muted-foreground">Source asset:</span>{" "}
										<span className="font-mono text-foreground">
											{campaignFactory.source_asset_id || "—"}
										</span>
									</div>
									<div>
										<span className="text-muted-foreground">Rendered asset:</span>{" "}
										<span className="font-mono text-foreground">
											{campaignFactory.rendered_asset_id || "—"}
										</span>
									</div>
								</div>
							</div>

							{performanceLineage && (
								<div className="mt-3 border-t border-border pt-3">
									<div className="mb-1 text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
										Performance lineage
									</div>
									<div className="text-[0.75rem] text-muted-foreground">
										Read-only keys are available for Campaign Factory sync.
									</div>
									{campaignFactoryPerformance && (
										<div className="mt-2 grid grid-cols-3 gap-1.5 text-[0.6875rem] tabular-nums">
											{[
												["Views", campaignFactoryPerformance.views],
												["Reach", campaignFactoryPerformance.reach],
												["Likes", campaignFactoryPerformance.likes],
												["Comments", campaignFactoryPerformance.comments],
												["Shares", campaignFactoryPerformance.shares],
												["Saves", campaignFactoryPerformance.saves],
											].map(([label, value]) => (
												<div
													key={label}
													className="rounded bg-foreground/[0.04] px-2 py-1"
												>
													<div className="text-[0.5625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
														{label}
													</div>
													<div className="text-foreground">{value}</div>
												</div>
											))}
										</div>
									)}
								</div>
							)}

							<details className="mt-3 border-t border-border pt-3">
								<summary className="cursor-pointer text-[0.75rem] font-semibold text-muted-foreground">
									Show lineage IDs and hashes
								</summary>
								<div className="mt-2 flex flex-col gap-1.5 break-all font-mono text-[0.6875rem] text-muted-foreground">
									{campaignFactoryLongRows.map((row) => (
										<div key={row.label}>
											{row.label}: {row.value || "—"}
										</div>
									))}
								</div>
							</details>
						</div>
					)}

					{/* Media */}
					{post.mediaCount !== undefined && post.mediaCount > 0 && (
						<div>
							<div className="flex items-baseline justify-between mb-1.5">
								<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
									Media
								</div>
								<div className="text-[0.6875rem] text-muted-foreground tabular-nums">
									{post.mediaCount} {post.mediaCount === 1 ? "asset" : "assets"}
								</div>
							</div>
							{firstMediaUrl ? (
								<div className="overflow-hidden rounded-md border border-border bg-muted/40">
									{firstMediaIsVideo ? (
										<video
											src={firstMediaUrl}
											controls
											preload="metadata"
											className="h-64 w-full bg-black object-contain"
										>
											<track kind="captions" />
										</video>
									) : (
										<img
											src={firstMediaUrl}
											alt=""
											loading="lazy"
											decoding="async"
											className="h-64 w-full object-cover"
										/>
									)}
								</div>
							) : (
								<div className="rounded-md border border-border bg-muted/40 px-3 py-3 text-[0.6875rem] text-muted-foreground">
									Media preview unavailable
								</div>
							)}
						</div>
					)}

					{/* Performance autopsy — published posts only */}
					{post.status === "published" && (
						<div>
							<div className="flex items-baseline justify-between mb-1.5">
								<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
									Performance autopsy
								</div>
								{autopsy.status === "loaded" && autopsy.result.performance && (
									<span
										className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] tabular-nums"
										style={{
											color:
												autopsy.result.performance === "above"
													? "var(--color-health-good)"
													: "var(--color-oxblood)",
										}}
									>
										{autopsy.result.performance === "above"
											? "ABOVE AVG"
											: "BELOW AVG"}
									</span>
								)}
							</div>
							{autopsy.status === "idle" && (
								<Button
									type="button"
									onClick={() => void handleAnalyze()}
									variant="outline"
									className="w-full"
								>
									Analyze why this performed
								</Button>
							)}
							{autopsy.status === "loading" && (
								<div className="text-[0.8125rem] text-muted-foreground py-2">
									Analyzing post performance…
								</div>
							)}
							{autopsy.status === "loaded" && (
								<div className="flex flex-col gap-2.5">
									{autopsy.result.factors?.slice(0, 3).map((f, i) => (
										<div key={i} className="flex flex-col gap-0.5">
											<div className="text-[0.8125rem] font-medium text-foreground">
												{f.title}
											</div>
											{f.explanation && (
												<div className="text-[0.78125rem] text-muted-foreground leading-snug">
													{f.explanation}
												</div>
											)}
										</div>
									))}
									{autopsy.result.recommendation && (
										<div className="mt-2 pt-2.5 border-t border-dashed border-border">
											<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1">
												Try next
											</div>
											<p className="text-[0.8125rem] text-foreground leading-snug">
												{autopsy.result.recommendation}
											</p>
										</div>
									)}
								</div>
							)}
							{autopsy.status === "error" && (
								<div className="flex flex-col gap-2">
									<div
										className="text-[0.8125rem] py-1"
										style={{ color: "var(--color-oxblood)" }}
									>
										Analysis failed: {autopsy.message}
									</div>
									<Button
										type="button"
										onClick={() => void handleAnalyze()}
										variant="ghost"
										size="sm"
										className="px-0"
									>
										Try again
									</Button>
								</div>
							)}
						</div>
					)}

					{/* Comment sentiment scan — published posts only */}
					{post.status === "published" && (
						<div>
							<div className="flex items-baseline justify-between mb-1.5">
								<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
									Comment sentiment
								</div>
								{sentiment.status === "loaded" && sentiment.result.llm && (
									<span
										className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] tabular-nums"
										style={{
											color:
												VERDICT_COLORS[sentiment.result.llm.overall_verdict] ??
												"var(--color-muted-foreground)",
										}}
									>
										{sentiment.result.llm.overall_verdict}
									</span>
								)}
							</div>
							{sentiment.status === "idle" && (
								<Button
									type="button"
									onClick={() => void handleScanSentiment()}
									variant="outline"
									className="w-full"
								>
									Scan comment sentiment
								</Button>
							)}
							{sentiment.status === "loading" && (
								<div className="text-[0.8125rem] text-muted-foreground py-2">
									Reading comments…
								</div>
							)}
							{sentiment.status === "loaded" &&
								sentiment.result.totalComments === 0 && (
									<div className="text-[0.8125rem] text-muted-foreground py-1">
										No comments to analyze yet.
									</div>
								)}
							{sentiment.status === "loaded" &&
								sentiment.result.totalComments > 0 && (
									<div className="flex flex-col gap-2.5">
										{sentiment.result.llm?.summary && (
											<p className="text-[0.8125rem] text-foreground leading-snug">
												{sentiment.result.llm.summary}
											</p>
										)}
										{!sentiment.result.llm && (
											<p className="text-[0.8125rem] text-foreground leading-snug">
												{sentiment.result.verdict}
											</p>
										)}
										<div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[0.6875rem] tabular-nums text-muted-foreground">
											<span>
												<span className="text-foreground font-medium">
													{sentiment.result.totalComments}
												</span>{" "}
												comments
											</span>
											<span>
												<span style={{ color: "var(--color-health-good)" }}>
													+{sentiment.result.breakdown.positive}
												</span>
												{" / "}
												<span style={{ color: "var(--color-oxblood)" }}>
													−{sentiment.result.breakdown.negative}
												</span>
												{" / "}
												<span>
													{sentiment.result.breakdown.neutral} neutral
												</span>
												{sentiment.result.breakdown.question > 0 && (
													<>
														{" / "}
														<span>
															{sentiment.result.breakdown.question} questions
														</span>
													</>
												)}
											</span>
										</div>
										{sentiment.result.llm?.top_themes &&
											sentiment.result.llm.top_themes.length > 0 && (
												<div className="flex flex-wrap gap-1">
													{sentiment.result.llm.top_themes
														.slice(0, 5)
														.map((t) => (
															<Badge
																key={t}
																variant="secondary"
																className="h-5 px-2 text-[0.6875rem]"
															>
																{t}
															</Badge>
														))}
												</div>
											)}
										{sentiment.result.llm &&
											sentiment.result.llm.concerning_count > 0 && (
												<div
													className="text-[0.75rem] px-2.5 py-1.5 rounded-md"
													style={{
														backgroundColor:
															"color-mix(in srgb, var(--color-oxblood) 8%, transparent)",
														color: "var(--color-oxblood)",
													}}
												>
													{sentiment.result.llm.concerning_count} comment
													{sentiment.result.llm.concerning_count === 1
														? ""
														: "s"}{" "}
													flagged for human review.
												</div>
											)}
										{sentiment.result.degraded && (
											<div className="text-[0.6875rem] text-muted-foreground">
												AI summary unavailable — showing rule-based breakdown
												only.
											</div>
										)}
										{sentiment.result.llmSkipped && (
											<div className="text-[0.6875rem] text-muted-foreground">
												Too few comments for AI summary; rule-based breakdown
												shown.
											</div>
										)}
									</div>
								)}
							{sentiment.status === "error" && (
								<div className="flex flex-col gap-2">
									<div
										className="text-[0.8125rem] py-1"
										style={{ color: "var(--color-oxblood)" }}
									>
										Sentiment scan failed: {sentiment.message}
									</div>
									<Button
										type="button"
										onClick={() => void handleScanSentiment()}
										variant="ghost"
										size="sm"
										className="px-0"
									>
										Try again
									</Button>
								</div>
							)}
						</div>
					)}

					{/* Actions */}
					<div className="pt-3 border-t border-border flex flex-col gap-2">
						{editing ? (
							<>
								<Button
									type="button"
									onClick={handleSave}
									disabled={saving || charCount > charLimit || charCount === 0}
								>
									{saving ? "Saving…" : "Save changes"}
								</Button>
								<Button type="button" onClick={handleCancel} variant="outline">
									Cancel
								</Button>
							</>
						) : (
							<>
								<Button type="button" onClick={() => setEditing(true)}>
									<PenSquare data-icon="inline-start" />
									Edit post
								</Button>
								<Button
									type="button"
									onClick={() => {
										onDuplicate(post.id);
										onClose();
									}}
									variant="outline"
								>
									<Copy data-icon="inline-start" />
									Duplicate
								</Button>
								{onRepost &&
									post.platform === "threads" &&
									post.threadsPostId && (
										<Button
											type="button"
											onClick={() => void handleRepost()}
											disabled={reposting}
											title="Repost on Threads"
											variant="outline"
										>
											<Repeat2 data-icon="inline-start" />
											{reposting ? "Reposting..." : "Repost on Threads"}
										</Button>
									)}
								{post.status === "failed" && (
									<Button
										type="button"
										onClick={() => void handleRetry()}
										disabled={retrying}
										variant="outline"
									>
										{retrying ? "Retrying…" : "Retry publish"}
									</Button>
								)}
								{/* Delete with inline confirm — no nested modal */}
								{confirmDelete ? (
									<div
										className="flex gap-2"
										role="group"
										aria-label="Confirm delete"
									>
										<Button
											type="button"
											onClick={handleConfirmDelete}
											disabled={deleting}
											variant="danger"
											className="flex-1"
										>
											<Trash2 data-icon="inline-start" />
											{deleting ? "Deleting…" : "Yes, delete"}
										</Button>
										<Button
											ref={cancelDeleteRef}
											type="button"
											onClick={() => setConfirmDelete(false)}
											variant="outline"
										>
											Cancel
										</Button>
									</div>
								) : (
									<Button
										type="button"
										onClick={() => setConfirmDelete(true)}
										disabled={!!deleteDisabledReason}
										title={deleteDisabledReason ?? undefined}
										variant="danger"
									>
										<Trash2 data-icon="inline-start" />
										Delete post
									</Button>
								)}
							</>
						)}
					</div>
				</div>
			</aside>
		</>,
		document.body,
	);
}
