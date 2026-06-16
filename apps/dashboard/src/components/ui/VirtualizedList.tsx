import React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@/lib/utils";

export interface VirtualizedListProps<TItem> {
	items: TItem[];
	estimateSize: number;
	height?: number | string | undefined;
	overscan?: number | undefined;
	getItemKey?: ((item: TItem, index: number) => React.Key) | undefined;
	renderItem: (item: TItem, index: number) => React.ReactNode;
	empty?: React.ReactNode | undefined;
	ariaLabel?: string | undefined;
	className?: string | undefined;
	contentClassName?: string | undefined;
}

export function VirtualizedList<TItem>({
	items,
	estimateSize,
	height = 420,
	overscan = 8,
	getItemKey,
	renderItem,
	empty,
	ariaLabel,
	className,
	contentClassName,
}: VirtualizedListProps<TItem>) {
	const parentRef = React.useRef<HTMLDivElement>(null);
	const numericHeight = typeof height === "number" ? height : 420;
	const virtualizer = useVirtualizer({
		count: items.length,
		getScrollElement: () => parentRef.current,
		estimateSize: () => estimateSize,
		overscan,
		initialRect: {
			width: 320,
			height: numericHeight,
		},
		...(getItemKey
			? {
					getItemKey: (index: number) => {
						const item = items[index];
						return item ? getItemKey(item, index) : index;
					},
				}
			: {}),
	});
	const virtualItems = virtualizer.getVirtualItems();
	const initialVisibleCount = Math.min(
		items.length,
		Math.ceil(numericHeight / estimateSize) + overscan,
	);
	const rows =
		virtualItems.length > 0
			? virtualItems
			: Array.from({ length: initialVisibleCount }, (_, index) => ({
					index,
					key: getItemKey?.(items[index] as TItem, index) ?? index,
					start: index * estimateSize,
				}));

	if (items.length === 0 && empty) {
		return <>{empty}</>;
	}

	return (
		<div
			ref={parentRef}
			role="list"
			aria-label={ariaLabel}
			className={cn(
				"virtualized-list min-w-0 overflow-auto rounded-xl border border-border bg-card",
				className,
			)}
			style={{ height }}
		>
			<div
				className={cn("relative min-w-0", contentClassName)}
				style={{ height: virtualizer.getTotalSize() }}
			>
				{rows.map((virtualRow) => {
					const item = items[virtualRow.index];
					if (!item) {
						return null;
					}
					return (
						<div
							key={virtualRow.key}
							role="listitem"
							data-index={virtualRow.index}
							ref={
								virtualItems.length > 0 ? virtualizer.measureElement : undefined
							}
							className="absolute left-0 top-0 w-full min-w-0"
							style={{
								transform: `translateY(${virtualRow.start}px)`,
							}}
						>
							{renderItem(item, virtualRow.index)}
						</div>
					);
				})}
			</div>
		</div>
	);
}
