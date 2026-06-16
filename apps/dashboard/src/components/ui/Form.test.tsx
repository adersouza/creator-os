import { zodResolver } from "@hookform/resolvers/zod";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import {
	Form,
	FormCheckboxField,
	FormInputField,
	FormSelectField,
	FormSwitchField,
	FormTextareaField,
} from "@/components/ui/Form";

const settingsSchema = z.object({
	name: z.string().min(2, "Name must be at least 2 characters."),
	bio: z.string().max(120).optional(),
	role: z.enum(["owner", "editor"]),
	active: z.boolean(),
	weekly: z.boolean(),
});

type SettingsValues = z.infer<typeof settingsSchema>;

function ExampleForm({
	onSubmit = vi.fn(),
}: {
	onSubmit?: (values: SettingsValues) => void;
}) {
	const form = useForm<SettingsValues>({
		resolver: zodResolver(settingsSchema),
		defaultValues: {
			name: "",
			bio: "",
			role: "editor",
			active: false,
			weekly: true,
		},
	});

	return (
		<Form form={form} onSubmit={onSubmit} aria-label="Workspace settings">
			<FormInputField
				name="name"
				label="Workspace name"
				hint="Visible to your team."
			/>
			<FormTextareaField name="bio" label="Bio" />
			<FormSelectField
				name="role"
				label="Role"
				options={[
					{ value: "owner", label: "Owner" },
					{ value: "editor", label: "Editor" },
				]}
			/>
			<FormSwitchField name="active" label="Active workspace" />
			<FormCheckboxField name="weekly" label="Weekly summary" />
			<Button type="submit">Save</Button>
		</Form>
	);
}

describe("RHF-backed Juno form adapters", () => {
	it("renders labels, hints, controls, and default values", () => {
		render(<ExampleForm />);

		expect(screen.getByText("Workspace name")).toBeInTheDocument();
		expect(screen.getByText("Visible to your team.")).toBeInTheDocument();
		expect(screen.getByLabelText("Bio")).toHaveValue("");
		expect(screen.getByLabelText("Role")).toHaveValue("editor");
		expect(screen.getByRole("switch", { name: "Active workspace" })).not.toBeChecked();
		expect(screen.getByRole("checkbox", { name: "Weekly summary" })).toBeChecked();
	});

	it("shows Zod validation and sets invalid control state", async () => {
		const user = userEvent.setup();
		render(<ExampleForm />);

		await user.click(screen.getByRole("button", { name: "Save" }));

		expect(
			await screen.findByText("Name must be at least 2 characters."),
		).toBeInTheDocument();
		expect(screen.getByLabelText("Workspace name")).toHaveAttribute(
			"aria-invalid",
			"true",
		);
	});

	it("submits typed values through the stable form wrapper", async () => {
		const user = userEvent.setup();
		const onSubmit = vi.fn();
		render(<ExampleForm onSubmit={onSubmit} />);

		await user.type(screen.getByLabelText("Workspace name"), "Juno");
		await user.type(screen.getByLabelText("Bio"), "Social operations");
		await user.selectOptions(screen.getByLabelText("Role"), "owner");
		await user.click(screen.getByRole("switch", { name: "Active workspace" }));
		await user.click(screen.getByRole("checkbox", { name: "Weekly summary" }));
		await user.click(screen.getByRole("button", { name: "Save" }));

		await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
		expect(onSubmit).toHaveBeenCalledWith(
			{
				name: "Juno",
				bio: "Social operations",
				role: "owner",
				active: true,
				weekly: false,
			},
			expect.anything(),
		);
	});
});
