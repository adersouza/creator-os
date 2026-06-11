import { Skeleton } from "@/components/ui/Skeleton";

const pageShellClass =
	"min-h-full w-full bg-background px-4 py-6 text-foreground sm:px-6 lg:px-8";
const densePageShellClass =
	"min-h-full w-full bg-background px-4 py-5 text-foreground sm:px-6";
const composerPageShellClass =
	"min-h-full w-full bg-background px-4 py-6 text-foreground sm:px-6 lg:px-8";
const panelClass =
	"rounded-xl border border-border bg-card text-card-foreground shadow-sm";
const panelOverflowClass = `${panelClass} overflow-hidden`;

/**
 * Page-level loading skeletons rendered while a route's chunk is still
 * lazy-loading (RouteAwareFallback in App.tsx) or while a page's primary
 * data hook is on its first cold fetch.
 *
 * Each skeleton mirrors the SAME outer container, hero, filter bar, and
 * primary grid as its page so the swap from skeleton → content is one
 * content swap, not a layout reflow.
 *
 * Source-of-truth pages live in `src/pages/*.tsx` and the active route
 * components. If you change a page's top-level layout, update the matching
 * skeleton below.
 */

/* =========================================================================
   Shared building blocks
   ========================================================================= */

/** Hero with an oxblood eyebrow dot — Reports / Inbox / Links / Autopilot
 *  / ContentLibrary / Attribution. */
function OxbloodEyebrowHero({
	titleW = "w-44",
	metaW = "w-72",
	actions,
}: {
	titleW?: string | undefined;
	metaW?: string | undefined;
	actions?: React.ReactNode | undefined;
}) {
	return (
		<div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-6">
			<div>
				<div className="flex items-center gap-2 mb-2">
					<span
						className="w-[5px] h-[5px] rounded-full"
						style={{ background: "var(--color-oxblood)" }}
						aria-hidden="true"
					/>
					<Skeleton className="h-2 w-20 rounded-full opacity-80" />
				</div>
				<Skeleton className={`h-8 ${titleW} rounded-[8px]`} />
				<Skeleton className={`mt-2 h-3 ${metaW} rounded-full opacity-70`} />
			</div>
			{actions ? (
				<div className="flex items-center gap-2">{actions}</div>
			) : null}
		</div>
	);
}

/** Hero without the eyebrow dot — Accounts / Calendar / Analytics. */
function PlainHero({
	titleW = "w-44",
	metaW = "w-72",
	actions,
}: {
	titleW?: string | undefined;
	metaW?: string | undefined;
	actions?: React.ReactNode | undefined;
}) {
	return (
		<div className="flex flex-col md:flex-row md:items-end md:justify-between gap-5 mb-6">
			<div>
				<Skeleton className={`h-8 ${titleW} rounded-[8px]`} />
				<Skeleton className={`mt-2 h-3 ${metaW} rounded-full opacity-70`} />
			</div>
			{actions ? (
				<div className="flex items-center gap-2">{actions}</div>
			) : null}
		</div>
	);
}

/** 4-card stat strip used by Accounts and Autopilot. */
function StatStrip() {
	return (
		<div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
			{Array.from({ length: 4 }).map((_, i) => (
				<div key={i} className={`${panelClass} p-4 flex flex-col gap-2.5`}>
					<Skeleton className="h-2.5 w-16 rounded-full" />
					<Skeleton className="h-7 w-14 rounded-[8px]" />
					<Skeleton className="h-2 w-20 rounded-full opacity-70" />
				</div>
			))}
		</div>
	);
}

/* =========================================================================
   Dashboard
   ========================================================================= */
export function DashboardSkeleton() {
	return (
		<>
			<MobileDashboardSkeleton />
			<DesktopDashboardSkeleton />
		</>
	);
}

/** Mobile shape — mirrors src/components/dashboard/MobileOverview.tsx:
 *  top bar + platform pills + greeting (kicker / h1 / body) + timeframe pills
 *  + alert card + Fleet pulse vertical tile stack + Next up horizontal strip
 *  + Top performing condensed list. */
function MobileDashboardSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading dashboard"
			className="lg:hidden min-h-[100dvh] bg-background pb-24 px-4 pt-4"
		>
			{/* Top bar */}
			<div className="flex items-center justify-between mb-4">
				<div className="flex items-center gap-2">
					<Skeleton className="w-7 h-7 rounded-md" />
					<Skeleton className="h-3.5 w-16 rounded-full" />
					<Skeleton className="w-2 h-2 rounded-full" />
				</div>
				<Skeleton className="w-9 h-9 rounded-full" />
			</div>

			{/* Platform pills */}
			<div className="flex gap-2 mb-4 overflow-hidden">
				{Array.from({ length: 3 }).map((_, i) => (
					<Skeleton key={i} className="h-8 w-[88px] rounded-full" />
				))}
			</div>

			{/* Hero text — kicker / h1 / body */}
			<Skeleton className="h-2.5 w-20 rounded-full opacity-70 mb-2" />
			<Skeleton className="h-5 w-52 rounded-[6px] mb-1.5" />
			<Skeleton className="h-3 w-64 rounded-full opacity-70 mb-4" />

			{/* Timeframe pills */}
			<div className="flex gap-2 mb-4">
				{Array.from({ length: 3 }).map((_, i) => (
					<Skeleton key={i} className="h-7 w-[60px] rounded-full" />
				))}
			</div>

			{/* Alert card */}
			<div className="mb-4">
				<div
					className={`${panelClass} p-3 flex gap-2.5 items-start`}
					style={{ minHeight: 60 }}
				>
					<Skeleton className="w-[22px] h-[22px] rounded-md shrink-0" />
					<div className="flex-1 flex flex-col gap-1.5">
						<Skeleton className="h-3 w-[60%] rounded-full" />
						<Skeleton className="h-2 w-[80%] rounded-full opacity-60" />
					</div>
				</div>
			</div>

			{/* Fleet pulse — section header + 6 vertical tiles */}
			<div className="mb-4">
				<Skeleton className="h-2.5 w-24 rounded-full opacity-70 mb-2 ml-1" />
				<div className="flex flex-col gap-3">
					{[180, 160, 140, 120, 140, 160].map((h, i) => (
						<div
							key={i}
							className={`${panelClass} p-4 flex flex-col gap-2.5`}
							style={{ minHeight: h }}
						>
							<Skeleton className="h-2.5 w-24 rounded-full opacity-80" />
							<Skeleton className="h-7 w-32 rounded-[8px]" />
							<Skeleton className="h-2 w-28 rounded-full opacity-60" />
							<div className="mt-auto pt-1">
								<Skeleton className="h-12 w-full rounded-[6px] opacity-70" />
							</div>
						</div>
					))}
				</div>
			</div>

			{/* Next up — header + horizontal scroll cards */}
			<div className="mb-4">
				<div className="flex items-center justify-between mb-2">
					<Skeleton className="h-3 w-20 rounded-full" />
					<Skeleton className="h-3 w-16 rounded-full opacity-60" />
				</div>
				<div className="flex gap-2 overflow-hidden">
					{Array.from({ length: 3 }).map((_, i) => (
						<div
							key={i}
							className={`${panelClass} p-2.5 min-w-[200px] shrink-0 flex gap-2 items-start`}
						>
							<Skeleton className="h-3 w-8 rounded-full opacity-70 shrink-0" />
							<div className="flex-1 flex flex-col gap-1.5 min-w-0">
								<Skeleton className="h-3 w-full rounded-full" />
								<Skeleton className="h-2 w-[60%] rounded-full opacity-50" />
							</div>
							<Skeleton className="h-4 w-12 rounded-full shrink-0" />
						</div>
					))}
				</div>
			</div>

			{/* Top performing — header + 3 row bones */}
			<div>
				<div className="flex items-center justify-between mb-2">
					<Skeleton className="h-3 w-28 rounded-full" />
					<Skeleton className="h-3 w-10 rounded-full opacity-60" />
				</div>
				<div className={`${panelClass} p-3 flex flex-col gap-2.5`}>
					{Array.from({ length: 3 }).map((_, i) => (
						<div
							key={i}
							className={`flex items-center gap-2 py-1 ${i > 0 ? "border-t border-border pt-2.5" : ""}`}
						>
							<Skeleton className="h-2.5 w-3 rounded-full" />
							<Skeleton className="w-[22px] h-[22px] rounded-full shrink-0" />
							<div className="flex-1 flex flex-col gap-1.5">
								<Skeleton className="h-3 w-[60%] rounded-full" />
								<Skeleton className="h-2 w-[40%] rounded-full opacity-60" />
							</div>
							<Skeleton className="h-4 w-12 rounded-full" />
						</div>
					))}
				</div>
			</div>
		</div>
	);
}

function DesktopDashboardSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading dashboard"
			className="hidden lg:block"
			style={{
				paddingTop: 24,
				paddingBottom: 48,
				paddingLeft: 32,
				paddingRight: 32,
				maxWidth: 1400,
				margin: "0 auto",
				width: "100%",
			}}
		>
			{/* Topbar — logo + meta + actions */}
			<div className="flex items-center justify-between mb-5">
				<div className="flex items-center gap-4">
					<Skeleton className="rounded-lg" style={{ width: 36, height: 36 }} />
					<div className="flex flex-col gap-1.5">
						<Skeleton className="h-3.5 w-20 rounded-full" />
						<Skeleton className="h-2 w-44 rounded-full opacity-70" />
					</div>
				</div>
				<div className="flex items-center gap-3">
					<Skeleton className="h-9 w-24 rounded-md" />
					<Skeleton className="h-9 w-28 rounded-md" />
				</div>
			</div>

			{/* Shell row — segmented + horizon + analytics btn */}
			<div className="flex items-center justify-between mb-5">
				<Skeleton className="h-9 w-[200px] rounded-full" />
				<div className="flex items-center gap-3">
					<Skeleton className="h-3 w-14 rounded-full opacity-70" />
					<Skeleton className="h-7 w-40 rounded-full" />
					<Skeleton className="h-9 w-24 rounded-md" />
				</div>
			</div>

			{/* Processing rail — mirrors Dashboard V2's shell/metrics/evidence readout */}
			<div
				className={`${panelClass} mb-4 px-3 py-2.5 flex items-center justify-between gap-4`}
			>
				<div className="flex items-center gap-2.5 min-w-0">
					<Skeleton className="h-2 w-2 rounded-full" />
					<div className="flex flex-col gap-1.5 min-w-0">
						<Skeleton className="h-2.5 w-32 rounded-full" />
						<Skeleton className="h-2 w-[320px] max-w-full rounded-full opacity-70" />
					</div>
				</div>
				<div className="hidden md:flex items-center gap-1.5">
					<Skeleton className="h-6 w-14 rounded-full" />
					<Skeleton className="h-6 w-16 rounded-full" />
					<Skeleton className="h-6 w-16 rounded-full" />
				</div>
			</div>

			{/* Hero — full-width fleet snapshot */}
			<div className={`${panelClass} p-5 mb-3.5`} style={{ minHeight: 200 }}>
				<div className="flex items-start justify-between gap-6">
					<div className="min-w-0 flex-1">
						<Skeleton className="h-2.5 w-40 rounded-full opacity-80 mb-8" />
						<Skeleton className="h-8 w-[340px] max-w-full rounded-[8px] mb-3" />
						<Skeleton className="h-3 w-[520px] max-w-full rounded-full opacity-70 mb-4" />
						<div className="flex gap-2 flex-wrap">
							<Skeleton className="h-7 w-24 rounded-full" />
							<Skeleton className="h-7 w-32 rounded-full" />
							<Skeleton className="h-7 w-24 rounded-full" />
						</div>
					</div>
					<Skeleton className="hidden md:block h-[132px] w-[320px] rounded-lg opacity-80" />
				</div>
				<Skeleton className="h-px w-full rounded-none mt-5 opacity-60" />
				<Skeleton className="h-5 w-48 rounded-full mt-3 ml-auto opacity-70" />
			</div>

			{/* Fundamentals ribbon — 5 small tiles */}
			<div
				className="grid mb-3.5"
				style={{ gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 0 }}
			>
				{Array.from({ length: 5 }).map((_, i) => (
					<div
						key={i}
						className={`${panelClass} p-3.5 flex flex-col gap-2 rounded-none first:rounded-l-xl last:rounded-r-xl`}
						style={{ height: 88 }}
					>
						<Skeleton className="h-2 w-14 rounded-full opacity-80" />
						<Skeleton className="h-5 w-20 rounded-[6px]" />
						<Skeleton className="h-2 w-10 rounded-full opacity-60" />
					</div>
				))}
			</div>

			{/* Bento grid — mirrors the All view band rhythm: 6/3/3, 6/3/3, 4/5/3, 4/4/4 */}
			<section
				className="grid"
				style={{
					gridTemplateColumns: "repeat(12, 1fr)",
					gridAutoRows: 88,
					gap: 14,
				}}
			>
				<BentoPanel col="1 / 7" row="1 / 4" />
				<BentoPanel col="7 / 10" row="1 / 4" compact />
				<BentoPanel col="10 / 13" row="1 / 4" compact />

				<BentoPanel col="1 / 7" row="4 / 7" />
				<BentoPanel col="7 / 10" row="4 / 7" compact />
				<BentoPanel col="10 / 13" row="4 / 7" compact />

				<BentoPanel col="1 / 5" row="7 / 10" compact />
				<BentoPanel col="5 / 10" row="7 / 10" />
				<BentoPanel col="10 / 13" row="7 / 10" compact />

				<BentoPanel col="1 / 5" row="10 / 13" compact />
				<BentoPanel col="5 / 9" row="10 / 13" compact />
				<BentoPanel col="9 / 13" row="10 / 13" compact />
			</section>
		</div>
	);
}

function BentoPanel({
	col,
	row,
	compact = false,
}: {
	col: string;
	row: string;
	compact?: boolean | undefined;
}) {
	return (
		<div
			className={`${panelClass} p-5 flex flex-col gap-2.5`}
			style={{ gridColumn: col, gridRow: row }}
		>
			<Skeleton className="h-2.5 w-24 rounded-full opacity-80" />
			<Skeleton
				className={`${compact ? "h-7 w-24" : "h-8 w-36"} rounded-[6px]`}
			/>
			<Skeleton className="h-2 w-20 rounded-full opacity-60" />
			<div className="mt-auto">
				<Skeleton
					className={`${compact ? "h-10" : "h-14"} w-full rounded-[6px] opacity-70`}
				/>
			</div>
		</div>
	);
}

/* =========================================================================
   Accounts — src/pages/Accounts.tsx
   ========================================================================= */
const ACCOUNTS_GRID =
	"3px 36px minmax(0,1.8fr) 100px 92px 80px 88px 72px 84px 86px";

