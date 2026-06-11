/**
 * Prompt utilities for AI endpoint safety
 */

/**
 * Decode common HTML entities so injection patterns hidden behind &#xx; encoding
 * are revealed before pattern matching.
 */
function decodeHtmlEntities(text: string): string {
	return text
		.replace(/&#(\d+);/g, (_, n) => String.fromCharCode(parseInt(n, 10)))
		.replace(/&#x([0-9a-fA-F]+);/g, (_, h) =>
			String.fromCharCode(parseInt(h, 16)),
		)
		.replace(/&lt;/g, "<")
		.replace(/&gt;/g, ">")
		.replace(/&amp;/g, "&")
		.replace(/&quot;/g, '"')
		.replace(/&#039;/g, "'");
}

/**
 * Strip prompt injection patterns from user input before including in AI prompts.
 * Removes common override/jailbreak patterns while preserving legitimate content.
 */
export function stripInjection(text: string): string {
	// Collapse Unicode variants (e.g. fullwidth, compatibility forms)
	text = text.normalize("NFKC");
	// Decode HTML entities so encoded injection patterns are caught
	text = decodeHtmlEntities(text);
	// Strip base64-encoded payloads (50+ chars of base64 alphabet)
	text = text.replace(/\b[A-Za-z0-9+/]{50,}={0,2}\b/g, "");
	return (
		text
			// Remove system/assistant role overrides
			.replace(/\b(system|assistant)\s*:\s*/gi, "")
			// Remove newline-separated role overrides (e.g. "\n\nsystem:\n")
			.replace(/\n{2,}\s*(system|assistant|user)\s*:\s*/gi, "\n")
			// Remove instruction override patterns
			.replace(
				/ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)/gi,
				"[filtered]",
			)
			.replace(
				/disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)/gi,
				"[filtered]",
			)
			.replace(
				/forget\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)/gi,
				"[filtered]",
			)
			// Remove "do not follow" / "override" instruction patterns
			.replace(
				/do\s+not\s+follow\s+(any\s+)?(previous|above|prior|original)\s+(instructions?|prompts?|rules?|guidelines?)/gi,
				"[filtered]",
			)
			.replace(
				/override\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)/gi,
				"[filtered]",
			)
			// Remove attempts to redefine the AI's role
			.replace(/you\s+are\s+now\s+/gi, "")
			.replace(/act\s+as\s+(if\s+you\s+are\s+)?/gi, "")
			// Remove markdown-style code fences that could contain injection payloads
			.replace(/```(system|instruction|prompt)[^`]*```/gis, "[filtered]")
			// Limit length to prevent context flooding
			.substring(0, 5000)
	);
}

/**
 * Escape user-controlled strings before interpolating into AI prompts.
 * Prevents breaking out of quoted strings in prompt templates.
 */
export function escapeForPrompt(text: string): string {
	return stripInjection(text)
		.replace(/\\/g, "\\\\")
		.replace(/"/g, '\\"')
		.replace(/\n/g, "\\n")
		.replace(/\r/g, "\\r");
}

/**
 * Sanitize AI-generated output before returning to clients.
 * Strips potential XSS vectors from AI responses.
 */
export function sanitizeAIOutput(text: string): string {
	return text
		.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
		.replace(/<[^>]*on\w+\s*=/gi, "")
		.replace(/javascript:/gi, "");
}
