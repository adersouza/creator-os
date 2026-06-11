import { Plus } from "lucide-react";
import type { ComposerVariant } from "@/services/api/composer";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	Card,
	CardContent,
	CardFooter,
	CardHeader,
} from "@/components/ui/Card";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";

export function VariantsLab({
	variants,
	generating,
	onGenerate,
	onPromote,
	onSelect,
}: {
	variants: ComposerVariant[];
	generating: boolean;
	onGenerate: () => void;
	onPromote: (variant: ComposerVariant) => void;
	onSelect: (variant: ComposerVariant) => void;
}) {
	return (
		<NovaCard
			eyebrow="Variants Lab"
			action={
				<Button
					type="button"
					onClick={onGenerate}
					disabled={generating}
					variant="outline"
					size="sm"
					className="gap-1.5"
				>
					<Plus
						data-icon="inline-start"
						className={cn(generating && "animate-pulse")}
						aria-hidden="true"
					/>
					{generating
						? "Generating…"
						: variants.length > 0
							? "Regenerate"
							: "Generate"}
				</Button>
			}
			contentClassName="flex flex-col gap-3"
		>
			{variants.length > 0 ? (
				<Badge tone="outline" className="w-fit tabular-nums">
					{variants.length} active
				</Badge>
			) : null}
			<div className="grid grid-cols-1 md:grid-cols-3 gap-2">
				{variants.length === 0
					? Array.from({ length: 3 }).map((_, index) => (
							<Card
								key={index}
								material="dense"
								size="sm"
								className="min-h-[142px] rounded-lg border-dashed bg-muted/30 shadow-none"
							>
								<CardHeader className="p-3 pb-0">
									<span className="font-mono text-[0.75rem] text-muted-foreground">
										Variant {String.fromCharCode(65 + index)}
									</span>
									<Skeleton className="h-4 w-9 rounded" />
								</CardHeader>
								<CardContent className="p-3">
									<Skeleton className="h-1.5 rounded-full" />
									<div className="mt-4 flex flex-col gap-2" aria-hidden="true">
										<Skeleton className="h-2 rounded" />
										<Skeleton className="h-2 w-5/6 rounded" />
										<Skeleton className="h-2 w-2/3 rounded" />
									</div>
								</CardContent>
							</Card>
						))
					: variants.map((variant) => {
							const score = Math.max(
								0,
								Math.min(100, variant.predicted_score ?? 0),
							);
							return (
								<Card
									key={variant.id}
									material="dense"
									size="sm"
									className="flex rounded-lg shadow-none"
								>
									<CardHeader className="p-3 pb-0">
										<span className="font-mono text-[0.75rem] text-foreground">
											Variant {variant.variant_label}
										</span>
										<span className="text-[0.6875rem] text-muted-foreground tabular-nums">
											{score}/100
										</span>
									</CardHeader>
									<CardContent className="flex-1 p-3">
										<Progress value={score} className="h-1.5" />
										<p className="mt-3 line-clamp-5 whitespace-pre-wrap text-[0.78125rem] leading-relaxed text-muted-foreground">
											{variant.content}
										</p>
									</CardContent>
									<CardFooter className="mt-auto p-3 pt-0">
										<Button
											type="button"
											onClick={() => onSelect(variant)}
											variant="outline"
											size="sm"
										>
											Edit inline
										</Button>
										<Button
											type="button"
											onClick={() => onPromote(variant)}
											size="sm"
										>
											Promote
										</Button>
									</CardFooter>
								</Card>
							);
						})}
			</div>
		</NovaCard>
	);
}
