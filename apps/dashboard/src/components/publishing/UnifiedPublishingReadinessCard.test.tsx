import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UnifiedPublishingReadinessCard } from "./UnifiedPublishingReadinessCard";

describe("UnifiedPublishingReadinessCard", () => {
	it("renders blockers from composer checks and setup issues", () => {
		render(
			<UnifiedPublishingReadinessCard
				postHealth={{
					score: 42,
					label: "Blocked",
					tone: "blocked",
					issues: ["Choose an account"],
				}}
				checks={[
					{
						id: "account",
						label: "Choose an account",
						detail: "Pick a Threads or Instagram account before publishing.",
						tone: "blocked",
					},
					{
						id: "content",
						label: "Add caption or media",
						detail: "Posts need a caption, media, or both.",
						tone: "blocked",
					},
				]}
				setupIssues={[
					{
						id: "notify-push",
						label: "Enable Notify Me push",
						detail: "Enable or test push before relying on mobile reminders.",
						state: "needs_setup",
					},
				]}
			/>,
		);

		expect(screen.getByText("Choose an account")).toBeInTheDocument();
		expect(screen.getByText("Add caption or media")).toBeInTheDocument();
		expect(screen.getByText("Enable Notify Me push")).toBeInTheDocument();
	});

	it("preserves check and setup action callbacks", async () => {
		const user = userEvent.setup();
		const checkAction = vi.fn();
		const setupAction = vi.fn();
		const onCheckAction = vi.fn();
		const onSetupIssueAction = vi.fn();

		render(
			<UnifiedPublishingReadinessCard
				postHealth={{ score: 72, label: "Needs review", tone: "warning", issues: [] }}
				onCheckAction={onCheckAction}
				onSetupIssueAction={onSetupIssueAction}
				checks={[
					{
						id: "format",
						label: "Format needs review",
						detail: "Instagram Reels require exactly one video.",
						tone: "blocked",
						actionLabel: "Review",
						action: checkAction,
					},
				]}
				setupIssues={[
					{
						id: "notify-push",
						label: "Enable Notify Me push",
						detail: "Enable or test push before relying on mobile reminders.",
						state: "needs_setup",
						actionLabel: "Setup push",
						action: setupAction,
					},
				]}
			/>,
		);

		await user.click(screen.getByRole("button", { name: "Review" }));
		await user.click(screen.getByRole("button", { name: "Setup push" }));

		expect(onCheckAction).toHaveBeenCalledWith(expect.objectContaining({ id: "format" }));
		expect(checkAction).toHaveBeenCalledOnce();
		expect(onSetupIssueAction).toHaveBeenCalledWith(
			expect.objectContaining({ id: "notify-push" }),
		);
		expect(setupAction).toHaveBeenCalledOnce();
	});

	it("renders one clear ready state", () => {
		render(
			<UnifiedPublishingReadinessCard
				postHealth={{ score: 96, label: "Excellent", tone: "ready", issues: [] }}
				checks={[
					{
						id: "account",
						label: "Account selected",
						detail: "1 target ready.",
						tone: "ready",
					},
				]}
				setupIssues={[
					{
						id: "instagram-account",
						label: "Instagram connected",
						detail: "Juno33 can target at least one Instagram account.",
						state: "ready",
					},
				]}
			/>,
		);

		expect(screen.getByText("Ready to publish")).toBeInTheDocument();
		expect(screen.getByText(/Server preflight still verifies/i)).toBeInTheDocument();
	});
});