export function AccountsSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading accounts"
			className={densePageShellClass}
		>
			<PlainHero
				titleW="w-40"
				metaW="w-60"
				actions={<Skeleton className="h-9 w-32 rounded-md" />}
			/>

			<StatStrip />

			{/* Filter bar — search + 3 selects + view toggle */}
			<div className="flex items-center gap-2 mb-4 flex-wrap">
				<Skeleton className="h-9 w-[240px] rounded-md" />
				<Skeleton className="h-9 w-[140px] rounded-md" />
				<Skeleton className="h-9 w-[140px] rounded-md" />
				<Skeleton className="h-9 w-[140px] rounded-md" />
				<Skeleton className="h-9 w-[150px] rounded-md" />
				<div className="ml-auto">
					<Skeleton className="h-9 w-[120px] rounded-md" />
				</div>
			</div>

			{/* Result count */}
			<Skeleton className="h-2.5 w-44 rounded-full opacity-70 mb-3" />

			{/* Table — same column template as ListView */}
			<div className={panelOverflowClass}>
				{/* Header */}
				<div
					className="h-9 grid items-center border-b border-border px-0"
					style={{ gridTemplateColumns: ACCOUNTS_GRID }}
				>
					<div />
					<div />
					<div className="pl-2">
						<Skeleton className="h-2 w-14 rounded-full opacity-70" />
					</div>
					<Skeleton className="h-2 w-12 rounded-full opacity-70" />
					<Skeleton className="h-2 w-12 rounded-full opacity-70" />
					<div className="flex justify-end pr-3">
						<Skeleton className="h-2 w-12 rounded-full opacity-70" />
					</div>
					<div className="flex justify-end pr-3">
						<Skeleton className="h-2 w-14 rounded-full opacity-70" />
					</div>
					<div />
					<div className="flex justify-end pr-3">
						<Skeleton className="h-2 w-12 rounded-full opacity-70" />
					</div>
					<div className="flex justify-end pr-3">
						<Skeleton className="h-2 w-14 rounded-full opacity-70" />
					</div>
				</div>
				{/* Rows */}
				{Array.from({ length: 10 }).map((_, i) => (
					<div
						key={i}
						className="h-10 grid items-center border-b border-[color-mix(in_srgb,var(--color-foreground)_4%,transparent)] dark:border-[color-mix(in_srgb,var(--color-card-elevated)_5%,transparent)] last:border-0"
						style={{ gridTemplateColumns: ACCOUNTS_GRID }}
					>
						<div />
						<div className="flex justify-center">
							<Skeleton className="h-6 w-6 rounded-full" />
						</div>
						<div className="flex items-center gap-2 pl-2">
							<Skeleton className="h-3 w-28 rounded-full" />
						</div>
						<Skeleton className="h-4 w-16 rounded-full" />
						<Skeleton className="h-4 w-14 rounded-full" />
						<div className="flex justify-end pr-3">
							<Skeleton className="h-3 w-10 rounded-full" />
						</div>
						<div className="flex justify-end pr-3">
							<Skeleton className="h-3 w-8 rounded-full" />
						</div>
						<div className="flex justify-end pr-3">
							<Skeleton className="h-3 w-12 rounded-full opacity-70" />
						</div>
						<div className="flex justify-end pr-3">
							<Skeleton className="h-4 w-14 rounded-full" />
						</div>
						<div className="flex justify-end pr-3">
							<Skeleton className="h-3 w-12 rounded-full opacity-70" />
						</div>
					</div>
				))}
			</div>
		</div>
	);
}

/* =========================================================================
   Calendar — src/pages/Calendar.tsx (week view default)
   ========================================================================= */
export function CalendarSkeleton() {
	return (
		<>
			<MobileCalendarSkeleton />
			<DesktopCalendarSkeleton />
		</>
	);
}

/** Mobile shape — agenda-style: hero + day group + 5 post cards stacked. */
function MobileCalendarSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading calendar"
			className="md:hidden min-h-[100dvh] bg-background pb-24 px-4 pt-4"
		>
			{/* Hero */}
			<div className="flex items-center justify-between mb-4">
				<div className="flex flex-col gap-1.5">
					<Skeleton className="h-6 w-32 rounded-[6px]" />
					<Skeleton className="h-3 w-44 rounded-full opacity-70" />
				</div>
				<Skeleton className="w-9 h-9 rounded-full" />
			</div>

			{/* Week nav */}
			<div className="flex items-center justify-between mb-4">
				<Skeleton className="h-8 w-8 rounded-md" />
				<Skeleton className="h-4 w-32 rounded-full" />
				<Skeleton className="h-8 w-8 rounded-md" />
			</div>

			{/* Filter pills */}
			<div className="flex gap-2 mb-5 overflow-hidden">
				{Array.from({ length: 3 }).map((_, i) => (
					<Skeleton key={i} className="h-7 w-[88px] rounded-full" />
				))}
			</div>

			{/* Agenda — 2 day groups, 3 posts each */}
			{Array.from({ length: 2 }).map((_, day) => (
				<div key={day} className="mb-5">
					<Skeleton className="h-3 w-24 rounded-full opacity-80 mb-2.5" />
					<div className="flex flex-col gap-2">
						{Array.from({ length: 3 }).map((_, i) => (
							<div
								key={i}
								className={`${panelClass} p-3 flex gap-3 items-start`}
							>
								<Skeleton className="w-12 h-12 rounded-md shrink-0" />
								<div className="flex-1 flex flex-col gap-1.5 min-w-0">
									<Skeleton className="h-3 w-[80%] rounded-full" />
									<Skeleton className="h-2 w-[50%] rounded-full opacity-60" />
									<div className="flex gap-1.5 pt-0.5">
										<Skeleton className="h-4 w-10 rounded-full" />
										<Skeleton className="h-4 w-12 rounded-full" />
									</div>
								</div>
							</div>
						))}
					</div>
				</div>
			))}
		</div>
	);
}

function DesktopCalendarSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading calendar"
			className={`${pageShellClass} hidden md:block`}
		>
			<PlainHero
				titleW="w-32"
				metaW="w-56"
				actions={
					<>
						<Skeleton className="h-9 w-9 rounded-md" />
						<Skeleton className="h-9 w-9 rounded-md" />
						<Skeleton className="h-9 w-32 rounded-full opacity-80" />
						<Skeleton className="h-9 w-[180px] rounded-md" />
						<Skeleton className="h-9 w-28 rounded-md" />
					</>
				}
			/>

			{/* Filter bar */}
			<div className="flex items-center gap-2 mb-4 flex-wrap">
				<Skeleton className="h-8 w-32 rounded-md" />
				<Skeleton className="h-8 w-32 rounded-md" />
				<Skeleton className="h-8 w-40 rounded-full opacity-80" />
			</div>

			{/* 7-col week grid — column heads + day cells with sample posts */}
			<div className="grid grid-cols-7 gap-2">
				{Array.from({ length: 7 }).map((_, col) => (
					<div key={col} className="flex flex-col gap-2">
						<div
							className={`${panelClass} p-2.5 flex items-center justify-between`}
						>
							<Skeleton className="h-3 w-10 rounded-full" />
							<Skeleton className="h-3 w-6 rounded-full opacity-70" />
						</div>
						{Array.from({ length: 2 + (col % 3) }).map((_, row) => (
							<div
								key={row}
								className={`${panelClass} p-2 flex flex-col gap-1.5`}
							>
								<Skeleton className="h-12 w-full rounded-[6px]" />
								<Skeleton className="h-2 w-[70%] rounded-full opacity-70" />
								<Skeleton className="h-2 w-[40%] rounded-full opacity-50" />
							</div>
						))}
					</div>
				))}
			</div>
		</div>
	);
}

/* =========================================================================
   Inbox — src/pages/Inbox.tsx
   Two-pane card: 340px list | 1fr detail
   ========================================================================= */
export function InboxSkeleton() {
	return (
		<>
			<MobileInboxSkeleton />
			<DesktopInboxSkeleton />
		</>
	);
}

