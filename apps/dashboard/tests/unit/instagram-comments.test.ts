import { describe, expect, it, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
	decrypt: vi.fn(),
	igFetch: vi.fn(),
}));

vi.mock("../../api/_lib/instagram/shared.js", () => ({
	decrypt: mocks.decrypt,
	getGraphBaseUrl: vi.fn(() => "https://graph.instagram.com"),
	igFetch: mocks.igFetch,
	logger: mocks.logger,
}));

import { getMediaComments } from "../../api/_lib/instagram/comments";

describe("getMediaComments", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("fails cleanly when the encrypted token is null at runtime", async () => {
		const result = await getMediaComments(
			null as unknown as string,
			"1789",
			undefined,
			"instagram",
		);

		expect(result).toEqual({
			success: false,
			error: "Instagram access token not available",
		});
		expect(mocks.decrypt).not.toHaveBeenCalled();
		expect(mocks.igFetch).not.toHaveBeenCalled();
		expect(mocks.logger.error).toHaveBeenCalledWith("IG getMediaComments error", {
			error: "Error: Instagram access token not available",
		});
	});
});
