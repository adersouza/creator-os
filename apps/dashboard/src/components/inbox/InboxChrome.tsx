import type React from "react";
import { Inbox as InboxIcon, MessageCircle, Radio } from "lucide-react";
import { AccountScopeChip } from "@/components/ui/AccountScopeChip";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaDataPanel, NovaEmpty, NovaHeader, NovaToolbar } from "@/components/ui/NovaPrimitives";
import { PillSegmented } from "@/components/ui/PillSegmented";
import { Skeleton } from "@/components/ui/Skeleton";
import { TogglePill } from "@/components/ui/TogglePill";
import { cn } from "@/lib/utils";
import { tabsForPlatform } from "./helpers";
import type { PlatformKind, TabKey } from "./types";

export function InboxHeader({
	total,
	platform,
	scopedAccount,
	accountCount,
	onClearScope,
	onPlatformChange,
}: {
	total: number;
	platform: PlatformKind;
	scopedAccount: {
		handle: string;
		groupColor: string;
		platform: PlatformKind;
	} | null;
	accountCount: number;
	onClearScope: () => void;
	onPlatformChange: (platform: PlatformKind) => void;
}) {
	const platformLabel = platform === "instagram" ? "Instagram" : "Threads";

	return (
		<div className="shrink-0">
			<NovaHeader
				eyebrow="Audience command center"
				title="Inbox"
				meta={`${platformLabel} · live`}
				description={`Manage conversations and engage your audience. ${total} ${platformLabel.toLowerCase()} conversation${total === 1 ? "" : "s"} ${
					scopedAccount ? `for ${scopedAccount.handle}` : "across your fleet"
				}.`}
				actions={
					scopedAccount ? (
						<div
							className="h-9 rounded-full border border-border bg-card px-3.5 inline-flex items-center text-[0.78125rem] font-medium text-muted-foreground"
							title={`Locked to ${scopedAccount.handle}`}
						>
							{platformLabel}
						</div>
					) : (
						<PillSegmented<PlatformKind>
							value={platform}
							onChange={onPlatformChange}
							ariaLabel="Platform filter"
							options={[
								{ id: "threads", label: "Threads" },
								{ id: "instagram", label: "Instagram" },
							]}
						/>
					)
				}
				filters={
					<>
						{scopedAccount ? (
							<AccountScopeChip
								handle={scopedAccount.handle}
								color={scopedAccount.groupColor}
								onClear={onClearScope}
							/>
						) : (
							<AccountScopeChip count={accountCount} />
						)}
						<Badge tone="oxblood" className="gap-1.5">
							<span className="size-1.5 rounded-full inbox-live-dot bg-[color:var(--color-oxblood)]" />
							{total} active
						</Badge>
					</>
				}
			/>
		</div>
	);
}

export function InboxFilterBar({
	platform,
	tab,
	counts,
	lockedToAccount = false,
	onTabChange,
	onTablistKey,
}: {
	platform: PlatformKind;
	tab: TabKey;
	counts: Record<TabKey, number>;
	lockedToAccount?: boolean;
	onTabChange: (tab: TabKey) => void;
	onTablistKey: (event: React.KeyboardEvent<HTMLElement>) => void;
}) {
	const messageTabs = tabsForPlatform(platform);
	if (lockedToAccount && messageTabs.length <= 1) return null;

	return (
		<NovaToolbar className="mb-4 shrink-0 justify-between gap-3 overflow-x-auto scrollbar-hide">
			<div
				role="tablist"
				aria-label="Message filter"
				data-tablist="inbox-tabs"
				onKeyDown={onTablistKey}
				className="inline-flex items-center gap-1 rounded-full border border-border bg-card p-1 shadow-sm"
			>
				{messageTabs.map((t) => {
					const active = t.id === tab;
					return (
						<TogglePill
							type="button"
							key={t.id}
							active={active}
							role="tab"
							aria-selected={active}
							data-tab-id={t.id}
							tabIndex={active ? 0 : -1}
							onClick={() => onTabChange(t.id)}
							className="h-8 text-[0.75rem]"
							trailing={
								<span
									className={cn(
										"text-[0.6875rem] tabular-nums px-1.5 py-0.5 rounded-full",
										active
											? "bg-primary-foreground/15 text-primary-foreground"
											: "bg-muted text-muted-foreground",
									)}
								>
									{counts[t.id]}
								</span>
							}
						>
							{t.label}
						</TogglePill>
					);
				})}
			</div>
			<div className="hidden items-center gap-2 lg:flex">
				<Badge tone="outline" className="h-8 px-3 text-[0.71875rem]">
					<Radio data-icon="inline-start" />
					Live messages
				</Badge>
				<Badge tone="outline" className="h-8 px-3 text-[0.71875rem]">
					<MessageCircle data-icon="inline-start" />
					Reply workflow
				</Badge>
			</div>
		</NovaToolbar>
	);
}

