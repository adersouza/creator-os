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
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/shadcn/table";
import { Button } from "@/components/ui/Button";
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
	toolbar?: ReactNode | undefined;
	footer?: ReactNode | undefined;
	getRowHref?: ((row: TData) => string | undefined) | undefined;
	onRowClick?: ((row: TData) => void) | undefined;
	isRowInteractive?: ((row: TData) => boolean) | undefined;
	className?: string | undefined;
	frameClassName?: string | undefined;
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
	toolbar,
	footer,
	getRowHref,
	onRowClick,
	isRowInteractive,
	className,
	frameClassName,
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
		<div className={cn("data-table-shell grid min-w-0 max-w-full gap-3", className)}>
			{toolbar ? (
				<div className="data-table-toolbar flex min-w-0 max-w-full flex-col gap-3 overflow-x-auto overflow-y-hidden rounded-xl border border-border bg-card p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
					{toolbar}
				</div>
			) : null}
			<div
				className={cn(
					"analytics-table-frame min-w-0 max-w-full overflow-x-auto overflow-y-hidden rounded-xl border border-border bg-card shadow-sm",
					frameClassName,
				)}
			>
				<Table
					aria-label={ariaLabel}
					className={cn("analytics-fit-table w-full text-[0.8125rem]", tableClassName)}
				>
					<TableHeader>
						{table.getHeaderGroups().map((headerGroup) => (
							<TableRow
								key={headerGroup.id}
								className={cn(
									"border-b border-border bg-muted/45 text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground hover:bg-muted/45",
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
										<TableHead
											key={header.id}
											colSpan={header.colSpan}
											className={cn("h-9 px-3 py-2 text-left font-medium", meta?.headerClassName)}
											aria-sort={
												sortDirection === "asc"
													? "ascending"
													: sortDirection === "desc"
														? "descending"
														: undefined
											}
										>
											{header.isPlaceholder ? null : canSort ? (
												<Button
													type="button"
													variant="ghost"
													size="sm"
													onClick={header.column.getToggleSortingHandler()}
													className="h-8 justify-start px-1 text-inherit hover:text-foreground"
												>
													{flexRender(
														header.column.columnDef.header,
														header.getContext(),
													)}
													<SortIcon direction={sortDirection} />
												</Button>
											) : (
												flexRender(header.column.columnDef.header, header.getContext())
											)}
										</TableHead>
									);
								})}
							</TableRow>
						))}
					</TableHeader>
					<TableBody>
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
					</TableBody>
				</Table>
			</div>
			{footer ? (
				<div className="data-table-footer flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-card px-3 py-2.5 text-sm text-muted-foreground shadow-sm sm:flex-row sm:items-center sm:justify-between sm:gap-3">
					{footer}
				</div>
			) : null}
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
		<TableRow
			role={interactive ? (href ? "link" : "button") : undefined}
			tabIndex={interactive ? 0 : undefined}
			onClick={interactive ? activate : undefined}
			onKeyDown={onKeyDown}
			className={cn(
				"border-t border-border/70 bg-card transition-colors",
				interactive &&
					"cursor-pointer hover:bg-muted/45 focus-visible:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-ring-oxblood)]",
				className,
			)}
		>
			{row.getVisibleCells().map((cell) => (
				<TableCell
					key={cell.id}
					className={cn(
						"px-3 py-2.5 align-middle",
						(cell.column.columnDef.meta as DataTableColumnMeta | undefined)
							?.cellClassName,
						cellClassName,
					)}
				>
					{flexRender(cell.column.columnDef.cell, cell.getContext())}
				</TableCell>
			))}
		</TableRow>
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
