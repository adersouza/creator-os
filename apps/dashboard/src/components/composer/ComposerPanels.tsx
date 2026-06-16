import { type ReactNode, useState } from "react";
import {
	BellRing,
	CheckCircle2,
	Command as CommandIcon,
	Crop,
	History,
	RotateCcw,
	Smartphone,
	UploadCloud,
	Wand2,
} from "lucide-react";
import type { InspirationIdea } from "@/services/inspirationService";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import {
	CommandDialog,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
	CommandShortcut,
} from "@/components/ui/Command";
import { FormSection } from "@/components/ui/FormSection";
import { Input } from "@/components/ui/Input";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import type { IGPostType } from "@/components/composer/PreviewSection";

type PhoneSetupChecks = {
	openedOnPhone: boolean;
	homeScreen: boolean;
	instagramReady: boolean;
};

type PushHealthState =
	| "checking"
	| "unsupported"
	| "denied"
	| "permission-needed"
	| "not-subscribed"
	| "subscribed"
	| "unavailable";

type MediaOptimizationSuggestion = {
	id: string;
	label: string;
	detail: string;
	actionLabel?: string | undefined;
	action?: (() => void) | undefined;
};

type ComposerActivity = {
	id: string;
	label: string;
	detail: string;
	at: number;
	undo?: (() => void) | undefined;
};

type BulkUploadQueueItem = {
	id: string;
	file: File;
	previewUrl: string;
	name: string;
	kind: "image" | "video";
	caption: string;
	selected: boolean;
	postType: IGPostType;
	publishMode: "auto" | "notify";
	scheduleDate: string;
	scheduleTime: string;
	status: "queued" | "uploading" | "ready" | "saving" | "done" | "error";
	mediaUrl?: string | undefined;
	error?: string | undefined;
	warnings: string[];
};

function pushSetupState(state: PushHealthState): string {
	if (state === "subscribed") return "subscribed";
	if (state === "permission-needed") return "permission_needed";
	if (state === "not-subscribed") return "not_subscribed";
	if (state === "denied") return "denied";
	if (state === "unsupported") return "unsupported";
	return "unknown";
}

export function SampleDraftPanel({
	hasAccounts,
	onUseSample,
	onPickAccount,
}: {
	hasAccounts: boolean;
	onUseSample: () => void;
	onPickAccount: () => void;
}) {
	return (
		<FormSection
			eyebrow="Starter draft"
			title="Start with a realistic Reel setup."
			description="Replace the copy and media when you are ready. This stays client-side until you save or schedule it."
			action={
				<Button type="button" onClick={onUseSample} size="sm">
					Use sample
				</Button>
			}
			contentClassName="p-4 pt-0"
		>
			<div className="rounded-md border border-border bg-muted/35 p-3 text-sm text-muted-foreground">
				Use a sample draft to quickly check account targeting, media validation,
				and preview states without publishing anything.
			</div>
			{hasAccounts ? (
				<div className="mt-3">
					<Button
						type="button"
						onClick={onPickAccount}
						variant="outline"
						size="sm"
					>
						Pick account
					</Button>
				</div>
			) : null}
		</FormSection>
	);
}

export function ComposerMobileButton({
	onClick,
	label,
	icon,
	highlighted,
}: {
	onClick: () => void;
	label: string;
	icon: ReactNode;
	highlighted?: boolean;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			variant={highlighted ? "secondary" : "ghost"}
			size="sm"
			className="h-11 min-w-0 flex-1 flex-col gap-0.5 px-2 text-[0.6875rem]"
		>
			{icon}
			<span className="max-w-full truncate">{label}</span>
		</Button>
	);
}

