import { Link2 } from "lucide-react";
import { useSmartLinks } from "@/hooks/useSmartLinks";
import { formatCompact } from "@/components/analytics/analyticsShared";
import { Badge } from "@/components/ui/Badge";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";
import { getSmartLinkRowTopPerformer } from "@/lib/smartLinksSampleGate";

export function SmartLinksAnalytics() {
	const { links, isLoading } = useSmartLinks();

	const top5 = [...links]
		.filter((l) => l.isActive && l.clickCount > 0)
		.sort((a, b) => b.clickCount - a.clickCount)
		.slice(0, 5);

	const maxClicks = top5[0]?.clickCount ?? 1;
	const topPerformer = getSmartLinkRowTopPerformer(
		links.filter((link) => link.isActive),
	);

	if (!isLoading && top5.length === 0) return null;

	return (
		<NovaCard
			title={
				<span className="flex items-center gap-2">
					<Link2
						className="h-4 w-4"
						style={{ color: "var(--color-meridian)" }}
					/>
					Top clicked links
				</span>
			}
			description="Ranked by tracked Smart Link clicks."
		>
			{isLoading ? (
				<div className="flex flex-col gap-2">
					{[1, 2, 3].map((i) => (
						<div key={i} className="flex items-center gap-3 rounded-lg border border-border bg-muted/35 p-3">
							<Skeleton className="h-4 flex-1 rounded" />
							<Skeleton className="h-4 w-10 rounded" />
						</div>
					))}
				</div>
			) : (
				<div className="flex flex-col gap-2 rounded-xl border border-border bg-muted/35 p-2">
					{top5.map((link) => (
						<div key={link.id} className="group flex items-center gap-3 rounded-lg border border-transparent p-3 transition-colors hover:border-border hover:bg-card">
							<div className="flex-1 min-w-0">
								<div className="flex min-w-0 items-center gap-2">
									<span className="min-w-0 truncate font-mono text-[0.6875rem] text-muted-foreground transition-colors group-hover:text-foreground">
										/{link.code}
									</span>
									{topPerformer?.id === link.id ? (
										<Badge tone="outline" className="h-[18px] shrink-0 px-1.5 text-[0.5625rem] tracking-normal">
											Top performer
										</Badge>
									) : null}
								</div>
								<Progress
									value={Math.round((link.clickCount / maxClicks) * 100)}
									className="mt-1 [&>div]:bg-[color:var(--color-meridian)]"
									aria-label={`/${link.code} clicks`}
								/>
							</div>
							<div className="text-[0.71875rem] font-medium tabular-nums text-foreground shrink-0 w-10 text-right">
								{formatCompact(link.clickCount)}
							</div>
						</div>
					))}
				</div>
			)}
		</NovaCard>
	);
}
