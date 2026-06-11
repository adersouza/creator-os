import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BrandLogo, IntegrationLogo } from "./BrandLogo";
import { Button } from "./Button";
import { MatrixLoader } from "./MatrixLoader";
import { NovaCard, NovaStat } from "./NovaPrimitives";

describe("visual foundation adapters", () => {
	it("renders accessible local brand logos", () => {
		render(
			<div>
				<BrandLogo name="instagram" />
				<IntegrationLogo name="github" label="GitHub integration" />
			</div>,
		);

		expect(screen.getByRole("img", { name: "Instagram" })).toBeInTheDocument();
		expect(screen.getByRole("img", { name: "GitHub integration" })).toBeInTheDocument();
	});

	it("renders a status-aware matrix loader", () => {
		render(<MatrixLoader label="Refreshing dashboard" tone="muted" size="sm" />);

		expect(screen.getByRole("status", { name: "Refreshing dashboard" })).toBeInTheDocument();
	});

	it("renders stat values, progress, trends, and actions", () => {
		const onClick = vi.fn();
		render(
			<NovaStat
				label="Success rate"
				value="99.4%"
				icon={<span aria-hidden="true">S</span>}
				status="Healthy"
				trend={{ direction: "up", label: "+2.1%" }}
				progress={{ value: 99.4, label: "Success progress" }}
				description="24h processing window"
				action={
					<Button type="button" onClick={onClick}>
						Open reliability
					</Button>
				}
			/>,
		);

		expect(screen.getByText("Success rate")).toBeInTheDocument();
		expect(screen.getByText("99.4%")).toBeInTheDocument();
		expect(screen.getByText("Healthy")).toBeInTheDocument();
		expect(screen.getByText("+2.1%")).toBeInTheDocument();
		expect(screen.getByText("24h processing window")).toBeInTheDocument();
		expect(screen.getByLabelText("Success progress")).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /open reliability/i }));
		expect(onClick).toHaveBeenCalledOnce();
	});

	it("composes dashboard cards with header, action, body, and footer slots", () => {
		render(
			<NovaCard
				eyebrow="Ops"
				title="Queue health"
				description="Latest worker status"
				action={<button type="button">Refresh</button>}
				footer={<span>Updated just now</span>}
			>
				<span>QStash clear</span>
			</NovaCard>,
		);

		expect(screen.getByText("Ops")).toBeInTheDocument();
		expect(screen.getByText("Queue health")).toBeInTheDocument();
		expect(screen.getByText("Latest worker status")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
		expect(screen.getByText("QStash clear")).toBeInTheDocument();
		expect(screen.getByText("Updated just now")).toBeInTheDocument();
	});

	it("allows route shells to preserve content layout classes", () => {
		const { container } = render(
			<NovaCard contentClassName="custom-content-layout">
				<span>Evidence body</span>
			</NovaCard>,
		);

		expect(container.querySelector(".custom-content-layout")).toHaveClass(
			"custom-content-layout",
		);
	});
});
