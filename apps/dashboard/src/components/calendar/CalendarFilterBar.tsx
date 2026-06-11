import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { Input } from "@/components/ui/Input";
import { PillSegmented } from "@/components/ui/PillSegmented";
import { Separator } from "@/components/ui/Separator";
import {
	hasActiveCampaignFactoryFilters,
	type CampaignFactoryFilters,
} from "@/lib/campaignFactory";
import type { GroupOption, Platform } from "./shared";

/* =========================================================================
   FILTER BAR — extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
export function CalendarFilterBar({
	groupFilter,
	setGroupFilter,
	platformFilter,
	setPlatformFilter,
	emptySlotCount,
	onViewGaps,
	groups,
	onAddTravelTimezone,
	travelTimezoneLabel,
	aiHoursEnabled,
	onToggleAIHours,
	onOpenHistory,
	campaignFactoryFilters,
	setCampaignFactoryFilters,
}: {
	groupFilter: string;
	setGroupFilter: (id: string) => void;
	platformFilter: Platform | "all";
	setPlatformFilter: (p: Platform | "all") => void;
	emptySlotCount: number;
	onViewGaps: () => void;
	groups: GroupOption[];
	onAddTravelTimezone?: () => void;
	travelTimezoneLabel?: string | null | undefined;
	aiHoursEnabled?: boolean | undefined;
	onToggleAIHours?: () => void;
	onOpenHistory?: () => void;
	campaignFactoryFilters: CampaignFactoryFilters;
	setCampaignFactoryFilters: (filters: CampaignFactoryFilters) => void;
}) {
	const campaignFiltersActive = hasActiveCampaignFactoryFilters(
		campaignFactoryFilters,
	);
	const updateCampaignFilter = (patch: Partial<CampaignFactoryFilters>) =>
		setCampaignFactoryFilters({ ...campaignFactoryFilters, ...patch });

	return (
		<NovaCard variant="compact" contentClassName="p-3">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<div className="flex flex-wrap items-center gap-2">
					{groups.length > 0 && (
						<FilterSelect<string>
							value={groupFilter}
							onChange={setGroupFilter}
							ariaLabel="Group filter"
							options={[
								{ value: "all", label: "All groups" },
								...groups.map((g) => ({
									value: g.id,
									label: g.name,
									dot: g.color,
								})),
							]}
						/>
					)}

					<PillSegmented<Platform | "all">
						value={platformFilter}
						onChange={setPlatformFilter}
						ariaLabel="Platform filter"
						options={[
							{ id: "all", label: "All" },
							{ id: "threads", label: "Threads" },
							{ id: "instagram", label: "Instagram" },
						]}
					/>

					<Button
						type="button"
						variant={campaignFactoryFilters.only ? "default" : "outline"}
						size="sm"
						onClick={() =>
							updateCampaignFilter({ only: !campaignFactoryFilters.only })
						}
						aria-pressed={!!campaignFactoryFilters.only}
					>
						Campaign Factory
					</Button>
				</div>

				<div className="flex flex-wrap items-center gap-2">
					{emptySlotCount > 0 && (
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={onViewGaps}
							aria-label={`Jump to ${emptySlotCount} empty ${emptySlotCount === 1 ? "slot" : "slots"} this week`}
						>
							<AlertTriangle data-icon="inline-start" aria-hidden="true" />
							{emptySlotCount} empty {emptySlotCount === 1 ? "slot" : "slots"}
						</Button>
					)}

					{onToggleAIHours && (
						<Button
							type="button"
							variant={aiHoursEnabled ? "default" : "outline"}
							size="sm"
							onClick={onToggleAIHours}
							aria-pressed={!!aiHoursEnabled}
						>
							Best hours
						</Button>
					)}

					{onAddTravelTimezone && (
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={onAddTravelTimezone}
						>
							{travelTimezoneLabel ? travelTimezoneLabel : "+ TZ"}
						</Button>
					)}

					{onOpenHistory && (
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={onOpenHistory}
						>
							History
						</Button>
					)}
				</div>
			</div>

			{campaignFiltersActive && (
				<div className="mt-3 flex flex-col gap-3">
					<Separator />
					<div className="flex flex-wrap items-center gap-2">
						<Badge tone="outline">Draft review</Badge>
						<Input
							value={campaignFactoryFilters.campaignId ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ campaignId: event.target.value })
							}
							placeholder="Campaign ID"
							aria-label="Campaign Factory campaign ID"
							sizeVariant="sm"
							className="w-32"
						/>
						<Input
							value={campaignFactoryFilters.modelId ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ modelId: event.target.value })
							}
							placeholder="Model"
							aria-label="Campaign Factory model ID"
							sizeVariant="sm"
							className="w-28"
						/>
						<Input
							value={campaignFactoryFilters.sourceAssetId ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ sourceAssetId: event.target.value })
							}
							placeholder="Source asset"
							aria-label="Campaign Factory source asset ID"
							sizeVariant="sm"
							className="w-32"
						/>
						<Input
							value={campaignFactoryFilters.renderedAssetId ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ renderedAssetId: event.target.value })
							}
							placeholder="Rendered asset"
							aria-label="Campaign Factory rendered asset ID"
							sizeVariant="sm"
							className="w-32"
						/>
						<FilterSelect<string>
							value={campaignFactoryFilters.auditStatus ?? "all"}
							onChange={(auditStatus) => updateCampaignFilter({ auditStatus })}
							ariaLabel="Campaign Factory audit status"
							options={[
								{ value: "all", label: "Any audit" },
								{ value: "approved_candidate", label: "Approved candidate" },
								{ value: "needs_review", label: "Needs review" },
								{ value: "pending", label: "Pending" },
							]}
						/>
						<Input
							value={campaignFactoryFilters.contentPillar ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ contentPillar: event.target.value })
							}
							placeholder="Pillar"
							aria-label="Campaign Factory content pillar"
							sizeVariant="sm"
							className="w-24"
						/>
						<Input
							value={campaignFactoryFilters.ctaType ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ ctaType: event.target.value })
							}
							placeholder="CTA"
							aria-label="Campaign Factory CTA type"
							sizeVariant="sm"
							className="w-24"
						/>
						<Input
							value={campaignFactoryFilters.language ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ language: event.target.value })
							}
							placeholder="Lang"
							aria-label="Campaign Factory language"
							sizeVariant="sm"
							className="w-20"
						/>
						<Input
							value={campaignFactoryFilters.recipe ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ recipe: event.target.value })
							}
							placeholder="Recipe"
							aria-label="Campaign Factory recipe"
							sizeVariant="sm"
							className="w-24"
						/>
						<Input
							value={campaignFactoryFilters.instagramAccountId ?? ""}
							onChange={(event) =>
								updateCampaignFilter({ instagramAccountId: event.target.value })
							}
							placeholder="IG account ID"
							aria-label="Campaign Factory Instagram account ID"
							sizeVariant="sm"
							className="w-32"
						/>
						<FilterSelect<string>
							value={campaignFactoryFilters.status ?? "all"}
							onChange={(status) => updateCampaignFilter({ status })}
							ariaLabel="Campaign Factory post status"
							options={[
								{ value: "all", label: "Any status" },
								{ value: "draft", label: "Draft" },
								{ value: "scheduled", label: "Scheduled" },
								{ value: "published", label: "Published" },
							]}
						/>
						<FilterSelect<string>
							value={campaignFactoryFilters.audioState ?? "all"}
							onChange={(audioState) =>
								updateCampaignFilter({
									audioState:
										audioState as CampaignFactoryFilters["audioState"],
								})
							}
							ariaLabel="Campaign Factory native audio state"
							options={[
								{ value: "all", label: "Any audio" },
								{ value: "needs_audio", label: "Needs audio" },
								{ value: "selected_not_attached", label: "Selected" },
								{ value: "missing_proof", label: "Proof missing" },
								{ value: "blocked", label: "Audio blocked" },
								{ value: "ready", label: "Audio ready" },
								{ value: "needs_handoff", label: "Needs handoff" },
							]}
						/>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => setCampaignFactoryFilters({})}
						>
							Clear
						</Button>
					</div>
				</div>
			)}
		</NovaCard>
	);
}
