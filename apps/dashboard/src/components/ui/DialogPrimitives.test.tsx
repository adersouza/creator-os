import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";
import { ConfirmDialog } from "./ConfirmDialog";
import { Modal } from "./Modal";

describe("dialog primitives", () => {
	it("Modal closes on Escape and restores trigger focus", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();
		function Harness() {
			const [open, setOpen] = useState(false);
			return (
				<>
					<Button onClick={() => setOpen(true)}>Open dialog</Button>
					<Modal
						open={open}
						onClose={() => {
							onClose();
							setOpen(false);
						}}
						title="Edit account"
					>
						<p>Account body</p>
					</Modal>
				</>
			);
		}
		render(<Harness />);

		await user.click(screen.getByRole("button", { name: "Open dialog" }));
		await user.keyboard("{Escape}");

		expect(onClose).toHaveBeenCalledOnce();
		await waitFor(() =>
			expect(screen.queryByRole("dialog", { name: "Edit account" })).not.toBeInTheDocument(),
		);
		expect(screen.getByRole("button", { name: "Open dialog" })).toHaveFocus();
	});

	it("ConfirmDialog uses alertdialog semantics and blocks backdrop close while busy", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();
		render(
			<ConfirmDialog
				open
				onClose={onClose}
				onConfirm={vi.fn()}
				title="Delete post"
				description="This cannot be undone."
				confirmLabel="Delete"
				busy
			/>,
		);

		expect(screen.getByRole("alertdialog", { name: "Delete post" })).toBeInTheDocument();
		const overlay = document.querySelector(".td-overlay");
		expect(overlay).toBeInstanceOf(HTMLElement);
		fireEvent.pointerDown(overlay as HTMLElement);
		await user.keyboard("{Escape}");

		expect(onClose).not.toHaveBeenCalled();
	});
});
