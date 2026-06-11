import { describe, expect, it } from "vitest";
import { deriveComposerPresentation } from "./composerPresentation";

const account = (platform: "threads" | "instagram") => ({ platform });

describe("deriveComposerPresentation", () => {
	it("shows only Threads options for Threads-only targets", () => {
		expect(
			deriveComposerPresentation({
				targets: [account("threads")],
				igType: "feed",
				scheduleMode: "now",
				publishMode: "auto",
			}),
		).toMatchObject({
			mode: "threads",
			showThreadsOptions: true,
			showInstagramOptions: false,
		});
	});

	it("shows Reel presentation for Instagram Reels targets", () => {
		expect(
			deriveComposerPresentation({
				targets: [account("instagram")],
				igType: "reels",
				scheduleMode: "now",
				publishMode: "auto",
			}),
		).toMatchObject({
			mode: "instagram-reel",
			showThreadsOptions: false,
			showInstagramOptions: true,
		});
	});

	it("shows Story presentation for Instagram Story targets", () => {
		expect(
			deriveComposerPresentation({
				targets: [account("instagram")],
				igType: "story",
				scheduleMode: "now",
				publishMode: "auto",
			}),
		).toMatchObject({
			mode: "instagram-story",
			showThreadsOptions: false,
			showInstagramOptions: true,
		});
	});

	it("keeps both platform panels available for mixed targets", () => {
		expect(
			deriveComposerPresentation({
				targets: [account("threads"), account("instagram")],
				igType: "feed",
				scheduleMode: "schedule",
				publishMode: "notify",
			}),
		).toMatchObject({
			mode: "mixed",
			showThreadsOptions: true,
			showInstagramOptions: true,
		});
	});

	it("uses Notify handoff presentation for Instagram scheduled Notify Me", () => {
		expect(
			deriveComposerPresentation({
				targets: [account("instagram")],
				igType: "feed",
				scheduleMode: "schedule",
				publishMode: "notify",
			}).mode,
		).toBe("notify-handoff");
	});
});
