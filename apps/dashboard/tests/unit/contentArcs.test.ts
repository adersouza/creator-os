import { describe, expect, it } from "vitest";
import {
	buildContentArcMetadata,
	selectUsableArcBeat,
	type ContentArcCandidate,
	type ContentArcBeatCandidate,
} from "../../api/_lib/handlers/auto-post/contentArcs.js";

const baseArc: ContentArcCandidate = {
	id: "arc-1",
	title: "late ranked reset",
	mood: "reflective",
	status: "active",
	current_beat_index: 1,
	next_suggested_beat: "turn the playlist into the payoff",
	cooldown_until: null,
	payoff_status: "not_due",
};

const baseBeat: ContentArcBeatCandidate = {
	id: "beat-1",
	arc_id: "arc-1",
	beat_index: 1,
	beat_title: "playlist setup",
	beat_prompt: "connect late ranked games to the playlist motif",
	mood: "reflective",
	status: "pending",
};

describe("content arcs", () => {
	it("selects the next pending beat for an active arc", () => {
		const context = selectUsableArcBeat({
			arc: baseArc,
			beats: [baseBeat],
			now: new Date("2026-06-05T19:00:00Z"),
		});

		expect(context?.arcId).toBe("arc-1");
		expect(context?.beatId).toBe("beat-1");
		expect(context?.title).toBe("late ranked reset");
		expect(context?.nextSuggestedBeat).toBe(
			"turn the playlist into the payoff",
		);
	});

	it("does not select an arc that is still cooling down", () => {
		const context = selectUsableArcBeat({
			arc: {
				...baseArc,
				status: "cooldown",
				cooldown_until: "2026-06-05T20:00:00Z",
			},
			beats: [baseBeat],
			now: new Date("2026-06-05T19:00:00Z"),
		});

		expect(context).toBeNull();
	});

	it("serializes compact queue metadata for generation and review", () => {
		const context = selectUsableArcBeat({
			arc: baseArc,
			beats: [baseBeat],
			now: new Date("2026-06-05T19:00:00Z"),
		});

		expect(buildContentArcMetadata(context)).toEqual({
			content_arc: {
				active_arc_id: "arc-1",
				arc_beat_id: "beat-1",
				title: "late ranked reset",
				mood: "reflective",
				current_beat_index: 1,
				next_suggested_beat: "turn the playlist into the payoff",
				payoff_status: "not_due",
				beat_title: "playlist setup",
				beat_prompt: "connect late ranked games to the playlist motif",
			},
		});
	});
});
