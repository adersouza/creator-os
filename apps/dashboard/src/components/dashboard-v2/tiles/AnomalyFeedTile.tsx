import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaEmpty,
	NovaInset,
	NovaMiniStat,
} from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAnomalyFeed } from "@/hooks/useAnomalyFeed";
import type { AnomalyAlert } from "@/hooks/useAnomalyFeed";
import { getApiAuthHeaders } from "@/lib/apiAuth";
import { apiUrl } from "@/lib/apiUrl";
import { scopedRoute } from "@/lib/scopedRoutes";
import { appToast } from "@/lib/toast";
import type { DashboardScopeProps } from "../scope";

/**
 * Anomaly feed (mockup #3 redesign) — light tile with per-row severity
 * color-coding. Each row: severity icon + title/body + relative time +
 * category pill. Cuts the prior dark-variant treatment in favor of the
 * mockup's lighter look so it reads as the same visual language as the
 * rest of the All-view band.
 */

type Severity = "crit" | "warn" | "pos";

interface Row {
	id: string;
	state: Severity;
	icon: string;
	title: string;
	body: string;
	baseline: string | null;
	category: string;
	ageMin: number | null;
}

function severityFor(raw: string): Severity {
	const s = raw.toLowerCase();
	if (s === "critical" || s === "crit") return "crit";
	if (s === "good" || s === "positive" || s === "up" || s === "pos")
		return "pos";
	return "warn";
}

function categoryFor(alert: AnomalyAlert): string {
	// Try data.category first; fall back to alertType keywords
	const cat = (alert.data as { category?: string | undefined })?.category;
	if (cat) return cat.toUpperCase().slice(0, 8);
	const t = `${alert.alertType ?? ""} ${alert.title ?? ""}`.toLowerCase();
	if (t.includes("token") || t.includes("expire")) return "TOKEN";
	if (t.includes("reach") || t.includes("suppress")) return "REACH";
	if (t.includes("engage") || t.includes("reply")) return "ENGAGE";
	if (t.includes("pillar") || t.includes("topic")) return "PILLAR";
	if (t.includes("funnel") || t.includes("cta") || t.includes("bio"))
		return "FUNNEL";
	return "NOTE";
}

function actionForCategory(category: string): { label: string; to: string } {
	switch (category) {
		case "TOKEN":
			return { label: "Fix", to: "/accounts?status=flagged" };
		case "REACH":
			return { label: "Inspect", to: "/analytics" };
		case "ENGAGE":
			return { label: "Reply", to: "/inbox" };
		case "PILLAR":
			return { label: "Idea", to: "/ideas" };
		case "FUNNEL":
			return { label: "Links", to: "/links" };
		default:
			return { label: "Open", to: "/analytics" };
	}
}

function ageFor(iso: string | null): number | null {
	if (!iso) return null;
	const t = Date.parse(iso);
	if (!Number.isFinite(t)) return null;
	return Math.max(0, Math.round((Date.now() - t) / 60_000));
}

function formatAge(min: number | null): string {
	if (min === null) return "new";
	if (min < 60) return `${min}m`;
	if (min < 60 * 24) return `${Math.floor(min / 60)}h`;
	return `${Math.floor(min / (60 * 24))}d`;
}

function cleanAlertTitle(title: string): string {
	return (
		title
			.replace(
				/^(\s|\u200D|\uFE0F|\p{Emoji_Presentation}|\p{Extended_Pictographic})+/u,
				"",
			)
			.trim() || title
	);
}

function iconFor(alert: AnomalyAlert): string {
	const text =
		`${alert.alertType ?? ""} ${alert.title ?? ""} ${alert.description ?? ""}`.toLowerCase();
	if (
		text.includes("token") ||
		text.includes("auth") ||
		text.includes("expire")
	)
		return "!";
	if (text.includes("gap") || text.includes("missing") || text.includes("idle"))
		return "○";
	if (text.includes("spike") || text.includes("surge") || text.includes("up"))
		return "↑";
	if (
		text.includes("drop") ||
		text.includes("decline") ||
		text.includes("suppress") ||
		text.includes("down")
	)
		return "↓";
	return "!";
}

function formatUnknownMetric(value: unknown): string | null {
	if (typeof value === "number" && Number.isFinite(value))
		return value.toLocaleString();
	if (typeof value === "string" && value.trim()) return value.trim();
	return null;
}

