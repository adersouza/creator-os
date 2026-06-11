import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import {
	Bell,
	Check,
	Clipboard,
	Download,
	ExternalLink,
	RefreshCw,
	Save,
	Share2,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { NovaCard, NovaHeader } from "@/components/ui/NovaPrimitives";
import { Textarea } from "@/components/ui/Textarea";
import { apiUrl } from "@/lib/apiUrl";
import { appToast } from "@/lib/toast";
import { trackClientEvent } from "@/services/clientTelemetry";
import { supabase } from "@/services/supabase";

type HandoffEvent =
	| "opened"
	| "caption_copied"
	| "media_downloaded"
	| "media_shared"
	| "completed";

type HandoffPost = {
	id: string;
	content: string;
	mediaUrls: string[];
	mediaType: string | null;
	igMediaType: string | null;
	status: string | null;
	scheduledFor: string | null;
	handoffStatus: string | null;
	captionCopiedAt: string | null;
	mediaDownloadedAt: string | null;
	mediaSharedAt: string | null;
	manualPublishConfirmedAt: string | null;
	accountUsername: string | null;
	followUp: {
		instagramUrl?: string | undefined;
		notes?: string | undefined;
		savedAt?: string | undefined;
	} | null;
};

function proxyMediaUrl(postId: string, index: number): string {
	return apiUrl(`/api/media/${encodeURIComponent(postId)}?index=${index}`);
}

async function authHeaders(): Promise<Record<string, string>> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) throw new Error("Not authenticated");
	return {
		Authorization: `Bearer ${session.access_token}`,
		"Content-Type": "application/json",
	};
}

function fileNameFor(contentType: string | null, index: number): string {
	if (contentType?.includes("video"))
		return `juno33-instagram-${index + 1}.mp4`;
	if (contentType?.includes("png")) return `juno33-instagram-${index + 1}.png`;
	return `juno33-instagram-${index + 1}.jpg`;
}

