import { ShieldAlert, Database, History, Info } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { NovaCard, NovaStat } from "@/components/ui/NovaPrimitives";

export function DeletionStatusTab() {
	return (
		<div className="flex flex-col gap-8">
			<div>
				<h1 className="text-2xl font-semibold text-foreground mb-2 flex items-center gap-2">
					Data & Compliance
				</h1>
				<p className="text-base text-muted-foreground">
					Manage data scrubbing, GDPR compliance, and active deletion pipelines.
				</p>
			</div>

			<div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
				{[
					{
						label: "Deletion Queue",
						value: "Coming soon",
						icon: Database,
					},
					{
						label: "Retention Rules",
						value: "Coming soon",
						icon: History,
					},
					{
						label: "Emergency Wipe",
						value: "Owner-only",
						icon: ShieldAlert,
						status: "Owner",
					},
				].map((stat, i) => (
					<NovaStat
						key={i}
						label={stat.label}
						value={stat.value}
						status={stat.status}
						icon={<stat.icon aria-hidden="true" />}
						variant="compact"
					/>
				))}
			</div>

			<NovaCard variant="panel">
				<div className="flex items-start gap-3">
					<span className="w-10 h-10 rounded-lg flex items-center justify-center border border-border bg-card text-muted-foreground shrink-0">
						<ShieldAlert className="w-5 h-5" />
					</span>
					<div className="min-w-0">
						<div className="text-[0.9375rem] font-semibold text-foreground">
							Deletion workflows are not exposed in-app yet
						</div>
						<p className="mt-1 text-[0.78125rem] text-muted-foreground leading-relaxed max-w-[64ch]">
							Data export is live today, but purge queues, retention
							configuration, and emergency wipe controls are still being wired
							to real backend workflows. This panel is intentionally
							informational until those actions ship.
						</p>
					</div>
				</div>
			</NovaCard>

			<div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
				<NovaCard>
					<div className="flex items-center gap-2 text-oxblood dark:text-oxblood mb-2">
						<ShieldAlert className="w-4 h-4" />
						<h4 className="text-base font-bold uppercase tracking-wider">
							Panic Wipe
						</h4>
					</div>
					<p className="text-xs text-oxblood/60 dark:text-oxblood/60 font-medium mb-4">
						Emergency revoke-and-scrub tooling is coming soon. Use the Security
						tab to sign out active sessions for now.
					</p>
					<Badge tone="oxblood" className="h-7 px-3 text-xs">
						Coming soon
					</Badge>
				</NovaCard>
				<NovaCard>
					<div className="flex items-center gap-2 text-foreground mb-2">
						<Info className="w-4 h-4 opacity-60" />
						<h4 className="text-base font-bold uppercase tracking-wider">
							Auto-Scrub
						</h4>
					</div>
					<p className="text-xs text-muted-foreground font-medium mb-4">
						Retention-window controls are not configurable from the product yet.
					</p>
					<Badge tone="secondary" className="h-7 px-3 text-xs">
						Coming soon
					</Badge>
				</NovaCard>
			</div>
		</div>
	);
}