export function InboxLoadingPane() {
	return (
		<NovaDataPanel
			className="min-h-0 flex-1"
			contentClassName="flex min-h-0 p-0"
		>
			<aside className="w-full md:w-[340px] border-r border-border flex flex-col shrink-0">
				<div className="p-3 border-b border-border">
					<Skeleton className="h-9 w-full rounded-md" />
				</div>
				<div className="flex-1 overflow-hidden p-2 flex flex-col gap-1">
					{Array.from({ length: 10 }).map((_, i) => (
						<div key={i} className="flex items-start gap-3 p-2 rounded-md">
							<Skeleton className="h-9 w-9 rounded-full shrink-0" />
							<div className="flex-1 flex min-w-0 flex-col gap-1.5">
								<div className="flex items-center justify-between gap-2">
									<Skeleton className="h-3 w-24 rounded-full" />
									<Skeleton className="h-2 w-8 rounded-full opacity-60" />
								</div>
								<Skeleton className="h-2.5 w-[85%] rounded-full opacity-70" />
								<Skeleton className="h-2.5 w-[60%] rounded-full opacity-50" />
							</div>
						</div>
					))}
				</div>
			</aside>
			<div className="flex-1 hidden md:flex flex-col">
				<div className="flex items-center gap-3 p-4 border-b border-border">
					<Skeleton className="h-10 w-10 rounded-full shrink-0" />
					<div className="flex flex-1 flex-col gap-1.5">
						<Skeleton className="h-3 w-32 rounded-full" />
						<Skeleton className="h-2.5 w-24 rounded-full opacity-70" />
					</div>
				</div>
				<div className="flex-1 p-6 flex flex-col gap-4">
					{Array.from({ length: 4 }).map((_, i) => (
						<div
							key={i}
							className={`flex ${i % 2 === 0 ? "justify-start" : "justify-end"}`}
						>
							<Skeleton
								className={`h-14 rounded-[10px] ${i % 2 === 0 ? "w-[60%]" : "w-[50%]"}`}
							/>
						</div>
					))}
				</div>
				<div className="p-4 border-t border-border">
					<Skeleton className="h-20 w-full rounded-md" />
				</div>
			</div>
		</NovaDataPanel>
	);
}

export function EmptyShell({
	eyebrow,
	title,
	description,
	primaryLabel,
	secondaryLabel,
	onPrimary,
	onSecondary,
}: {
	eyebrow: string;
	title: string;
	description: string;
	primaryLabel?: string | undefined;
	secondaryLabel?: string | undefined;
	onPrimary?: (() => void | Promise<void>) | undefined;
	onSecondary?: (() => void | Promise<void>) | undefined;
}) {
	const action =
		(primaryLabel && onPrimary) || (secondaryLabel && onSecondary) ? (
			<div className="flex flex-row flex-wrap justify-center gap-2">
				{primaryLabel && onPrimary ? (
					<Button type="button" onClick={onPrimary}>
						{primaryLabel}
					</Button>
				) : null}
				{secondaryLabel && onSecondary ? (
					<Button type="button" variant="outline" onClick={onSecondary}>
						{secondaryLabel}
					</Button>
				) : null}
			</div>
		) : null;

	return (
		<NovaDataPanel
			className="min-h-0 flex-1"
			contentClassName="flex min-h-0 p-0"
		>
			<NovaEmpty
				className="min-h-full flex-1 border-0 bg-transparent"
				icon={<InboxIcon />}
				title={title}
				description={
					<span className="flex flex-col items-center gap-3">
						<Badge tone="outline">{eyebrow}</Badge>
						<span>{description}</span>
					</span>
				}
				action={action}
			/>
		</NovaDataPanel>
	);
}
