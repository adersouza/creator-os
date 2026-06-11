import type { ReactNode } from "react";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { EmptyEvidenceTile } from "./EmptyEvidenceTile";
import { LoadingEvidenceTile } from "./LoadingEvidenceTile";

export type EvidenceTileState = "empty" | "loading" | "data";
export type EvidenceEmptyKind =
	| "error"
	| "filter"
	| "loading"
	| "positive"
	| "sample"
	| "setup";
export type EvidenceTileVariant =
	| "bars"
	| "bullet"
	| "funnel"
	| "heatmap"
	| "line"
	| "list"
	| "network"
	| "table"
	| "thread-tree";

type EvidenceTileProps = {
	state: EvidenceTileState;
	label?: string | undefined;
	title: string;
	note?: string | undefined;
	hint?: string | undefined;
	eyebrow?: string | undefined;
	index?: number | undefined;
	statusLabel?: string | undefined;
	emptyKind?: EvidenceEmptyKind | undefined;
	variant?: EvidenceTileVariant | undefined;
	action?:
		| { label: string; href: string; onClick?: never }
		| { label: string; href?: never; onClick: () => void }
		| undefined;
	children?: ReactNode;
};

export function EvidenceTile({
	state,
	label = "Evidence",
	title,
	note,
	hint,
	eyebrow,
	index,
	statusLabel,
	emptyKind,
	variant = "bars",
	action,
	children,
}: EvidenceTileProps) {
	if (state === "empty") {
		return (
			<EmptyEvidenceTile
				label={label}
				title={title}
				note={note ?? hint ?? "No qualified sample for this scope yet."}
				statusLabel={statusLabel}
				kind={emptyKind}
				variant={variant === "list" ? "table" : variant}
				action={action}
			/>
		);
	}

	if (state === "loading") {
		return (
			<LoadingEvidenceTile
				index={index}
				title={title}
				hint={hint}
				eyebrow={eyebrow}
				variant={variant}
			/>
		);
	}

	return (
		<EvidenceCard
			className="analytics-evidence-tile h-full w-full flex flex-col p-0"
			contentClassName="p-0 flex-1 flex flex-col"
		>
			{children}
		</EvidenceCard>
	);
}
