/**
 * HTML Sanitization Utility
 *
 * Sanitizes user-provided content to prevent XSS attacks.
 * Used for Instagram DM messages, comment replies, and other user-generated content.
 */

/**
 * Sanitizes HTML content to prevent XSS attacks.
 *
 * This is a basic sanitizer that:
 * - Strips all HTML tags except safe ones (for plain text, strips all)
 * - Escapes special characters
 * - Removes script tags and event handlers
 *
 * For Instagram messages/comments, we want plain text only.
 */
export function sanitizeHtml(input: string): string {
	if (!input) return "";

	// Remove all HTML tags
	let sanitized = input.replace(/<[^>]*>/g, "");

	// Decode HTML entities that could be used to bypass tag stripping, then re-strip tags
	sanitized = sanitized
		.replace(/&lt;/g, "<")
		.replace(/&gt;/g, ">")
		.replace(/&amp;/g, "&")
		.replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
		.replace(/&#x([\da-fA-F]+);/g, (_, hex) =>
			String.fromCharCode(parseInt(hex, 16)),
		)
		.replace(/<[^>]*>/g, "");

	// Strip remaining HTML tags but do NOT re-encode characters.
	// Post content goes to Threads/Instagram as plain text — HTML entities
	// like &#x27; and &#x2F; render literally on those platforms.

	// Remove null bytes
	sanitized = sanitized.replace(/\0/g, "");

	// Trim whitespace
	sanitized = sanitized.trim();

	return sanitized;
}

/**
 * Sanitizes plain text for Instagram messages.
 * Allows basic formatting but removes dangerous content.
 */
export function sanitizeMessage(message: string): string {
	// For Instagram messages, use basic sanitization
	// Instagram API handles most formatting, we just prevent XSS
	return sanitizeHtml(message);
}

/**
 * Validates message length for Instagram.
 * Instagram has a 1000 character limit for DM text.
 */
export function validateMessageLength(
	message: string,
	maxLength: number = 1000,
): {
	valid: boolean;
	message?: string | undefined;
} {
	if (!message || message.trim().length === 0) {
		return { valid: false, message: "Message cannot be empty" };
	}

	if (message.length > maxLength) {
		return {
			valid: false,
			message: `Message too long. Maximum ${maxLength} characters allowed.`,
		};
	}

	return { valid: true };
}
