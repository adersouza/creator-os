import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
	CommandMenuActionRow,
	CommandMenuShell,
} from "@/components/ui/CommandMenuShell";

describe("CommandMenuShell", () => {
	beforeEach(() => {
		class ResizeObserverMock {
			observe = vi.fn();
			unobserve = vi.fn();
			disconnect = vi.fn();
		}
		Object.defineProperty(window, "ResizeObserver", {
			configurable: true,
			value: ResizeObserverMock,
		});
		Element.prototype.scrollIntoView = vi.fn();
	});

	it("renders grouped commands and shortcuts", async () => {
		const onSelect = vi.fn();
		const user = userEvent.setup();
		render(
			<CommandMenuShell
				open
				onOpenChange={() => undefined}
				title="Global command menu"
				description="Run a command"
				groups={[
					{
						id: "create",
						heading: "Create",
						items: [
							{
								id: "post",
								label: "Create post",
								description: "Open Composer",
								shortcut: "C",
								onSelect,
							},
						],
					},
				]}
			/>,
		);

		expect(screen.getByRole("dialog", { name: "Global command menu" })).toBeInTheDocument();
		expect(screen.getByText("Create")).toBeInTheDocument();
		expect(screen.getByText("Create post")).toBeInTheDocument();
		expect(screen.getByText("Open Composer")).toBeInTheDocument();
		expect(screen.getByText("C")).toBeInTheDocument();

		await user.click(screen.getByText("Create post"));
		expect(onSelect).toHaveBeenCalledOnce();
	});

	it("renders empty state when there are no groups", () => {
		render(
			<CommandMenuShell
				open
				onOpenChange={() => undefined}
				description="No commands are available."
				empty="No matches"
			/>,
		);

		expect(screen.getByText("No matches")).toBeInTheDocument();
	});

	it("renders the shared command action row anatomy", () => {
		render(
			<CommandMenuActionRow
				label="Schedule post"
				description="Open the scheduling workspace"
				shortcut="S"
			/>,
		);

		expect(screen.getByText("Schedule post")).toBeInTheDocument();
		expect(screen.getByText("Open the scheduling workspace")).toBeInTheDocument();
		expect(screen.getByText("S")).toBeInTheDocument();
	});
});
