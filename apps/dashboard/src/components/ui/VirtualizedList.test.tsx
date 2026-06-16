import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VirtualizedList } from "@/components/ui/VirtualizedList";

describe("VirtualizedList", () => {
	it("renders visible rows inside a stable scroll container", () => {
		const rows = Array.from({ length: 100 }, (_, index) => ({
			id: `row-${index}`,
			label: `Row ${index}`,
		}));

		render(
			<VirtualizedList
				items={rows}
				estimateSize={36}
				height={180}
				ariaLabel="Virtualized rows"
				getItemKey={(row) => row.id}
				renderItem={(row) => (
					<div className="px-3 py-2" data-testid="virtual-row">
						{row.label}
					</div>
				)}
			/>,
		);

		expect(screen.getByRole("list", { name: "Virtualized rows" })).toHaveStyle({
			height: "180px",
		});
		expect(screen.getByText("Row 0")).toBeInTheDocument();
		expect(screen.getAllByTestId("virtual-row").length).toBeLessThan(rows.length);
	});

	it("renders the supplied empty state without creating an empty scroller", () => {
		render(
			<VirtualizedList
				items={[]}
				estimateSize={40}
				empty={<p>No rows available</p>}
				renderItem={() => null}
			/>,
		);

		expect(screen.getByText("No rows available")).toBeInTheDocument();
		expect(screen.queryByRole("list")).not.toBeInTheDocument();
	});
});
