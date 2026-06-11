import { describe, expect, it } from "vitest";
import { resolveInstagramMetricContract } from "../../api/_lib/instagram/metricContracts.js";

describe("resolveInstagramMetricContract", () => {
	it("selects the Reel metric contract", () => {
		const contract = resolveInstagramMetricContract({
			contentSurface: "reel",
			igMediaType: "REELS",
		});

		expect(contract).toMatchObject({
			ok: true,
			version: "instagram_metrics_contract_v1",
			surface: "reel",
			igMediaType: "REELS",
		});
		expect(contract.ok && contract.metrics).toContain("ig_reels_avg_watch_time");
	});

	it("selects the Story metric contract without Reel-only metrics", () => {
		const contract = resolveInstagramMetricContract({
			contentSurface: "story",
			igMediaType: "STORIES",
		});

		expect(contract).toMatchObject({
			ok: true,
			surface: "story",
			igMediaType: "STORIES",
		});
		expect(contract.ok && contract.metrics).toContain("navigation");
		expect(contract.ok && contract.metrics).not.toContain("ig_reels_avg_watch_time");
	});

	it("selects feed image and carousel parent metric contracts", () => {
		const feed = resolveInstagramMetricContract({
			contentSurface: "feed_single",
			igMediaType: "IMAGE",
		});
		const carousel = resolveInstagramMetricContract({
			contentSurface: "feed_carousel",
			igMediaType: "CAROUSEL",
		});

		expect(feed).toMatchObject({ ok: true, surface: "feed_single" });
		expect(carousel).toMatchObject({ ok: true, surface: "feed_carousel" });
		expect(feed.ok && feed.metrics).toEqual(carousel.ok && carousel.metrics);
		expect(feed.ok && feed.metrics).not.toContain("navigation");
	});

	it("blocks mismatched surface/media type pairs", () => {
		const contract = resolveInstagramMetricContract({
			contentSurface: "story",
			igMediaType: "REELS",
		});

		expect(contract.ok).toBe(false);
		expect(!contract.ok && contract.blockers).toContain(
			"ig_media_type_surface_mismatch:REELS:STORIES",
		);
	});

	it("blocks missing Campaign media type instead of defaulting to Reels", () => {
		const contract = resolveInstagramMetricContract({
			contentSurface: "feed_single",
		});

		expect(contract.ok).toBe(false);
		expect(!contract.ok && contract.blockers).toContain("ig_media_type_unresolvable");
	});
});
