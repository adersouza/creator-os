import { LayoutGrid, Rows3, Search } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import type { FleetGroupMeta } from "@/hooks/useFleetAccounts";
import type {
	GroupFilter,
	PlatformFilter,
	SortKey,
	StatusFilter,
	ViewMode,
} from "./shared";

interface AccountsFilterBarProps {
	search: string;
	groupFilter: GroupFilter;
	platform: PlatformFilter;
	status: StatusFilter;
	sort: SortKey;
	view: ViewMode;
	tags: string[];
	tagFilter: string;
	groups: FleetGroupMeta[];
	onSearchChange: (value: string) => void;
	onGroupFilterChange: (value: GroupFilter) => void;
	onPlatformChange: (value: PlatformFilter) => void;
	onStatusChange: (value: StatusFilter) => void;
	onSortChange: (value: SortKey) => void;
	onViewChange: (value: ViewMode) => void;
	onTagFilterChange: (value: string) => void;
}

export function AccountsFilterBar({
	search,
	groupFilter,
	platform,
	status,
	sort,
	view,
	tags,
	tagFilter,
	groups,
	onSearchChange,
	onGroupFilterChange,
	onPlatformChange,
	onStatusChange,
	onSortChange,
	onViewChange,
	onTagFilterChange,
}: AccountsFilterBarProps) {
	return (
		<div className="flex items-center gap-2 mb-2 flex-wrap">
			<label
				htmlFor="accounts-filter-search"
				className="flex-1 min-w-[240px] max-w-lg"
			>
				<Input
					id="accounts-filter-search"
					type="text"
					value={search}
					onChange={(e) => onSearchChange(e.target.value)}
					placeholder="Search handles or names..."
					leadingIcon={<Search aria-hidden="true" />}
					className="bg-muted"
				/>
			</label>
			{groups.length > 0 && (
				<Select
					value={groupFilter}
					onChange={(event) =>
						onGroupFilterChange(event.target.value as GroupFilter)
					}
					options={[
						{ value: "all", label: "All networks" },
						...groups.map((g) => ({ value: g.id, label: g.name })),
					]}
					aria-label="Filter by network"
					className="w-auto min-w-[9rem]"
				/>
			)}
			<Select
				value={platform}
				onChange={(event) =>
					onPlatformChange(event.target.value as PlatformFilter)
				}
				options={[
					{ value: "all", label: "All platforms" },
					{ value: "threads", label: "Threads" },
					{ value: "instagram", label: "Instagram" },
				]}
				aria-label="Filter by platform"
				className="w-auto min-w-[9rem]"
			/>
			<Select
				value={status}
				onChange={(event) => onStatusChange(event.target.value as StatusFilter)}
				options={[
					{ value: "all", label: "All statuses" },
					{ value: "active", label: "Active" },
					{ value: "drifting", label: "Drifting" },
					{ value: "flagged", label: "Flagged" },
					{ value: "inactive", label: "Inactive" },
				]}
				aria-label="Filter by status"
				className="w-auto min-w-[9rem]"
			/>
			<Select
				value={sort}
				onChange={(event) => onSortChange(event.target.value as SortKey)}
				options={[
					{ value: "recent", label: "Recently posted" },
					{ value: "followers", label: "Followers" },
					{ value: "health", label: "Health (low to high)" },
					{ value: "posts24h", label: "Posts (24h)" },
				]}
				aria-label="Sort accounts"
				className="w-auto min-w-[11rem]"
			/>
			{tags.length > 0 && (
				<Select
					value={tagFilter}
					onChange={(event) => onTagFilterChange(event.target.value)}
					options={[
						{ value: "all", label: "All tags" },
						...tags.map((tag) => ({ value: tag, label: `#${tag}` })),
					]}
					aria-label="Filter by tag"
					className="w-auto min-w-[8rem]"
				/>
			)}
			<ToggleGroup
				type="single"
				value={view}
				onValueChange={(value) => {
					if (value === "list" || value === "map") onViewChange(value);
				}}
				className="ml-auto"
				aria-label="Account view"
			>
				<ToggleGroupItem value="list" sizeVariant="sm" aria-label="List view">
					<Rows3 data-icon="inline-start" />
					List
				</ToggleGroupItem>
				<ToggleGroupItem value="map" sizeVariant="sm" aria-label="Map view">
					<LayoutGrid data-icon="inline-start" />
					Map
				</ToggleGroupItem>
			</ToggleGroup>
		</div>
	);
}
