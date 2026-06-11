import { GitCompare } from "lucide-react";
import type {
	AnalyticsCompareMode,
	AnalyticsDateRange,
	AnalyticsPlatform,
} from "@/lib/analyticsUrlState";
import { dateRangeToDays as getDateRangeDays } from "@/lib/analyticsUrlState";
import { PillSegmented } from "@/components/ui/PillSegmented";
import { FilterChip } from "@/components/ui/FilterChip";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/Tooltip";

interface ShellRowProps {
	platform: AnalyticsPlatform;
	onPlatformChange: (p: AnalyticsPlatform) => void;
	platformOptions?: { id: AnalyticsPlatform; label: string }[] | undefined;
	compare: AnalyticsCompareMode;
	dateRange: AnalyticsDateRange;
	onCompareToggle: () => void;
	hidePlatformSwitch?: boolean | undefined;
	savedViewsSlot?: React.ReactNode | undefined;
}

const PLATFORMS: { id: AnalyticsPlatform; label: string }[] = [
	{ id: "all", label: "Fleet" },
	{ id: "threads", label: "Threads" },
	{ id: "ig", label: "Instagram" },
];

export function ShellRow(props: ShellRowProps) {
	const platformOptions = props.platformOptions ?? PLATFORMS;
	const compareDays = getDateRangeDays(props.dateRange);
	const compareLabel =
		props.dateRange.kind === "preset"
			? `vs previous ${compareDays}d`
			: "vs previous window";
	const compareDescription =
		props.dateRange.kind === "preset"
			? `Compares the selected last ${compareDays} days against the immediately preceding ${compareDays} days.`
			: `Compares the selected date range against the immediately preceding ${compareDays}-day range.`;

	return (
		<div className="flex flex-wrap items-center gap-2">
			{!props.hidePlatformSwitch ? (
				<PillSegmented
					ariaLabel="Platform"
					options={platformOptions}
					value={props.platform}
					onChange={props.onPlatformChange}
				/>
			) : null}

			<Tooltip>
				<TooltipTrigger asChild>
					<FilterChip
						icon={GitCompare}
						active={props.compare !== "off"}
						onClick={props.onCompareToggle}
						aria-label={`${compareLabel}. ${compareDescription}`}
					>
						{compareLabel}
					</FilterChip>
				</TooltipTrigger>
				<TooltipContent side="bottom" className="max-w-[260px] leading-snug">
					{compareDescription}
				</TooltipContent>
			</Tooltip>

			{props.savedViewsSlot && (
				<div className="w-full sm:w-auto sm:ml-auto">{props.savedViewsSlot}</div>
			)}
		</div>
	);
}
