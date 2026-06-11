import { appToast } from "@/lib/toast";

/**
 * Copy text to clipboard with error handling.
 * Falls back to a toast error if the Clipboard API is unavailable or fails.
 */
export async function copyToClipboard(
	text: string,
	successMessage = "Copied to clipboard",
): Promise<boolean> {
	try {
		await navigator.clipboard.writeText(text);
		appToast.success(successMessage);
		return true;
	} catch {
		appToast.error("Failed to copy to clipboard");
		return false;
	}
}
