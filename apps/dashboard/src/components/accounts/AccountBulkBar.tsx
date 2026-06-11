import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
	PopoverContent,
	PopoverRoot,
	PopoverTrigger,
} from "@/components/ui/Popover";
import { Separator } from "@/components/ui/Separator";

interface AccountBulkBarProps {
	count: number;
	tokenExpiringCount: number;
	taggableCount: number;
	onClear: () => void;
	onBulkPause: () => void;
	onBulkReschedule: () => void;
	onBulkMoveGroup: () => void;
	onBulkRemove: () => void;
	onBulkSync: () => void;
	onBulkHealthCheck: () => void;
	onFixTokens: () => void;
	onAddTag: (tag: string) => void;
}

export function AccountBulkBar({
	count,
	tokenExpiringCount,
	taggableCount,
	onClear,
	onBulkPause,
	onBulkReschedule,
	onBulkMoveGroup,
	onBulkRemove,
	onBulkSync,
	onBulkHealthCheck,
	onFixTokens,
	onAddTag,
}: AccountBulkBarProps) {
	const [tagOpen, setTagOpen] = useState(false);
	const [tag, setTag] = useState("");

	return (
		<div
			className="fixed bottom-6 left-1/2 z-[120] flex min-h-12 w-[min(1040px,calc(100vw-32px))] -translate-x-1/2 items-center justify-center gap-1 rounded-xl border border-border bg-card px-3 py-2 text-foreground shadow-lg"
		>
			<div className="shrink-0 px-3 text-[0.8125rem] font-medium text-foreground tabular-nums">
				<span className="text-muted-foreground">Selected</span>{" "}
				<span className="ml-0.5">{count}</span>
			</div>
			<Separator orientation="vertical" className="h-6" />
			<BulkButton label="Pause" onClick={onBulkPause} />
			<BulkButton label="Reschedule" onClick={onBulkReschedule} />
			<BulkButton label="Move group" onClick={onBulkMoveGroup} />
			<BulkButton label="Bulk sync" onClick={onBulkSync} />
			<BulkButton label="Health check" onClick={onBulkHealthCheck} />
			<BulkButton
				label={`Fix tokens${tokenExpiringCount > 0 ? ` (${tokenExpiringCount})` : ""}`}
				onClick={onFixTokens}
				disabled={tokenExpiringCount === 0}
				title={
					tokenExpiringCount === 0
						? "No selected accounts need token repair"
						: undefined
				}
			/>
			<PopoverRoot open={tagOpen} onOpenChange={setTagOpen}>
				<PopoverTrigger asChild>
					<Button
						type="button"
						variant="ghost"
						size="sm"
						disabled={taggableCount === 0}
						title={
							taggableCount === 0
								? "Tags are only available for selected Threads accounts"
								: undefined
						}
						className="shrink-0 whitespace-nowrap disabled:opacity-45"
					>
						{taggableCount > 0 && taggableCount < count
							? `Add tag (${taggableCount})`
							: "Add tag"}
					</Button>
				</PopoverTrigger>
				<PopoverContent
					side="top"
					align="center"
					className="w-56 rounded-md border border-border bg-popover p-2 shadow-lg"
				>
					<form
						onSubmit={(event) => {
							event.preventDefault();
							const next = tag.trim().replace(/^#/, "");
							if (!next) return;
							onAddTag(next);
							setTag("");
							setTagOpen(false);
						}}
					>
						<Input
							value={tag}
							onChange={(event) => setTag(event.target.value)}
							placeholder="Tag name"
							sizeVariant="sm"
						/>
						<Button type="submit" size="sm" className="mt-2 w-full">
							Add tag
						</Button>
					</form>
				</PopoverContent>
			</PopoverRoot>
			<BulkButton label="Remove" destructive onClick={onBulkRemove} />
			<Separator orientation="vertical" className="h-6" />
			<Button type="button" onClick={onClear} variant="ghost" size="sm">
				Clear
			</Button>
		</div>
	);
}

function BulkButton({
	label,
	destructive = false,
	onClick,
	disabled = false,
	title,
}: {
	label: string;
	destructive?: boolean | undefined;
	onClick?: () => void;
	disabled?: boolean | undefined;
	title?: string | undefined;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			disabled={disabled}
			title={title}
			variant={destructive ? "danger" : "ghost"}
			size="sm"
			className="shrink-0 whitespace-nowrap disabled:opacity-45"
			style={{ color: destructive ? "var(--color-danger)" : undefined }}
		>
			{label}
		</Button>
	);
}
