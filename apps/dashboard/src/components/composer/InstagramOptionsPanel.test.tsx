import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import {
	InstagramOptionsPanel,
	type InstagramOptions,
} from "./InstagramOptionsPanel";

beforeAll(() => {
	class ResizeObserverStub {
		observe() {}
		unobserve() {}
		disconnect() {}
	}
	vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

const baseOptions: InstagramOptions = {
	igType: "feed",
	firstComment: "",
	location: "",
	collaborators: [],
	collaboratorDraft: "",
	userTags: "",
	productTags: "",
	reelCover: 3,
	coverUrl: "",
	audioName: "",
	igAudioId: "",
	igAudioTitle: "",
	igAudioArtist: "",
	igAudioType: "music",
	shareToFeed: true,
	trialReel: false,
	graduation: "SS_PERFORMANCE",
	commentEnabled: true,
	isPaidPartnership: false,
	brandedContentSponsorIds: "",
};

function renderPanel(options: Partial<InstagramOptions>) {
	return render(
		<InstagramOptionsPanel
			targets={[{ id: "ig_1", platform: "instagram", label: "IG" } as never]}
			open
			onToggle={vi.fn()}
			options={{ ...baseOptions, ...options }}
			onChange={vi.fn()}
			showPostType
		/>,
	);
}

describe("InstagramOptionsPanel presentation gating", () => {
	it("shows Reel-only controls for Reels", () => {
		renderPanel({ igType: "reels" });

		expect(screen.getByText("Cover frame — 3.0s")).toBeInTheDocument();
		expect(screen.getByText("Instagram audio")).toBeInTheDocument();
		expect(screen.getByText("Trial Reel")).toBeInTheDocument();
	});

	it("hides Reel-only controls for Stories", () => {
		renderPanel({ igType: "story" });

		expect(screen.queryByText("Instagram audio")).not.toBeInTheDocument();
		expect(screen.queryByText("Trial Reel")).not.toBeInTheDocument();
		expect(screen.queryByText("First comment")).not.toBeInTheDocument();
		expect(screen.queryByText("Comments")).not.toBeInTheDocument();
	});
});
