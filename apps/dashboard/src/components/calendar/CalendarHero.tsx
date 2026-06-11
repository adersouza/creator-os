import {
	CalendarClock,
	ChevronLeft,
	ChevronRight,
	PenSquare,
} from "lucide-react";
import { AccountScopeChip } from "@/components/ui/AccountScopeChip";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaHeader } from "@/components/ui/NovaPrimitives";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import type { ViewMode } from "./shared";

/* =========================================================================
   HERO + CONTROLS — extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
export function CalendarHero({
	weekLabel,
	onPrevWeek,
	onNextWeek,
	onToday,
	onNewPost,
	viewMode,
	setViewMode,
	totals,
	isCurrentWeek,
	scopedAccount,
	publishingQuota,
	onClearScope,
}: {
	weekLabel: string;
	onPrevWeek: () => void;
	onNextWeek: () => void;
	onToday: () => void;
	onNewPost: () => void;
	viewMode: ViewMode;
	setViewMode: (v: ViewMode) => void;
	totals: { queue: number; visible: number };
	isCurrentWeek: boolean;
	scopedAccount: { handle: string; groupColor: string } | null;
	publishingQuota?:
		| { remaining: number; limit: number; windowHours: number }
		| null
		| undefined;
	onClearScope: () => void;
}) {
	const views: { id: ViewMode; label: string }[] = [
		{ id: "week", label: "Week" },
		{ id: "month", label: "Month" },
		{ id: "list", label: "List" },
		{ id: "streaks", label: "Streaks" },
		{ id: "portfolio", label: "Portfolio" },
	];

	// Timezone label — all scheduler times render in the operator's browser TZ
	// until a workspace-wide override lands. Use the short name (e.g. "EDT")
	// with the IANA zone as a tooltip so the operator can verify.
	const { tzShort, tzFull } = (() => {
		try {
			const now = new Date();
			const full = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
			const parts = new Intl.DateTimeFormat(undefined, {
				timeZoneName: "short",
			}).formatToParts(now);
			const name = parts.find((p) => p.type === "timeZoneName")?.value || full;
			return { tzShort: name, tzFull: full };
		} catch {
			return { tzShort: "UTC", tzFull: "UTC" };
		}
	})();

	return (
		<NovaHeader
			title="Content calendar"
			description="Plan, schedule, and publish content across Threads and Instagram."
			filters={
				<div className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-muted-foreground tabular-nums">
					{scopedAccount ? (
						<>
							<Badge tone="oxblood">Scope</Badge>
							<AccountScopeChip
								handle={scopedAccount.handle}
								color={scopedAccount.groupColor}
								onClear={onClearScope}
							/>
							{publishingQuota && (
								<Badge
									tone={publishingQuota.remaining <= 0 ? "danger" : "outline"}
								>
									{publishingQuota.remaining} of {publishingQuota.limit} posts
									left in this {publishingQuota.windowHours}h window
								</Badge>
							)}
							<Badge tone="outline">
								{totals.visible} {totals.visible === 1 ? "post" : "posts"}
							</Badge>
						</>
					) : (
						<>
							<Badge tone="oxblood">
								{totals.queue.toLocaleString()} queued
							</Badge>
							<Badge tone="outline" title={`Times shown in ${tzFull}`}>
								Times in {tzShort}
							</Badge>
						</>
					)}
				</div>
			}
			actions={
				<>
					{/* Week nav */}
					<div className="inline-flex items-center gap-1 rounded-md border border-border bg-card p-1">
						<Button
							type="button"
							variant="ghost"
							size="icon"
							onClick={onPrevWeek}
							aria-label="Previous week"
						>
							<ChevronLeft />
						</Button>
						<span className="text-[0.75rem] font-medium text-foreground tabular-nums px-2 min-w-[92px] text-center">
							{weekLabel}
						</span>
						<Button
							type="button"
							variant="ghost"
							size="icon"
							onClick={onNextWeek}
							aria-label="Next week"
						>
							<ChevronRight />
						</Button>
					</div>

					{!isCurrentWeek && (
						<Button type="button" onClick={onToday} variant="outline" size="sm">
							Today
						</Button>
					)}

					<Badge
						tone="outline"
						title={tzFull}
						className="inline-flex items-center gap-1.5"
					>
						<CalendarClock data-icon="inline-start" />
						Times in {tzShort}
					</Badge>

					<Button type="button" onClick={onNewPost} size="sm">
						<PenSquare data-icon="inline-start" />
						New post
					</Button>
				</>
			}
		>
			<ToggleGroup
				type="single"
				value={viewMode}
				onValueChange={(value) => {
					if (value) setViewMode(value as ViewMode);
				}}
				aria-label="Calendar view"
				className="w-full justify-start"
			>
				{views.map((v) => (
					<ToggleGroupItem key={v.id} value={v.id} aria-label={v.label}>
						{v.label}
					</ToggleGroupItem>
				))}
			</ToggleGroup>
		</NovaHeader>
	);
}
