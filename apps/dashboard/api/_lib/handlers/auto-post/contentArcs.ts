import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

export type ContentArcStatus =
	| "draft"
	| "active"
	| "cooldown"
	| "payoff_pending"
	| "completed"
	| "retired";

export type ArcBeatStatus = "pending" | "queued" | "posted" | "skipped";

export interface ContentArcCandidate {
	id: string;
	title: string;
	mood: string;
	status: ContentArcStatus;
	current_beat_index: number;
	next_suggested_beat?: string | null | undefined;
	cooldown_until?: string | null | undefined;
	payoff_status: string;
}

export interface ContentArcBeatCandidate {
	id: string;
	arc_id: string;
	beat_index: number;
	beat_title: string;
	beat_prompt: string;
	mood?: string | null | undefined;
	status: ArcBeatStatus;
}

export interface ContentArcContext {
	arcId: string;
	beatId: string | null;
	title: string;
	mood: string;
	currentBeatIndex: number;
	nextSuggestedBeat: string | null;
	payoffStatus: string;
	beatTitle: string | null;
	beatPrompt: string | null;
}

export interface LoadActiveContentArcInput {
	workspaceId: string;
	groupId?: string | null | undefined;
	accountId?: string | null | undefined;
	now?: Date | undefined;
}

function isCoolingDown(
	arc: ContentArcCandidate,
	now: Date,
): boolean {
	if (!arc.cooldown_until) return false;
	const cooldown = new Date(arc.cooldown_until);
	return Number.isFinite(cooldown.getTime()) && cooldown > now;
}

export function selectUsableArcBeat(input: {
	arc: ContentArcCandidate | null;
	beats: ContentArcBeatCandidate[];
	now?: Date | undefined;
}): ContentArcContext | null {
	const { arc, beats } = input;
	if (!arc) return null;
	const now = input.now ?? new Date();
	if (arc.status === "draft" || arc.status === "completed" || arc.status === "retired") {
		return null;
	}
	if (isCoolingDown(arc, now)) return null;

	const nextBeat =
		beats.find((beat) => beat.status === "pending") ??
		beats.find((beat) => beat.status === "queued") ??
		null;

	return {
		arcId: arc.id,
		beatId: nextBeat?.id ?? null,
		title: arc.title,
		mood: nextBeat?.mood ?? arc.mood,
		currentBeatIndex: nextBeat?.beat_index ?? arc.current_beat_index,
		nextSuggestedBeat: arc.next_suggested_beat ?? null,
		payoffStatus: arc.payoff_status,
		beatTitle: nextBeat?.beat_title ?? null,
		beatPrompt: nextBeat?.beat_prompt ?? null,
	};
}

export function buildContentArcMetadata(
	context: ContentArcContext | null,
): Record<string, unknown> | undefined {
	if (!context) return undefined;
	return {
		content_arc: {
			active_arc_id: context.arcId,
			arc_beat_id: context.beatId,
			title: context.title,
			mood: context.mood,
			current_beat_index: context.currentBeatIndex,
			next_suggested_beat: context.nextSuggestedBeat,
			payoff_status: context.payoffStatus,
			beat_title: context.beatTitle,
			beat_prompt: context.beatPrompt,
		},
	};
}

export async function loadActiveContentArcContext(
	input: LoadActiveContentArcInput,
): Promise<ContentArcContext | null> {
	if (!input.accountId) return null;
	try {
		const query = db()
			.from("account_content_arcs")
			.select(
				"id, title, mood, status, current_beat_index, next_suggested_beat, cooldown_until, payoff_status",
			)
			.eq("workspace_id", input.workspaceId)
			.eq("account_id", input.accountId)
			.in("status", ["active", "cooldown", "payoff_pending"])
			.order("updated_at", { ascending: false })
			.limit(1);

		const { data: arcs, error: arcError } = input.groupId
			? await query.eq("group_id", input.groupId)
			: await query;
		if (arcError) throw arcError;
		const arc = (arcs?.[0] ?? null) as ContentArcCandidate | null;
		if (!arc) return null;

		const { data: beats, error: beatError } = await db()
			.from("arc_beats")
			.select(
				"id, arc_id, beat_index, beat_title, beat_prompt, mood, status",
			)
			.eq("arc_id", arc.id)
			.in("status", ["pending", "queued"])
			.order("beat_index", { ascending: true })
			.limit(3);
		if (beatError) throw beatError;

		return selectUsableArcBeat({
			arc,
			beats: (beats ?? []) as ContentArcBeatCandidate[],
			now: input.now,
		});
	} catch (error) {
		logger.warn("[contentArcs] Failed to load active arc context", {
			workspaceId: input.workspaceId,
			groupId: input.groupId ?? null,
			accountId: input.accountId ?? null,
			error: error instanceof Error ? error.message : String(error),
		});
		return null;
	}
}
