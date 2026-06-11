import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	capture: vi.fn(),
	getSession: vi.fn(),
}));

vi.mock("@/lib/analytics", () => ({
	analytics: { capture: mocks.capture },
}));

vi.mock("@/services/supabase", () => ({
	supabase: {
		auth: { getSession: mocks.getSession },
	},
}));

import { trackClientEvent } from "./clientTelemetry";

describe("trackClientEvent", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.getSession.mockResolvedValue({
			data: { session: { access_token: "token-1" } },
		});
		vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
		window.history.pushState(null, "", "/composer?mode=notify");
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("strips content-bearing keys before analytics and server telemetry", async () => {
		trackClientEvent("composer_schedule_success", {
			surface: "composer",
			caption: "private",
			mediaUrl: "https://private.example/video.mov",
			token: "secret",
			count: 1,
		});

		await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());

		expect(mocks.capture).toHaveBeenCalledWith("composer_schedule_success", {
			surface: "composer",
			count: 1,
		});
		expect(fetch).toHaveBeenCalledWith(
			expect.stringContaining("/api/telemetry?action=client-event"),
			expect.objectContaining({
				method: "POST",
				body: JSON.stringify({
					event: "composer_schedule_success",
					route: "/composer?mode=notify",
					properties: {
						surface: "composer",
						count: 1,
					},
				}),
			}),
		);
	});

	it("does not send server telemetry without an auth session", async () => {
		mocks.getSession.mockResolvedValue({ data: { session: null } });

		trackClientEvent("empty_state_cta_clicked", { surface: "dashboard" });

		await Promise.resolve();
		expect(mocks.capture).toHaveBeenCalledWith("empty_state_cta_clicked", {
			surface: "dashboard",
		});
		expect(fetch).not.toHaveBeenCalled();
	});
});