export function PhoneSetupPanel({
	pushHealth,
	pushHealthBusy,
	checks,
	onToggle,
	onEnablePush,
	onTestPush,
}: {
	pushHealth: PushHealthState;
	pushHealthBusy: boolean;
	checks: PhoneSetupChecks;
	onToggle: (key: keyof PhoneSetupChecks) => void;
	onEnablePush: () => void;
	onTestPush: () => void;
}) {
	const rows: Array<{
		key: keyof PhoneSetupChecks;
		label: string;
		detail: string;
	}> = [
		{
			key: "openedOnPhone",
			label: "Open Juno33 on iPhone",
			detail: "Use the same login as desktop.",
		},
		{
			key: "homeScreen",
			label: "Add to Home Screen",
			detail: "Required for reliable iOS PWA push.",
		},
		{
			key: "instagramReady",
			label: "Instagram logged in",
			detail: "The handoff opens the native Instagram app.",
		},
	];
	return (
		<FormSection
			eyebrow={
				<span className="inline-flex items-center gap-2">
					<Smartphone data-icon="inline-start" aria-hidden="true" />
					Phone setup
				</span>
			}
			title="Prepare native handoff."
			description="Confirm the phone workflow before scheduling Instagram-native posts."
			action={
				<Badge tone={pushHealth === "subscribed" ? "secondary" : "oxblood"}>
					{pushSetupState(pushHealth).replace(/_/g, " ")}
				</Badge>
			}
			contentClassName="p-4 pt-0"
			footer={
				<div className="flex w-full items-center gap-2">
					<Button
						type="button"
						onClick={onEnablePush}
						disabled={pushHealthBusy}
						variant="outline"
						size="sm"
						className="flex-1"
					>
						<BellRing data-icon="inline-start" aria-hidden="true" />
						{pushHealthBusy ? "Working..." : "Enable"}
					</Button>
					<Button
						type="button"
						onClick={onTestPush}
						disabled={pushHealthBusy}
						size="sm"
						className="flex-1"
					>
						Test push
					</Button>
				</div>
			}
		>
			<div className="flex flex-col gap-2">
				{rows.map((row) => (
					<Button
						key={row.key}
						type="button"
						variant="outline"
						onClick={() => onToggle(row.key)}
						className="h-auto w-full justify-start gap-2 px-3 py-2.5 text-left"
					>
						<span
							className={cn(
								"mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full border",
								checks[row.key]
									? "border-[color:var(--color-positive)] bg-[color:var(--color-positive)] text-white"
									: "border-border text-muted-foreground",
							)}
						>
							{checks[row.key] && (
								<CheckCircle2 className="size-3" aria-hidden="true" />
							)}
						</span>
						<span className="min-w-0">
							<span className="block text-[0.8125rem] font-medium text-foreground">
								{row.label}
							</span>
							<span className="mt-0.5 block text-[0.71875rem] leading-snug text-muted-foreground">
								{row.detail}
							</span>
						</span>
					</Button>
				))}
			</div>
		</FormSection>
	);
}

export function MediaOptimizationPanel({
	suggestions,
}: {
	suggestions: MediaOptimizationSuggestion[];
}) {
	return (
		<FormSection
			eyebrow={
				<span className="inline-flex items-center gap-2">
					<Crop data-icon="inline-start" aria-hidden="true" />
					Media optimization
				</span>
			}
			title="Keep media platform-ready."
			description="Review crop, length, and accessibility suggestions before publishing."
			contentClassName="p-4 pt-0"
		>
			<div className="flex flex-col gap-2">
				{suggestions.map((suggestion) => (
					<div
						key={suggestion.id}
						className="rounded-md border border-border bg-card px-3 py-2.5"
					>
						<div className="text-[0.8125rem] font-medium text-foreground">
							{suggestion.label}
						</div>
						<div className="mt-0.5 text-[0.71875rem] text-muted-foreground">
							{suggestion.detail}
						</div>
						{suggestion.action && suggestion.actionLabel && (
							<Button
								type="button"
								onClick={suggestion.action}
								variant="outline"
								size="sm"
								className="mt-2 h-7"
							>
								{suggestion.actionLabel}
							</Button>
						)}
					</div>
				))}
			</div>
		</FormSection>
	);
}

