import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { APITabContent } from "@/components/settings/APITabContent";
import { WebhooksTabContent } from "@/components/settings/WebhooksTabContent";

const mocks = vi.hoisted(() => ({
	createApiKey: vi.fn(),
	createUserWebhook: vi.fn(),
	deleteUserWebhook: vi.fn(),
	listApiKeys: vi.fn(),
	listUserWebhooks: vi.fn(),
	revokeApiKey: vi.fn(),
	testUserWebhook: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
	appToast: {
		error: vi.fn(),
		success: vi.fn(),
	},
}));

vi.mock("@/services/api/settingsDeveloper", () => ({
	createApiKey: mocks.createApiKey,
	createUserWebhook: mocks.createUserWebhook,
	deleteUserWebhook: mocks.deleteUserWebhook,
	listApiKeys: mocks.listApiKeys,
	listUserWebhooks: mocks.listUserWebhooks,
	revokeApiKey: mocks.revokeApiKey,
	testUserWebhook: mocks.testUserWebhook,
}));

describe("developer settings RHF forms", () => {
	beforeEach(() => {
		for (const mock of Object.values(mocks)) {
			mock.mockReset();
		}
	});

	it("creates API keys with the selected scope payload", async () => {
		const user = userEvent.setup();
		mocks.listApiKeys.mockResolvedValueOnce([]);
		mocks.createApiKey.mockResolvedValueOnce({
			key: {
				id: "key-1",
				name: "Production integration",
				key_prefix: "juno_live",
				scopes: ["read"],
				allowed_account_ids: null,
				created_at: "2026-06-16T00:00:00.000Z",
				last_used_at: null,
			},
			rawKey: "juno_live_secret",
		});

		render(<APITabContent />);
		await screen.findByText("No API keys yet");
		await user.click(screen.getByRole("button", { name: "Generate key" }));

		await waitFor(() =>
			expect(mocks.createApiKey).toHaveBeenCalledWith({
				name: "Production integration",
				scopes: ["read"],
			}),
		);
	});

	it("creates webhooks with validated endpoint and selected events", async () => {
		const user = userEvent.setup();
		mocks.listUserWebhooks.mockResolvedValueOnce([]);
		mocks.createUserWebhook.mockResolvedValueOnce({
			webhook: {
				id: "hook-1",
				url: "https://example.com/juno33/webhook",
				events: ["post_published"],
				last_triggered_at: null,
			},
		});

		render(<WebhooksTabContent />);
		await screen.findByText("No webhooks yet");
		await user.type(
			screen.getByLabelText("Endpoint URL"),
			"https://example.com/juno33/webhook",
		);
		await user.click(screen.getByRole("button", { name: "Add webhook" }));

		await waitFor(() =>
			expect(mocks.createUserWebhook).toHaveBeenCalledWith({
				url: "https://example.com/juno33/webhook",
				events: ["post_published"],
			}),
		);
	});
});
