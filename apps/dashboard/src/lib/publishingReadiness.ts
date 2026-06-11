import type {
	PublishingReadinessIssue,
	PublishingReadinessState,
	PwaInstallState,
} from "@/types/publishingReadiness";

export interface BuildPublishingReadinessInput {
	hasInstagramAccount: boolean;
	hasTokenWarning?: boolean | undefined;
	pushState?: string | undefined;
	pwaState?: PwaInstallState | undefined;
	instagramReady?: boolean | undefined;
	lastHandoffCompleted?: boolean | undefined;
}

function stateRank(state: PublishingReadinessState): number {
	return state === "blocked" ? 4 : state === "warning" ? 3 : state === "needs_setup" ? 2 : 1;
}

export function summarizeReadinessState(
	issues: PublishingReadinessIssue[],
): PublishingReadinessState {
	return issues.reduce<PublishingReadinessState>(
		(worst, issue) => (stateRank(issue.state) > stateRank(worst) ? issue.state : worst),
		"ready",
	);
}

export function buildPublishingReadinessIssues({
	hasInstagramAccount,
	hasTokenWarning = false,
	pushState = "unknown",
	pwaState = "desktop",
	instagramReady = false,
	lastHandoffCompleted = false,
}: BuildPublishingReadinessInput): PublishingReadinessIssue[] {
	const issues: PublishingReadinessIssue[] = [
		{
			id: "instagram-account",
			label: hasInstagramAccount ? "Instagram connected" : "Connect Instagram",
			detail: hasInstagramAccount
				? "Juno33 can target at least one Instagram account."
				: "Connect Instagram before scheduling Feed, Reel, Story, or Notify Me posts.",
			state: hasInstagramAccount ? "ready" : "blocked",
			actionLabel: hasInstagramAccount ? undefined : "Connect",
		},
		{
			id: "token-health",
			label: hasTokenWarning ? "Token needs attention" : "Token health clear",
			detail: hasTokenWarning
				? "One or more accounts has a token warning. Reconnect before relying on auto-publish."
				: "No token warning is visible in the current account health signals.",
			state: hasTokenWarning ? "warning" : "ready",
			actionLabel: hasTokenWarning ? "Reconnect" : undefined,
		},
		{
			id: "notify-push",
			label: pushState === "subscribed" ? "Notify Me push ready" : "Enable Notify Me push",
			detail:
				pushState === "subscribed"
					? "This browser has an active push subscription."
					: pushState === "denied"
						? "Notifications are blocked in browser settings. Handoff fallback still works."
						: "Enable or test push before relying on mobile reminders.",
			state:
				pushState === "subscribed"
					? "ready"
					: pushState === "denied"
						? "warning"
						: "needs_setup",
			actionLabel: pushState === "subscribed" ? undefined : "Setup push",
		},
		{
			id: "pwa-install",
			label:
				pwaState === "installed-ios" || pwaState === "android-chrome"
					? "Phone/PWA path ready"
					: "Finish phone setup",
			detail:
				pwaState === "iphone-safari"
					? "Add Juno33 to Home Screen on iPhone for the best Notify Me experience."
					: pwaState === "unsupported"
						? "This browser cannot use push; use in-app fallback or set up on phone."
						: "Use the phone setup checklist before your first Notify Me post.",
			state:
				pwaState === "installed-ios" || pwaState === "android-chrome"
					? "ready"
					: pwaState === "unsupported"
						? "warning"
						: "needs_setup",
			actionLabel: "Phone setup",
		},
		{
			id: "instagram-app",
			label: instagramReady ? "Instagram app ready" : "Confirm Instagram login",
			detail: instagramReady
				? "The manual handoff can open Instagram for final posting."
				: "For Notify Me, the phone must have Instagram installed and logged in.",
			state: instagramReady ? "ready" : "needs_setup",
			actionLabel: instagramReady ? undefined : "Confirm",
		},
		{
			id: "first-handoff",
			label: lastHandoffCompleted ? "First handoff completed" : "No completed handoff yet",
			detail: lastHandoffCompleted
				? "A Notify Me post has been marked as posted."
				: "Your first completed handoff will appear here after Mark Posted.",
			state: lastHandoffCompleted ? "ready" : "needs_setup",
			actionLabel: lastHandoffCompleted ? undefined : "Try Notify Me",
		},
	];
	return issues;
}