export function ActivityPanel({
	activity,
	open,
	onOpenChange,
}: {
	activity: ComposerActivity[];
	open: boolean;
	onOpenChange: (open: boolean) => void;
}) {
	const visible = open ? activity : activity.slice(0, 3);
	return (
		<FormSection
			eyebrow={
				<span className="inline-flex items-center gap-2">
					<History data-icon="inline-start" aria-hidden="true" />
					Activity
				</span>
			}
			title="Track draft changes."
			description="Recent edits and reversible actions for this Composer session."
			action={
				<Button
					type="button"
					onClick={() => onOpenChange(!open)}
					variant="outline"
					size="sm"
				>
					{open ? "Collapse" : "Open"}
				</Button>
			}
			contentClassName="p-4 pt-0"
		>
			{activity.length === 0 ? (
				<NovaEmpty
					className="min-h-24 p-4"
					icon={<History data-icon aria-hidden="true" />}
					title="No activity yet"
					description="Composer changes will appear here."
				/>
			) : (
				<div className="flex flex-col gap-2">
					{visible.map((entry) => (
						<div
							key={entry.id}
							className="rounded-md border border-border bg-card px-3 py-2.5"
						>
							<div className="flex items-start justify-between gap-2">
								<div className="min-w-0">
									<div className="text-[0.8125rem] font-medium text-foreground">
										{entry.label}
									</div>
									<div className="mt-0.5 text-[0.71875rem] text-muted-foreground">
										{entry.detail}
									</div>
								</div>
								{entry.undo && (
									<Button
										type="button"
										onClick={entry.undo}
										variant="ghost"
										size="sm"
										className="h-7 shrink-0 px-2 text-[0.71875rem]"
									>
										<RotateCcw data-icon="inline-start" aria-hidden="true" />
										Undo
									</Button>
								)}
							</div>
						</div>
					))}
				</div>
			)}
		</FormSection>
	);
}

interface ComposerCommand {
	id: string;
	label: string;
	detail: string;
	run: () => void;
}

export function ComposerCommandPalette({
	open,
	onOpenChange,
	commands,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	commands: ComposerCommand[];
}) {
	const [query, setQuery] = useState("");
	const filtered = commands.filter((command) =>
		`${command.label} ${command.detail}`
			.toLowerCase()
			.includes(query.toLowerCase()),
	);
	return (
		<CommandDialog
			open={open}
			title="Composer command palette"
			description="Search composer actions and run the selected command."
			onOpenChange={(nextOpen) => {
				onOpenChange(nextOpen);
				if (!nextOpen) setQuery("");
			}}
		>
			<CommandInput
				value={query}
				onValueChange={setQuery}
				placeholder="Run composer action..."
			/>
			<CommandList className="max-h-[420px] overflow-y-auto p-2">
				{filtered.length === 0 ? (
					<CommandEmpty>No composer action found.</CommandEmpty>
				) : (
					<CommandGroup heading="Composer actions">
						{filtered.map((command) => (
							<CommandItem
								key={command.id}
								value={command.id}
								onSelect={() => {
									command.run();
									onOpenChange(false);
									setQuery("");
								}}
								className="gap-3"
							>
								<span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
									<CommandIcon aria-hidden="true" />
								</span>
								<span className="min-w-0 flex-1">
									<span className="block text-[0.84375rem] font-medium text-foreground">
										{command.label}
									</span>
									<span className="mt-0.5 block text-[0.71875rem] text-muted-foreground">
										{command.detail}
									</span>
								</span>
								<CommandShortcut>Enter</CommandShortcut>
							</CommandItem>
						))}
					</CommandGroup>
				)}
			</CommandList>
		</CommandDialog>
	);
}

