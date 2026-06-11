import type { PostChannelDiff } from "@/services/api/composer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	Card,
	CardAction,
	CardContent,
	CardHeader,
	CardTitle,
} from "@/components/ui/Card";
import { NovaCard } from "@/components/ui/NovaPrimitives";

export function CrossPostDiffResolver({
	diffs,
	onAccept,
	onRevert,
}: {
	diffs: PostChannelDiff[];
	onAccept: (diff: PostChannelDiff) => void;
	onRevert: (diff: PostChannelDiff) => void;
}) {
	const unresolved = diffs.filter((diff) => diff.status === "unresolved");
	if (unresolved.length === 0) return null;
	return (
		<NovaCard
			eyebrow="Cross-post diffs"
			action={
				<Badge tone="outline" className="tabular-nums">
					{unresolved.length} unresolved
				</Badge>
			}
		>
			<div className="flex flex-col gap-2">
				{unresolved.map((diff) => (
					<Card
						key={diff.id}
						size="sm"
						material="dense"
						className="rounded-lg shadow-none"
					>
						<CardHeader className="p-3 pb-2">
							<CardTitle className="text-[0.75rem] capitalize">
								{diff.platform.replace(/_/g, " ")}
							</CardTitle>
							<CardAction>
								<Button type="button" onClick={() => onAccept(diff)} size="sm">
									Accept
								</Button>
								<Button
									type="button"
									onClick={() => onRevert(diff)}
									variant="outline"
									size="sm"
								>
									Revert
								</Button>
							</CardAction>
						</CardHeader>
						<CardContent className="grid grid-cols-1 gap-2 p-3 pt-0 text-[0.71875rem] md:grid-cols-2">
							<div>
								<div className="mb-1 text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
									Master
								</div>
								<pre className="min-h-20 whitespace-pre-wrap rounded-md bg-muted p-2 text-muted-foreground leading-relaxed">
									{diff.master_caption}
								</pre>
							</div>
							<div>
								<div className="mb-1 text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
									Override
								</div>
								<pre className="min-h-20 whitespace-pre-wrap rounded-md bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)] border border-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)] p-2 text-muted-foreground leading-relaxed">
									{diff.variant_caption}
								</pre>
							</div>
						</CardContent>
					</Card>
				))}
			</div>
		</NovaCard>
	);
}