/** Mobile shape — header bar + 8 row bones (avatar + 2 text bones each). */
function MobileInboxSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading inbox"
			className="flex md:hidden min-h-[100dvh] bg-background pb-24 px-4 pt-4 flex-col"
		>
			{/* Header bar — ~48px */}
			<div
				className="flex items-center justify-between mb-4"
				style={{ height: 48 }}
			>
				<div className="flex flex-col gap-1.5">
					<Skeleton className="h-5 w-24 rounded-[6px]" />
					<Skeleton className="h-2.5 w-40 rounded-full opacity-70" />
				</div>
				<Skeleton className="w-9 h-9 rounded-full" />
			</div>

			{/* Row bones */}
			<div className={`${panelClass} p-2 flex-1`}>
				{Array.from({ length: 8 }).map((_, i) => (
					<div key={i} className="flex items-start gap-3 p-2.5 rounded-md">
						<Skeleton className="h-9 w-9 rounded-full shrink-0" />
						<div className="flex-1 flex flex-col gap-1.5 min-w-0">
							<Skeleton className="h-3 w-32 rounded-full" />
							<Skeleton className="h-2.5 w-[80%] rounded-full opacity-70" />
						</div>
					</div>
				))}
			</div>
		</div>
	);
}

function DesktopInboxSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading inbox"
			className={`${densePageShellClass} hidden md:flex h-[calc(100dvh-64px)] flex-col`}
		>
			<OxbloodEyebrowHero
				titleW="w-24"
				metaW="w-72"
				actions={
					<>
						<Skeleton className="h-9 w-[220px] rounded-full" />
						<Skeleton className="h-9 w-[140px] rounded-md" />
					</>
				}
			/>

			{/* Tabs row + Unread toggle */}
			<div className="flex items-center gap-1 mb-4">
				{Array.from({ length: 4 }).map((_, i) => (
					<Skeleton key={i} className="h-9 w-[88px] rounded-full" />
				))}
				<div className="mx-1 w-px h-5 bg-border" aria-hidden="true" />
				<Skeleton className="h-9 w-[120px] rounded-full" />
			</div>

			{/* Two-pane card */}
			<div className={`${panelClass} flex-1 min-h-0 flex`}>
				{/* List */}
				<aside className="w-full md:w-[340px] border-r border-border flex flex-col shrink-0">
					<div className="p-3 border-b border-border">
						<Skeleton className="h-9 w-full rounded-md" />
					</div>
					<div className="flex-1 overflow-hidden p-2 flex flex-col gap-1">
						{Array.from({ length: 8 }).map((_, i) => (
							<div key={i} className="flex items-start gap-3 p-2 rounded-md">
								<Skeleton className="h-9 w-9 rounded-full shrink-0" />
								<div className="flex-1 flex flex-col gap-1.5 min-w-0">
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

				{/* Detail pane */}
				<div className="flex-1 hidden md:flex flex-col">
					<div className="flex items-center gap-3 p-4 border-b border-border">
						<Skeleton className="h-10 w-10 rounded-full shrink-0" />
						<div className="flex-1 flex flex-col gap-1.5">
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
			</div>
		</div>
	);
}

/* =========================================================================
   Reports — src/pages/Reports.tsx
   ========================================================================= */
export function ReportsSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading reports"
			className={densePageShellClass}
		>
			<OxbloodEyebrowHero
				titleW="w-32"
				metaW="w-72"
				actions={<Skeleton className="h-9 w-32 rounded-md" />}
			/>

			{/* Templates rail — 4-col grid (sm:2 / lg:4) */}
			<div className="mb-6">
				<div className="flex items-baseline justify-between mb-3">
					<Skeleton className="h-2 w-32 rounded-full opacity-70" />
					<Skeleton className="h-2 w-16 rounded-full opacity-50" />
				</div>
				<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
					{Array.from({ length: 4 }).map((_, i) => (
						<div key={i} className={`${panelClass} p-4 flex flex-col gap-2`}>
							<Skeleton className="h-4 w-32 rounded-[6px]" />
							<Skeleton className="h-2.5 w-full rounded-full opacity-70" />
							<Skeleton className="h-2.5 w-[70%] rounded-full opacity-50" />
							<div className="pt-2">
								<Skeleton className="h-7 w-24 rounded-md" />
							</div>
						</div>
					))}
				</div>
			</div>

			{/* Filter row — desktop */}
			<div className="hidden md:flex items-center gap-2 mb-4">
				<Skeleton className="h-9 w-[280px] rounded-md" />
				<Skeleton className="h-9 w-[120px] rounded-md" />
				<Skeleton className="h-9 w-[120px] rounded-md" />
				<Skeleton className="h-9 w-[140px] rounded-md" />
				<div className="ml-auto">
					<Skeleton className="h-2 w-32 rounded-full opacity-70" />
				</div>
			</div>

			{/* Filter row — mobile (flex-wrap chips) */}
			<div className="md:hidden flex flex-wrap gap-2 mb-4">
				<Skeleton className="h-9 w-full rounded-md" />
				<Skeleton className="h-8 w-[100px] rounded-full" />
				<Skeleton className="h-8 w-[100px] rounded-full" />
				<Skeleton className="h-8 w-[120px] rounded-full" />
			</div>

			{/* Reports table — column heads + 6 rows */}
			<div className={panelOverflowClass}>
				<header className="px-5 py-4 border-b border-border flex items-center justify-between">
					<Skeleton className="h-2.5 w-28 rounded-full opacity-70" />
					<Skeleton className="h-2 w-20 rounded-full opacity-50" />
				</header>
				<div
					className="hidden md:grid gap-3 px-5 py-2.5 border-b border-border"
					style={{ gridTemplateColumns: "1fr 110px 120px 110px 110px 44px" }}
				>
					<Skeleton className="h-2 w-14 rounded-full opacity-60" />
					<Skeleton className="h-2 w-12 rounded-full opacity-60" />
					<Skeleton className="h-2 w-16 rounded-full opacity-60" />
					<Skeleton className="h-2 w-12 rounded-full opacity-60" />
					<Skeleton className="h-2 w-10 rounded-full opacity-60" />
					<span />
				</div>
				{Array.from({ length: 6 }).map((_, i) => (
					<div
						key={i}
						className="grid gap-3 px-5 py-3.5 items-center border-b border-border last:border-0"
						style={{ gridTemplateColumns: "1fr 110px 120px 110px 110px 44px" }}
					>
						<div className="flex flex-col gap-1.5">
							<Skeleton className="h-3 w-48 rounded-full" />
							<Skeleton className="h-2 w-72 rounded-full opacity-60" />
						</div>
						<Skeleton className="h-5 w-16 rounded-full" />
						<Skeleton className="h-3 w-20 rounded-full opacity-70" />
						<Skeleton className="h-3 w-16 rounded-full opacity-70" />
						<Skeleton className="h-3 w-12 rounded-full opacity-70" />
						<Skeleton className="h-7 w-7 rounded-md ml-auto" />
					</div>
				))}
			</div>
		</div>
	);
}

/* =========================================================================
   Smart Links — src/pages/Links.tsx
   Two-pane: minmax(0,1fr) | minmax(0,1.4fr)  (right pane wider)
   ========================================================================= */
