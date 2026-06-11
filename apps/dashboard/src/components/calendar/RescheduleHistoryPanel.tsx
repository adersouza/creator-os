import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { Sheet } from "@/components/ui/Sheet";
import { supabase } from "@/services/supabase";

interface HistoryRow {
	id: string;
	post_id: string;
	prev_scheduled_at: string | null;
	new_scheduled_at: string | null;
	reason: string | null;
	triggered_by: string | null;
	reverted_at: string | null;
	created_at: string;
}

function fmt(iso: string | null): string {
	if (!iso) return "Draft";
	return new Date(iso).toLocaleString(undefined, {
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	});
}

export function RescheduleHistoryPanel({
	open,
	userId,
	onClose,
}: {
	open: boolean;
	userId: string | null;
	onClose: () => void;
}) {
	const [rows, setRows] = useState<HistoryRow[]>([]);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (!open || !userId) return;
		let cancelled = false;
		supabase
			.from("calendar_reschedule_log")
			.select(
				"id,post_id,prev_scheduled_at,new_scheduled_at,reason,triggered_by,reverted_at,created_at",
			)
			.eq("user_id", userId)
			.order("created_at", { ascending: false })
			.limit(50)
			.then(({ data, error }) => {
				if (cancelled) return;
				if (error) setError(error.message);
				else setRows((data ?? []) as HistoryRow[]);
			});
		return () => {
			cancelled = true;
		};
	}, [open, userId]);

	if (!open) return null;

	return (
		<Sheet
			open={open}
			onClose={onClose}
			title="Reschedule history"
			description="Recent calendar movement and recovery actions."
			widthClass="w-full sm:w-[380px]"
			ariaLabel="Reschedule history"
		>
			{error ? (
				<div className="p-4 text-sm text-muted-foreground">
					History unavailable: {error}
				</div>
			) : rows.length === 0 ? (
				<NovaEmpty
					className="m-4"
					title="No reschedules logged yet"
					description="Calendar moves and recovery actions will appear here."
				/>
			) : (
				<div className="flex flex-col">
					{rows.map((row, index) => (
						<div key={row.id}>
							{index > 0 ? <Separator /> : null}
							<div className="flex flex-col gap-2 p-4">
								<div className="flex items-center justify-between gap-3">
									<div className="text-xs font-semibold text-foreground">
										{row.reason ?? "Reschedule"}
									</div>
									<Badge tone="outline">{row.triggered_by ?? "user"}</Badge>
								</div>
								<div className="font-mono text-[0.6875rem] text-muted-foreground">
									{fmt(row.prev_scheduled_at)}
									<span className="px-1.5 text-muted-foreground">→</span>
									{fmt(row.new_scheduled_at)}
								</div>
								<div className="text-[0.6875rem] text-muted-foreground">
									{new Date(row.created_at).toLocaleString()}
									{row.reverted_at && " · reverted"}
								</div>
							</div>
						</div>
					))}
				</div>
			)}
		</Sheet>
	);
}
