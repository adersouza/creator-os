import { appToast } from "@/lib/toast";
import logger from "@/utils/logger";

/**
 * withErrorToast — wraps an async function with try/catch, shows toast.error
 * on failure, logs the error, and returns null.
 *
 * Usage:
 *   const result = await withErrorToast(() => saveConfig(data), "Failed to save");
 *   if (!result) return; // error already toasted
 */
export async function withErrorToast<T>(
	fn: () => Promise<T>,
	fallbackMessage = "Something went wrong",
): Promise<T | null> {
	try {
		return await fn();
	} catch (error) {
		const message = error instanceof Error ? error.message : fallbackMessage;
		const requestId =
			typeof error === "object" &&
			error !== null &&
			"requestId" in error &&
			typeof error.requestId === "string"
				? error.requestId
				: undefined;
		logger.error(fallbackMessage, error);
		appToast.error(message, requestId ? { description: `Request ID: ${requestId}` } : undefined);
		return null;
	}
}