function baselineFor(alert: AnomalyAlert): string | null {
	const data = alert.data ?? {};
	const baseline =
		formatUnknownMetric(data.baseline) ??
		formatUnknownMetric(data.baselineValue) ??
		formatUnknownMetric(data.previous) ??
		formatUnknownMetric(data.was);
	const current =
		formatUnknownMetric(data.current) ??
		formatUnknownMetric(data.currentValue) ??
		formatUnknownMetric(data.now) ??
		formatUnknownMetric(data.actual);
	return baseline && current ? `(was ${baseline}, now ${current})` : null;
}

export function AnomalyFeedTile({
	scopedAccount,
	accountIds,
	groupId,
	scopeLabel,
}: DashboardScopeProps) {
	const navigate = useNavigate();
	const [resolvingId, setResolvingId] = useState<string | null>(null);
	const scope = { scopedAccount, accountIds, groupId };
	const feed = useAnomalyFeed(
		{ hours: 24 },
		"all",
		scopedAccount,
		accountIds,
		groupId,
	);

	const rows: Row[] = useMemo(() => {
		return feed.alerts.map((a) => ({
			id: a.id,
			state: severityFor(a.severity),
			icon: iconFor(a),
			title: cleanAlertTitle(a.title),
			body: a.description ?? "",
			baseline: baselineFor(a),
			category: categoryFor(a),
			ageMin: ageFor(a.createdAt),
		}));
	}, [feed.alerts]);

	const counts = useMemo(() => {
		let crit = 0;
		let noted = 0;
		for (const a of feed.alerts) {
			if (severityFor(a.severity) === "crit") crit += 1;
			else noted += 1;
		}
		return { crit, noted };
	}, [feed.alerts]);

	const isEmpty = !feed.isLoading && rows.length === 0;
	const emptyScopeLabel = scopedAccount
		? "No account alerts fired."
		: accountIds && accountIds.length > 0
			? `No ${scopeLabel ?? "group"} alerts fired.`
			: "No all-account alerts fired.";

	const resolveAnomaly = async (row: Row) => {
		setResolvingId(row.id);
		try {
			const response = await fetch(apiUrl("/api/operator?action=source-workflow"), {
				method: "PATCH",
				headers: { ...(await getApiAuthHeaders()), "Content-Type": "application/json" },
				body: JSON.stringify({
					source: "anomaly_alert",
					source_id: row.id,
					status: "resolved",
					title: row.title,
					resolution_reason: "Marked handled from Dashboard anomaly feed",
					payload: {
						category: row.category,
						body: row.body,
						baseline: row.baseline,
					},
				}),
			});
			if (!response.ok) {
				const body = (await response.json().catch(() => null)) as { error?: string } | null;
				throw new Error(body?.error || "Failed to mark anomaly handled");
			}
			appToast.success("Anomaly marked handled");
			feed.refetch();
		} catch (error) {
			appToast.error("Could not mark anomaly handled", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setResolvingId(null);
		}
	};

	return (
		<NovaCard
			variant="compact"
			eyebrow="Anomaly feed · last 24h"
			title="Operational alerts"
			description={
				counts.crit + counts.noted > 0
					? `${counts.crit} critical · ${counts.noted} noted`
					: "No active anomaly records in the selected scope."
			}
			action={
				counts.crit + counts.noted > 0 ? (
					<Button
						type="button"
						size="sm"
						onClick={() => navigate(scopedRoute("/analytics", scope))}
					>
						Investigate
					</Button>
				) : (
					<Badge variant="outline">Stable</Badge>
				)
			}
		>
			{isEmpty ? (
				<div className="flex min-h-0 flex-col gap-3">
					<NovaInset className="border-dashed p-3">
						{(["crit", "warn", "pos"] as Severity[]).map((s, i) => (
							<div
								key={s}
								className="grid grid-cols-[32px_minmax(0,1fr)_52px] items-center gap-3 py-1"
								style={{ opacity: 0.52 - i * 0.09 }}
							>
								<div
									className="size-8 rounded-md"
									style={{
										background:
											s === "crit"
												? "color-mix(in srgb, var(--color-error) 14%, transparent)"
												: s === "warn"
													? "color-mix(in srgb, var(--color-warning) 14%, transparent)"
													: "color-mix(in srgb, var(--color-success) 14%, transparent)",
									}}
								/>
								<div className="min-w-0">
									<Skeleton
										className="h-2"
										style={{
											width: i === 0 ? "54%" : i === 1 ? "66%" : "46%",
										}}
									/>
									<Skeleton
										className="mt-1.5 h-1.5"
										style={{
											width: i === 0 ? "78%" : i === 1 ? "58%" : "70%",
											opacity: 0.55,
										}}
									/>
								</div>
								<Skeleton className="h-2 w-full opacity-60" />
							</div>
						))}
					</NovaInset>
					<NovaEmpty
						className="border-solid bg-transparent"
						title={feed.hasError ? "Anomaly scanner offline" : emptyScopeLabel}
						description={
							feed.hasError
								? "Retry once cron sync resumes."
								: "No anomaly records were returned for the last 24h. This is an alert-state, not a full health guarantee."
						}
					/>
					<div className="grid min-w-0 grid-cols-3 gap-2">
						{(["reach", "replies", "saves"] as const).map((label) => (
							<NovaMiniStat
								key={label}
								label={label}
								value={feed.hasError ? "Unchecked" : "Stable"}
								description="24h"
								tone={feed.hasError ? "default" : "success"}
								size="compact"
							/>
						))}
					</div>
				</div>
			) : feed.isLoading ? (
				(["crit", "warn", "pos"] as Severity[]).map((s, i) => (
					<div
						key={s}
						className="mb-2 grid grid-cols-[32px_minmax(0,1fr)_60px] items-center gap-3 rounded-lg border border-dashed border-border bg-muted/35 px-3 py-2.5"
						style={{ opacity: 0.45 - i * 0.08 }}
					>
						<div
							className="grid size-8 place-items-center rounded-md font-bold"
							style={{
								background:
									s === "crit"
										? "color-mix(in srgb, var(--color-error) 14%, transparent)"
										: s === "warn"
											? "color-mix(in srgb, var(--color-warning) 14%, transparent)"
											: "color-mix(in srgb, var(--color-success) 14%, transparent)",
								color:
									s === "crit"
										? "var(--color-error)"
										: s === "warn"
											? "var(--color-warning)"
											: "var(--color-success)",
							}}
						>
							{s === "pos" ? "↑" : "!"}
						</div>
						<div>
							<Skeleton className="h-2.5 w-3/5" />
							<Skeleton className="mt-1.5 h-2 w-4/5 opacity-60" />
						</div>
						<div className="flex flex-col items-end gap-1">
							<Skeleton className="h-2 w-6" />
							<Skeleton className="h-3 w-10 rounded-full" />
						</div>
					</div>
				))
			) : (
				<div className="max-h-[25rem] overflow-y-auto pr-1">
					{rows.map((r) => {
						const colorBase =
							r.state === "crit"
								? "var(--color-error)"
								: r.state === "warn"
									? "var(--color-warning)"
									: "var(--color-success)";
						const action = actionForCategory(r.category);
						return (
							<div
								key={r.id}
								className="mb-2 grid grid-cols-[32px_minmax(0,1fr)] gap-3 rounded-lg border px-3 py-2.5 md:grid-cols-[32px_minmax(0,1fr)_auto] md:items-center"
								style={{
									background: `color-mix(in srgb, ${colorBase} 7%, var(--color-card))`,
									borderColor: `color-mix(in srgb, ${colorBase} 28%, var(--color-border))`,
								}}
							>
								<div
									className="grid size-8 place-items-center rounded-md font-mono text-sm font-bold"
									style={{
										background: `color-mix(in srgb, ${colorBase} 18%, transparent)`,
										color: colorBase,
									}}
								>
									{r.icon}
								</div>
								<div className="min-w-0">
									<div
										className="line-clamp-1 text-[13px] font-medium leading-snug text-foreground"
									>
										{r.title}
									</div>
									{r.body ? (
										<div className="mt-0.5 line-clamp-1 text-[11px] leading-snug text-muted-foreground">
											{r.body}
											{r.baseline ? ` ${r.baseline}` : ""}
										</div>
									) : null}
								</div>
								<div className="flex shrink-0 flex-col items-end gap-1">
									<div className="flex items-center gap-1.5">
										<Button
											type="button"
											variant="outline"
											size="sm"
											onClick={() => navigate(scopedRoute(action.to, scope))}
										>
											{action.label}
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											disabled={resolvingId === r.id}
											onClick={() => void resolveAnomaly(r)}
										>
											{resolvingId === r.id ? "..." : "Done"}
										</Button>
									</div>
									<span className="font-mono text-[10px] text-muted-foreground">
										{formatAge(r.ageMin)}
									</span>
									<Badge variant="outline">{r.category}</Badge>
								</div>
							</div>
						);
					})}
				</div>
			)}
		</NovaCard>
	);
}
