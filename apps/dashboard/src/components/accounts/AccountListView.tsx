import type React from "react";
import { ArrowUpRightFromSquare, Pause } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { HealthDot } from "@/components/ui/HealthDot";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sparkline as UISparkline } from "@/components/ui/Sparkline";
import type { FleetAccount } from "@/hooks/useFleetAccounts";
import { labelFor } from "@/lib/socialPlatform";
import { AccountRowContextMenu } from "./AccountRowContextMenu";
import {
	accountSignalStatus,
	formatFollowers,
	formatLastPost,
	hasTokenExpiringSignal,
	STATUS_LABEL,
	STATUS_ROW_TINT,
	STATUS_STRIPE,
	type AccountHealthSignal,
	type AccountUiStatus,
	UI_TO_HEALTH_STATE,
} from "./shared";

interface AccountListViewProps {
	accounts: FleetAccount[];
	selected: Set<string>;
	focusedIndex: number;
	healthSignalsByAccount: Map<string, AccountHealthSignal[]>;
	isLoading: boolean;
	onToggleSelect: (id: string) => void;
	onOpen: (account: FleetAccount) => void;
	onFocusRow: (index: number) => void;
	onPause: (account: FleetAccount) => void;
	onViewScheduler: (account: FleetAccount) => void;
	onViewAnalytics: (account: FleetAccount) => void;
	onMoveGroup: (account: FleetAccount) => void;
	onSync: (account: FleetAccount) => void;
	onHealthCheck: (account: FleetAccount) => void;
	onReconnect: (account: FleetAccount) => void;
	onRemove: (account: FleetAccount) => void;
}

const ACCOUNT_GRID_COLUMNS =
	"3px 40px minmax(180px,1.7fr) minmax(92px,0.8fr) minmax(92px,0.7fr) 74px 70px 68px 70px 70px";

export function AccountListView({
	accounts,
	selected,
	focusedIndex,
	healthSignalsByAccount,
	isLoading,
	onToggleSelect,
	onOpen,
	onFocusRow,
	onPause,
	onViewScheduler,
	onViewAnalytics,
	onMoveGroup,
	onSync,
	onHealthCheck,
	onReconnect,
	onRemove,
}: AccountListViewProps) {
	return (
		<NovaCard className="relative" contentClassName="overflow-x-auto p-0">
			<div className="min-w-[840px]">
				<div
					className="sticky top-0 z-10 grid h-11 items-center border-b border-border bg-muted/40 text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground"
					style={{ gridTemplateColumns: ACCOUNT_GRID_COLUMNS }}
				>
					<div />
					<div />
					<div className="pl-2">Account</div>
					<div>Group</div>
					<div>Platform</div>
					<div className="pr-4 text-right">Followers</div>
					<div className="pr-4 text-right">Posts 24h</div>
					<div
						role="columnheader"
						tabIndex={0}
						className="pr-4 text-right"
						aria-label="Trend"
					/>
					<div className="pr-4 text-right">Health</div>
					<div className="pr-4 text-right">Last Post</div>
				</div>

				{isLoading ? (
					<LoadingRows />
				) : accounts.length === 0 ? (
					<EmptyRow />
				) : (
					accounts.map((account, index) => (
						<AccountRow
							key={account.id}
							account={account}
							signals={healthSignalsByAccount.get(account.id) ?? []}
							selected={selected.has(account.id)}
							focused={index === focusedIndex}
							onToggleSelect={() => onToggleSelect(account.id)}
							onOpen={() => onOpen(account)}
							onHover={() => onFocusRow(index)}
							onPause={() => onPause(account)}
							onViewScheduler={() => onViewScheduler(account)}
							onViewAnalytics={() => onViewAnalytics(account)}
							onMoveGroup={() => onMoveGroup(account)}
							onSync={() => onSync(account)}
							onHealthCheck={() => onHealthCheck(account)}
							onReconnect={() => onReconnect(account)}
							onRemove={() => onRemove(account)}
						/>
					))
				)}
			</div>
		</NovaCard>
	);
}

