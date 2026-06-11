import { NovaCard, type NovaCardProps } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";

export interface EvidenceCardProps extends NovaCardProps {
	state?: "data" | "loading" | "empty" | undefined;
}

export function EvidenceCard({
	state = "data",
	className,
	...props
}: EvidenceCardProps) {
	return (
		<NovaCard
			className={cn(
				"evidence-card h-full",
				state !== "data" && "border-dashed",
				className,
			)}
			{...props}
		/>
	);
}
