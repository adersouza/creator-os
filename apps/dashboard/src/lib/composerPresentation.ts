export type ComposerPresentationMode =
	| "threads"
	| "instagram-feed"
	| "instagram-reel"
	| "instagram-story"
	| "mixed"
	| "notify-handoff";

export interface ComposerPresentation {
	mode: ComposerPresentationMode;
	showThreadsOptions: boolean;
	showInstagramOptions: boolean;
}

export function deriveComposerPresentation({
	targets,
	igType,
	scheduleMode,
	publishMode,
}: {
	targets: Array<{ platform: "threads" | "instagram" | string }>;
	igType: "feed" | "reels" | "story";
	scheduleMode: "now" | "schedule" | "queue";
	publishMode: "auto" | "notify";
}): ComposerPresentation {
	const hasThreads = targets.some((target) => target.platform === "threads");
	const hasInstagram = targets.some((target) => target.platform === "instagram");

	if (hasThreads && hasInstagram) {
		return {
			mode: "mixed",
			showThreadsOptions: true,
			showInstagramOptions: true,
		};
	}

	if (hasThreads) {
		return {
			mode: "threads",
			showThreadsOptions: true,
			showInstagramOptions: false,
		};
	}

	if (hasInstagram) {
		if (scheduleMode === "schedule" && publishMode === "notify") {
			return {
				mode: "notify-handoff",
				showThreadsOptions: false,
				showInstagramOptions: true,
			};
		}
		return {
			mode:
				igType === "reels"
					? "instagram-reel"
					: igType === "story"
						? "instagram-story"
						: "instagram-feed",
			showThreadsOptions: false,
			showInstagramOptions: true,
		};
	}

	return {
		mode: "mixed",
		showThreadsOptions: false,
		showInstagramOptions: false,
	};
}
