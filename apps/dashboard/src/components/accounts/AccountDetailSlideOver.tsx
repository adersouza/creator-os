import type React from "react";
import { useEffect, useState } from "react";
import {
	BarChart3,
	CalendarDays,
	ExternalLink,
	FolderInput,
	Heart,
	MessageCircle,
	Pause,
	PlugZap,
	RefreshCw,
	Repeat2,
	ShieldCheck,
	Trash2,
	Users,
} from "lucide-react";
import { z } from "zod";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Separator } from "@/components/ui/Separator";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/Skeleton";
import { NovaEmpty, NovaStat } from "@/components/ui/NovaPrimitives";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import { apiFetch } from "@/lib/apiFetch";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import { instagramService } from "@/services/instagramService";
import type { FleetAccount } from "@/hooks/useFleetAccounts";
import {
	accountSignalStatus,
	formatFollowers,
	formatLastPost,
	signalLabel,
	signalSeverityColor,
	type AccountHealthSignal,
} from "./shared";

interface RecentPostPreview {
	content: string;
	mediaUrl: string | null;
	publishedAt: string | null;
}

interface CollaborativeMediaItem {
	id: string;
	caption?: string | undefined;
	media_type?: string | undefined;
	media_product_type?: string | undefined;
	media_url?: string | undefined;
	thumbnail_url?: string | undefined;
	permalink?: string | undefined;
	timestamp?: string | undefined;
	username?: string | undefined;
	like_count?: number | undefined;
	comments_count?: number | undefined;
	reposts_count?: number | undefined;
	saved_count?: number | undefined;
	shares_count?: number | undefined;
	total_like_count?: number | undefined;
	total_comments_count?: number | undefined;
	total_views_count?: number | undefined;
}

interface CollaborativeMediaResponse {
	success?: boolean | undefined;
	media?: CollaborativeMediaItem[] | undefined;
}

interface AccountDetailSlideOverProps {
	account: FleetAccount;
	signals: AccountHealthSignal[];
	onClose: () => void;
	onViewInScheduler: () => void;
	onViewAnalytics: () => void;
	onPause: () => void;
	onMoveGroup: () => void;
	onSync: () => void;
	onReconnect: () => void;
	onRemove: () => void;
	onSignalsRefresh: () => void;
}

const healthPingSchema = z.object({ ok: z.boolean().optional() }).passthrough();

