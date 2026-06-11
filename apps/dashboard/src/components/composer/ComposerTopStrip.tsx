import { GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ComposerVariant } from "@/services/api/composer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";

export function ComposerTopStrip({
	variants,
	activeVariantId,
	targetCount,
	critiqueScore,
	generating,
	onSelectMaster,
	onSelectVariant,
	onGenerate,
}: {
	variants: ComposerVariant[];
	activeVariantId: string;
	targetCount: number;
	critiqueScore: number | null;
	generating: boolean;
	onSelectMaster: () => void;
	onSelectVariant: (variant: ComposerVariant) => void;
	onGenerate: () => void;
}) {
	const visibleVariants = variants.slice(0, 3);
	return (
		<NovaCard className="mb-5" contentClassName="px-3 py-2">
			<div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
				<div className="flex min-w-0 items-center gap-2">
					<Badge
						tone="outline"
						className="h-7 gap-1.5 uppercase tracking-[0.1em]"
					>
						<GitBranch className="h-3.5 w-3.5" />
						Variants
					</Badge>
					<div
						role="tablist"
						aria-label="Composer variants"
						className="inline-flex rounded-md border border-border bg-muted p-0.5"
					>
						<VariantTab
							label="Master"
							active={activeVariantId === "master"}
							score={critiqueScore}
							onClick={onSelectMaster}
						/>
						{visibleVariants.map((variant) => (
							<VariantTab
								key={variant.id}
								label={variant.variant_label || "Variant"}
								active={activeVariantId === variant.id}
								score={variant.predicted_score ?? null}
								onClick={() => onSelectVariant(variant)}
							/>
						))}
						{visibleVariants.length < 3 && (
							<Button
								type="button"
								variant="ghost"
								size="sm"
								onClick={onGenerate}
								disabled={generating}
								className="min-w-8 px-2"
							>
								{generating ? "..." : "+"}
							</Button>
						)}
					</div>
				</div>
				<div className="flex flex-wrap items-center gap-2">
					<Badge tone="outline" className="h-7 gap-1.5">
						<span className="h-1.5 w-1.5 rounded-full bg-[var(--color-health-good)]" />
						Targets selected · {targetCount}
					</Badge>
				</div>
			</div>
		</NovaCard>
	);
}

function VariantTab({
	label,
	active,
	score,
	onClick,
}: {
	label: string;
	active: boolean;
	score: number | null;
	onClick: () => void;
}) {
	const tone =
		score === null
			? "var(--color-label-tertiary)"
			: score >= 72
				? "var(--color-health-good)"
				: score >= 45
					? "var(--color-gold)"
					: "var(--color-oxblood)";
	return (
		<Button
			type="button"
			variant={active ? "secondary" : "ghost"}
			size="sm"
			role="tab"
			aria-selected={active}
			onClick={onClick}
			className={cn("min-w-10 px-2", active && "bg-card shadow-sm")}
		>
			<span className="inline-flex items-center gap-1.5">
				<span
					className="h-1.5 w-1.5 rounded-full"
					style={{ background: tone }}
				/>
				{label}
			</span>
		</Button>
	);
}