export function SmartLinksSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading smart links"
			className={densePageShellClass}
		>
			<OxbloodEyebrowHero
				titleW="w-40"
				metaW="w-60"
				actions={<Skeleton className="h-9 w-36 rounded-md" />}
			/>

			{/* Filter row */}
			<div className="flex items-center gap-2 mb-4">
				<Skeleton className="h-9 w-[280px] rounded-md" />
				<div className="ml-auto">
					<Skeleton className="h-2 w-28 rounded-full opacity-70" />
				</div>
			</div>

			{/* Top-links analytics strip */}
			<div className={`${panelClass} p-5 mb-4`}>
				<div className="flex items-center justify-between mb-3">
					<Skeleton className="h-3 w-28 rounded-full" />
					<Skeleton className="h-3 w-16 rounded-full opacity-70" />
				</div>
				<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
					{Array.from({ length: 4 }).map((_, i) => (
						<div key={i} className="flex flex-col gap-2">
							<Skeleton className="h-2 w-16 rounded-full opacity-70" />
							<Skeleton className="h-6 w-20 rounded-[6px]" />
							<Skeleton className="h-2 w-14 rounded-full opacity-50" />
						</div>
					))}
				</div>
			</div>

			{/* Disclosure note */}
			<Skeleton className="h-9 w-full rounded-md mb-4 opacity-70" />

			{/* Two-pane: list (1fr) | detail (1.4fr) */}
			<div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-5">
				{/* LEFT — list */}
				<div className={panelOverflowClass}>
					{Array.from({ length: 6 }).map((_, i) => (
						<div
							key={i}
							className="flex items-center gap-3 p-4 border-b border-border last:border-0"
						>
							<Skeleton className="h-9 w-9 rounded-md shrink-0" />
							<div className="flex-1 flex flex-col gap-1.5 min-w-0">
								<Skeleton className="h-3 w-40 rounded-full" />
								<Skeleton className="h-2.5 w-52 rounded-full opacity-70" />
							</div>
							<Skeleton className="h-3 w-12 rounded-full opacity-70" />
							<Skeleton className="h-7 w-7 rounded-md" />
						</div>
					))}
				</div>

				{/* RIGHT — detail */}
				<div className="flex flex-col gap-4">
					<div className={`${panelClass} p-5 flex flex-col gap-3`}>
						<Skeleton className="h-3 w-24 rounded-full" />
						<Skeleton className="h-9 w-full rounded-md" />
						<Skeleton className="h-9 w-full rounded-md" />
						<Skeleton className="h-9 w-full rounded-md" />
						<div className="grid grid-cols-2 gap-2">
							<Skeleton className="h-9 w-full rounded-md" />
							<Skeleton className="h-9 w-full rounded-md" />
						</div>
					</div>
					<div className={`${panelClass} p-5 flex flex-col gap-3`}>
						<Skeleton className="h-3 w-32 rounded-full" />
						<Skeleton className="h-[120px] w-full rounded-[10px]" />
					</div>
				</div>
			</div>
		</div>
	);
}

/* =========================================================================
   Autopilot — src/pages/Autopilot.tsx
   ========================================================================= */