export function BulkUploadQueuePanel({
	items,
	onUpdate,
	onRemove,
	onMove,
	onAttach,
	onCreateDrafts,
	onScheduleSelected,
	disabled,
}: {
	items: BulkUploadQueueItem[];
	onUpdate: (id: string, patch: Partial<BulkUploadQueueItem>) => void;
	onRemove: (id: string) => void;
	onMove: (id: string, direction: -1 | 1) => void;
	onAttach: (item: BulkUploadQueueItem) => void;
	onCreateDrafts: () => void;
	onScheduleSelected: () => void;
	disabled: boolean;
}) {
	const selectedCount = items.filter((item) => item.selected).length;
	return (
		<NovaCard contentClassName="p-4">
			<div className="mb-3 flex items-center justify-between gap-3">
				<div className="inline-flex items-center gap-2">
					<UploadCloud
						className="h-4 w-4 text-muted-foreground"
						aria-hidden="true"
					/>
					<div>
						<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Bulk upload queue
						</div>
						<div className="mt-0.5 text-[0.71875rem] text-muted-foreground">
							{selectedCount} selected · review before creating posts
						</div>
					</div>
				</div>
				<div className="flex items-center gap-1.5">
					<Button
						type="button"
						onClick={onCreateDrafts}
						disabled={disabled || selectedCount === 0}
						variant="outline"
						size="sm"
					>
						Create drafts
					</Button>
					<Button
						type="button"
						onClick={onScheduleSelected}
						disabled={disabled || selectedCount === 0}
						size="sm"
					>
						Schedule selected
					</Button>
				</div>
			</div>
			<div className="flex flex-col gap-2">
				{items.map((item, index) => (
					<div
						key={item.id}
						className="grid gap-3 rounded-md border border-border bg-card p-3 md:grid-cols-[72px_minmax(0,1fr)_170px]"
					>
						<div className="relative h-[72px] overflow-hidden rounded-md border border-border bg-muted">
							{item.kind === "video" ? (
								<video
									src={item.previewUrl}
									muted
									playsInline
									className="h-full w-full object-cover"
								/>
							) : (
								<img
									src={item.previewUrl}
									alt=""
									className="h-full w-full object-cover"
								/>
							)}
							<Checkbox
								checked={item.selected}
								onCheckedChange={(checked) =>
									onUpdate(item.id, { selected: checked === true })
								}
								className="absolute left-1 top-1"
								aria-label={`Select ${item.name}`}
							/>
						</div>
						<div className="min-w-0">
							<div className="flex items-center gap-2">
								<div className="truncate text-[0.8125rem] font-medium text-foreground">
									{item.name}
								</div>
								<Badge
									tone={
										item.status === "error"
											? "oxblood"
											: item.status === "done"
												? "secondary"
												: "outline"
									}
								>
									{item.status}
								</Badge>
							</div>
							<div className="mt-2 flex items-center gap-1.5">
								<Button
									type="button"
									onClick={() => onMove(item.id, -1)}
									disabled={index === 0}
									variant="outline"
									size="sm"
									className="h-7"
								>
									Move up
								</Button>
								<Button
									type="button"
									onClick={() => onMove(item.id, 1)}
									disabled={index === items.length - 1}
									variant="outline"
									size="sm"
									className="h-7"
								>
									Move down
								</Button>
							</div>
							<Textarea
								value={item.caption}
								onChange={(event) =>
									onUpdate(item.id, { caption: event.target.value })
								}
								rows={2}
								placeholder="Caption for this post"
								className="mt-2"
							/>
							{(item.error || item.warnings.length > 0) && (
								<div className="mt-1.5 text-[0.6875rem] leading-snug text-muted-foreground">
									{item.error || item.warnings[0]}
								</div>
							)}
						</div>
						<div className="flex flex-col gap-2">
							<div className="grid grid-cols-2 gap-1.5">
								<Select
									value={item.postType}
									onChange={(event) =>
										onUpdate(item.id, {
											postType: event.target.value as IGPostType,
										})
									}
									sizeVariant="sm"
								>
									<option value="feed">Feed</option>
									<option value="reels">Reel</option>
									<option value="story">Story</option>
								</Select>
								<Select
									value={item.publishMode}
									onChange={(event) =>
										onUpdate(item.id, {
											publishMode: event.target.value as "auto" | "notify",
										})
									}
									sizeVariant="sm"
								>
									<option value="auto">Auto</option>
									<option value="notify">Notify</option>
								</Select>
							</div>
							<div className="grid grid-cols-2 gap-1.5">
								<Input
									type="date"
									value={item.scheduleDate}
									onChange={(event) =>
										onUpdate(item.id, { scheduleDate: event.target.value })
									}
									sizeVariant="sm"
								/>
								<Input
									type="time"
									value={item.scheduleTime}
									onChange={(event) =>
										onUpdate(item.id, { scheduleTime: event.target.value })
									}
									sizeVariant="sm"
								/>
							</div>
							<div className="flex items-center gap-1.5">
								<Button
									type="button"
									onClick={() => onAttach(item)}
									disabled={disabled || item.status === "error"}
									variant="outline"
									size="sm"
									className="flex-1"
								>
									Attach
								</Button>
								<Button
									type="button"
									onClick={() => onRemove(item.id)}
									variant="ghost"
									size="sm"
								>
									Remove
								</Button>
							</div>
						</div>
					</div>
				))}
			</div>
		</NovaCard>
	);
}

