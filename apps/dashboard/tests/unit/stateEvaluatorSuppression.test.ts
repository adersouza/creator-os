import { describe, expect, it } from "vitest";
import {
	evaluateAccountState,
	type AccountEvalInput,
} from "../../api/_lib/handlers/auto-post/stateEvaluator";

function suppressedInput(): AccountEvalInput {
	const now = Date.parse("2026-06-06T12:00:00Z");
	const posts = Array.from({ length: 10 }, (_, index) => ({
		id: `post-${index}`,
		views_count: index === 0 ? 3 : 1,
		published_at: new Date(now - (index + 1) * 86_400_000).toISOString(),
	}));
	return {
		account_id: "acc-suppressed",
		group_id: "group-1",
		workspace_id: "workspace-1",
		username: "suppressed",
		is_active: true,
		is_retired: false,
		needs_reauth: false,
		is_shadowbanned: false,
		created_at: "2026-01-01T00:00:00Z",
		followers_count: 500,
		posts_last_30d: posts,
		posts_last_14d: posts,
		recent_3_posts: posts.slice(0, 3),
		posts_last_2h: [],
		latest_post_over_2h: posts[0] ?? null,
		total_published_posts: posts.length,
		posts_last_48h: 0,
	};
}

describe("stateEvaluator suppression recovery", () => {
	it("moves a suppressed account into probe mode after the pause elapses", () => {
		const result = evaluateAccountState(
			suppressedInput(),
			new Date("2026-06-06T12:00:00Z"),
			{
				status: "suppressed",
				blocked_until: "2026-06-06T11:59:00Z",
				probe_posts_remaining: 3,
				probe_cycles_completed: 0,
			},
		);

		expect(result.status).toBe("suppressed_probe");
		expect(result.probe_posts_remaining).toBe(3);
		expect(result.probe_cycles_completed).toBe(0);
	});

	it("keeps an active probe cycle open until attempts are exhausted", () => {
		const result = evaluateAccountState(
			suppressedInput(),
			new Date("2026-06-06T12:00:00Z"),
			{
				status: "suppressed_probe",
				blocked_until: null,
				probe_posts_remaining: 2,
				probe_cycles_completed: 0,
			},
		);

		expect(result.status).toBe("suppressed_probe");
		expect(result.probe_posts_remaining).toBe(2);
	});
});