export function AutopilotSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading autopilot"
			className={densePageShellClass}
		>
			<OxbloodEyebrowHero
				titleW="w-32"
				metaW="w-72"
				actions={
					<>
						<Skeleton className="h-9 w-24 rounded-md" />
						<Skeleton className="h-9 w-24 rounded-md" />
					</>
				}
			/>

			{/* 4-card stat strip */}
			<div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
				{Array.from({ length: 4 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-4 flex flex-col gap-2.5`}>
						<div className="flex items-center gap-2">
							<Skeleton className="h-3.5 w-3.5 rounded" />
							<Skeleton className="h-2.5 w-20 rounded-full opacity-80" />
						</div>
						<Skeleton className="h-7 w-16 rounded-[8px]" />
					</div>
				))}
			</div>

			{/* Diagnostic pair — Jobs (1.4fr) | Failures (1fr) */}
			<div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-5 mb-8">
				{/* Jobs */}
				<div className="flex flex-col gap-2.5">
					<div className="flex items-baseline justify-between mb-1">
						<Skeleton className="h-2.5 w-28 rounded-full opacity-80" />
						<Skeleton className="h-2 w-20 rounded-full opacity-60" />
					</div>
					{Array.from({ length: 5 }).map((_, i) => (
						<div key={i} className={`${panelClass} p-4`}>
							<div className="flex items-center justify-between mb-2.5">
								<Skeleton className="h-3 w-32 rounded-full" />
								<Skeleton className="h-5 w-16 rounded-full" />
							</div>
							<Skeleton className="h-2 w-full rounded-full opacity-70 mb-1.5" />
							<Skeleton className="h-2 w-[80%] rounded-full opacity-50" />
						</div>
					))}
				</div>

				{/* Failures feed */}
				<div className="flex flex-col gap-2.5">
					<div className="flex items-baseline justify-between mb-1">
						<Skeleton className="h-2.5 w-20 rounded-full opacity-80" />
						<Skeleton className="h-2 w-24 rounded-full opacity-60" />
					</div>
					{Array.from({ length: 5 }).map((_, i) => (
						<div
							key={i}
							className={`${panelClass} p-3.5 flex items-center gap-3`}
						>
							<Skeleton className="h-2 w-2 rounded-full" />
							<div className="flex-1 flex flex-col gap-1.5">
								<Skeleton className="h-3 w-36 rounded-full" />
								<Skeleton className="h-2 w-52 rounded-full opacity-70" />
							</div>
							<Skeleton className="h-7 w-16 rounded-md" />
						</div>
					))}
				</div>
			</div>

			{/* Queue health */}
			<div className={`${panelClass} p-5 mb-6 flex flex-col gap-3`}>
				<Skeleton className="h-3 w-32 rounded-full mb-2" />
				{Array.from({ length: 4 }).map((_, i) => (
					<div
						key={i}
						className="grid grid-cols-[1fr_80px_2fr_80px] gap-3 items-center py-2"
					>
						<Skeleton className="h-3 w-28 rounded-full" />
						<Skeleton className="h-3 w-12 rounded-full" />
						<Skeleton className="h-2 w-full rounded-full" />
						<Skeleton className="h-7 w-16 rounded-md" />
					</div>
				))}
			</div>

			{/* Rate limits */}
			<div className={`${panelClass} p-5 flex flex-col gap-3`}>
				<Skeleton className="h-3 w-28 rounded-full mb-2" />
				{Array.from({ length: 6 }).map((_, i) => (
					<div
						key={i}
						className="grid grid-cols-[1.5fr_120px_2fr_120px] gap-3 items-center py-2 border-b border-border last:border-0"
					>
						<div className="flex items-center gap-2">
							<Skeleton className="h-2 w-2 rounded-full" />
							<Skeleton className="h-3 w-24 rounded-full" />
						</div>
						<Skeleton className="h-3 w-16 rounded-full" />
						<Skeleton className="h-2 w-full rounded-full" />
						<Skeleton className="h-2.5 w-24 rounded-full opacity-70" />
					</div>
				))}
			</div>
		</div>
	);
}

/* =========================================================================
   Content Library — src/pages/ContentLibrary.tsx (media tab default)
   ========================================================================= */
export function ContentLibrarySkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading content library"
			className={densePageShellClass}
		>
			<OxbloodEyebrowHero
				titleW="w-44"
				metaW="w-64"
				actions={<Skeleton className="h-9 w-36 rounded-md" />}
			/>

			{/* Tab pill segmented (3 tabs) */}
			<div className="inline-flex items-center p-[3px] bg-muted border border-border rounded-md mb-6">
				{Array.from({ length: 3 }).map((_, i) => (
					<Skeleton
						key={i}
						className="h-8 w-[110px] rounded-md mx-[1px] opacity-80"
					/>
				))}
			</div>

			{/* Recent strip — horizontal cards */}
			<div className="mb-6">
				<Skeleton className="h-2 w-24 rounded-full opacity-70 mb-3" />
				<div className="flex gap-3 overflow-hidden">
					{Array.from({ length: 5 }).map((_, i) => (
						<div
							key={i}
							className={`${panelClass} p-2 w-[160px] shrink-0 flex flex-col gap-2`}
						>
							<Skeleton className="aspect-square w-full rounded-[10px]" />
							<Skeleton className="h-2.5 w-[70%] rounded-full" />
						</div>
					))}
				</div>
			</div>

			{/* 3 stat cells */}
			<div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
				{Array.from({ length: 3 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-4 flex flex-col gap-2`}>
						<Skeleton className="h-2.5 w-24 rounded-full opacity-70" />
						<Skeleton className="h-7 w-20 rounded-[8px]" />
						<Skeleton className="h-2 w-32 rounded-full opacity-50" />
					</div>
				))}
			</div>

			{/* Filter row */}
			<div className="flex items-center gap-2 mb-4">
				<Skeleton className="h-9 w-[140px] rounded-md" />
				<Skeleton className="h-9 w-[140px] rounded-md" />
				<div className="ml-auto">
					<Skeleton className="h-9 w-[140px] rounded-md" />
				</div>
			</div>

			{/* Media grid — 4 col × 2 rows */}
			<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
				{Array.from({ length: 8 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-3 flex flex-col gap-2`}>
						<Skeleton className="aspect-square w-full rounded-[10px]" />
						<Skeleton className="h-2.5 w-[70%] rounded-full" />
						<Skeleton className="h-2 w-[40%] rounded-full opacity-70" />
					</div>
				))}
			</div>
		</div>
	);
}

/* =========================================================================
   Analytics — src/pages/Analytics.tsx (analytics-v2)
   ========================================================================= */
export function AnalyticsSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading analytics"
			className={`${densePageShellClass} flex flex-col gap-4`}
		>
			{/* Hero — title + scope chip + meta on left, NL bar / export / date chip on right */}
			<header className="flex flex-col md:flex-row md:items-end md:justify-between gap-5">
				<div>
					<Skeleton className="h-8 w-36 rounded-[8px]" />
					<div className="flex items-center gap-2 mt-1.5">
						<Skeleton className="h-5 w-24 rounded-full" />
						<span
							className="w-1 h-1 rounded-full bg-label-quaternary"
							aria-hidden="true"
						/>
						<Skeleton className="h-3 w-28 rounded-full opacity-70" />
					</div>
				</div>
				<div className="flex items-center gap-2">
					<Skeleton className="h-9 w-[260px] rounded-md" />
					<Skeleton className="h-9 w-24 rounded-md" />
					<Skeleton className="h-9 w-32 rounded-md" />
				</div>
			</header>

			{/* Shell row — segmented + compare + cohort + saved views */}
			<div className="flex items-center justify-between gap-3 flex-wrap">
				<div className="flex items-center gap-2">
					<Skeleton className="h-9 w-[200px] rounded-full" />
					<Skeleton className="h-9 w-[120px] rounded-md" />
					<Skeleton className="h-9 w-[140px] rounded-md" />
				</div>
				<Skeleton className="h-9 w-[120px] rounded-md" />
			</div>

			{/* KPI strip — 4 tiles (default 'all' view) */}
			<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
				{Array.from({ length: 4 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-4 flex flex-col gap-2.5`}>
						<Skeleton className="h-2.5 w-20 rounded-full" />
						<Skeleton className="h-8 w-24 rounded-[8px]" />
						<Skeleton className="h-2 w-28 rounded-full opacity-70" />
						<Skeleton className="h-3 w-16 rounded-full opacity-60" />
					</div>
				))}
			</div>

			<main className="flex flex-col gap-4">
				{/* Hero tile + insights rail (340px) */}
				<section
					className="grid gap-4 items-stretch"
					style={{ gridTemplateColumns: "minmax(0, 1fr) 340px" }}
				>
					<div
						className={`${panelClass} p-5 flex min-h-[300px] flex-col gap-3`}
					>
						<Skeleton className="h-3 w-32 rounded-full" />
						<Skeleton className="h-12 w-40 rounded-[8px]" />
						<Skeleton className="h-3 w-28 rounded-full opacity-70" />
						<Skeleton className="h-[180px] w-full rounded-[10px] mt-auto" />
					</div>
					<div
						className={`${panelClass} p-5 flex min-h-[300px] flex-col gap-3`}
					>
						<Skeleton className="h-3 w-28 rounded-full" />
						{Array.from({ length: 5 }).map((_, i) => (
							<div key={i} className="flex flex-col gap-1.5">
								<Skeleton className="h-3 w-full rounded-full opacity-80" />
								<Skeleton className="h-2 w-[70%] rounded-full opacity-50" />
							</div>
						))}
					</div>
				</section>

				{/* Insight feed row — 3 equal cards */}
				<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
					{Array.from({ length: 3 }).map((_, i) => (
						<div key={i} className={`${panelClass} p-5 flex flex-col gap-2.5`}>
							<Skeleton className="h-2.5 w-24 rounded-full opacity-80" />
							<Skeleton className="h-7 w-32 rounded-[8px]" />
							<Skeleton className="h-3 w-full rounded-full opacity-70" />
							<Skeleton className="h-3 w-[80%] rounded-full opacity-50" />
						</div>
					))}
				</div>

				{/* Anomaly grid — full-width data surface */}
				<div className={`${panelClass} p-5 flex flex-col gap-3`}>
					<div className="flex items-center justify-between">
						<Skeleton className="h-3 w-32 rounded-full" />
						<Skeleton className="h-3 w-20 rounded-full opacity-60" />
					</div>
					<div className="grid grid-cols-6 md:grid-cols-12 gap-1.5">
						{Array.from({ length: 48 }).map((_, i) => (
							<Skeleton
								key={i}
								className="aspect-square rounded-[4px]"
								style={{ opacity: 0.35 + ((i * 13) % 50) / 100 }}
							/>
						))}
					</div>
				</div>

				{/* Auto-insights */}
				<div className={`${panelClass} p-5 flex flex-col gap-3`}>
					<Skeleton className="h-3 w-36 rounded-full" />
					{Array.from({ length: 3 }).map((_, i) => (
						<div
							key={i}
							className="flex items-start gap-3 py-2 border-b border-border last:border-0"
						>
							<Skeleton className="h-7 w-7 rounded-full shrink-0" />
							<div className="flex-1 flex flex-col gap-1.5">
								<Skeleton className="h-3 w-[70%] rounded-full" />
								<Skeleton className="h-2.5 w-[90%] rounded-full opacity-60" />
							</div>
							<Skeleton className="h-5 w-16 rounded-full" />
						</div>
					))}
				</div>

				{/* Evidence rows — stacked pairs */}
				{Array.from({ length: 2 }).map((_, row) => (
					<div key={row} className="grid grid-cols-1 md:grid-cols-2 gap-4">
						{Array.from({ length: 2 }).map((_, col) => (
							<div
								key={col}
								className={`${panelClass} p-5 flex flex-col gap-3`}
							>
								<Skeleton className="h-3 w-32 rounded-full" />
								<Skeleton className="h-7 w-24 rounded-[8px]" />
								<Skeleton className="h-[140px] w-full rounded-[10px] opacity-70" />
							</div>
						))}
					</div>
				))}
			</main>
		</div>
	);
}

/* =========================================================================
   Attribution — src/pages/Attribution.tsx
   ========================================================================= */