function AccountRow({
	account,
	signals,
	selected,
	focused,
	onToggleSelect,
	onOpen,
	onHover,
	onPause,
	onViewScheduler,
	onViewAnalytics,
	onMoveGroup,
	onSync,
	onHealthCheck,
	onReconnect,
	onRemove,
}: {
	account: FleetAccount;
	signals: AccountHealthSignal[];
	selected: boolean;
	focused: boolean;
	onToggleSelect: () => void;
	onOpen: () => void;
	onHover: () => void;
	onPause: () => void;
	onViewScheduler: () => void;
	onViewAnalytics: () => void;
	onMoveGroup: () => void;
	onSync: () => void;
	onHealthCheck: () => void;
	onReconnect: () => void;
	onRemove: () => void;
}) {
	const ui = accountSignalStatus(account.health, signals);
	const pauseLabel = ui === "inactive" ? "Resume" : "Pause";
	const tokenExpiring = hasTokenExpiringSignal(signals);

	return (
		<AccountRowContextMenu
			pauseLabel={pauseLabel}
			onOpen={onOpen}
			onPause={onPause}
			onViewScheduler={onViewScheduler}
			onViewAnalytics={onViewAnalytics}
			onMoveGroup={onMoveGroup}
			onSync={onSync}
			onHealthCheck={onHealthCheck}
			onReconnect={onReconnect}
			onRemove={onRemove}
		>
			<div
				className={`group relative grid min-h-[56px] cursor-pointer items-center border-b border-border/70 transition-colors ${
					focused ? "td-active-tint" : "hover:bg-muted/60"
				}`}
				style={{
					gridTemplateColumns: ACCOUNT_GRID_COLUMNS,
					backgroundColor: !focused ? STATUS_ROW_TINT[ui] : undefined,
				}}
				onClick={onOpen}
				onMouseEnter={onHover}
			>
				<div
					className="self-stretch"
					style={{ background: STATUS_STRIPE[ui] }}
					aria-hidden="true"
				/>
				<div
					className="flex items-center justify-center relative"
					onClick={(e) => {
						e.stopPropagation();
						onToggleSelect();
					}}
				>
					<Checkbox
						checked={selected}
						aria-label={`Select ${account.handle}`}
						onCheckedChange={onToggleSelect}
						onClick={(event) => event.stopPropagation()}
					/>
				</div>
				<div className="flex min-w-0 items-center gap-3 pl-2">
					<div
						className="flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white shadow-sm ring-1 ring-border/60"
						style={{
							background: `linear-gradient(135deg, ${account.groupColor}, color-mix(in srgb, ${account.groupColor} 60%, var(--color-ink)))`,
						}}
					>
						{(account.displayName[0] ?? ".").toUpperCase()}
					</div>
					<div className="min-w-0">
						<div className="truncate text-sm font-medium text-foreground">
							{account.handle}
						</div>
						<div className="truncate text-xs text-muted-foreground">
							{account.displayName}
						</div>
					</div>
					{tokenExpiring && (
						<Badge
							tone="outline"
							className="shrink-0 px-1.5 py-0.5 text-[0.6875rem] uppercase tracking-[0.06em] text-[var(--color-warning)]"
						>
							Token
						</Badge>
					)}
					{("tags" in account && Array.isArray(account.tags)
						? account.tags
						: []
					)
						.slice(0, 2)
						.map((tag: string) => (
							<Badge
								key={tag}
								tone="secondary"
								className="hidden px-1.5 py-0.5 text-[0.6875rem] text-muted-foreground xl:inline-flex"
							>
								#{tag}
							</Badge>
						))}
				</div>
				<div className="flex min-w-0 items-center gap-2">
					<span
						className="size-2 rounded-full ring-2 ring-background"
						style={{ background: account.groupColor }}
					/>
					<span className="truncate text-sm text-muted-foreground">
						{account.groupName}
					</span>
				</div>
				<div className="flex items-center gap-2 text-sm text-muted-foreground">
					<BrandLogo
						name={account.platform === "instagram" ? "instagram" : "threads"}
						size="xs"
						monochrome={account.platform !== "instagram"}
					/>
					<span>{labelFor(account.platform)}</span>
				</div>
				<div className="pr-4 text-right text-sm text-foreground tabular-nums">
					{formatFollowers(account.followers)}
				</div>
				<div className="pr-4 text-right text-sm text-muted-foreground tabular-nums">
					{account.posts24h}
				</div>
				<div className="flex justify-end pr-4">
					<Sparkline values={account.trend7d} status={ui} />
				</div>
				<div
					className="flex items-center justify-end gap-1.5 pr-4"
					title={`${STATUS_LABEL[ui]} - health ${account.healthScore}`}
				>
					<span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2 py-1 text-xs text-foreground tabular-nums">
						<HealthDot
							state={UI_TO_HEALTH_STATE[ui]}
							label={`${account.handle} ${STATUS_LABEL[ui].toLowerCase()} - health ${account.healthScore}`}
							size={8}
						/>
						{account.healthScore}
					</span>
				</div>
				<div className="pr-4 text-right text-xs text-muted-foreground tabular-nums">
					{formatLastPost(account.lastPostHoursAgo)}
				</div>
				<div className="absolute right-3 top-1/2 hidden -translate-y-1/2 items-center gap-1 bg-card pl-3 pr-0 shadow-[-8px_0_12px_color-mix(in_srgb,var(--color-card)_85%,transparent)] group-hover:flex focus-within:flex">
					<RowAction
						label={pauseLabel}
						onClick={(e) => {
							e.stopPropagation();
							onPause();
						}}
					>
						<Pause data-icon="icon" />
					</RowAction>
					<RowAction
						label="Open"
						onClick={(e) => {
							e.stopPropagation();
							onOpen();
						}}
					>
						<ArrowUpRightFromSquare data-icon="icon" />
					</RowAction>
				</div>
			</div>
		</AccountRowContextMenu>
	);
}

