import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PhoneSetupChecklist } from "./PhoneSetupChecklist";

describe("PhoneSetupChecklist", () => {
	it("renders iPhone setup steps and enables push action", async () => {
		const user = userEvent.setup();
		const onEnablePush = vi.fn();
		render(
			<PhoneSetupChecklist
				pwaState="iphone-safari"
				pushState="permission-needed"
				onEnablePush={onEnablePush}
			/>,
		);

		expect(screen.getByText("Open juno33.com in Safari")).toBeInTheDocument();
		expect(screen.getByText("Tap Share, then Add to Home Screen")).toBeInTheDocument();

		await user.click(screen.getByRole("button", { name: /enable push/i }));
		expect(onEnablePush).toHaveBeenCalledOnce();
	});

	it("only allows test push once subscribed", async () => {
		const user = userEvent.setup();
		const onSendTestPush = vi.fn();
		render(
			<PhoneSetupChecklist
				pwaState="installed-ios"
				pushState="subscribed"
				onSendTestPush={onSendTestPush}
			/>,
		);

		await user.click(screen.getByRole("button", { name: /test push/i }));
		expect(onSendTestPush).toHaveBeenCalledOnce();
	});

	it("shows fallback state for unsupported push browsers", () => {
		render(<PhoneSetupChecklist pwaState="unsupported" pushState="unsupported" />);

		expect(screen.getByText("Push fallback")).toBeInTheDocument();
		expect(screen.getByText("Use the in-app handoff fallback")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /enable push/i })).toBeDisabled();
	});
});
