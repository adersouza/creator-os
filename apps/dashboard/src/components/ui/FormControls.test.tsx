import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Card, CardContent, CardFooter } from "./Card";
import { Field } from "./Field";
import { Input } from "./Input";
import { Select } from "./Select";
import { Switch } from "./Switch";
import { Textarea } from "./Textarea";

describe("Juno form controls", () => {
	it("renders field label, hint, and iOS-safe input sizing", () => {
		render(
			<Field label="Workspace name" hint="Visible to your team.">
				<Input aria-label="Workspace name" />
			</Field>,
		);

		expect(screen.getByText("Workspace name")).toBeInTheDocument();
		expect(screen.getByText("Visible to your team.")).toBeInTheDocument();
		expect(screen.getByLabelText("Workspace name")).toHaveClass("text-base");
		expect(screen.getByLabelText("Workspace name")).toHaveClass("shadow-xs");
	});

	it("renders native select options and reports changes", async () => {
		const user = userEvent.setup();
		const onChange = vi.fn();
		render(
			<Select
				aria-label="Cadence"
				defaultValue="weekly"
				onChange={onChange}
				options={[
					{ value: "weekly", label: "Weekly" },
					{ value: "monthly", label: "Monthly" },
				]}
			/>,
		);

		await user.selectOptions(screen.getByLabelText("Cadence"), "monthly");
		expect(onChange).toHaveBeenCalledOnce();
		expect(screen.getByRole("option", { name: "Monthly" })).toBeInTheDocument();
	});

	it("renders textarea and switch primitives", async () => {
		const user = userEvent.setup();
		const onCheckedChange = vi.fn();
		render(
			<>
				<Textarea aria-label="Reply" defaultValue="Draft" />
				<Switch aria-label="Dark mode" onCheckedChange={onCheckedChange} />
			</>,
		);

		expect(screen.getByLabelText("Reply")).toHaveValue("Draft");
		expect(screen.getByLabelText("Reply")).toHaveClass("shadow-xs");
		await user.click(screen.getByRole("switch", { name: "Dark mode" }));
		expect(onCheckedChange).toHaveBeenCalledWith(true);
	});

	it("exports CardFooter without changing card composition", () => {
		render(
			<Card>
				<CardContent>Body</CardContent>
				<CardFooter>Footer</CardFooter>
			</Card>,
		);

		expect(screen.getByText("Body")).toBeInTheDocument();
		expect(screen.getByText("Footer")).toHaveClass("p-5");
	});
});