function RowAction({
	children,
	label,
	onClick,
}: {
	children: React.ReactNode;
	label: string;
	onClick: (e: React.MouseEvent<HTMLButtonElement>) => void;
}) {
	return (
		<Button
			type="button"
			aria-label={label}
			title={label}
			onClick={onClick}
			variant="ghost"
			size="icon"
			className="size-7 text-muted-foreground hover:text-foreground"
		>
			{children}
		</Button>
	);
}

function Sparkline({
	values,
	status,
}: {
	values: number[];
	status: AccountUiStatus;
}) {
	const color =
		status === "flagged"
			? "var(--color-critical)"
			: status === "drifting"
				? "var(--color-warning)"
				: status === "inactive"
					? "color-mix(in_srgb,var(--color-foreground)_25%,transparent)"
					: "currentColor";
	return (
		<div className="w-[48px] text-foreground opacity-60">
			<UISparkline
				points={values.length >= 2 ? values : [0, 0]}
				color={color}
				height={16}
				strokeWidth={1.25}
				animate={false}
				ariaLabel="Account trend"
			/>
		</div>
	);
}

function EmptyRow() {
	return (
		<NovaEmpty
			className="m-3 min-h-28 border-0 bg-transparent"
			title="No accounts match these filters"
			description="Adjust the search, group, platform, or health filters to widen the result set."
		/>
	);
}

function LoadingRows() {
	return (
		<div>
			{Array.from({ length: 10 }).map((_, i) => (
				<div
					key={i}
					className="grid h-14 items-center border-b border-border/70 px-0"
					style={{ gridTemplateColumns: ACCOUNT_GRID_COLUMNS }}
					aria-hidden="true"
				>
					<div />
					<div className="flex justify-center">
						<Skeleton className="size-8 rounded-full" />
					</div>
					<div className="flex items-center gap-2 pl-2">
						<Skeleton className="h-4 w-32 rounded-full" />
					</div>
					<Skeleton className="h-4 w-16 rounded-full" />
					<Skeleton className="h-4 w-14 rounded-full" />
					<div className="flex justify-end pr-4">
						<Skeleton className="h-3 w-10 rounded-full" />
					</div>
					<div className="flex justify-end pr-4">
						<Skeleton className="h-3 w-8 rounded-full" />
					</div>
					<div className="flex justify-end pr-4">
						<Skeleton className="h-3 w-12 rounded-full opacity-70" />
					</div>
					<div className="flex justify-end pr-4">
						<Skeleton className="h-4 w-14 rounded-full" />
					</div>
					<div className="flex justify-end pr-4">
						<Skeleton className="h-3 w-12 rounded-full opacity-70" />
					</div>
				</div>
			))}
		</div>
	);
}

export function Pagination({
	page,
	pageCount,
	onChange,
}: {
	page: number;
	pageCount: number;
	onChange: (next: number) => void;
}) {
	const items: (number | "...")[] = [];
	for (let i = 1; i <= pageCount; i += 1) {
		if (i === 1 || i === pageCount || (i >= page - 1 && i <= page + 1)) {
			items.push(i);
		} else if (items[items.length - 1] !== "...") {
			items.push("...");
		}
	}
	return (
		<div className="mt-4 flex items-center justify-center gap-1 text-[0.78125rem] tabular-nums">
			<IconTooltipButton
				label="Previous page"
				onClick={() => onChange(Math.max(1, page - 1))}
				disabled={page <= 1}
				className="text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
				side="top"
			>
				<span className="h-8 w-8 rounded-md inline-flex items-center justify-center hover:bg-muted">
					<span aria-hidden="true">&lt;</span>
				</span>
			</IconTooltipButton>
			{items.map((item, i) =>
				item === "..." ? (
					<span key={`dots-${i}`} className="px-1.5 text-muted-foreground">
						...
					</span>
				) : (
					<Button
						key={item}
						type="button"
						onClick={() => onChange(item)}
						aria-current={item === page ? "page" : undefined}
						variant={item === page ? "default" : "ghost"}
						size="sm"
						className="min-w-8 px-2"
					>
						{item}
					</Button>
				),
			)}
			<IconTooltipButton
				label="Next page"
				onClick={() => onChange(Math.min(pageCount, page + 1))}
				disabled={page >= pageCount}
				className="text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
				side="top"
			>
				<span className="h-8 w-8 rounded-md inline-flex items-center justify-center hover:bg-muted">
					<span aria-hidden="true">&gt;</span>
				</span>
			</IconTooltipButton>
		</div>
	);
}
