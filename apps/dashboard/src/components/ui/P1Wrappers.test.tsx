import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Avatar, AvatarFallback } from "./Avatar";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
} from "./Command";
import {
	ContextMenuContent,
	ContextMenuItem,
	ContextMenuRoot,
	ContextMenuTrigger,
} from "./ContextMenu";
import { Progress } from "./Progress";

describe("P1 shadcn-backed wrappers", () => {
	beforeAll(() => {
		class ResizeObserverMock {
			observe() {}
			unobserve() {}
			disconnect() {}
		}
		Object.defineProperty(window, "ResizeObserver", {
			writable: true,
			value: ResizeObserverMock,
		});
		Element.prototype.scrollIntoView = vi.fn();
		window.scrollTo = vi.fn();
	});

	it("renders Avatar fallback through the Juno wrapper", () => {
		render(
			<Avatar>
				<AvatarFallback>AD</AvatarFallback>
			</Avatar>,
		);

		expect(screen.getByText("AD")).toHaveClass("text-muted-foreground");
	});

	it("renders Progress with token tone classes", () => {
		render(<Progress aria-label="Sync progress" value={42} tone="good" />);

		const progress = screen.getByRole("progressbar", {
			name: "Sync progress",
		});
		expect(progress).toHaveAttribute("aria-valuenow", "42");
		expect(progress).toHaveClass("[&>div]:bg-[color:var(--color-health-good)]");
	});

	it("keeps Command input and item selection behavior", async () => {
		const user = userEvent.setup();
		const onValueChange = vi.fn();
		const onSelect = vi.fn();
		render(
			<Command shouldFilter={false}>
				<CommandInput
					aria-label="Search commands"
					onValueChange={onValueChange}
				/>
				<CommandList>
					<CommandEmpty>No commands</CommandEmpty>
					<CommandGroup heading="Actions">
						<CommandItem value="open-calendar" onSelect={onSelect}>
							Open calendar
						</CommandItem>
					</CommandGroup>
				</CommandList>
			</Command>,
		);

		await user.type(screen.getByLabelText("Search commands"), "open");
		await user.click(screen.getByText("Open calendar"));

		expect(onValueChange).toHaveBeenLastCalledWith("open");
		expect(onSelect).toHaveBeenCalledWith("open-calendar");
	});

	it("preserves ContextMenu destructive item styling", () => {
		render(
			<ContextMenuRoot>
				<ContextMenuTrigger>Row</ContextMenuTrigger>
				<ContextMenuContent>
					<ContextMenuItem destructive>Remove account</ContextMenuItem>
				</ContextMenuContent>
			</ContextMenuRoot>,
		);
		fireEvent.contextMenu(screen.getByText("Row"));

		expect(screen.getByText("Remove account")).toHaveClass(
			"text-[color:var(--color-danger)]",
		);
	});
});
