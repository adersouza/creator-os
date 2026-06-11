import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { FormSection } from "@/components/ui/FormSection";
import { NovaCard, NovaDataPanel, NovaHeader, NovaStat } from "@/components/ui/NovaPrimitives";

describe("shadcn rebuild primitives", () => {
	it("renders the route canvas and page header slots", () => {
		render(
			<NovaScreen data-testid="screen">
				<NovaHeader
					eyebrow="Analytics"
					title="Performance evidence"
					description="Read the fleet"
					meta="All accounts · 30D"
					filters={<button type="button">Fleet</button>}
					actions={<button type="button">Export</button>}
				/>
			</NovaScreen>,
		);

		expect(screen.getByTestId("screen")).toHaveClass("nova-screen");
		expect(screen.getByRole("heading", { name: "Performance evidence" })).toBeInTheDocument();
		expect(screen.getByText("All accounts · 30D")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Fleet" })).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
	});

	it("renders stat card hierarchy and optional state slots", () => {
		render(
			<NovaStat
				label="Fleet reach"
				value="12.4K"
				description="30 posts"
				status="Preview"
				trend={{ direction: "up", label: "+8.2%" }}
				progress={{ value: 64, label: "Reach progress" }}
				action={<button type="button">Open</button>}
			/>,
		);

		expect(screen.getByText("Fleet reach")).toBeInTheDocument();
		expect(screen.getByText("12.4K")).toBeInTheDocument();
		expect(screen.getByText("+8.2%")).toBeInTheDocument();
		expect(screen.getByLabelText("Reach progress")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
	});

	it("composes dashboard, evidence, form, and data panels", () => {
		render(
			<div>
				<NovaCard title="Ops health" action={<button type="button">Refresh</button>}>
					Operational body
				</NovaCard>
				<EvidenceCard title="Evidence queue" footer="Updated now">
					Evidence body
				</EvidenceCard>
				<FormSection title="Workspace">Form body</FormSection>
				<NovaDataPanel title="Fleet table" toolbar={<button type="button">Filter</button>}>
					Table body
				</NovaDataPanel>
			</div>,
		);

		expect(screen.getByRole("heading", { name: "Ops health" })).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
		expect(screen.getByText("Evidence body")).toBeInTheDocument();
		expect(screen.getByText("Updated now")).toBeInTheDocument();
		expect(screen.getByText("Form body")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Filter" })).toBeInTheDocument();
	});

	it("shows loading and empty states in NovaDataPanel", () => {
		const { rerender } = render(<NovaDataPanel title="Loading panel" loading />);

		expect(screen.getByLabelText("Loading panel")).toBeInTheDocument();

		rerender(
			<NovaDataPanel
				title="Empty panel"
				empty={{
					title: "No rows",
					description: "Try a different filter.",
				}}
			/>,
		);

		expect(screen.getByText("No rows")).toBeInTheDocument();
		expect(screen.getByText("Try a different filter.")).toBeInTheDocument();
	});
});
