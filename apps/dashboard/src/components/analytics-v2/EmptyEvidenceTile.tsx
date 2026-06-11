import { Button } from "@/components/ui/Button";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";

type EvidenceEmptyKind =
	| "error"
	| "filter"
	| "loading"
	| "positive"
	| "sample"
	| "setup";
type EvidenceEmptyPreview =
	| "account-grid"
	| "bars"
	| "bullet"
	| "funnel"
	| "heatmap"
	| "line"
	| "network"
	| "status"
	| "table"
	| "thread-tree";
export type EmptyPreview = EvidenceEmptyPreview;

export function EmptyEvidenceTile({
	label,
	title,
	note,
	statusLabel = "Awaiting qualified sample",
	action,
}: {
	label: string;
	title: string;
	note: string;
	variant?: EmptyPreview | undefined;
	statusLabel?: string | undefined;
	kind?: EvidenceEmptyKind | undefined;
	action?:
		| { label: string; href: string; onClick?: never }
		| { label: string; href?: never; onClick: () => void }
		| undefined;
}) {
	const displayLabel = sanitizeLabel(label, title) ?? undefined;
	const actionNode = action ? (
		action.href ? (
			<Button asChild size="sm">
				<a href={action.href}>{action.label}</a>
			</Button>
		) : (
			<Button size="sm" onClick={action.onClick}>
				{action.label}
			</Button>
		)
	) : null;

	return (
		<EvidenceCard
			state="empty"
			className="analytics-evidence-tile h-full w-full min-h-[220px] p-0"
			contentClassName="p-4 flex h-full flex-col"
		>
			<NovaEmpty
				className="h-full flex-1 justify-center"
				eyebrow={displayLabel}
				title={statusLabel}
				description={note}
				action={actionNode}
			/>
		</EvidenceCard>
	);
}

function sanitizeLabel(label: string, title: string): string | null {
	const clean = label
		.replace(/\s*·?\s*§\s*\d+\b/g, "")
		.replace(/\s+/g, " ")
		.trim();
	if (!clean) return null;
	if (/^(evidence|analytics|upcoming)$/i.test(clean)) return null;
	const normalizedLabel = clean.toLowerCase().replace(/\s+/g, "");
	const normalizedTitle = title.toLowerCase().replace(/\s+/g, "");
	if (normalizedTitle.startsWith(normalizedLabel)) return null;
	return clean;
}