export function ComposerIntelligencePanel({
	contentKits,
	captionKits,
	trendIdeas,
	loadingTrends,
	onApplyKit,
	onSaveCurrent,
	onUseTrend,
}: {
	contentKits: Array<{
		id: string;
		name: string;
		textTemplate: string;
		hashtags: string[];
	}>;
	captionKits: Array<{
		id: string;
		name: string;
		textTemplate: string;
		hashtags: string[];
	}>;
	trendIdeas: InspirationIdea[];
	loadingTrends: boolean;
	onApplyKit: (kit: {
		id: string;
		textTemplate: string;
		hashtags: string[];
	}) => void;
	onSaveCurrent: () => void;
	onUseTrend: (idea: InspirationIdea) => void;
}) {
	const starterKits = [
		{
			id: "starter-product-launch",
			name: "Product launch",
			textTemplate:
				"New drop is live.\n\nWhat changed:\n- \n- \n- \n\nBuilt for people who want ",
			hashtags: ["launch", "buildinpublic"],
		},
		{
			id: "starter-proof",
			name: "Proof/testimonial",
			textTemplate: 'Proof point from this week:\n\n""\n\nWhy it matters:\n',
			hashtags: ["socialproof"],
		},
		{
			id: "starter-bts-reel",
			name: "Behind-the-scenes Reel",
			textTemplate:
				"Behind the scenes of how this came together.\n\nStep 1:\nStep 2:\nStep 3:\n\nSave this for later.",
			hashtags: ["reels", "behindthescenes"],
		},
		{
			id: "starter-education",
			name: "Educational carousel",
			textTemplate: "Most people miss this:\n\n1. \n2. \n3. \n\nThe takeaway:",
			hashtags: ["learn", "tips"],
		},
		{
			id: "starter-cta",
			name: "Direct CTA",
			textTemplate:
				'If you want the fastest path to , start here:\n\n\n\nComment "start" and I’ll send the next step.',
			hashtags: ["growth"],
		},
	];
	const kits = [...contentKits, ...captionKits].slice(0, 5);
	const visibleKits = kits.length > 0 ? kits : starterKits;
	return (
		<NovaCard contentClassName="p-4">
			<div className="mb-3 flex items-center justify-between gap-3">
				<div className="inline-flex items-center gap-2">
					<Wand2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
					<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
						Kits & trends
					</span>
				</div>
				<Button
					type="button"
					onClick={onSaveCurrent}
					variant="outline"
					size="sm"
					className="h-7"
				>
					Save kit
				</Button>
			</div>
			<div className="flex flex-col gap-3">
				<div>
					<div className="mb-1.5 text-[0.6875rem] font-medium text-muted-foreground">
						Content kits
					</div>
					<div className="flex flex-wrap gap-1.5">
						{visibleKits.length > 0 ? (
							visibleKits.map((kit) => (
								<Button
									key={kit.id}
									type="button"
									variant="outline"
									size="sm"
									onClick={() => onApplyKit(kit)}
									className="max-w-full rounded-full px-2.5 py-1 text-[0.71875rem]"
								>
									{kit.name}
								</Button>
							))
						) : (
							<span className="text-[0.71875rem] text-muted-foreground">
								Save reusable structures from the current caption.
							</span>
						)}
					</div>
				</div>
				<div>
					<div className="mb-1.5 text-[0.6875rem] font-medium text-muted-foreground">
						Draft from trend
					</div>
					<div className="flex flex-col gap-1.5">
						{loadingTrends ? (
							<div className="text-[0.71875rem] text-muted-foreground">
								Loading trend ideas…
							</div>
						) : trendIdeas.length > 0 ? (
							trendIdeas.slice(0, 3).map((idea) => (
								<Button
									key={idea.id}
									type="button"
									variant="outline"
									onClick={() => onUseTrend(idea)}
									className="h-auto w-full justify-start px-2.5 py-2 text-left"
								>
									<div className="line-clamp-2 text-[0.78125rem] font-medium text-foreground">
										{idea.adaptedContent || idea.originalPost.content}
									</div>
									<div className="mt-1 text-[0.6875rem] text-muted-foreground">
										Score {Math.round(idea.viralScore ?? 0)} · @
										{idea.competitorUsername ?? "trend"}
									</div>
								</Button>
							))
						) : (
							<div className="text-[0.71875rem] text-muted-foreground">
								No trend ideas available yet.
							</div>
						)}
					</div>
				</div>
			</div>
		</NovaCard>
	);
}
