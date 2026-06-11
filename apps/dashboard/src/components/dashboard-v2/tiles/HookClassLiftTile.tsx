import { useHookClassLift, type HookLiftPlatform } from "@/hooks/useHookClassLift";
import { Badge } from "@/components/ui/Badge";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCompact } from "../shared";
import type { DashboardScopeProps } from "../scope";

const HOOK_COLORS = [
	"var(--color-oxblood)",
	"var(--color-warning)",
	"var(--color-chart-2)",
	"var(--color-chart-5)",
];

function labelize(value: string): string {
	return value.replace(/[-_]+/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function liftLabel(lift: number): string {
	if (!Number.isFinite(lift)) return "No lift";
	return `${lift.toFixed(lift >= 10 ? 1 : 2)}×`;
}

export function HookClassLiftTile({
	scopedAccount,
	accountIds,
	groupId,
	periodDays = 30,
	platform = "all",
}: DashboardScopeProps & { periodDays?: number; platform?: HookLiftPlatform }) {
	const {
		hooks,
		fleetAvgReach,
		fleetPostCount,
		thresholdMinPosts,
		notes,
		hasError,
	} = useHookClassLift(periodDays, platform, scopedAccount, accountIds, groupId);
	const top = hooks.slice(0, 4);
	const hasData = top.length > 0;
	const hasScopedSelection =
		!!scopedAccount || !!groupId || (accountIds?.length ?? 0) > 0;
	const baselineScope = scopedAccount
		? scopedAccount.platform === "instagram"
			? "instagram account"
			: "threads account"
		: hasScopedSelection
			? "selected scope"
			: "workspace";

	return (
		<NovaCard
			eyebrow={`Content patterns · ${periodDays}d`}
			title="First-line archetypes"
			description={`Ranked by average reach lift vs ${baselineScope} baseline.`}
			action={<Badge tone="outline">Min {thresholdMinPosts} posts</Badge>}
			contentClassName="flex h-full flex-col"
		>
				{hasData ? (
					<>
						<div
							style={{
								marginTop: 14,
								display: "flex",
								flexDirection: "column",
								gap: 9,
							}}
						>
							{top.map((hook, i) => {
								const position = Math.max(
									0,
									Math.min(100, ((hook.lift - 0.5) / 1.5) * 100),
								);
								const color = HOOK_COLORS[i % HOOK_COLORS.length];
								const isNegative = Number.isFinite(hook.lift) && hook.lift < 1;
								const confidence =
									hook.postCount < 5
										? "low"
										: hook.postCount <= 20
											? "med"
											: "high";
								return (
									<div key={hook.hookClass}>
										<div
											className="flex items-center justify-between"
											style={{ gap: 10 }}
										>
											<div
												className="flex items-center gap-2"
												style={{ minWidth: 0 }}
											>
												<span
													style={{
														width: 8,
														height: 8,
														borderRadius: 999,
														background: color,
														flexShrink: 0,
													}}
												/>
												<span
													style={{
														fontSize: 12,
														fontWeight: 600,
														overflow: "hidden",
														textOverflow: "ellipsis",
														whiteSpace: "nowrap",
													}}
												>
													{labelize(hook.hookClass)}
												</span>
											</div>
											<span
												className="font-mono text-xs font-bold tabular-nums"
												style={{
													color: isNegative ? "var(--color-danger)" : color,
													opacity: confidence === "low" ? 0.55 : 1,
												}}
												title={
													Number.isFinite(hook.lift)
														? undefined
														: `Insufficient sample (<${thresholdMinPosts} posts).`
												}
											>
												{liftLabel(hook.lift)}
											</span>
										</div>
										<div
											style={{
												marginTop: 5,
												height: 8,
												borderRadius: 999,
												background: "var(--color-muted)",
												overflow: "hidden",
												position: "relative",
											}}
										>
											<span
												aria-hidden="true"
												style={{
													position: "absolute",
													left: "33.33%",
													top: 0,
													bottom: 0,
													width: 1,
													background: "var(--color-border)",
												}}
											/>
											<div
												style={{
													marginLeft: isNegative ? `${position}%` : "33.33%",
													width: `${Math.max(2, Math.abs(position - 33.33))}%`,
													height: "100%",
													borderRadius: 999,
													background: isNegative ? "var(--color-danger)" : color,
												}}
											/>
										</div>
										<div
											className="mt-1 text-[0.6875rem] text-muted-foreground"
										>
											<span
												className="mr-1.5 inline-flex rounded-full border border-border px-1.5 py-0.5 text-[0.625rem] uppercase text-muted-foreground"
											>
												{confidence}
											</span>
											{hook.postCount} posts · {formatCompact(hook.avgReach)}{" "}
											avg reach
										</div>
									</div>
								);
							})}
						</div>

						<div
							className="mt-auto flex justify-between gap-3 rounded-lg border border-border bg-muted/35 px-3 py-2"
						>
							<span className="text-xs text-muted-foreground">
								{scopedAccount
									? "Account baseline"
									: hasScopedSelection
										? "Scope baseline"
										: "Workspace baseline"}{" "}
								· {baselineScope}
							</span>
							<span
								className="text-xs font-semibold tabular-nums text-foreground"
							>
								{formatCompact(fleetAvgReach)} reach ·{" "}
								{formatCompact(fleetPostCount)} posts
							</span>
						</div>
						{notes?.reachField ? (
							<div
								className="mt-2 text-[0.6875rem] leading-snug text-muted-foreground"
							>
								Reach note: {notes.reachField}.
							</div>
						) : null}
					</>
				) : (
					<NovaEmpty
						className="mt-2"
						title={hasError ? "First-line patterns unavailable" : "Reading first-line patterns"}
						description={
							hasError
								? "Refresh to retry the pattern read."
								: "Lift appears once each archetype has enough recent posts."
						}
					>
						<div className="grid w-full gap-3">
							{[0.84, 0.64, 0.48, 0.34].map((width, i) => (
								<div key={width}>
									<div className="flex items-center justify-between gap-3">
										<div className="flex flex-1 items-center gap-2">
											<span
												className="size-2 rounded-full"
												style={{
													background: HOOK_COLORS[i % HOOK_COLORS.length],
													opacity: 0.52,
												}}
											/>
											<Skeleton className="h-3" style={{ width: `${Math.max(34, width * 62)}%` }} />
										</div>
										<Skeleton className="h-3 w-8" />
									</div>
									<Skeleton className="mt-2 h-2" style={{ width: `${width * 100}%` }} />
								</div>
							))}
						</div>
					</NovaEmpty>
				)}
		</NovaCard>
	);
}
