/**
 * Error handling utilities for API routes.
 *
 * Replaces `catch (error: any)` pattern with type-safe error extraction.
 */

/**
 * Safely extract an error message from an unknown caught value.
 */
export function getErrorMessage(error: unknown): string {
	if (error instanceof Error) return error.message;
	if (typeof error === "string") return error;
	if (
		error !== null &&
		typeof error === "object" &&
		"message" in error &&
		typeof (error as { message: unknown }).message === "string"
	) {
		return (error as { message: string }).message;
	}
	return "An unknown error occurred";
}

/**
 * Safely extract an error code from an unknown caught value.
 */
export function getErrorCode(error: unknown): string | undefined {
	if (
		error !== null &&
		typeof error === "object" &&
		"code" in error &&
		typeof (error as { code: unknown }).code === "string"
	) {
		return (error as { code: string }).code;
	}
	return undefined;
}
