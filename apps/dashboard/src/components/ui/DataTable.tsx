import type { KeyboardEvent, ReactNode } from "react";
import {
	flexRender,
	getCoreRowModel,
	getSortedRowModel,
	type ColumnDef,
	type Row,
	type SortingState,
	useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

type DataTableColumnMeta = {
	headerClassName?: string | undefined;
	cellClassName?: string | undefined;
};

export interface DataTableProps<TData> {
	data: TData[];
	columns: ColumnDef<TData>[];
	ariaLabel: string;
	empty?: ReactNode | undefined;
	getRowHref?: ((row: TData) => string | undefined) | undefined;
	onRowClick?: ((row: TData) => void) | undefined;
	isRowInteractive?: ((row: TData) => boolean) | undefined;
	className?: string | undefined;
	tableClassName?: string | undefined;
	headerRowClassName?: string | undefined;
	rowClassName?: string | ((row: TData) => string | undefined) | undefined;
	cellClassName?: string | undefined;
}

export function DataTable<TData>({
	data,
	columns,
	ariaLabel,
	empty,
	getRowHref,
	onRowClick,
	isRowInteractive,
	className,
	tableClassName,
	headerRowClassName,
	rowClassName,
	cellClassName,
}: DataTableProps<TData>) {
	const [sorting, setSorting] = useState<SortingState>([]);
	const table = useReactTable({
		data,
		columns,
		state: { sorting },
		onSortingChange: setSorting,
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
	});

	if (data.length === 0 && empty) {
		return <>{empty}</>;
	}

	return (
		<div className={cn("analytics-table-frame", className)}>
			<table
				aria-label={ariaLabel}
				className={cn("analytics-fit-table w-full text-[0.8125rem]", tableClassName)}
			>
				<thead>
					{table.getHeaderGroups().map((headerGroup) => (
						<tr
							key={headerGroup.id}
							className={cn(
								"text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground",
								headerRowClassName,
							)}
						>
							{headerGroup.headers.map((header) => {
								const canSort = header.column.getCanSort();
								const sortDirection = header.column.getIsSorted();
								const meta = header.column.columnDef.meta as
									| DataTableColumnMeta
									| undefined;
								return (
									<th
										key={header.id}
										colSpan={header.colSpan}
										className={cn("px-3 py-2 text-left font-medium", meta?.headerClassName)}
										aria-sort={
											sortDirection === "asc"
												? "ascending"
												: sortDirection === "desc"
													? "descending"
													: undefined
										}
									>
										{header.isPlaceholder ? null : canSort ? (
											<button
												type="button"
												onClick={header.column.getToggleSortingHandler()}
												className="inline-flex min-h-8 items-center gap-1 rounded-md px-1 text-inherit transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
											>
												{flexRender(
													header.column.columnDef.header,
													header.getContext(),
												)}
												<SortIcon direction={sortDirection} />
											</button>
										) : (
											flexRender(header.column.columnDef.header, header.getContext())
										)}
									</th>
								);
							})}
						</tr>
					))}
				</thead>
				<tbody>
					{table.getRowModel().rows.map((row) => (
						<DataTableRow
							key={row.id}
							row={row}
							href={getRowHref?.(row.original)}
							onRowClick={onRowClick}
							isInteractive={isRowInteractive?.(row.original)}
							rowClassName={rowClassName}
							cellClassName={cellClassName}
						/>
					))}
				</tbody>
			</table>
		</div>
	);
}

function DataTableRow<TData>({
	row,
	href,
	onRowClick,
	isInteractive,
	rowClassName,
	cellClassName,
}: {
	row: Row<TData>;
	href?: string | undefined;
	onRowClick?: ((row: TData) => void) | undefined;
	isInteractive?: boolean | undefined;
	rowClassName?: string | ((row: TData) => string | undefined) | undefined;
	cellClassName?: string | undefined;
}) {
	const interactive = isInteractive ?? (!!href || !!onRowClick);
	const className =
		typeof rowClassName === "function" ? rowClassName(row.original) : rowClassName;
	const activate = () => {
		if (onRowClick) {
			onRowClick(row.original);
			return;
		}
		if (href) window.location.assign(href);
	};
	const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
		if (!interactive) return;
		if (event.key === "Enter" || event.key === " ") {
			event.preventDefault();
			activate();
		}
	};

	return (
		<tr
			role={interactive ? (href ? "link" : "button") : undefined}
			tabIndex={interactive ? 0 : undefined}
			onClick={interactive ? activate : undefined}
			onKeyDown={onKeyDown}
			className={cn(
				"border-t border-border/70 transition-colors",
				interactive &&
					"cursor-pointer hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-ring-oxblood)]",
				className,
			)}
		>
			{row.getVisibleCells().map((cell) => (
				<td
					key={cell.id}
					className={cn(
						"px-3 py-2 align-middle",
						(cell.column.columnDef.meta as DataTableColumnMeta | undefined)
							?.cellClassName,
						cellClassName,
					)}
				>
					{flexRender(cell.column.columnDef.cell, cell.getContext())}
				</td>
			))}
		</tr>
	);
}

function SortIcon({
	direction,
}: {
	direction: false | "asc" | "desc";
}) {
	const Icon =
		direction === "asc"
			? ArrowUp
			: direction === "desc"
				? ArrowDown
				: ChevronsUpDown;

	return (
		<Icon
			data-icon="inline-end"
			aria-hidden="true"
			className={cn(!direction && "opacity-45")}
		/>
	);
}
