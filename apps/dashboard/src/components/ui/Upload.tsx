import type React from "react";
import {
	CheckCircle2,
	FileUp,
	Loader2,
	UploadCloud,
	XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Progress } from "@/components/ui/Progress";
import { Separator } from "@/components/ui/Separator";
import { cn } from "@/lib/utils";

export type UploadStatus =
	| "queued"
	| "uploading"
	| "ready"
	| "saving"
	| "done"
	| "completed"
	| "error";

export interface UploadStatusItem {
	id: string;
	name: React.ReactNode;
	description?: React.ReactNode | undefined;
	status: UploadStatus;
	progress?: number | undefined;
	preview?: React.ReactNode | undefined;
	meta?: React.ReactNode | undefined;
	actions?: React.ReactNode | undefined;
	selectedControl?: React.ReactNode | undefined;
	tone?: "default" | "primary" | "success" | "warning" | "danger" | undefined;
}

export interface UploadZoneProps
	extends Omit<
		React.ComponentProps<typeof Button>,
		"children" | "onDrop" | "title"
	> {
	title?: React.ReactNode | undefined;
	description?: React.ReactNode | undefined;
	helper?: React.ReactNode | undefined;
	actionLabel?: React.ReactNode | undefined;
	icon?: React.ReactNode | undefined;
	dragActive?: boolean | undefined;
	accept?: string | undefined;
	multiple?: boolean | undefined;
	inputRef?: React.RefObject<HTMLInputElement | null> | undefined;
	onFilesSelected?: ((files: FileList | null) => void) | undefined;
	onDropFiles?: ((files: FileList) => void) | undefined;
}

const STATUS_LABEL: Record<UploadStatus, string> = {
	queued: "Queued",
	uploading: "Uploading",
	ready: "Ready",
	saving: "Saving",
	done: "Done",
	completed: "Complete",
	error: "Error",
};

const STATUS_TONE: Record<
	UploadStatus,
	NonNullable<UploadStatusItem["tone"]>
> = {
	queued: "default",
	uploading: "primary",
	ready: "default",
	saving: "primary",
	done: "success",
	completed: "success",
	error: "danger",
};

function UploadStatusIcon({ status }: { status: UploadStatus }) {
	if (status === "error") {
		return <XCircle data-icon="stacked" aria-hidden="true" />;
	}
	if (status === "done" || status === "completed") {
		return <CheckCircle2 data-icon="stacked" aria-hidden="true" />;
	}
	if (status === "uploading" || status === "saving") {
		return <Loader2 data-icon="stacked" aria-hidden="true" className="animate-spin" />;
	}
	return <FileUp data-icon="stacked" aria-hidden="true" />;
}

function statusBadgeTone(
	tone: NonNullable<UploadStatusItem["tone"]>,
): React.ComponentProps<typeof Badge>["tone"] {
	if (tone === "danger") return "danger";
	if (tone === "success") return "secondary";
	if (tone === "primary") return "oxblood";
	if (tone === "warning") return "outline";
	return "outline";
}

export function UploadZone({
	title = "Drop files here or choose files",
	description = "Files stay attached to the current workflow.",
	helper,
	actionLabel = "Choose files",
	icon,
	dragActive = false,
	accept,
	multiple,
	inputRef,
	onFilesSelected,
	onDropFiles,
	disabled,
	className,
	onClick,
	...props
}: UploadZoneProps) {
	const openPicker = (event: React.MouseEvent<HTMLButtonElement>) => {
		onClick?.(event);
		if (event.defaultPrevented || disabled) return;
		inputRef?.current?.click();
	};

	return (
		<>
			<Button
				type="button"
				variant="outline"
				disabled={disabled}
				onClick={openPicker}
				onDrop={(event) => {
					event.preventDefault();
					if (disabled) return;
					onDropFiles?.(event.dataTransfer.files);
				}}
				onDragOver={(event) => {
					event.preventDefault();
					if (!disabled) event.dataTransfer.dropEffect = "copy";
				}}
				className={cn(
					"upload-zone h-auto min-h-[11rem] w-full min-w-0 flex-col gap-3 rounded-xl border-dashed bg-muted/35 px-5 py-6 text-center shadow-none hover:bg-muted/50 disabled:cursor-wait md:min-h-[13.5rem]",
					dragActive &&
						"border-primary bg-[color-mix(in_srgb,var(--color-primary)_7%,var(--color-card))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_22%,transparent)]",
					className,
				)}
				{...props}
			>
				<span className="flex size-11 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground shadow-xs">
					{icon ?? <UploadCloud data-icon="stacked" aria-hidden="true" />}
				</span>
				<span className="flex min-w-0 max-w-full flex-col items-center gap-1.5">
					<span className="text-sm font-semibold text-foreground">{title}</span>
					<span className="w-full max-w-full text-balance text-xs font-normal leading-relaxed text-muted-foreground sm:max-w-md">
						{description}
					</span>
					{helper ? (
						<span className="text-xs font-normal text-muted-foreground">
							{helper}
						</span>
					) : null}
				</span>
				<span className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground">
					{actionLabel}
				</span>
			</Button>
			{inputRef || onFilesSelected ? (
				<input
					ref={inputRef}
					type="file"
					accept={accept}
					multiple={multiple}
					className="hidden"
					onChange={(event) => onFilesSelected?.(event.target.files)}
				/>
			) : null}
		</>
	);
}

