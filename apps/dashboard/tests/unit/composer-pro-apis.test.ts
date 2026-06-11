import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockMethodNotAllowed = vi.fn();
const mockCheckRateLimit = vi.fn();
const mockSendWebPushToUser = vi.fn();

vi.mock("@/api/_lib/apiResponse", () => ({
	apiError: (...args: unknown[]) => mockApiError(...args),
	apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
	methodNotAllowed: (res: unknown) => mockMethodNotAllowed(res),
}));

vi.mock("@/api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/middleware", () => ({
	withAuth: (handler: Function) => async (req: unknown, res: unknown) =>
		handler(req, res, { id: "user-1", email: "test@example.com" }),
}));

vi.mock("@/api/_lib/rateLimiter", () => ({
	checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

vi.mock("@/api/_lib/webPushDelivery", () => ({
	sendWebPushToUser: (...args: unknown[]) => mockSendWebPushToUser(...args),
}));

import telemetryHandler from "@/api/_lib/handlers/telemetry/client-event";
import testPushHandler from "@/api/_lib/handlers/notifications/test-push";

function mockReq(overrides: Record<string, unknown> = {}) {
	return {
		method: "POST",
		query: {},
		body: {},
		headers: {},
		...overrides,
	};
}

describe("composer pro API handlers", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockCheckRateLimit.mockResolvedValue({ allowed: true });
		mockSendWebPushToUser.mockResolvedValue({
			attempted: 1,
			sent: 1,
			expired: 0,
			failed: 0,
			configured: true,
		});
	});

	it("rejects telemetry payloads with content-bearing property keys", async () => {
		const req = mockReq({
			body: {
				event: "composer_opened",
				properties: { caption: "private caption text" },
			},
		});
		const res = mockRes();

		await telemetryHandler(req as any, res as any);

		expect(mockApiError).toHaveBeenCalledWith(
			res,
			400,
			"Telemetry properties cannot include content fields",
		);
		expect(mockApiSuccess).not.toHaveBeenCalled();
	});

	it("accepts privacy-safe telemetry events", async () => {
		const req = mockReq({
			body: {
				event: "first_post_wizard_opened",
				route: "/composer",
				properties: { surface: "setup_publishing" },
			},
		});
		const res = mockRes();

		await telemetryHandler(req as any, res as any);

		expect(mockApiSuccess).toHaveBeenCalledWith(res, { accepted: true });
	});

	it("sends test push only to the authenticated user's subscriptions", async () => {
		const req = mockReq();
		const res = mockRes();

		await testPushHandler(req as any, res as any);

		expect(mockSendWebPushToUser).toHaveBeenCalledWith(
			"user-1",
			expect.objectContaining({
				tag: "juno33-test-push",
				data: { url: "/composer", source: "test-push" },
			}),
		);
		expect(mockApiSuccess).toHaveBeenCalledWith(
			res,
			expect.objectContaining({ delivered: true }),
		);
	});
});
