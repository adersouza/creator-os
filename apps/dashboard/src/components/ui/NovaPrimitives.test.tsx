import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NovaScreen } from "@/components/layout/NovaScreen";
import {
	NovaCard,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaInset,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
	NovaStat,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Button } from "@/components/ui/Button";

describe("Nova route-screen primitives", () => {
	it("renders the route canvas, header, toolbar, and section slots", () => {
		render(
			<NovaScreen data-testid="nova-screen" mode="workflow">
				<NovaHeader
					eyebrow="Content"
					title="Posted content"
					description="Read published posts"
					meta="Fleet · 30d"
					actions={
						<NovaToolbar>
							<Button type="button">Create</Button>
						</NovaToolbar>
					}
				/>
				<NovaSection>
					<NovaCard title="Recent posts">Rows</NovaCard>
				</NovaSection>
			</NovaScreen>,
		);

		expect(screen.getByTestId("nova-screen")).toHaveClass("nova-screen");
		expect(screen.getByRole("heading", { name: "Posted content" })).toBeInTheDocument();
		expect(screen.getByText("Fleet · 30d")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
		expect(screen.getByRole("heading", { name: "Recent posts" })).toBeInTheDocument();
	});

	it("renders stat, data panel, and empty states through shadcn-backed wrappers", () => {
		render(
			<div>
				<NovaStat
					label="Published posts"
					value="42"
					description="Synced posts"
					progress={{ value: 64, label: "Published post coverage" }}
				/>
				<NovaDataPanel title="Content table" loading />
				<NovaMiniStat
					label="Reach"
					value="12.4K"
					description="vs. prior"
					trend="+8%"
					tone="success"
					size="compact"
				/>
				<NovaListRow
					title="@juno"
					description="Threads · 12K reach"
					meta="88"
					action={<button type="button">Open</button>}
					progress={88}
					progressLabel="@juno quality score"
				/>
				<NovaInset>Inner panel</NovaInset>
				<NovaEmpty title="No posts" description="Create a post to start tracking." />
				<NovaEmpty
					eyebrow="Evidence"
					title="No source data"
					description="The sync has not returned bucketed rows yet."
				/>
			</div>,
		);

		expect(screen.getByText("Published posts")).toBeInTheDocument();
		expect(screen.getByText("42")).toBeInTheDocument();
		expect(screen.getByLabelText("Published post coverage")).toBeInTheDocument();
		expect(screen.getByLabelText("Loading panel")).toBeInTheDocument();
		expect(screen.getByText("12.4K")).toBeInTheDocument();
		expect(screen.getByText("12.4K")).toHaveClass("text-xl");
		expect(screen.getByText("@juno")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
		expect(screen.getByLabelText("@juno quality score")).toBeInTheDocument();
		expect(screen.getByText("Inner panel")).toBeInTheDocument();
		expect(screen.getByText("No posts")).toBeInTheDocument();
		expect(screen.getByText("Evidence")).toBeInTheDocument();
		expect(screen.getByText("No source data")).toBeInTheDocument();
	});
});