export function AttributionSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading attribution"
			className={pageShellClass}
		>
			<PlainHero
				titleW="w-40"
				metaW="w-72"
				actions={
					<>
						<Skeleton className="h-9 w-32 rounded-md" />
						<Skeleton className="h-11 w-[140px] rounded-md" />
					</>
				}
			/>

			{/* Summary tiles */}
			<div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
				{Array.from({ length: 4 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-5 flex flex-col gap-2`}>
						<Skeleton className="h-2 w-24 rounded-full opacity-70" />
						<Skeleton className="h-7 w-20 rounded-[8px]" />
						<Skeleton className="h-2.5 w-28 rounded-full opacity-50" />
					</div>
				))}
			</div>

			{/* Confidence card */}
			<div
				className={`${panelClass} p-5 mb-6 flex flex-col md:flex-row gap-4 items-start`}
			>
				<div className="flex flex-col gap-2">
					<Skeleton className="h-2 w-24 rounded-full opacity-70" />
					<div className="flex items-center gap-3">
						<Skeleton className="h-7 w-20 rounded-[8px]" />
						<Skeleton className="h-6 w-32 rounded-full" />
					</div>
				</div>
				<div className="flex-1 min-w-[240px] flex flex-col gap-1.5">
					<Skeleton className="h-2 w-12 rounded-full opacity-70" />
					{Array.from({ length: 3 }).map((_, i) => (
						<Skeleton
							key={i}
							className="h-2.5 w-full rounded-full opacity-60"
						/>
					))}
				</div>
			</div>

			{/* Chart card */}
			<div className={`${panelClass} p-5 mb-4 flex flex-col gap-3`}>
				<Skeleton className="h-2.5 w-48 rounded-full opacity-70" />
				<Skeleton className="h-[260px] w-full rounded-[10px]" />
			</div>

			{/* Top converters */}
			<div className={`${panelClass} p-5 mb-4 flex flex-col gap-3`}>
				<Skeleton className="h-2.5 w-40 rounded-full opacity-70" />
				{Array.from({ length: 5 }).map((_, i) => (
					<div
						key={i}
						className="flex items-start justify-between gap-4 py-2 border-b border-border last:border-0"
					>
						<div className="flex-1 flex flex-col gap-1.5">
							<Skeleton className="h-3 w-[80%] rounded-full" />
							<Skeleton className="h-2 w-32 rounded-full opacity-60" />
						</div>
						<Skeleton className="h-4 w-14 rounded-full" />
					</div>
				))}
			</div>

			{/* Days that moved the needle */}
			<div className={`${panelClass} p-5 mb-4 flex flex-col gap-3`}>
				<Skeleton className="h-2.5 w-44 rounded-full opacity-70" />
				{Array.from({ length: 5 }).map((_, i) => (
					<div
						key={i}
						className="grid grid-cols-[72px_1fr] gap-3 py-2 border-b border-border last:border-0"
					>
						<div className="flex flex-col gap-1">
							<Skeleton className="h-2 w-12 rounded-full opacity-70" />
							<Skeleton className="h-5 w-14 rounded-[6px]" />
						</div>
						<div className="flex flex-col gap-1.5">
							<Skeleton className="h-3 w-[85%] rounded-full" />
							<Skeleton className="h-2 w-20 rounded-full opacity-60" />
						</div>
					</div>
				))}
			</div>

			{/* Methodology */}
			<div className={`${panelClass} p-5 flex flex-col gap-2`}>
				<Skeleton className="h-2.5 w-36 rounded-full opacity-70" />
				<Skeleton className="h-3 w-full rounded-full opacity-60" />
				<Skeleton className="h-3 w-full rounded-full opacity-60" />
				<Skeleton className="h-3 w-[80%] rounded-full opacity-60" />
			</div>
		</div>
	);
}

/* =========================================================================
   Settings — src/pages/Settings.tsx
   232px sidebar (desktop) | main panel
   ========================================================================= */
export function SettingsSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading settings"
			className="flex min-h-full w-full flex-col bg-background text-foreground md:flex-row"
		>
			{/* Desktop sidebar */}
			<nav className="hidden md:flex w-[232px] shrink-0 border-r border-border flex-col py-5 px-3 gap-4 sticky top-12 self-start max-h-[calc(100dvh-48px)]">
				{Array.from({ length: 3 }).map((_, group) => (
					<div key={group}>
						<Skeleton className="h-2 w-16 rounded-full opacity-60 mb-2" />
						<div className="flex flex-col gap-0.5">
							{Array.from({ length: 4 }).map((_, t) => (
								<div
									key={t}
									className="h-8 px-2.5 flex items-center gap-2.5 rounded-md"
								>
									<Skeleton className="w-3.5 h-3.5 rounded-sm" />
									<Skeleton className="h-3 w-24 rounded-full opacity-80" />
								</div>
							))}
						</div>
					</div>
				))}
			</nav>

			{/* Mobile horizontal tabs */}
			<nav className="flex md:hidden gap-1 px-3 py-2 border-b border-border overflow-hidden shrink-0">
				{Array.from({ length: 6 }).map((_, i) => (
					<Skeleton key={i} className="h-7 w-[100px] rounded-full shrink-0" />
				))}
			</nav>

			{/* Main panel */}
			<main className="flex-1 px-6 md:px-10 pt-7 pb-16 w-full">
				<div className="mb-8">
					<Skeleton className="h-7 w-44 rounded-[8px]" />
					<Skeleton className="mt-2 h-3 w-80 rounded-full opacity-70" />
				</div>

				{/* Setting groups — 3 sections × form rows */}
				{Array.from({ length: 3 }).map((_, section) => (
					<div key={section} className={`${panelClass} p-5 mb-5`}>
						<Skeleton className="h-3 w-32 rounded-full mb-1" />
						<Skeleton className="h-2.5 w-60 rounded-full opacity-70 mb-4" />
						<div className="flex flex-col gap-4">
							{Array.from({ length: 3 }).map((_, row) => (
								<div
									key={row}
									className="flex items-center justify-between gap-4 py-2 border-b border-border last:border-0"
								>
									<div className="flex-1 flex flex-col gap-1.5">
										<Skeleton className="h-3 w-40 rounded-full" />
										<Skeleton className="h-2 w-72 rounded-full opacity-60" />
									</div>
									<Skeleton className="h-9 w-[160px] rounded-md" />
								</div>
							))}
						</div>
					</div>
				))}
			</main>
		</div>
	);
}

/* =========================================================================
   Billing — src/pages/Billing.tsx
   ========================================================================= */
export function BillingSkeleton() {
	return (
		<div role="status" aria-label="Loading billing" className={pageShellClass}>
			<div className="mb-8">
				<Skeleton className="h-7 w-48 rounded-[8px]" />
				<Skeleton className="mt-2 h-3 w-[60ch] max-w-full rounded-full opacity-70" />
			</div>

			{/* Plan + payment grid */}
			<div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-10">
				{/* Current plan + usage (2-col) */}
				<div className={`${panelClass} p-5 lg:col-span-2 flex flex-col gap-5`}>
					<div className="flex items-center justify-between">
						<div className="flex flex-col gap-1.5">
							<Skeleton className="h-2.5 w-24 rounded-full opacity-70" />
							<Skeleton className="h-5 w-40 rounded-[6px]" />
							<Skeleton className="h-2.5 w-56 rounded-full opacity-60" />
						</div>
						<Skeleton className="h-[22px] w-20 rounded-full" />
					</div>

					{/* Usage bars */}
					{Array.from({ length: 2 }).map((_, i) => (
						<div key={i} className="flex flex-col gap-2">
							<div className="flex items-center justify-between">
								<Skeleton className="h-3 w-32 rounded-full" />
								<Skeleton className="h-3 w-16 rounded-full opacity-70" />
							</div>
							<Skeleton className="h-2 w-full rounded-full" />
						</div>
					))}
				</div>

				{/* Payment method (1-col) */}
				<div className={`${panelClass} p-5 flex flex-col gap-3`}>
					<Skeleton className="h-2.5 w-28 rounded-full opacity-70" />
					<div className="flex items-center gap-3 mt-2">
						<Skeleton className="w-10 h-7 rounded-md" />
						<div className="flex-1 flex flex-col gap-1.5">
							<Skeleton className="h-3 w-32 rounded-full" />
							<Skeleton className="h-2 w-20 rounded-full opacity-60" />
						</div>
					</div>
					<Skeleton className="h-9 w-full rounded-md mt-2" />
				</div>
			</div>

			{/* Plan picker — 3 cards across */}
			<div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
				{Array.from({ length: 3 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-5 flex flex-col gap-3`}>
						<Skeleton className="h-3 w-24 rounded-full" />
						<Skeleton className="h-9 w-32 rounded-[8px]" />
						<Skeleton className="h-2.5 w-40 rounded-full opacity-60" />
						<div className="flex flex-col gap-2 pt-2">
							{Array.from({ length: 4 }).map((_, j) => (
								<div key={j} className="flex items-center gap-2">
									<Skeleton className="w-3 h-3 rounded-full" />
									<Skeleton className="h-2.5 w-[70%] rounded-full opacity-70" />
								</div>
							))}
						</div>
						<Skeleton className="h-9 w-full rounded-md mt-2" />
					</div>
				))}
			</div>

			{/* Invoice history */}
			<div className={panelOverflowClass}>
				<div className="px-5 py-4 border-b border-border">
					<Skeleton className="h-3 w-32 rounded-full" />
				</div>
				{Array.from({ length: 5 }).map((_, i) => (
					<div
						key={i}
						className="px-5 py-3.5 flex items-center gap-4 border-b border-border last:border-0"
					>
						<div className="flex-1 flex flex-col gap-1.5">
							<Skeleton className="h-3 w-40 rounded-full" />
							<Skeleton className="h-2 w-24 rounded-full opacity-60" />
						</div>
						<Skeleton className="h-3 w-16 rounded-full" />
						<Skeleton className="h-7 w-7 rounded-md" />
					</div>
				))}
			</div>
		</div>
	);
}

