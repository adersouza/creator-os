import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "./DataTable";

interface Row {
	id: string;
	name: string;
	score: number;
}

const rows: Row[] = [
	{ id: "a", name: "Beta", score: 2 },
	{ id: "b", name: "Alpha", score: 9 },
];

const columns: ColumnDef<Row>[] = [
	{
		accessorKey: "name",
		header: "Name",
		cell: ({ row }) => row.original.name,
	},
	{
		accessorKey: "score",
		header: "Score",
		cell: ({ row }) => row.original.score,
	},
];

describe("DataTable", () => {
	it("sorts sortable columns and renders row cells", async () => {
		const user = userEvent.setup();
		render(<DataTable data={rows} columns={columns} ariaLabel="Scores" />);

		const rowGroups = screen.getAllByRole("rowgroup");
		expect(rowGroups).toHaveLength(2);
		const body = rowGroups[1];
		if (!body) throw new Error("Expected table body rowgroup");
		const firstRow = within(body).getAllByRole("row")[0];
		if (!firstRow) throw new Error("Expected first row");
		expect(firstRow).toHaveTextContent("Beta");

		await user.click(screen.getByRole("button", { name: "Name" }));
		const sortedFirstRow = within(body).getAllByRole("row")[0];
		if (!sortedFirstRow) throw new Error("Expected sorted first row");
		expect(sortedFirstRow).toHaveTextContent("Alpha");
	});

	it("calls onRowClick with the original row", async () => {
		const user = userEvent.setup();
		const onRowClick = vi.fn();
		render(
			<DataTable
				data={rows}
				columns={columns}
				ariaLabel="Scores"
				onRowClick={onRowClick}
			/>,
		);

		await user.click(screen.getByRole("button", { name: /Beta/ }));
		expect(onRowClick).toHaveBeenCalledWith(rows[0]);
	});

	it("renders a provided empty state", () => {
		render(
			<DataTable
				data={[]}
				columns={columns}
				ariaLabel="Scores"
				empty={<div>No scores yet</div>}
			/>,
		);

		expect(screen.getByText("No scores yet")).toBeInTheDocument();
	});
});
