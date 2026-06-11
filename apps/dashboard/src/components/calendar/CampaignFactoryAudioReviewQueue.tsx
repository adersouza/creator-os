import { AlertTriangle, CheckCircle2, Clock3, ListChecks, Music2, ShieldAlert } from "lucide-react";
import {
	getCampaignFactoryAudioQueueLane,
	summarizeCampaignFactoryAudioQueue,
	type CampaignFactoryAudioQueueLane,
	type CampaignFactoryFilters,
} from "@/lib/campaignFactory";
import type { Post } from "./shared";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";

const LANES: Array<{
	id: CampaignFactoryAudioQueueLane;
	label: string;
	description: string;
	icon: typeof AlertTriangle;
}> = [
	{
		id: "needs_audio",
		label: "Needs audio",
		description: "No operator choice yet",
		icon: Music2,
	},
	{
		id: "selected_not_attached",
		label: "Selected",
		description: "Chosen, not attached",
		icon: Clock3,
	},
	{
		id: "missing_proof",
		label: "Proof missing",
		description: "Attached/verified needs locator",
		icon: ShieldAlert,
	},
	{
		id: "blocked",
		label: "Blocked",
		description: "Unavailable or bad fit",
		icon: AlertTriangle,
	},
	{
		id: "ready",
		label: "Ready",
		description: "Safe for scheduling",
		icon: CheckCircle2,
	},
	{
		id: "needs_handoff",
		label: "Handoff",
		description: "Scheduled/manual follow-up",
		icon: ListChecks,
	},
];

function shortTitle(post: Post) {
	const text = post.title || post.campaignFactory?.rendered_asset_id || post.id;
	return text.length > 44 ? `${text.slice(0, 41)}...` : text;
}

export function CampaignFactoryAudioReviewQueue({
	posts,
	activeAudioState,
	onAudioStateChange,
	onOpenPost,
}: {
	posts: Post[];
	activeAudioState?: CampaignFactoryFilters["audioState"];
	onAudioStateChange: (audioState: CampaignFactoryFilters["audioState"]) => void;
	onOpenPost: (post: Post) => void;
}) {
	const campaignPosts = posts.filter((post) => post.campaignFactory?.audio_intent?.required);
	if (campaignPosts.length === 0) return null;
	const counts = summarizeCampaignFactoryAudioQueue(campaignPosts);
	const urgentCount =
		counts.needs_audio +
		counts.selected_not_attached +
		counts.missing_proof +
		counts.blocked;
	const lanePosts = LANES.reduce<Record<CampaignFactoryAudioQueueLane, Post[]>>(
		(acc, lane) => {
			acc[lane.id] = campaignPosts
				.filter((post) => getCampaignFactoryAudioQueueLane(post) === lane.id)
				.slice(0, 3);
			return acc;
		},
		{
			needs_audio: [],
			selected_not_attached: [],
			missing_proof: [],
			blocked: [],
			ready: [],
			needs_handoff: [],
		},
	);

	return (
		<NovaCard
			eyebrow="Campaign Factory"
			title="Audio queue"
			description={
				urgentCount > 0
					? `${urgentCount} posts need operator audio work`
					: "Native audio is clear for this view"
			}
			action={
				<Button type="button" variant="outline" size="sm" onClick={() => onAudioStateChange("all")}>
					Show all
				</Button>
			}
		>
			<div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-6">
				{LANES.map((lane) => {
					const Icon = lane.icon;
					const active = activeAudioState === lane.id;
					return (
						<Button
							key={lane.id}
							type="button"
							onClick={() => onAudioStateChange(lane.id)}
							aria-pressed={active}
							variant={active ? "default" : "outline"}
							className="h-auto min-h-[112px] flex-col items-stretch justify-start p-3 text-left"
						>
							<div className="flex items-center justify-between gap-2">
								<Icon data-icon="inline-start" />
								<span className="text-lg font-semibold tabular-nums">
									{counts[lane.id]}
								</span>
							</div>
							<div className="mt-2 text-[0.8125rem] font-semibold">{lane.label}</div>
							<div className={`mt-0.5 text-[0.71875rem] ${active ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
								{lane.description}
							</div>
							<div className="mt-2 flex flex-col gap-1">
								{lanePosts[lane.id].map((post) => (
									<span
										key={post.id}
										className={`block truncate text-[0.68rem] ${active ? "text-primary-foreground/80" : "text-muted-foreground"}`}
										onClick={(event) => {
											event.stopPropagation();
											onOpenPost(post);
										}}
									>
										{shortTitle(post)}
									</span>
								))}
							</div>
							{active && <Badge tone="secondary" className="mt-2">Filtered</Badge>}
						</Button>
					);
				})}
			</div>
		</NovaCard>
	);
}