export function UploadStatusList({
	items,
	empty,
	activeTitle = "Active uploads",
	completedTitle = "Completed",
	showSections = true,
	className,
}: {
	items: UploadStatusItem[];
	empty?: React.ReactNode | undefined;
	activeTitle?: React.ReactNode | undefined;
	completedTitle?: React.ReactNode | undefined;
	showSections?: boolean | undefined;
	className?: string | undefined;
}) {
	const completed = items.filter(
		(item) => item.status === "done" || item.status === "completed",
	);
	const active = showSections
		? items.filter((item) => !completed.some((done) => done.id === item.id))
		: items;
	const groups = showSections
		? [
				{ id: "active", title: activeTitle, items: active },
				{ id: "completed", title: completedTitle, items: completed },
			].filter((group) => group.items.length > 0)
		: [{ id: "all", title: null, items }];

	if (items.length === 0) {
		return empty ? (
			<div className={cn("upload-status-list", className)}>{empty}</div>
		) : null;
	}

	return (
		<div
			className={cn("upload-status-list grid min-w-0 gap-3", className)}
			role="status"
			aria-live="polite"
		>
			{groups.map((group, groupIndex) => (
				<div key={group.id} className="grid min-w-0 gap-2">
					{group.title ? (
						<div className="flex items-center justify-between gap-3">
							<div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
								{group.title}
							</div>
							<Badge tone="outline">{group.items.length}</Badge>
						</div>
					) : null}
					<div className="grid min-w-0 gap-2">
						{group.items.map((item) => (
							<UploadStatusRow key={item.id} item={item} />
						))}
					</div>
					{groupIndex < groups.length - 1 ? <Separator /> : null}
				</div>
			))}
		</div>
	);
}

function UploadStatusRow({ item }: { item: UploadStatusItem }) {
	const tone = item.tone ?? STATUS_TONE[item.status];
	const progress =
		item.progress ??
		(item.status === "done" || item.status === "completed" ? 100 : undefined);
	return (
		<div
			className={cn(
				"upload-status-row grid min-w-0 gap-3 rounded-xl border bg-card p-3 shadow-xs",
				"sm:grid-cols-[auto_minmax(0,1fr)_auto]",
				tone === "danger"
					? "border-[color-mix(in_srgb,var(--color-danger)_32%,var(--color-border))]"
					: tone === "primary"
						? "border-[color-mix(in_srgb,var(--color-primary)_28%,var(--color-border))]"
						: "border-border",
			)}
		>
			<div className="flex min-w-0 items-start gap-3 sm:contents">
				<div className="flex min-w-0 items-start gap-2.5">
					{item.selectedControl ? (
						<div className="shrink-0 pt-1">{item.selectedControl}</div>
					) : null}
					<div className="shrink-0">
						{item.preview ?? (
							<span className="flex size-10 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
								<UploadStatusIcon status={item.status} />
							</span>
						)}
					</div>
				</div>
				<div className="min-w-0 flex-1 sm:min-w-0">
					<div className="flex min-w-0 flex-wrap items-center gap-2">
						<div className="min-w-0 truncate text-sm font-semibold text-foreground">
							{item.name}
						</div>
						<Badge tone={statusBadgeTone(tone)}>{STATUS_LABEL[item.status]}</Badge>
					</div>
					{item.description ? (
						<div className="mt-1 text-xs leading-snug text-muted-foreground">
							{item.description}
						</div>
					) : null}
					{progress !== undefined ? (
						<div className="mt-2 grid gap-1.5">
							<Progress
								value={progress}
								aria-label={`${String(item.name)} upload progress`}
								tone={tone === "danger" ? "critical" : tone === "warning" ? "warn" : "default"}
							/>
							<div className="text-right text-[0.6875rem] tabular-nums text-muted-foreground">
								{Math.round(progress)}%
							</div>
						</div>
					) : null}
					{item.meta ? <div className="mt-2 min-w-0">{item.meta}</div> : null}
				</div>
			</div>
			{item.actions ? (
				<div className="flex min-w-0 flex-wrap items-center gap-1.5 sm:justify-end">
					{item.actions}
				</div>
			) : null}
		</div>
	);
}
