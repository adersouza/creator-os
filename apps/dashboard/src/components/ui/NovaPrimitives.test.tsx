import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NovaScreen } from "@/components/layout/NovaScreen";
import {
	NovaCard,
	NovaBentoGrid,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaInset,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
	NovaStat,
	NovaToolbar,
	NovaUsageList,
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
					<NovaBentoGrid data-testid="nova-bento-grid" className="lg:grid-cols-12">
						<NovaCard title="Recent posts" className="lg:col-span-12">
							Rows
						</NovaCard>
					</NovaBentoGrid>
				</NovaSection>
			</NovaScreen>,
		);

		expect(screen.getByTestId("nova-screen")).toHaveClass("nova-screen");
		expect(screen.getByRole("heading", { name: "Posted content" })).toBeInTheDocument();
		expect(screen.getByText("Fleet · 30d")).toBeInTheDocument();
		expect(screen.getByTestId("nova-bento-grid")).toHaveClass("nova-bento-grid");
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
					sparkline={{ points: [12, 18, 16, 24], label: "Published posts trend" }}
					footer={<span>30 day window</span>}
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
					eyebrow="Insights"
					title="No source data"
					description="The sync has not returned bucketed rows yet."
				/>
			</div>,
		);

		expect(screen.getByText("Published posts")).toBeInTheDocument();
		expect(screen.getByText("42")).toBeInTheDocument();
		expect(screen.getByText("30 day window")).toBeInTheDocument();
		expect(screen.getByLabelText("Published post coverage")).toBeInTheDocument();
		expect(screen.getByLabelText("Published posts trend")).toBeInTheDocument();
		expect(screen.getByLabelText("Loading panel")).toBeInTheDocument();
		expect(screen.getByText("12.4K")).toBeInTheDocument();
		expect(screen.getByText("12.4K")).toHaveClass("text-lg");
		expect(screen.getByText("@juno")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
		expect(screen.getByLabelText("@juno quality score")).toBeInTheDocument();
		expect(screen.getByText("Inner panel")).toBeInTheDocument();
		expect(screen.getByText("No posts")).toBeInTheDocument();
		expect(screen.getByText("Insights")).toBeInTheDocument();
		expect(screen.getByText("No source data")).toBeInTheDocument();
	});

	it("lets flush card content override responsive default padding", () => {
		render(
			<NovaCard title="Flush media" contentClassName="p-0" data-testid="flush-card">
				<div>Full bleed table</div>
			</NovaCard>,
		);

		const content = screen.getByText("Full bleed table").closest(".nova-card-content");
		expect(content).toHaveClass("p-0");
		expect(content).toHaveClass("md:p-0");
	});

	it("renders Blocks-style usage rows through Nova tokens", () => {
		render(
			<NovaUsageList
				items={[
					{
						label: "Connected accounts",
						value: "12 / 25",
						description: "13 slots remaining",
						progress: 48,
						limit: "25 max",
						tone: "primary",
					},
					{
						label: "Team members",
						value: "4",
						description: "Unlimited seats",
						limit: "unlimited",
						tone: "success",
					},
				]}
			/>,
		);

		expect(screen.getByText("Connected accounts")).toBeInTheDocument();
		expect(screen.getByText("12 / 25")).toBeInTheDocument();
		expect(screen.getByText("25 max")).toBeInTheDocument();
		expect(screen.getByLabelText("Connected accounts usage")).toHaveAttribute("aria-valuenow", "48");
		expect(screen.getByText("Team members")).toBeInTheDocument();
		expect(screen.getByText("unlimited")).toBeInTheDocument();
	});
});
