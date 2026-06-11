import type { ComposerCritique } from "@/services/api/composer";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";

export function CritiquePanel({
	critique,
	loading,
}: {
	critique: ComposerCritique | null;
	loading: boolean;
}) {
	const score = Math.max(0, Math.min(100, critique?.score ?? 0));
	const progressTone =
		!critique && !loading
			? "default"
			: score >= 72
				? "good"
				: score >= 45
					? "warn"
					: "critical";
	return (
		<NovaCard
			eyebrow="Critique"
			action={
				<span className="text-[0.65625rem] text-muted-foreground tabular-nums">
					{loading ? "Scoring…" : critique ? `${score}/100` : "Waiting"}
				</span>
			}
			contentClassName="p-4 pt-0"
		>
			<Progress
				value={loading ? 36 : score}
				tone={progressTone}
				className="h-2"
			/>
			{loading && !critique && (
				<div className="mt-3 flex flex-col gap-2" aria-hidden="true">
					<div className="grid grid-cols-2 gap-2">
						<Skeleton className="h-8 rounded-md" />
						<Skeleton className="h-8 rounded-md" />
					</div>
					<Skeleton className="h-9 rounded-md" />
					<Skeleton className="h-9 rounded-md" />
				</div>
			)}
			{!loading && !critique && (
				<NovaEmpty
					className="mt-3 min-h-24 p-4"
					title="No critique yet"
					description="Write a caption and pause briefly to get a score, forecast, and notes."
				/>
			)}
			{critique && (
				<>
					<div className="mt-3 grid grid-cols-2 gap-2 text-[0.75rem]">
						<div className="rounded-md bg-muted px-2 py-1.5 text-muted-foreground">
							<span className="text-muted-foreground">Likes</span>
							<span className="float-right font-mono tabular-nums text-foreground">
								{critique.predicted_likes.toLocaleString()}
							</span>
						</div>
						<div className="rounded-md bg-muted px-2 py-1.5 text-muted-foreground">
							<span className="text-muted-foreground">Replies</span>
							<span className="float-right font-mono tabular-nums text-foreground">
								{critique.predicted_replies.toLocaleString()}
							</span>
						</div>
					</div>
					<div className="mt-3 flex flex-col gap-1.5">
						{critique.reasoning.map((row, index) => (
							<details
								key={`${row.type}-${index}`}
								className="group rounded-md border border-border px-2 py-1.5 text-[0.75rem] open:bg-muted/25"
							>
								<summary className="cursor-pointer capitalize text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] rounded-sm">
									{row.type}
								</summary>
								<p className="mt-1 text-muted-foreground leading-relaxed">
									{row.text}
								</p>
							</details>
						))}
					</div>
				</>
			)}
		</NovaCard>
	);
}
