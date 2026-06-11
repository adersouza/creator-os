import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PublishingReadinessPanel } from "./PublishingReadinessPanel";
import { PublishingStartCard } from "./PublishingStartCard";

const navigateMock = vi.fn();

vi.mock("react-router-dom", () => ({
	useNavigate: () => navigateMock,
}));

vi.mock("@/services/clientTelemetry", () => ({
	trackClientEvent: vi.fn(),
}));

describe("Publishing P2A cards", () => {
	beforeEach(() => {
		navigateMock.mockClear();
	});

	it("renders readiness issue actions and preserves callbacks", async () => {
		const user = userEvent.setup();
		const issueAction = vi.fn();
		const onIssueAction = vi.fn();
		render(
			<PublishingReadinessPanel
				issues={[
					{
						id: "notify-push",
						label: "Enable push",
						detail: "Notify Me posts need browser push enabled.",
						state: "needs_setup",
						actionLabel: "Enable",
						action: issueAction,
					},
				]}
				onIssueAction={onIssueAction}
			/>,
		);

		await user.click(screen.getByRole("button", { name: "Enable" }));

		expect(onIssueAction).toHaveBeenCalledWith(
			expect.objectContaining({ id: "notify-push" }),
		);
		expect(issueAction).toHaveBeenCalledOnce();
	});

	it("renders the ready empty state when no readiness issues are visible", () => {
		render(<PublishingReadinessPanel issues={[]} />);

		expect(screen.getByText("Ready to publish")).toBeInTheDocument();
		expect(
			screen.getByText("Everything required for publishing is ready."),
		).toBeInTheDocument();
	});

	it("keeps start-card navigation targets", async () => {
		const user = userEvent.setup();
		render(<PublishingStartCard surface="accounts_empty" />);

		await user.click(screen.getByRole("button", { name: /phone setup/i }));
		expect(navigateMock).toHaveBeenLastCalledWith("/settings/notifications");

		await user.click(screen.getByRole("button", { name: /start here/i }));
		expect(navigateMock).toHaveBeenLastCalledWith("/setup/publishing");
	});
});