/* =========================================================================
   Composer — src/pages/Composer.tsx
   1.5fr editor | 1fr settings sidebar
   ========================================================================= */
export function ComposerSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading composer"
			className={composerPageShellClass}
		>
			<div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-6">
				{/* Editor panel */}
				<div className="flex flex-col gap-5 min-w-0">
					{/* Targeting */}
					<div className={`${panelClass} p-4 flex flex-col gap-3`}>
						<Skeleton className="h-2 w-24 rounded-full opacity-70" />
						<div className="flex flex-wrap gap-1.5">
							{Array.from({ length: 4 }).map((_, i) => (
								<Skeleton key={i} className="h-7 w-[110px] rounded-full" />
							))}
							<Skeleton className="h-7 w-[120px] rounded-full opacity-60" />
						</div>
					</div>

					{/* Editor textarea */}
					<div className={`${panelClass} p-4 flex flex-col gap-3`}>
						<div className="flex items-center justify-between">
							<Skeleton className="h-2 w-20 rounded-full opacity-70" />
							<Skeleton className="h-2 w-12 rounded-full opacity-50" />
						</div>
						<Skeleton className="h-[180px] w-full rounded-md" />
						{/* Toolbar */}
						<div className="flex items-center gap-1.5">
							{Array.from({ length: 6 }).map((_, i) => (
								<Skeleton key={i} className="h-8 w-8 rounded-md" />
							))}
							<div className="ml-auto">
								<Skeleton className="h-8 w-24 rounded-md" />
							</div>
						</div>
					</div>

					{/* Media area */}
					<div className={`${panelClass} p-4 flex flex-col gap-3`}>
						<Skeleton className="h-2 w-24 rounded-full opacity-70" />
						<div className="grid grid-cols-4 gap-2">
							{Array.from({ length: 4 }).map((_, i) => (
								<Skeleton
									key={i}
									className="aspect-square rounded-md opacity-70"
								/>
							))}
						</div>
					</div>
				</div>

				{/* Settings sidebar */}
				<div className="flex flex-col gap-5">
					{/* Schedule */}
					<div className={`${panelClass} p-4 flex flex-col gap-3`}>
						<Skeleton className="h-2 w-20 rounded-full opacity-70" />
						<div className="flex gap-2">
							<Skeleton className="h-9 w-full rounded-md" />
							<Skeleton className="h-9 w-full rounded-md" />
						</div>
					</div>

					{/* Advanced */}
					{Array.from({ length: 3 }).map((_, i) => (
						<div key={i} className={`${panelClass} p-4 flex flex-col gap-2.5`}>
							<div className="flex items-center justify-between">
								<Skeleton className="h-3 w-28 rounded-full" />
								<Skeleton className="h-5 w-9 rounded-full" />
							</div>
							<Skeleton className="h-2 w-[80%] rounded-full opacity-50" />
						</div>
					))}

					{/* Action buttons */}
					<div className="flex gap-2">
						<Skeleton className="h-10 w-full rounded-md" />
						<Skeleton className="h-10 w-full rounded-md" />
					</div>
				</div>
			</div>
		</div>
	);
}

/* =========================================================================
   Welcome — src/pages/auth/Welcome.tsx (onboarding wizard)
   Single centered card with progress bar + step content
   ========================================================================= */
export function WelcomeSkeleton() {
	return (
		<div
			role="status"
			aria-label="Loading welcome"
			className="w-full max-w-xl bg-card border border-border rounded-[24px] overflow-hidden mx-auto"
		>
			{/* Progress bar */}
			<Skeleton className="h-[3px] w-full rounded-none opacity-50" />

			{/* Step indicator */}
			<div className="flex items-center justify-between px-6 pt-5">
				<Skeleton className="h-2 w-24 rounded-full opacity-70" />
				<Skeleton className="h-3 w-20 rounded-full opacity-50" />
			</div>

			{/* Step body */}
			<div className="px-6 py-6 flex flex-col gap-6">
				<div className="flex flex-col gap-2">
					<Skeleton className="h-7 w-[80%] rounded-[8px]" />
					<Skeleton className="h-3 w-full rounded-full opacity-70" />
					<Skeleton className="h-3 w-[60%] rounded-full opacity-60" />
				</div>

				{/* Two connect buttons */}
				<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
					{Array.from({ length: 2 }).map((_, i) => (
						<div
							key={i}
							className={`${panelClass} p-4 flex items-center gap-3`}
						>
							<Skeleton className="w-10 h-10 rounded-md" />
							<div className="flex-1 flex flex-col gap-1.5">
								<Skeleton className="h-3 w-20 rounded-full" />
								<Skeleton className="h-2 w-32 rounded-full opacity-60" />
							</div>
						</div>
					))}
				</div>

				{/* Footer buttons */}
				<div className="flex items-center justify-between pt-2">
					<Skeleton className="h-9 w-20 rounded-md" />
					<Skeleton className="h-9 w-28 rounded-md" />
				</div>
			</div>
		</div>
	);
}

/* =========================================================================
   AuthCheckingFallback — for ProtectedLayout's auth-check state and other
   short transitional gates. Tiny centered indicator. Used as the
   ultimate fallback in App.tsx's PageLoader.
   ========================================================================= */
export function AuthCheckingFallback() {
	return (
		<div
			role="status"
			aria-label="Checking session"
			className="flex-1 w-full p-8 max-w-[1400px] mx-auto"
		>
			<div className="flex items-center justify-between mb-8">
				<div className="flex flex-col gap-2">
					<Skeleton className="w-44 h-8 rounded-[8px]" />
					<Skeleton className="w-64 h-3 rounded-full opacity-70" />
				</div>
			</div>
			<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
				{Array.from({ length: 4 }).map((_, i) => (
					<div key={i} className={`${panelClass} p-5 flex flex-col gap-2.5`}>
						<Skeleton className="h-2.5 w-20 rounded-full" />
						<Skeleton className="h-7 w-24 rounded-[8px]" />
						<Skeleton className="h-2 w-16 rounded-full opacity-60" />
					</div>
				))}
			</div>
		</div>
	);
}
