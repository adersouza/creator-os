import { Link } from "react-router-dom";
import { ArrowUpRight, Link2 } from "lucide-react";
import { useSmartLinks } from "@/hooks/useSmartLinks";
import { formatCompact } from "@/components/analytics/analyticsShared";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaDataPanel,
	NovaEmpty,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
} from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { getSmartLinkRowTopPerformer } from "@/lib/smartLinksSampleGate";

export function SmartLinksAnalytics() {
	const { links, isLoading } = useSmartLinks();

	const top5 = [...links]
		.filter((l) => l.isActive && l.clickCount > 0)
		.sort((a, b) => b.clickCount - a.clickCount)
		.slice(0, 5);
	const activeLinks = links.filter((link) => link.isActive);
	const totalClicks = activeLinks.reduce((sum, link) => sum + link.clickCount, 0);

	const maxClicks = top5[0]?.clickCount ?? 1;
	const topPerformer = getSmartLinkRowTopPerformer(
		activeLinks,
	);

	return (
		<NovaSection className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
			<NovaDataPanel
				title="Link performance"
				description="Smart Link clicks and active destinations for the selected workspace."
				toolbar={
					<Button asChild variant="outline" size="sm">
						<Link to="/links">
							Open Links
							<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
						</Link>
					</Button>
				}
				loading={isLoading}
			>
				<div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
					<NovaMiniStat
						label="Active links"
						value={activeLinks.length.toLocaleString()}
						description="Available destinations"
					/>
					<NovaMiniStat
						label="Tracked clicks"
						value={formatCompact(totalClicks)}
						description="Across active links"
						tone={totalClicks > 0 ? "primary" : "default"}
					/>
					<NovaMiniStat
						label="Best link"
						value={topPerformer ? `/${topPerformer.code}` : "Unavailable"}
						description={topPerformer ? `${formatCompact(topPerformer.clickCount)} clicks` : "No clicked links yet"}
					/>
				</div>
			</NovaDataPanel>

			<NovaCard
				title={
					<span className="inline-flex items-center gap-2">
						<Link2 data-icon="inline-start" aria-hidden="true" />
						Top clicked links
					</span>
				}
				description="Ranked by tracked Smart Link clicks."
				action={<Badge tone="outline">{top5.length} shown</Badge>}
			>
				{isLoading ? (
					<div className="flex flex-col gap-2">
						{[1, 2, 3].map((i) => (
							<div key={i} className="flex items-center gap-3 rounded-lg border border-border bg-muted/45 p-3">
								<Skeleton className="h-4 flex-1 rounded" />
								<Skeleton className="h-4 w-10 rounded" />
							</div>
						))}
					</div>
				) : top5.length > 0 ? (
					<div className="flex flex-col gap-2">
						{top5.map((link) => (
							<NovaListRow
								key={link.id}
								leading={<Link2 data-icon="inline-start" aria-hidden="true" />}
								title={`/${link.code}`}
								description={`${formatCompact(link.clickCount)} tracked clicks`}
								meta={
									topPerformer?.id === link.id ? (
										<Badge tone="outline">Top performer</Badge>
									) : null
								}
								progress={Math.round((link.clickCount / maxClicks) * 100)}
								progressLabel={`/${link.code} share of top clicked links`}
							/>
						))}
					</div>
				) : (
					<NovaEmpty
						title="No clicked links yet"
						description={
							activeLinks.length > 0
								? "Active links are ready. Click data will appear here after traffic is tracked."
								: "Create or activate a Smart Link to start tracking link performance."
						}
						action={
							<Button asChild>
								<Link to="/links">
									Open Links
									<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
								</Link>
							</Button>
						}
						icon={<Link2 data-icon="inline-start" aria-hidden="true" />}
					/>
				)}
			</NovaCard>
		</NovaSection>
	);
}
