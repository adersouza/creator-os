export function ComposerStatusChip({
	label,
	value,
}: {
	label: string;
	value: string;
}) {
	return (
		<div className="h-7 rounded-md border border-border bg-card px-2.5 inline-flex items-center gap-1.5 text-[0.71875rem]">
			<span className="text-muted-foreground">{label}</span>
			<span className="font-medium text-foreground tabular-nums">{value}</span>
		</div>
	);
}
