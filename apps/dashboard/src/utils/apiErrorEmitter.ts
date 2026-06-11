type ErrorHandler = (error: {
	type: "rate_limit" | "auth" | "network" | "server";
	message: string;
	retryAfter?: number | undefined;
	requestId?: string | undefined;
}) => void;

let handler: ErrorHandler | null = null;

export function setApiErrorHandler(h: ErrorHandler) {
	handler = h;
}

export function emitApiError(error: Parameters<ErrorHandler>[0]) {
	handler?.(error);
}
