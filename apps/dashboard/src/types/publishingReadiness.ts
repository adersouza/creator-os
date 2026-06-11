export type PublishingReadinessState = "ready" | "needs_setup" | "warning" | "blocked";

export interface PublishingReadinessIssue {
	id: string;
	label: string;
	detail: string;
	state: PublishingReadinessState;
	actionLabel?: string | undefined;
	action?: (() => void) | undefined;
}

export type FirstPostWizardStep =
	| "connect"
	| "mode"
	| "media"
	| "readiness"
	| "phone"
	| "schedule"
	| "handoff";

export type PreviewMode = "feed" | "reel" | "story" | "handoff";

export type PwaInstallState =
	| "installed-ios"
	| "iphone-safari"
	| "android-chrome"
	| "desktop"
	| "unsupported";

export type CalendarCommandAction =
	| "schedule_draft"
	| "duplicate_post"
	| "convert_to_notify"
	| "move_next_best_time"
	| "open_readiness"
	| "open_first_post_wizard";

export interface PostPublishFollowUp {
	instagramUrl?: string | undefined;
	notes?: string | undefined;
	savedAt: string;
}

