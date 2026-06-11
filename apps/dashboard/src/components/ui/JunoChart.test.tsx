import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
	JunoBarChart,
	JunoChartContainer,
	JunoChartTooltip,
	JunoComparisonBarChart,
	JunoDeltaBarChart,
	JunoShareBarChart,
	JunoStackedAreaChart,
} from "./JunoChart";

describe("JunoChart", () => {
	it("renders an accessible responsive chart container", () => {
		render(
			<JunoChartContainer ariaLabel="Reach source mix" variant="source-mix">
				<div>chart body</div>
			</JunoChartContainer>,
		);

		const chart = screen.getByRole("img", { name: "Reach source mix" });
		expect(chart).toHaveClass("juno-chart-container");
		expect(chart).toHaveClass("min-h-[220px]");
		expect(chart).toHaveAttribute("data-chart-variant", "source-mix");
		expect(chart).toHaveAttribute("data-chart-ready", "false");
		expect(chart).toHaveStyle({
			height: "240px",
		});
	});

	it("renders themed tooltip rows", () => {
		render(
			<JunoChartTooltip
				active
				label="Jun 2"
				payload={[
					{
						name: "Home",
						value: 42.5,
						color: "var(--color-chart-1)",
						payload: {},
					},
				]}
			/>,
		);

		expect(screen.getByText("Jun 2")).toBeInTheDocument();
		expect(screen.getByText("Home")).toBeInTheDocument();
		expect(screen.getByText("42.5%")).toBeInTheDocument();
		expect(screen.getByText("Jun 2").closest(".juno-chart-tooltip")).toBeInTheDocument();
	});

	it("renders a routine bar chart through the Juno adapter", () => {
		render(
			<JunoBarChart
				ariaLabel="Daily reach"
				data={[
					{ label: "06-01", value: 1200 },
					{ label: "06-02", value: 1800 },
				]}
				valueLabel="Reach"
			/>,
		);

		const chart = screen.getByRole("img", { name: "Daily reach" });
		expect(chart).toHaveClass("juno-chart-container");
		expect(chart).toHaveAttribute("data-chart-variant", "routine-bar");
	});

	it("renders a source-mix stacked area chart through the Juno adapter", () => {
		render(
			<JunoStackedAreaChart
				ariaLabel="Source mix"
				data={[
					{ date: "2026-06-01", home: 70, search: 30 },
					{ date: "2026-06-02", home: 60, search: 40 },
				]}
				series={[
					{ key: "home", label: "Home", color: "var(--color-chart-1)" },
					{ key: "search", label: "Search", color: "var(--color-chart-2)" },
				]}
				xKey="date"
			/>,
		);

		const chart = screen.getByRole("img", { name: "Source mix" });
		expect(chart).toHaveClass("juno-chart-container");
		expect(chart).toHaveAttribute("data-chart-variant", "source-mix");
	});

	it("renders a current-vs-prior comparison chart through the Juno adapter", () => {
		render(
			<JunoComparisonBarChart
				ariaLabel="Format mix"
				data={[
					{ label: "Reels", current: 3200, previous: 1800 },
					{ label: "Stories", current: 900, previous: 1100 },
				]}
			/>,
		);

		const chart = screen.getByRole("img", { name: "Format mix" });
		expect(chart).toHaveClass("juno-chart-container");
		expect(chart).toHaveAttribute("data-chart-variant", "routine-bar");
	});

	it("renders a delta bar chart through the Juno adapter", () => {
		render(
			<JunoDeltaBarChart
				ariaLabel="Follower flow"
				data={[
					{ label: "1", gain: 12, loss: -3 },
					{ label: "2", gain: 7, loss: -5 },
				]}
			/>,
		);

		const chart = screen.getByRole("img", { name: "Follower flow" });
		expect(chart).toHaveAttribute("data-chart-variant", "routine-bar");
	});

	it("renders a percent share bar chart through the Juno adapter", () => {
		render(
			<JunoShareBarChart
				ariaLabel="Audience split"
				data={[
					{ label: "Followers", pct: 48, color: "var(--color-chart-1)" },
					{ label: "Non-followers", pct: 52, color: "var(--color-chart-2)" },
				]}
			/>,
		);

		const chart = screen.getByRole("img", { name: "Audience split" });
		expect(chart).toHaveAttribute("data-chart-variant", "routine-bar");
	});
});
