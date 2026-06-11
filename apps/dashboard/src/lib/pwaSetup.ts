import type { PwaInstallState } from "@/types/publishingReadiness";

type NavigatorLike = {
	userAgent?: string | undefined;
	standalone?: boolean | undefined;
};

export function detectPwaInstallState(input?: {
	userAgent?: string | undefined;
	standalone?: boolean | undefined;
	displayModeStandalone?: boolean | undefined;
	pushSupported?: boolean | undefined;
}): PwaInstallState {
	const nav =
		typeof navigator !== "undefined" ? (navigator as NavigatorLike) : undefined;
	const ua = input?.userAgent ?? nav?.userAgent ?? "";
	const standalone = input?.standalone ?? nav?.standalone === true;
	const displayModeStandalone =
		input?.displayModeStandalone ??
		(typeof window !== "undefined" &&
			typeof window.matchMedia === "function" &&
			window.matchMedia("(display-mode: standalone)").matches);
	const pushSupported =
		input?.pushSupported ??
		(typeof navigator !== "undefined" &&
			"serviceWorker" in navigator &&
			typeof window !== "undefined" &&
			"PushManager" in window &&
			"Notification" in window);

	const isiPhone = /iphone|ipad|ipod/i.test(ua);
	const isAndroid = /android/i.test(ua);
	const isChrome = /chrome|crios/i.test(ua);
	const isSafari = /safari/i.test(ua) && !/chrome|crios|android/i.test(ua);

	if (isiPhone && (standalone || displayModeStandalone)) return "installed-ios";
	if (isiPhone && isSafari) return "iphone-safari";
	if (isAndroid && isChrome && pushSupported) return "android-chrome";
	if (!pushSupported) return "unsupported";
	return "desktop";
}

export function pwaSetupCopy(state: PwaInstallState): {
	label: string;
	detail: string;
	steps: string[];
} {
	switch (state) {
		case "installed-ios":
			return {
				label: "iPhone PWA installed",
				detail: "This phone can receive Notify Me reminders after notification permission is enabled.",
				steps: ["Log in to Juno33 from the Home Screen icon", "Enable notifications", "Confirm Instagram is installed and logged in"],
			};
		case "iphone-safari":
			return {
				label: "Install on iPhone",
				detail: "Open Juno33 in Safari, add it to Home Screen, then log in from the installed app before enabling push.",
				steps: ["Open juno33.com in Safari", "Tap Share, then Add to Home Screen", "Open Juno33 from the Home Screen icon", "Log in and enable notifications"],
			};
		case "android-chrome":
			return {
				label: "Android ready",
				detail: "Chrome can use web push and share media into native apps.",
				steps: ["Install the PWA if prompted", "Log in to Juno33", "Enable notifications", "Confirm Instagram is installed and logged in"],
			};
		case "unsupported":
			return {
				label: "Push fallback",
				detail: "This browser cannot receive web push. Scheduling still creates the handoff.",
				steps: ["Schedule with Notify Me anyway", "Use the in-app handoff fallback", "Download/share media manually", "Open Instagram yourself"],
			};
		default:
			return {
				label: "Desktop setup",
				detail: "Use desktop for scheduling, then finish Notify Me setup on your phone.",
				steps: ["Schedule from desktop", "Open juno33.com on iPhone or Android", "Log in with the same account", "Install the PWA and enable notifications"],
			};
	}
}
