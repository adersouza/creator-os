import { useQuery } from "@tanstack/react-query";
import { Sparkles, RefreshCw, BarChart2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaListRow } from "@/components/ui/NovaPrimitives";
import { getCostSummary } from "@/services/api/campaignFactory";

export function AICostMetricsTile({ days = 30 }: { days?: number }) {
	const { data, isLoading, isError, refetch } = useQuery({
		queryKey: ["ai-cost-summary", days],
		queryFn: () => getCostSummary({ days }),
	});

	const totalCost = data?.total_cost_usd || 0;
	const providers = data?.by_provider || {};

	return (
		<NovaCard className="h-full" contentClassName="p-5 flex flex-col">
			<div className="flex items-start justify-between gap-3 mb-4">
				<div>
					<Badge tone="outline" className="gap-1">
						<Sparkles className="h-3 w-3" /> AI Cost Tracker
					</Badge>
					<div className="mt-2 flex items-baseline gap-3">
						<div className="text-4xl font-semibold tracking-[-0.04em] text-foreground">
							{isLoading ? "..." : `$${totalCost.toFixed(2)}`}
						</div>
						<div className="text-xs font-semibold text-muted-foreground">
							{days} Days
						</div>
					</div>
					<div className="mt-1 text-xs text-muted-foreground">
						Total estimated pipeline API spend.
					</div>
				</div>
				<Button
					type="button"
					variant="outline"
					size="sm"
					onClick={() => void refetch()}
					disabled={isLoading}
				>
					<RefreshCw
						className={isLoading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"}
					/>
				</Button>
			</div>

			<div className="flex-1 min-h-[120px] rounded-lg border border-border/50 bg-background/50 p-3 space-y-3">
				{isLoading ? (
					<div className="flex h-full items-center justify-center text-sm text-muted-foreground">
						Loading cost data...
					</div>
				) : isError ? (
					<div className="flex h-full items-center justify-center text-sm text-[var(--color-oxblood)]">
						Failed to load costs.
					</div>
				) : Object.keys(providers).length === 0 ? (
					<div className="flex h-full flex-col items-center justify-center text-sm text-muted-foreground">
						<BarChart2 className="h-6 w-6 mb-2 opacity-50" />
						No API spend recorded.
					</div>
				) : (
					<div className="space-y-2">
						{Object.entries(providers).map(([provider, ops]) => {
							const providerTotal = ops.reduce((acc, op) => acc + op.cost_usd, 0);
							return (
								<NovaListRow
									key={provider}
									className="bg-background"
									title={<span className="capitalize">{provider}</span>}
									meta={
										<span className="text-sm font-semibold">
											${providerTotal.toFixed(2)}
										</span>
									}
									description={
										<div className="mt-1 flex flex-col gap-1">
											{ops.map((op, idx) => (
												<div
													key={`${op.operation}-${idx}`}
													className="flex justify-between items-center text-xs text-muted-foreground"
												>
													<span className="truncate mr-2">
														{op.operation} ({op.calls} calls)
													</span>
													<span className="shrink-0 text-[10px]">
														${op.cost_usd.toFixed(2)}
													</span>
												</div>
											))}
										</div>
									}
								/>
							);
						})}
					</div>
				)}
			</div>
		</NovaCard>
	);
}