export function Handoff() {
	const { postId = "" } = useParams();
	const navigate = useNavigate();
	const [post, setPost] = useState<HandoffPost | null>(null);
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState<
		HandoffEvent | "download" | "share" | "followup" | null
	>(null);
	const [error, setError] = useState<string | null>(null);
	const [liveUrl, setLiveUrl] = useState("");
	const [notes, setNotes] = useState("");
	const openedRecordedFor = useRef<string | null>(null);

	const mediaUrls = useMemo(
		() =>
			post
				? post.mediaUrls.map((_, index) => proxyMediaUrl(post.id, index))
				: [],
		[post],
	);
	const firstMediaUrl = mediaUrls[0] ?? null;
	const isVideo = post?.igMediaType === "REELS" || post?.mediaType === "video";

	const recordEvent = useCallback(
		async (event: HandoffEvent, targetPostId = post?.id) => {
			if (!targetPostId) return;
			const headers = await authHeaders();
			const response = await fetch(apiUrl("/api/posts?action=handoff-event"), {
				method: "POST",
				headers,
				body: JSON.stringify({ postId: targetPostId, event }),
			});
			const data = await response.json().catch(() => null);
			if (!response.ok)
				throw new Error(data?.error || "Failed to update handoff");
			setPost((current) =>
				current
					? {
							...current,
							handoffStatus: data.handoffStatus || current.handoffStatus,
							...(event === "caption_copied"
								? { captionCopiedAt: new Date().toISOString() }
								: {}),
							...(event === "media_downloaded"
								? { mediaDownloadedAt: new Date().toISOString() }
								: {}),
							...(event === "media_shared"
								? { mediaSharedAt: new Date().toISOString() }
								: {}),
							...(event === "completed"
								? {
										manualPublishConfirmedAt: new Date().toISOString(),
										status: "published",
									}
								: {}),
						}
					: current,
			);
		},
		[post?.id],
	);

	const load = useCallback(async () => {
		if (!postId) return;
		setLoading(true);
		setError(null);
		try {
			const headers = await authHeaders();
			const response = await fetch(
				apiUrl(
					`/api/posts?action=handoff&postId=${encodeURIComponent(postId)}`,
				),
				{ headers },
			);
			const data = await response.json().catch(() => null);
			if (!response.ok)
				throw new Error(data?.error || "Failed to load handoff");
			setPost(data.post);
			const followUp = data.post?.followUp;
			if (followUp && typeof followUp === "object") {
				setLiveUrl(
					typeof followUp.instagramUrl === "string"
						? followUp.instagramUrl
						: "",
				);
				setNotes(typeof followUp.notes === "string" ? followUp.notes : "");
			}
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load handoff");
		} finally {
			setLoading(false);
		}
	}, [postId]);

	useEffect(() => {
		void load();
	}, [load]);

	useEffect(() => {
		if (!post || post.handoffStatus === "completed") return;
		if (openedRecordedFor.current === post.id) return;
		openedRecordedFor.current = post.id;
		trackClientEvent("handoff_opened", {
			post_id_present: true,
			media_count: post.mediaUrls.length,
		});
		void recordEvent("opened", post.id).catch(() => {});
	}, [post, recordEvent]);

	const copyCaption = async () => {
		if (!post) return;
		setBusy("caption_copied");
		try {
			await navigator.clipboard.writeText(post.content || "");
			await recordEvent("caption_copied");
			appToast.success("Caption copied");
		} catch (err) {
			appToast.error("Copy failed", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	const downloadMedia = async () => {
		if (!post || mediaUrls.length === 0) return;
		setBusy("download");
		try {
			mediaUrls.forEach((url, index) => {
				const a = document.createElement("a");
				a.href = url;
				a.download = fileNameFor(null, index);
				a.rel = "noopener";
				document.body.appendChild(a);
				a.click();
				a.remove();
			});
			await recordEvent("media_downloaded");
			appToast.success("Media download started");
		} catch (err) {
			appToast.error("Download failed", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	const shareMedia = async () => {
		if (!post || mediaUrls.length === 0) return;
		setBusy("share");
		try {
			const files = await Promise.all(
				mediaUrls.map(async (url, index) => {
					const response = await fetch(url);
					if (!response.ok)
						throw new Error("Could not prepare media for sharing");
					const blob = await response.blob();
					return new File([blob], fileNameFor(blob.type, index), {
						type: blob.type || "application/octet-stream",
					});
				}),
			);
			const shareData = {
				files,
				title: "Juno33 Instagram post",
				text: post.content,
			};
			if (!navigator.canShare?.(shareData)) {
				throw new Error("This browser cannot share these media files.");
			}
			await navigator.share(shareData);
			await recordEvent("media_shared");
			appToast.success("Media shared");
		} catch (err) {
			appToast.error("Share unavailable", {
				description:
					err instanceof Error ? err.message : "Use Download Media instead.",
			});
		} finally {
			setBusy(null);
		}
	};

	const openInstagram = () => {
		window.location.href = "instagram://app";
		window.setTimeout(() => {
			window.location.href = "https://www.instagram.com/";
		}, 900);
	};

	const markPosted = async () => {
		if (!post) return;
		setBusy("completed");
		try {
			await recordEvent("completed");
			trackClientEvent("handoff_completed", {
				post_id_present: true,
				media_count: post.mediaUrls.length,
			});
			appToast.success("Marked as posted");
		} catch (err) {
			appToast.error("Could not mark posted", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	const saveFollowUp = async () => {
		if (!post) return;
		setBusy("followup");
		try {
			const headers = await authHeaders();
			const response = await fetch(
				apiUrl("/api/posts?action=handoff-followup"),
				{
					method: "POST",
					headers,
					body: JSON.stringify({
						postId: post.id,
						instagramUrl: liveUrl.trim() || undefined,
						notes: notes.trim() || undefined,
					}),
				},
			);
			const data = await response.json().catch(() => null);
			if (!response.ok)
				throw new Error(data?.error || "Failed to save follow-up");
			setPost((current) =>
				current ? { ...current, followUp: data.followUp } : current,
			);
			trackClientEvent("post_publish_followup_saved", {
				link_added: liveUrl.trim().length > 0,
				has_notes: notes.trim().length > 0,
			});
			appToast.success("Follow-up saved");
		} catch (err) {
			appToast.error("Could not save follow-up", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	if (loading) {
		return (
			<NovaScreen mode="dense">
				<NovaHeader
					eyebrow="Handoff"
					title="Instagram handoff"
					meta="Loading"
					description="Preparing the mobile publishing checklist and media package."
				/>
				<NovaCard description="Loading handoff..." />
			</NovaScreen>
		);
	}

	if (error || !post) {
		return (
			<NovaScreen mode="dense">
				<NovaHeader
					eyebrow="Handoff"
					title="Instagram handoff"
					meta="Unavailable"
					description="This post could not be prepared for handoff."
				/>
				<NovaCard
					title="Handoff unavailable"
					description={error || "Post not found."}
				>
					<Button className="mt-4" onClick={load}>
						<RefreshCw data-icon="inline-start" aria-hidden="true" />
						Retry
					</Button>
				</NovaCard>
			</NovaScreen>
		);
	}

	const checklist = [
		{ label: "Copy caption", done: !!post.captionCopiedAt },
		{
			label: post.mediaSharedAt ? "Media shared" : "Share or download media",
			done: !!post.mediaSharedAt || !!post.mediaDownloadedAt,
		},
		{ label: "Open Instagram", done: false },
		{ label: "Confirm posted", done: !!post.manualPublishConfirmedAt },
	];

	return (
		<NovaScreen mode="dense">
			<NovaHeader
				eyebrow="Handoff"
				title="Finish this Instagram post"
				meta={post.manualPublishConfirmedAt ? "Posted" : "Ready"}
				description="Copy the caption, move the media to Instagram, and record the publish follow-up without changing the scheduled post data."
				actions={
					<div className="flex flex-wrap items-center gap-2">
						<Badge tone="oxblood">Notify Me</Badge>
						<Badge
							tone={post.manualPublishConfirmedAt ? "secondary" : "outline"}
						>
							{post.manualPublishConfirmedAt ? "Posted" : "Ready"}
						</Badge>
						<Badge tone="outline">
							{post.accountUsername ? `@${post.accountUsername}` : "Instagram"}
						</Badge>
					</div>
				}
			/>
			<div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
				<NovaCard
					title="Media and caption"
					description="Use these assets in the Instagram app."
					contentClassName="p-0"
					className="overflow-hidden"
				>
					<div className="grid gap-4 p-4 md:grid-cols-[280px_minmax(0,1fr)]">
						<div className="overflow-hidden rounded-lg border border-border bg-muted">
							{firstMediaUrl ? (
								isVideo ? (
									<video
										src={firstMediaUrl}
										controls
										playsInline
										className="aspect-[9/16] max-h-[520px] w-full object-cover"
									>
										<track kind="captions" label="No captions available" />
									</video>
								) : (
									<img
										src={firstMediaUrl}
										alt=""
										className="aspect-square w-full object-cover"
									/>
								)
							) : (
								<div className="flex aspect-square items-center justify-center text-sm text-muted-foreground">
									No media
								</div>
							)}
						</div>

						<div>
							<div className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
								Caption
							</div>
							<div className="min-h-48 whitespace-pre-wrap rounded-lg border border-border bg-card p-3 text-sm leading-relaxed text-foreground">
								{post.content}
							</div>
						</div>
					</div>
				</NovaCard>

				<NovaCard>
					<div className="mb-4 flex items-center gap-2">
						<Bell
							data-icon="inline-start"
							className="text-muted-foreground"
							aria-hidden="true"
						/>
						<div className="text-sm font-semibold text-foreground">
							Publishing checklist
						</div>
					</div>
					<div className="mb-4 flex flex-col gap-2">
						{checklist.map((step, index) => (
							<div
								key={step.label}
								className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-[0.8125rem]"
							>
								<span
									className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[0.6875rem] font-semibold"
									style={{
										color: step.done
											? "var(--color-success)"
											: "var(--color-muted-foreground)",
										background: step.done
											? "color-mix(in srgb, var(--color-success) 12%, transparent)"
											: "var(--color-muted)",
									}}
								>
									{step.done ? (
										<Check data-icon="inline-start" aria-hidden="true" />
									) : (
										index + 1
									)}
								</span>
								<span
									className={
										step.done ? "text-foreground" : "text-muted-foreground"
									}
								>
									{step.label}
								</span>
							</div>
						))}
					</div>
					<div className="flex flex-col gap-2">
						<ActionButton
							icon={<Clipboard data-icon="inline-start" aria-hidden="true" />}
							label="Copy Caption"
							done={!!post.captionCopiedAt}
							busy={busy === "caption_copied"}
							onClick={copyCaption}
						/>
						<ActionButton
							icon={<Share2 data-icon="inline-start" aria-hidden="true" />}
							label="Share Media"
							done={!!post.mediaSharedAt}
							busy={busy === "share"}
							onClick={shareMedia}
							disabled={mediaUrls.length === 0}
						/>
						<ActionButton
							icon={<Download data-icon="inline-start" aria-hidden="true" />}
							label="Download Media"
							done={!!post.mediaDownloadedAt}
							busy={busy === "download"}
							onClick={downloadMedia}
							disabled={mediaUrls.length === 0}
						/>
						<ActionButton
							icon={
								<ExternalLink data-icon="inline-start" aria-hidden="true" />
							}
							label="Open Instagram"
							onClick={openInstagram}
						/>
						<ActionButton
							icon={<Check data-icon="inline-start" aria-hidden="true" />}
							label="Mark Posted"
							done={!!post.manualPublishConfirmedAt}
							busy={busy === "completed"}
							onClick={markPosted}
						/>
					</div>
					{post.manualPublishConfirmedAt && (
						<div className="mt-4 rounded-lg border border-border bg-card p-3">
							<div className="text-[0.8125rem] font-semibold text-foreground">
								Post-publish follow-up
							</div>
							<div className="mt-1 text-[0.71875rem] text-muted-foreground">
								Add the live Instagram URL or notes for later analytics. This is
								optional.
							</div>
							<Field className="mt-3" label="Instagram URL">
								<Input
									id="handoff-live-url"
									value={liveUrl}
									onChange={(event) => setLiveUrl(event.target.value)}
									placeholder="https://www.instagram.com/..."
								/>
							</Field>
							<Field className="mt-3" label="Notes">
								<Textarea
									id="handoff-notes"
									value={notes}
									onChange={(event) => setNotes(event.target.value)}
									rows={3}
									placeholder="What changed in Instagram before posting?"
									className="min-h-24"
								/>
							</Field>
							<div className="mt-3 grid grid-cols-2 gap-2">
								<Button
									type="button"
									onClick={saveFollowUp}
									disabled={busy === "followup"}
								>
									<Save data-icon="inline-start" aria-hidden="true" />
									Save
								</Button>
								<Button
									type="button"
									variant="outline"
									onClick={() => navigate("/calendar")}
								>
									Calendar
								</Button>
								<Button
									type="button"
									variant="outline"
									onClick={() =>
										navigate(
											"/composer?fromHandoff=1&postType=reels&publishMode=notify",
										)
									}
									className="col-span-2"
								>
									Schedule next post
								</Button>
							</div>
						</div>
					)}
				</NovaCard>
			</div>
		</NovaScreen>
	);
}

function ActionButton({
	icon,
	label,
	done = false,
	busy = false,
	disabled = false,
	onClick,
}: {
	icon: React.ReactNode;
	label: string;
	done?: boolean;
	busy?: boolean;
	disabled?: boolean;
	onClick: () => void;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			disabled={disabled || busy}
			variant="outline"
			className="h-11 w-full justify-between"
		>
			<span className="inline-flex items-center gap-2">
				{icon}
				{label}
			</span>
			{done ? (
				<Check
					data-icon="inline-end"
					className="text-[var(--color-success)]"
					aria-hidden="true"
				/>
			) : null}
		</Button>
	);
}
