// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
export interface ErrorMessageInfo {
	title: string;
	description: string;
	action?: string | undefined;
	actionUrl?: string | undefined;
}

export const ERROR_MESSAGES: Record<string, ErrorMessageInfo> = {
	meta_api_down: {
		title: "Meta API temporarily unavailable",
		description: "Your data is safe — we'll auto-retry in 5 minutes.",
		action: "Check Meta Status",
		actionUrl: "https://metastatus.com",
	},
	token_expired: {
		title: "Connection needs refresh",
		description: "Your Instagram connection expired. This takes 10 seconds.",
		action: "Reconnect →",
	},
	rate_limited: {
		title: "Too many requests",
		description: "Please wait a moment before trying again.",
	},
	network_error: {
		title: "Connection issue",
		description: "Check your internet connection and try again.",
	},
	permission_denied: {
		title: "Permission needed",
		description: "This feature requires additional Instagram permissions.",
		action: "Update Permissions →",
	},
};

export function getErrorMessage(error: unknown): ErrorMessageInfo {
	if (!error) {
		return {
			title: "Something went wrong",
			description: "An unexpected error occurred.",
		};
	}

	const err = error as Record<string, unknown>;
	const msg =
		typeof error === "string" ? error : String(err?.message ?? err?.code ?? "");
	const code = String(err?.code ?? "");
	const status = Number(err?.status ?? err?.statusCode ?? 0);

	// Check for token expiry
	if (
		/token.*expir|expir.*token|OAuthException/i.test(msg) ||
		code === "token_expired"
	) {
		return ERROR_MESSAGES.token_expired!;
	}

	// Rate limiting
	if (
		status === 429 ||
		/rate.?limit|too many request/i.test(msg) ||
		code === "rate_limited"
	) {
		return ERROR_MESSAGES.rate_limited!;
	}

	// Network errors
	if (
		/fetch|network|ECONNREFUSED|ETIMEDOUT|ERR_NETWORK/i.test(msg) ||
		code === "network_error"
	) {
		return ERROR_MESSAGES.network_error!;
	}

	// Permission / auth
	if (
		status === 403 ||
		/permission|forbidden/i.test(msg) ||
		code === "permission_denied"
	) {
		return ERROR_MESSAGES.permission_denied!;
	}

	// Meta API issues
	if (
		/meta|graph\.threads|graph\.facebook|graph\.instagram/i.test(msg) ||
		status === 503 ||
		code === "meta_api_down"
	) {
		return ERROR_MESSAGES.meta_api_down!;
	}

	return {
		title: "Something went wrong",
		description:
			msg || "An unexpected error occurred. Try again or contact support.",
	};
}