export function AccountDetailSlideOver({
	account,
	signals,
	onClose,
	onViewInScheduler,
	onViewAnalytics,
	onPause,
	onMoveGroup,
	onSync,
	onReconnect,
	onRemove,
	onSignalsRefresh,
}: AccountDetailSlideOverProps) {
	const ui = accountSignalStatus(account.health, signals);
	const [recentPost, setRecentPost] = useState<RecentPostPreview | null>(null);
	const [tab, setTab] = useState<"overview" | "health" | "collabs">("overview");
	const [healthBusy, setHealthBusy] = useState(false);
	const [collabMedia, setCollabMedia] = useState<CollaborativeMediaItem[]>([]);
	const [collabLoading, setCollabLoading] = useState(false);
	const [collabError, setCollabError] = useState<string | null>(null);

	useEffect(() => {
		if (account.platform !== "instagram" && tab === "collabs")
			setTab("overview");
	}, [account.platform, tab]);

	useEffect(() => {
		let cancelled = false;
		if (!account.lastPublishedAt) {
			setRecentPost(null);
			return () => {
				cancelled = true;
			};
		}
		(async () => {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user || cancelled) return;
			const column =
				account.platform === "instagram"
					? "instagram_account_id"
					: "account_id";
			const { data } = await supabase
				.from("posts")
				.select("content, media_urls, published_at")
				.eq("user_id", user.id)
				.eq("status", "published")
				.eq(column, account.id)
				.order("published_at", { ascending: false, nullsFirst: false })
				.limit(1)
				.maybeSingle();
			if (cancelled || !data) return;
			setRecentPost({
				content: (data.content as string | null) ?? "",
				mediaUrl:
					Array.isArray(data.media_urls) && data.media_urls.length > 0
						? String(data.media_urls[0])
						: null,
				publishedAt: (data.published_at as string | null) ?? null,
			});
		})();
		return () => {
			cancelled = true;
		};
	}, [account.id, account.platform, account.lastPublishedAt]);

	useEffect(() => {
		let cancelled = false;
		if (account.platform !== "instagram" || tab !== "collabs") return;
		setCollabLoading(true);
		setCollabError(null);
		instagramService
			.getCollaborativeMedia(account.id, 20)
			.then((response) => {
				if (cancelled) return;
				const data = response as CollaborativeMediaResponse | null;
				setCollabMedia(data?.media ?? []);
			})
			.catch((error) => {
				if (cancelled) return;
				setCollabError(
					error instanceof Error
						? error.message
						: "Could not load collaborative media",
				);
				setCollabMedia([]);
			})
			.finally(() => {
				if (!cancelled) setCollabLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [account.id, account.platform, tab]);

	const healthDot =
		ui === "flagged"
			? "var(--color-critical)"
			: ui === "drifting"
				? "var(--color-warning)"
				: ui === "inactive"
					? "color-mix(in_srgb,var(--color-foreground)_30%,transparent)"
					: "var(--color-health-good)";
	const isPaused = ui === "inactive";

	const runHealthCheck = async () => {
		setHealthBusy(true);
		try {
			await apiFetch("/api/health?action=ping", healthPingSchema, {
				method: "POST",
				json: { accountId: account.id, platform: account.platform },
			});
			onSignalsRefresh();
			appToast.success("Health check complete");
		} catch (error) {
			appToast.error("Health check failed", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setHealthBusy(false);
		}
	};

	return (
		<Sheet
			open
			onClose={onClose}
			ariaLabel="Account details"
			widthClass="w-full sm:w-[560px]"
			title={
				<div className="flex min-w-0 items-center gap-3">
					<div
						className="size-10 rounded-full shrink-0 flex items-center justify-center text-[0.875rem] font-semibold text-white"
						style={{
							background: `linear-gradient(135deg, ${account.groupColor}, color-mix(in srgb, ${account.groupColor} 60%, var(--color-ink)))`,
						}}
					>
						{(account.displayName[0] ?? ".").toUpperCase()}
					</div>
					<div className="min-w-0">
						<div className="text-[0.9375rem] font-medium text-foreground truncate">
							{account.handle}
						</div>
						<div className="text-[0.71875rem] text-muted-foreground flex items-center gap-1.5">
							<span className="capitalize">{account.platform}</span>
							<span className="text-muted-foreground">-</span>
							<span>{account.groupName}</span>
							<span className="text-muted-foreground">-</span>
							<span className="tabular-nums">
								{formatFollowers(account.followers)}
							</span>
						</div>
					</div>
				</div>
			}
		>
			<div className="flex min-h-0 flex-1 flex-col">
				<div className="border-b border-border px-6 pt-4 pb-3">
					<ToggleGroup
						type="single"
						value={tab}
						onValueChange={(value) => {
							if (
								value === "overview" ||
								value === "health" ||
								value === "collabs"
							) {
								setTab(value);
							}
						}}
						aria-label="Account detail section"
					>
						<ToggleGroupItem value="overview" sizeVariant="sm">
							Overview
						</ToggleGroupItem>
						<ToggleGroupItem value="health" sizeVariant="sm">
							Health
						</ToggleGroupItem>
						{account.platform === "instagram" && (
							<ToggleGroupItem value="collabs" sizeVariant="sm">
								Collabs
							</ToggleGroupItem>
						)}
					</ToggleGroup>
				</div>

				<div className="flex flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
					{tab === "overview" ? (
						<OverviewTab
							account={account}
							ui={ui}
							healthDot={healthDot}
							recentPost={recentPost}
						/>
					) : tab === "health" ? (
						<HealthTab
							signals={signals}
							account={account}
							busy={healthBusy}
							onRunHealthCheck={() => void runHealthCheck()}
						/>
					) : (
						<CollaborativeMediaTab
							items={collabMedia}
							loading={collabLoading}
							error={collabError}
							accountHandle={account.handle}
						/>
					)}
				</div>

				<Separator />
				<div className="px-6 py-4">
					<div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
						<FooterButton label="Scheduler" onClick={onViewInScheduler} primary>
							<CalendarDays data-icon="inline-start" />
						</FooterButton>
						<FooterButton label="Analytics" onClick={onViewAnalytics}>
							<BarChart3 data-icon="inline-start" />
						</FooterButton>
						<FooterButton label="Move group" onClick={onMoveGroup}>
							<FolderInput data-icon="inline-start" />
						</FooterButton>
						<FooterButton label="Sync now" onClick={onSync}>
							<RefreshCw data-icon="inline-start" />
						</FooterButton>
						<FooterButton
							label="Health check"
							onClick={() => void runHealthCheck()}
						>
							<ShieldCheck data-icon="inline-start" />
						</FooterButton>
						<FooterButton label="Reconnect" onClick={onReconnect}>
							<PlugZap data-icon="inline-start" />
						</FooterButton>
						<FooterButton
							label={isPaused ? "Resume" : "Pause"}
							onClick={onPause}
						>
							<Pause data-icon="inline-start" />
						</FooterButton>
						<FooterButton label="Remove" onClick={onRemove} destructive>
							<Trash2 data-icon="inline-start" />
						</FooterButton>
					</div>
				</div>
			</div>
		</Sheet>
	);
}

function FooterButton({
	children,
	label,
	primary,
	destructive,
	onClick,
}: {
	children: React.ReactNode;
	label: string;
	primary?: boolean | undefined;
	destructive?: boolean | undefined;
	onClick: () => void;
}) {
	const variant = destructive ? "danger" : primary ? "default" : "secondary";

	return (
		<Button
			type="button"
			onClick={onClick}
			variant={variant}
			size="sm"
			className="h-9 px-2 text-[0.78125rem]"
		>
			{children}
			<span className="truncate">{label}</span>
		</Button>
	);
}

function OverviewTab({
	account,
	ui,
	healthDot,
	recentPost,
}: {
	account: FleetAccount;
	ui: ReturnType<typeof accountSignalStatus>;
	healthDot: string;
	recentPost: RecentPostPreview | null;
}) {
	return (
		<>
			<div className="grid grid-cols-3 gap-2 sm:gap-3">
				<NovaStat
					label="Health"
					value={account.healthScore}
					status={
						<span
							className="size-1 rounded-full"
							style={{ background: healthDot }}
							aria-hidden="true"
						/>
					}
					variant="compact"
					className="min-h-0"
				/>
				<NovaStat
					label="Posts (24h)"
					value={account.posts24h}
					variant="compact"
					className="min-h-0"
				/>
				<NovaStat
					label="Followers"
					value={formatFollowers(account.followers)}
					variant="compact"
					className="min-h-0"
				/>
			</div>
			<section>
				<SectionHeader>Engagement - 7 days</SectionHeader>
				<div className="h-24 flex items-end gap-1 mt-2 px-1">
					{(() => {
						const max = Math.max(...account.trend7d, 0.0001);
						return account.trend7d.map((value, index) => (
							<div
								key={index}
								className="flex-1 rounded-t-sm"
								style={{
									height: `${(value / max) * 100}%`,
									background:
										ui === "flagged"
											? "var(--color-critical)"
											: ui === "drifting"
												? "var(--color-warning)"
												: "var(--color-foreground)",
									opacity: ui === "active" ? 0.7 : 0.9,
								}}
							/>
						));
					})()}
				</div>
				{account.trend7d.every((value) => value === 0) && (
					<div className="mt-2 text-[0.71875rem] text-muted-foreground">
						Not enough data yet. Trend appears after the first 7 days.
					</div>
				)}
			</section>
			{account.lastPublishedAt && (
				<section>
					<SectionHeader>Most recent post</SectionHeader>
					<div className="mt-2 flex flex-col gap-2">
						<div className="rounded-md bg-muted/50 p-3 text-[0.78125rem] text-foreground/85">
							<div className="flex items-start gap-2.5">
								{recentPost?.mediaUrl ? (
									<img
										src={recentPost.mediaUrl}
										alt=""
										loading="lazy"
										decoding="async"
										className="size-10 rounded-md object-cover shrink-0 bg-muted"
									/>
								) : (
									<div
										className="size-10 rounded-md shrink-0"
										style={{
											background: `linear-gradient(135deg, ${account.groupColor}, color-mix(in srgb, ${account.groupColor} 55%, var(--color-ink)))`,
										}}
										aria-hidden="true"
									/>
								)}
								<div className="min-w-0 flex-1">
									{recentPost?.content ? (
										<p className="text-[0.78125rem] text-foreground line-clamp-2 leading-snug">
											{recentPost.content}
										</p>
									) : (
										<p className="text-[0.78125rem] text-muted-foreground italic">
											No caption
										</p>
									)}
									<div className="mt-1 text-[0.6875rem] text-muted-foreground tabular-nums">
										{formatLastPost(account.lastPostHoursAgo)} ago -{" "}
										{account.posts24h} in last 24h
									</div>
								</div>
							</div>
						</div>
					</div>
				</section>
			)}
			<section>
				<SectionHeader>API token</SectionHeader>
				<div className="mt-2 flex items-center gap-2 text-[0.78125rem]">
					<span
						className="w-1.5 h-1.5 rounded-full"
						style={{
							background: account.tokenActive
								? "var(--color-health-good)"
								: "var(--color-critical)",
						}}
					/>
					<span className="text-foreground">
						{account.tokenActive
							? "Active"
							: account.needsReauth
								? "Needs reauth"
								: "Expired"}
					</span>
					{account.tokenActive && account.tokenDaysLeft !== null && (
						<span className="text-muted-foreground tabular-nums">
							- {account.tokenDaysLeft}d remaining
						</span>
					)}
				</div>
			</section>
		</>
	);
}

function HealthTab({
	signals,
	account,
	busy,
	onRunHealthCheck,
}: {
	signals: AccountHealthSignal[];
	account: FleetAccount;
	busy: boolean;
	onRunHealthCheck: () => void;
}) {
	return (
		<section className="flex flex-col gap-3">
			<div className="flex items-center justify-between">
				<SectionHeader>Health signals</SectionHeader>
				<Button
					type="button"
					onClick={onRunHealthCheck}
					disabled={busy}
					variant="secondary"
					size="sm"
				>
					{busy ? "Checking..." : "Run health check"}
				</Button>
			</div>
			<div className="flex flex-col gap-2">
				{signals.length > 0 ? (
					signals.map((signal) => (
						<div
							key={signal.id}
							className="rounded-md border border-border bg-muted/30 p-3"
						>
							<div className="flex items-center gap-2">
								<span
									className="rounded-[4px] px-2 py-1 text-[0.65625rem] font-semibold uppercase tracking-[0.08em] text-background"
									style={{ background: signalSeverityColor(signal.severity) }}
								>
									{signalLabel(signal.signal_type)}
								</span>
								<span className="text-[0.71875rem] capitalize text-muted-foreground">
									{signal.severity}
								</span>
							</div>
							<div className="mt-2 text-[0.71875rem] text-muted-foreground tabular-nums">
								Detected {new Date(signal.detected_at).toLocaleString()} -{" "}
								{signal.resolved_at
									? `Resolved ${new Date(signal.resolved_at).toLocaleString()}`
									: "Active"}
							</div>
						</div>
					))
				) : (
					<NovaEmpty
						className="min-h-24 p-4"
						title="No health signals"
						description={`No persisted health signals for ${account.handle}.`}
					/>
				)}
			</div>
		</section>
	);
}

function CollaborativeMediaTab({
	items,
	loading,
	error,
	accountHandle,
}: {
	items: CollaborativeMediaItem[];
	loading: boolean;
	error: string | null;
	accountHandle: string;
}) {
	return (
		<section className="flex flex-col gap-3">
			<div className="flex items-center justify-between gap-3">
				<SectionHeader>Collaborative media</SectionHeader>
				<span className="text-[0.6875rem] text-muted-foreground tabular-nums">
					{loading
						? "Loading"
						: `${items.length} item${items.length === 1 ? "" : "s"}`}
				</span>
			</div>
			{error ? (
				<div className="rounded-md border border-[color-mix(in_srgb,var(--color-critical)_18%,transparent)] bg-[color-mix(in_srgb,var(--color-critical)_6%,transparent)] p-4 text-[0.8125rem] text-foreground">
					{error}
				</div>
			) : loading ? (
				<div className="grid grid-cols-1 gap-2">
					{Array.from({ length: 3 }).map((_, index) => (
						<Skeleton
							key={index}
							className="h-24 rounded-md border border-border"
						/>
					))}
				</div>
			) : items.length === 0 ? (
				<NovaEmpty
					className="min-h-24 p-4"
					title="No collaborative media"
					description={`No accepted collaborative media found for ${accountHandle}.`}
				/>
			) : (
				<div className="flex flex-col gap-2">
					{items.map((item) => (
						<CollaborativeMediaCard key={item.id} item={item} />
					))}
				</div>
			)}
		</section>
	);
}

function CollaborativeMediaCard({ item }: { item: CollaborativeMediaItem }) {
	const imageUrl = item.thumbnail_url || item.media_url || null;
	const likes = item.total_like_count ?? item.like_count ?? 0;
	const comments = item.total_comments_count ?? item.comments_count ?? 0;
	const views = item.total_views_count ?? 0;

	return (
		<article className="rounded-md border border-border bg-muted/50 p-3">
			<div className="flex gap-3">
				{imageUrl ? (
					<img
						src={imageUrl}
						alt=""
						loading="lazy"
						decoding="async"
						className="size-16 rounded-md object-cover shrink-0 bg-muted"
					/>
				) : (
					<div className="size-16 rounded-md shrink-0 bg-muted flex items-center justify-center text-muted-foreground">
						<Users data-icon="inline" aria-hidden="true" />
					</div>
				)}
				<div className="min-w-0 flex-1">
					<div className="flex items-start justify-between gap-2">
						<div className="min-w-0">
							<div className="text-[0.75rem] font-medium text-foreground truncate">
								{item.username
									? `@${item.username}`
									: item.media_product_type ||
										item.media_type ||
										"Collaborative post"}
							</div>
							<p className="mt-1 text-[0.71875rem] leading-[1.45] text-muted-foreground line-clamp-2">
								{item.caption || "No caption"}
							</p>
						</div>
						{item.permalink && (
							<Button
								asChild
								variant="outline"
								size="icon"
								className="size-7 shrink-0"
							>
								<a
									href={item.permalink}
									target="_blank"
									rel="noreferrer"
									aria-label="Open collaborative media on Instagram"
								>
									<ExternalLink aria-hidden="true" />
								</a>
							</Button>
						)}
					</div>
					<div className="mt-2 flex flex-wrap items-center gap-2 text-[0.6875rem] text-muted-foreground tabular-nums">
						<MetricChip icon={<Heart data-icon="inline-start" />} value={likes} />
						<MetricChip
							icon={<MessageCircle data-icon="inline-start" />}
							value={comments}
						/>
						<MetricChip
							icon={<Repeat2 data-icon="inline-start" />}
							value={item.reposts_count ?? 0}
						/>
						{views > 0 && <MetricChip label="Views" value={views} />}
					</div>
				</div>
			</div>
		</article>
	);
}

function MetricChip({
	icon,
	label,
	value,
}: {
	icon?: React.ReactNode;
	label?: string | undefined;
	value: number;
}) {
	return (
		<Badge tone="outline" className="tabular-nums">
			{icon}
			{label && <span>{label}</span>}
			<span>{value.toLocaleString()}</span>
		</Badge>
	);
}

function SectionHeader({ children }: { children: React.ReactNode }) {
	return (
		<h3 className="text-[0.65625rem] uppercase tracking-[0.08em] font-medium text-muted-foreground">
			{children}
		</h3>
	);
}
