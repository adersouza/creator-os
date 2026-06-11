// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type React from "react";
import {
	lazy,
	Suspense,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useSearchParams } from "react-router-dom";
import {
	Search,
	Plus,
	Download,
	Share2,
	Copy,
	Trash2,
	Clock,
	FileText,
	Calendar as CalendarIcon,
	Sparkles,
	Check,
	ChevronRight,
	Loader2,
	AlertTriangle,
	Send,
} from "lucide-react";
import { z } from "zod";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { Input } from "@/components/ui/Input";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Kbd, KbdGroup } from "@/components/ui/Kbd";
import {
	NovaCard,
	NovaEmpty,
	NovaHeader,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { StatusPill as UIStatusPill } from "@/components/ui/StatusPill";
import { DataTable } from "@/components/ui/DataTable";
import { cn } from "@/lib/utils";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useAccountGroups } from "@/hooks/useAccountGroups";
import {
	useReports,
	type ReportRow,
	type ReportCadence,
	type ReportStatus,
	type ReportType,
} from "@/hooks/useReports";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { ReportsSkeleton } from "@/components/skeletons/PageSkeletons";
import { apiFetch } from "@/lib/apiFetch";
import { appToast } from "@/lib/toast";
import { randomUUID } from "@/lib/uuid";
import { shareOrCopy } from "@/utils/share";
import { downloadReportPdf } from "@/services/api/reportsPdf";
import { supabase } from "@/services/supabase";
import { groupColorFromId, groupLabelFromId } from "@/lib/groupPresentation";

/* =========================================================================
   Reports — scheduled + one-off PDF generators, white-labeled for clients
   Matches Inbox / Links / Analytics register (eyebrow labels, solid .card,
   FilterSelect, tabular-nums, signature motion).
   Keyboard: J/K navigate rows · Esc deselect.
   ========================================================================= */

type Cadence = ReportCadence;

const sendSchema = z
	.object({ success: z.boolean().optional(), delivered: z.number().optional() })
	.passthrough();

interface Report {
	id: string;
	name: string;
	type: ReportType;
	cadence: Cadence;
	status: ReportStatus;
	network: string | "all";
	recipients: number;
	lastRun: string;
	nextRun: string;
	shared: boolean;
	accountIds: string[];
	lastDeliveryStatus: "sent" | "failed" | "skipped" | null;
	lastDeliveryError: string | null;
	lastDeliveryAt: string;
}

function coerceNetwork(value: string | null): string | "all" {
	if (!value) return "all";
	return value;
}

const DATE_FMT = new Intl.DateTimeFormat(undefined, {
	month: "short",
	day: "numeric",
});

function formatRunDate(iso: string | null): string {
	if (!iso) return "—";
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return "—";
	return DATE_FMT.format(date);
}

function readReportAccountIds(config: Record<string, unknown>): string[] {
	const raw = config.accountIds;
	if (!Array.isArray(raw)) return [];
	return raw.filter(
		(id): id is string => typeof id === "string" && id.length > 0,
	);
}

function rowToReport(row: ReportRow): Report {
	return {
		id: row.id,
		name: row.name,
		type: row.type,
		cadence: row.cadence,
		status: row.status,
		network: coerceNetwork(row.network),
		recipients: row.recipients.length,
		lastRun: formatRunDate(row.lastRunAt),
		nextRun: row.type === "one-off" ? "—" : formatRunDate(row.nextRunAt),
		shared: row.recipients.length > 0,
		accountIds: readReportAccountIds(row.config),
		lastDeliveryStatus: row.lastDeliveryStatus,
		lastDeliveryError: row.lastDeliveryError,
		lastDeliveryAt: formatRunDate(row.lastDeliveryAt),
	};
}

interface SharedReportPayload {
	reportId: string;
	name: string;
	headline: string;
	description: string;
	stats: Array<{ label: string; value: string }>;
}

interface Template {
	id: string;
	name: string;
	description: string;
	cadence: Cadence;
	swatches: [string, string, string];
	recommended?: boolean | undefined;
}

const STATUS_META: Record<
	ReportStatus,
	{ label: string; tone: "good" | "info" | "oxblood" | "warn" }
> = {
	active: { label: "Active", tone: "good" },
	paused: { label: "Paused", tone: "info" },
	generated: { label: "Generated", tone: "oxblood" },
	draft: { label: "Draft", tone: "warn" },
};

const ReportEditor = lazy(() =>
	import("@/components/reports/ReportEditor").then((m) => ({
		default: m.ReportEditor,
	})),
);

const TEMPLATES: Template[] = [
	{
		id: "t1",
		name: "Monthly engagement summary",
		description:
			"EQS trend · top/bottom posts · audience growth · competitor bar",
		cadence: "monthly",
		swatches: ["#1A1A1C", "#E5484D", "#F4F4F2"],
		recommended: true,
	},
	{
		id: "t2",
		name: "Weekly executive briefing",
		description:
			"One-page TL;DR · 5 KPIs · AI-written commentary · 3 next actions",
		cadence: "weekly",
		swatches: ["#1A1A1C", "#A67C2D", "#FFFFFF"],
	},
	{
		id: "t3",
		name: "Creator benchmark",
		description:
			"Percentile vs. agency cohort · content-type mix · posting heatmap",
		cadence: "quarterly",
		swatches: ["#5F6670", "#E5484D", "#F4F4F2"],
	},
	{
		id: "t4",
		name: "Client campaign recap",
		description:
			"Campaign window · reach · sends+saves · link CTR · ROAS proxy",
		cadence: "one-off",
		swatches: ["#6F7078", "#E5484D", "#FFFFFF"],
	},
];

/* =========================================================================
   HELPERS
   ========================================================================= */

function CadenceIcon({ cadence }: { cadence: Cadence }) {
	if (cadence === "one-off")
		return <FileText className="w-3 h-3" aria-hidden="true" />;
	return <Clock className="w-3 h-3" aria-hidden="true" />;
}

function StatusPill({ status }: { status: ReportStatus }) {
	const meta = STATUS_META[status];
	return (
		<UIStatusPill
			tone={meta.tone}
			size="xs"
			dot
			className="!rounded-[var(--surface-control-radius)]"
		>
			{meta.label}
		</UIStatusPill>
	);
}

/* =========================================================================
   COMPONENT
   ========================================================================= */
export function Reports() {
	const [searchParams, setSearchParams] = useSearchParams();
	const { accounts, isLoading: accountsLoading } = useConnectedAccounts();
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const { groups } = useAccountGroups();
	const hasAccounts = accounts.length > 0;
	const {
		reports: reportRows,
		isLoading: reportsLoading,
		createReport: createReportRow,
		deleteReport: deleteReportRow,
		duplicateReport: duplicateReportRow,
		refetch: refetchReports,
	} = useReports();
	const groupMetaById = useMemo(
		() =>
			new Map(
				groups.map((group) => [
					group.id,
					{ name: group.name, color: group.color },
				]),
			),
		[groups],
	);
	const reports = useMemo(() => reportRows.map(rowToReport), [reportRows]);
	const scopedReports = useMemo(() => {
		if (!scopedAccount) return reports;
		return reports.filter(
			(report) =>
				report.accountIds.length === 0 ||
				report.accountIds.includes(scopedAccount.id),
		);
	}, [reports, scopedAccount]);
	const isFirstLoad =
		(reportsLoading || accountsLoading) &&
		reportRows.length === 0 &&
		accounts.length === 0;
	const [type, setType] = useState<"all" | ReportType>("all");
	const [status, setStatus] = useState<"all" | ReportStatus>("all");
	const [network, setNetwork] = useState<"all" | string>("all");
	const [search, setSearch] = useState("");
	const [activeId, setActiveId] = useState<string | null>(null);
	const [editorId, setEditorId] = useState<string | null>(null);
	const [copiedId, setCopiedId] = useState<string | null>(null);
	const [downloadingId, setDownloadingId] = useState<string | null>(null);
	const [sendingId, setSendingId] = useState<string | null>(null);
	const [downloadError, setDownloadError] = useState<string | null>(null);
	const [sendError, setSendError] = useState<string | null>(null);
	const copyResetTimerRef = useRef<number | null>(null);
	const editorReport = useMemo(
		() => reportRows.find((report) => report.id === editorId) ?? null,
		[editorId, reportRows],
	);

	const filtered = useMemo(() => {
		const q = search.trim().toLowerCase();
		return scopedReports.filter((r) => {
			if (type !== "all" && r.type !== type) return false;
			if (status !== "all" && r.status !== status) return false;
			if (network !== "all" && r.network !== network) return false;
			if (q && !r.name.toLowerCase().includes(q)) return false;
			return true;
		});
	}, [scopedReports, type, status, network, search]);

	const stats = useMemo(() => {
		const active = scopedReports.filter((r) => r.status === "active").length;
		const scheduled = scopedReports.filter(
			(r) => r.type === "scheduled",
		).length;
		const sharedLinks = scopedReports.filter((r) => r.shared).length;
		const deliveryIssues = scopedReports.filter(
			(r) => r.lastDeliveryStatus === "failed",
		).length;
		return { active, scheduled, sharedLinks, deliveryIssues };
	}, [scopedReports]);

	useEffect(() => {
		const reportId = searchParams.get("report");
		if (!reportId) return;
		if (reports.some((report) => report.id === reportId)) {
			setActiveId(reportId);
		}
	}, [searchParams, reports]);

	const deleteReport = useCallback(
		(id: string) => {
			void deleteReportRow(id);
			if (activeId === id) setActiveId(null);
		},
		[activeId, deleteReportRow],
	);

	const duplicateReport = useCallback(
		(id: string) => {
			void duplicateReportRow(id);
		},
		[duplicateReportRow],
	);

	const createReport = useCallback(
		async (template?: Template) => {
			const created = await createReportRow({
				name: template?.name ?? "Untitled report",
				type: template?.cadence === "one-off" ? "one-off" : "scheduled",
				cadence: template?.cadence ?? "monthly",
				status: "draft",
				network: null,
				recipients: [],
			});
			if (!created) {
				appToast.error("Could not create report", {
					description: "Try again in a moment.",
				});
				return;
			}
			setActiveId(created.id);
			setEditorId(created.id);
			appToast.success(
				template ? `${template.name} created` : "Report created",
			);
		},
		[createReportRow],
	);

	useEffect(() => {
		if (searchParams.get("new") !== "1") return;
		void createReport().then(() => {
			setSearchParams(
				(prev) => {
					const next = new URLSearchParams(prev);
					next.delete("new");
					return next;
				},
				{ replace: true },
			);
		});
	}, [createReport, searchParams, setSearchParams]);

	const downloadReport = useCallback(
		async (id: string) => {
			if (downloadingId) return;
			setDownloadError(null);
			setDownloadingId(id);
			const result = await downloadReportPdf(id);
			setDownloadingId(null);
			if (!result.ok) {
				setDownloadError(result.error ?? "Try again in a moment.");
				appToast.error("Could not generate report", {
					description: result.error ?? "Try again in a moment.",
				});
				return;
			}
			appToast.success("Report downloaded");
			// Backend stamped last_run_at + status; pull the fresh row.
			refetchReports();
		},
		[downloadingId, refetchReports],
	);

	const retryReportDelivery = useCallback(
		async (id: string) => {
			if (sendingId) return;
			const report = reports.find((item) => item.id === id);
			setSendError(null);
			setSendingId(id);
			try {
				const result = await apiFetch("/api/reports?action=send", sendSchema, {
					method: "POST",
					json: { report_id: id },
				});
				appToast.success(
					`Report delivery retried${typeof result.delivered === "number" ? ` · ${result.delivered} sent` : ""}`,
				);
				refetchReports();
			} catch (error) {
				const message =
					error instanceof Error ? error.message : "Try again in a moment.";
				setSendError(report?.name ? `${report.name}: ${message}` : message);
				appToast.error("Could not retry report delivery", {
					description: message,
				});
			} finally {
				setSendingId(null);
			}
		},
		[refetchReports, reports, sendingId],
	);

	const copyShareUrl = useCallback(
		async (id: string) => {
			const sourceRow = reportRows.find((row) => row.id === id);
			const sourceReport = reports.find((report) => report.id === id);
			if (!sourceRow || !sourceReport) {
				appToast.error("Could not create share link", {
					description: "Report data is still loading.",
				});
				return;
			}
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) {
				appToast.error("Could not create share link", {
					description: "You need to be signed in.",
				});
				return;
			}

			const snapshot: SharedReportPayload = {
				reportId: sourceRow.id,
				name: sourceRow.name,
				headline: sourceRow.name,
				description:
					sourceRow.type === "one-off"
						? `One-off ${sourceRow.cadence} report snapshot for ${sourceReport.network === "all" ? "all groups" : sourceReport.network}.`
						: `${sourceRow.cadence[0]!.toUpperCase()}${sourceRow.cadence.slice(1)} report snapshot for ${sourceReport.network === "all" ? "all groups" : sourceReport.network}.`,
				stats: [
					{ label: "Status", value: STATUS_META[sourceRow.status].label },
					{ label: "Cadence", value: sourceRow.cadence },
					{ label: "Recipients", value: String(sourceRow.recipients.length) },
					{ label: "Next run", value: sourceReport.nextRun },
				],
			};

			const shareToken = randomUUID();
			const expiresAt = new Date(
				Date.now() + 30 * 24 * 60 * 60 * 1000,
			).toISOString();

			const { error } = await supabase.from("shared_reports").insert({
				user_id: user.id,
				share_token: shareToken,
				expires_at: expiresAt,
				report_data: snapshot,
				view_count: 0,
			});
			if (error) {
				appToast.error("Could not create share link", {
					description: error.message,
				});
				return;
			}

			const url = `${window.location.origin}/share/${encodeURIComponent(shareToken)}`;
			const result = await shareOrCopy({
				url,
				title: `Juno33 report — ${sourceRow.name}`,
				text: `Snapshot of ${sourceRow.name}. Expires in 30 days.`,
			});
			if (result === "failed") {
				appToast.error("Could not copy share link");
				return;
			}
			setCopiedId(id);
			if (copyResetTimerRef.current) {
				window.clearTimeout(copyResetTimerRef.current);
			}
			copyResetTimerRef.current = window.setTimeout(() => {
				setCopiedId((s) => (s === id ? null : s));
				copyResetTimerRef.current = null;
			}, 1600);
			if (result === "copied") {
				appToast.success("Share link copied", {
					description: "Public snapshot link expires in 30 days.",
				});
			}
			// 'shared' -> the OS share sheet already gave feedback; a toast on top
			// would double up.
		},
		[reportRows, reports],
	);

	useEffect(
		() => () => {
			if (copyResetTimerRef.current) {
				window.clearTimeout(copyResetTimerRef.current);
			}
		},
		[],
	);

	/* Keyboard: J/K navigate, Esc deselect */
	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const target = e.target as HTMLElement | null;
			const typing =
				target &&
				(target.tagName === "INPUT" ||
					target.tagName === "TEXTAREA" ||
					target.isContentEditable);
			if (typing) {
				if (e.key === "Escape") (target as HTMLElement).blur();
				return;
			}

			if (!filtered.length) return;
			const idx = filtered.findIndex((r) => r.id === activeId);

			if (e.key === "j" || e.key === "ArrowDown") {
				e.preventDefault();
				const next = Math.min(filtered.length - 1, idx < 0 ? 0 : idx + 1);
				setActiveId(filtered[next]!.id);
				return;
			}
			if (e.key === "k" || e.key === "ArrowUp") {
				e.preventDefault();
				const next = Math.max(0, idx < 0 ? 0 : idx - 1);
				setActiveId(filtered[next]!.id);
				return;
			}
			if (e.key === "Escape" && activeId) {
				e.preventDefault();
				setActiveId(null);
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [filtered, activeId]);

	const reportColumns = useMemo<ColumnDef<Report>[]>(
		() => [
			{
				accessorKey: "name",
				header: "Report",
				cell: ({ row }) => (
					<ReportNameCell report={row.original} groupMetaById={groupMetaById} />
				),
				meta: {
					headerClassName: "w-[42%] px-5",
					cellClassName: "px-5 py-3",
				},
			},
			{
				accessorKey: "status",
				header: "Status",
				cell: ({ row }) => <StatusPill status={row.original.status} />,
				meta: {
					headerClassName: "w-[110px]",
					cellClassName: "whitespace-nowrap",
				},
			},
			{
				accessorKey: "recipients",
				header: "Recipients",
				cell: ({ row }) => <RecipientsCell report={row.original} />,
				meta: {
					headerClassName: "w-[150px]",
					cellClassName: "whitespace-nowrap",
				},
			},
			{
				accessorKey: "nextRun",
				header: "Next run",
				cell: ({ row }) => (
					<div className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm tabular-nums text-muted-foreground">
						<CalendarIcon aria-hidden="true" />
						{row.original.nextRun}
					</div>
				),
				meta: {
					headerClassName: "w-[120px]",
					cellClassName: "whitespace-nowrap",
				},
			},
			{
				id: "actions",
				header: "",
				enableSorting: false,
				cell: ({ row }) => (
					<ReportRowActions
						report={row.original}
						copied={copiedId === row.original.id}
						downloading={downloadingId === row.original.id}
						sending={sendingId === row.original.id}
						onCopy={() => copyShareUrl(row.original.id)}
						onDownload={() => void downloadReport(row.original.id)}
						onRetryDelivery={() => void retryReportDelivery(row.original.id)}
						onDuplicate={() => duplicateReport(row.original.id)}
						onDelete={() => deleteReport(row.original.id)}
					/>
				),
				meta: {
					headerClassName: "w-[180px]",
					cellClassName: "px-5",
				},
			},
		],
		[
			copiedId,
			downloadingId,
			groupMetaById,
			sendingId,
			copyShareUrl,
			downloadReport,
			retryReportDelivery,
			duplicateReport,
			deleteReport,
		],
	);

	if (isFirstLoad) return <ReportsSkeleton />;

	return (
		<NovaScreen width="wide" density="compact">
			<style>{`
        @keyframes reports-live-pulse {
          0%, 100% { box-shadow: 0 0 0 0 var(--color-ring-oxblood-strong); }
          70% { box-shadow: 0 0 0 6px transparent; }
        }
        .reports-live-dot { animation: reports-live-pulse 2s ease-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .reports-live-dot { animation: none; }
        }
      `}</style>

			<NovaHeader
				eyebrow="Reports"
				title="Scheduled reports"
				meta="Client packets · live"
				description={
					<>
						<strong className="font-semibold text-foreground">
							Turn live performance into client-ready recaps.
						</strong>{" "}
						Schedule PDFs, copy share links, and keep recurring briefs on
						cadence.
					</>
				}
				filters={
					<NovaToolbar>
						{scopedAccount ? (
							<Badge tone="oxblood">{scopedAccount.handle}</Badge>
						) : null}
						<Badge tone="secondary">{stats.active} active</Badge>
						<Badge tone="outline">{stats.scheduled} scheduled</Badge>
						<Badge tone={stats.sharedLinks > 0 ? "oxblood" : "outline"}>
							{stats.sharedLinks} shared
						</Badge>
						{stats.deliveryIssues > 0 ? (
							<Badge tone="danger">
								{stats.deliveryIssues} delivery issue
							</Badge>
						) : null}
					</NovaToolbar>
				}
				actions={
					<Button
						type="button"
						onClick={() => void createReport()}
						aria-label="Create report"
						size="sm"
					>
						<Plus data-icon="inline-start" aria-hidden="true" />
						Create report
					</Button>
				}
			/>

			{!hasAccounts && !accountsLoading ? (
				<NovaEmpty
					title="Your first scheduled report"
					description="Schedule weekly and monthly PDF reports for clients — engagement, growth, and campaign recaps with your workspace styling applied. Connect an account to start collecting the data reports run on."
					icon={<FileText data-icon="inline-start" aria-hidden="true" />}
					action={
						<Button onClick={() => window.location.assign("/accounts")}>
							Connect an account
						</Button>
					}
				/>
			) : (
				<>
					<div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
						<NovaMiniStat
							label="Active"
							value={stats.active.toLocaleString()}
							description="Live report configurations"
							tone={stats.active > 0 ? "success" : "default"}
						/>
						<NovaMiniStat
							label="Scheduled"
							value={stats.scheduled.toLocaleString()}
							description="Recurring delivery cadence"
						/>
						<NovaMiniStat
							label="Shared"
							value={stats.sharedLinks.toLocaleString()}
							description="Reports with recipients"
							tone={stats.sharedLinks > 0 ? "primary" : "default"}
						/>
						<NovaMiniStat
							label="Delivery issues"
							value={stats.deliveryIssues.toLocaleString()}
							description="Failures needing retry"
							tone={stats.deliveryIssues > 0 ? "danger" : "default"}
						/>
					</div>

					{/* Templates rail — primary entry point */}
					<NovaSection className="mb-6" aria-labelledby="templates-eyebrow">
						<div className="mb-3 flex items-center justify-between gap-3">
							<span
								id="templates-eyebrow"
								className="text-sm font-medium text-muted-foreground"
							>
								Start from a template
							</span>
							<Badge tone="outline" className="tabular-nums">
								{TEMPLATES.length} presets
							</Badge>
						</div>
						<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
							{TEMPLATES.map((t) => (
								<TemplateCard
									key={t.id}
									template={t}
									onCreate={() => void createReport(t)}
								/>
							))}
						</div>
					</NovaSection>

					{/* Filter row */}
					<NovaToolbar className="mb-4">
						<label
							htmlFor="reports-search"
							className="relative flex-1 max-w-[320px]"
						>
							<Search
								className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
								aria-hidden="true"
							/>
							<Input
								id="reports-search"
								type="search"
								value={search}
								onChange={(e) => setSearch(e.target.value)}
								aria-label="Search reports"
								placeholder="Search reports"
								sizeVariant="sm"
								className="w-full pl-8"
							/>
						</label>

						<FilterSelect<"all" | ReportType>
							value={type}
							onChange={setType}
							options={[
								{ value: "all", label: "All types" },
								{ value: "scheduled", label: "Scheduled" },
								{ value: "one-off", label: "One-off" },
							]}
						/>
						<FilterSelect<"all" | ReportStatus>
							value={status}
							onChange={setStatus}
							options={[
								{ value: "all", label: "All status" },
								{ value: "active", label: "Active" },
								{ value: "paused", label: "Paused" },
								{ value: "generated", label: "Generated" },
								{ value: "draft", label: "Draft" },
							]}
						/>
						<FilterSelect<"all" | string>
							value={network}
							onChange={setNetwork}
							options={[
								{ value: "all", label: "All groups" },
								...groups.map((group) => ({
									value: group.id,
									label: group.name,
									dot: group.color,
								})),
							]}
						/>
					</NovaToolbar>

					{downloadError || sendError ? (
						<NovaListRow
							role="alert"
							className="mb-4"
							leading={<AlertTriangle aria-hidden="true" />}
							title={
								sendError
									? "Could not retry report delivery"
									: "Could not generate report"
							}
							description={sendError ?? downloadError}
							tone="danger"
						/>
					) : null}

					{/* Reports table — full width */}
					<NovaSection>
						<NovaCard
							title="Configurations"
							action={
								<Badge tone="outline" className="tabular-nums">
									{filtered.length} of {scopedReports.length}
								</Badge>
							}
							contentClassName="p-0"
						>
							<DataTable
								data={filtered}
								columns={reportColumns}
								ariaLabel="Report configurations"
								className="rounded-none border-0 bg-transparent shadow-none"
								tableClassName="min-w-[760px]"
								headerRowClassName="border-b border-border"
								rowClassName={(report) =>
									cn("group", activeId === report.id && "bg-muted/45")
								}
								onRowClick={(report) => {
									setActiveId(report.id);
									setEditorId(report.id);
								}}
								empty={
									<NovaEmpty
										className="m-5 min-h-52"
										icon={<FileText data-icon="inline-start" aria-hidden="true" />}
										title={
											reportsLoading
												? "Loading reports..."
												: reports.length === 0
													? "No reports yet"
													: "No reports match"
										}
										description={
											reports.length === 0 && !reportsLoading
												? "Create a report from a template above to schedule deliveries or generate a one-off PDF."
												: "Clear filters or pick a template above to start one."
										}
									/>
								}
							/>
						</NovaCard>
					</NovaSection>

					{/* Keyboard hints */}
					<NovaCard
						variant="panel"
						contentClassName="px-3 py-2"
						className="mt-4 hidden md:block"
					>
						<div className="flex items-center gap-4 text-xs text-muted-foreground">
							<span className="inline-flex items-center gap-2">
								<KbdGroup>
									<Kbd>J</Kbd>
									<Kbd>K</Kbd>
								</KbdGroup>
								navigate
							</span>
							<span className="inline-flex items-center gap-2">
								<Kbd>Esc</Kbd>
								deselect
							</span>
						</div>
					</NovaCard>
				</>
			)}
			{editorReport && (
				<Suspense fallback={null}>
					<ReportEditor
						report={editorReport}
						accounts={accounts}
						groups={groups}
						onClose={() => setEditorId(null)}
						onSaved={refetchReports}
					/>
				</Suspense>
			)}
		</NovaScreen>
	);
}

/* =========================================================================
   SUB-COMPONENTS
   ========================================================================= */
function ReportNameCell({
	report,
	groupMetaById,
}: {
	report: Report;
	groupMetaById: Map<string, { name: string; color: string }>;
}) {
	const groupMeta =
		report.network !== "all" ? groupMetaById.get(report.network) : null;
	const netColor =
		report.network === "all"
			? "var(--color-oxblood)"
			: (groupMeta?.color ?? groupColorFromId(report.network));

	const netLabel =
		report.network === "all"
			? "All groups"
			: (groupMeta?.name ?? groupLabelFromId(report.network));

	return (
		<div className="min-w-0">
			<div className="flex items-center gap-2 min-w-0">
				<span
					className="w-1.5 h-1.5 rounded-full shrink-0"
					style={{ background: netColor }}
					aria-hidden="true"
				/>
				<span className="text-[0.84375rem] font-medium text-foreground tracking-[-0.005em] truncate">
					{report.name}
				</span>
			</div>
			<div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
				<span className="inline-flex items-center gap-1">
					<CadenceIcon cadence={report.cadence} />
					<span className="capitalize">{report.cadence}</span>
				</span>
				<span
					className="size-1 rounded-full bg-muted-foreground/40"
					aria-hidden="true"
				/>
				<span>{netLabel}</span>
				<span
					className="size-1 rounded-full bg-muted-foreground/40"
					aria-hidden="true"
				/>
				<span>Last: {report.lastRun}</span>
			</div>
			{report.lastDeliveryStatus === "failed" ? (
				<div className="mt-1 text-[0.6875rem] text-[color:var(--color-oxblood)] truncate">
					Delivery failed
					{report.lastDeliveryError ? `: ${report.lastDeliveryError}` : ""}
				</div>
			) : report.lastDeliveryStatus === "skipped" ? (
				<div className="mt-1 truncate text-xs text-muted-foreground">
					Delivery skipped
					{report.lastDeliveryError ? `: ${report.lastDeliveryError}` : ""}
				</div>
			) : null}
		</div>
	);
}

function RecipientsCell({ report }: { report: Report }) {
	return (
		<div className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm tabular-nums text-muted-foreground">
			{report.shared ? (
				<>
					<Share2 className="text-primary" aria-hidden="true" />
					<span>{report.recipients}</span>
					<span className="text-muted-foreground">
						{report.lastDeliveryStatus === "sent"
							? `sent ${report.lastDeliveryAt}`
							: "shared"}
					</span>
				</>
			) : (
				<span className="text-muted-foreground">Private</span>
			)}
		</div>
	);
}

function ReportRowActions({
	report,
	copied,
	downloading,
	sending,
	onCopy,
	onDownload,
	onRetryDelivery,
	onDuplicate,
	onDelete,
}: {
	report: Report;
	copied: boolean;
	downloading: boolean;
	sending: boolean;
	onCopy: () => void;
	onDownload: () => void;
	onRetryDelivery: () => void;
	onDuplicate: () => void;
	onDelete: () => void;
}) {
	return (
		<div className="flex items-center justify-end gap-0.5 md:opacity-0 md:group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
			<RowIcon
				onClick={(e) => {
					e.stopPropagation();
					if (!downloading) onDownload();
				}}
				label={downloading ? "Generating..." : "Download PDF"}
				disabled={downloading}
			>
				{downloading ? <Loader2 className="animate-spin" /> : <Download />}
			</RowIcon>
			{report.lastDeliveryStatus === "failed" ? (
				<RowIcon
					onClick={(e) => {
						e.stopPropagation();
						if (!sending) onRetryDelivery();
					}}
					label={sending ? "Retrying..." : "Retry delivery"}
					disabled={sending}
				>
					{sending ? <Loader2 className="animate-spin" /> : <Send />}
				</RowIcon>
			) : null}
			<RowIcon
				onClick={(e) => {
					e.stopPropagation();
					onCopy();
				}}
				label={copied ? "Copied" : "Copy share link"}
				active={copied}
			>
				{copied ? <Check /> : <Share2 />}
			</RowIcon>
			<RowIcon
				onClick={(e) => {
					e.stopPropagation();
					onDuplicate();
				}}
				label="Duplicate"
			>
				<Copy />
			</RowIcon>
			<RowIcon
				onClick={(e) => {
					e.stopPropagation();
					onDelete();
				}}
				label="Delete"
				danger
			>
				<Trash2 />
			</RowIcon>
		</div>
	);
}

function RowIcon({
	children,
	onClick,
	label,
	active,
	danger,
	disabled,
}: {
	children: React.ReactNode;
	onClick: (e: React.MouseEvent) => void;
	label: string;
	active?: boolean | undefined;
	danger?: boolean | undefined;
	disabled?: boolean | undefined;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			aria-label={label}
			title={label}
			disabled={disabled}
			variant={danger ? "ghost" : active ? "secondary" : "ghost"}
			size="icon"
			className={cn(
				"reports-row-icon size-9 md:size-7",
				disabled
					? "cursor-not-allowed text-muted-foreground opacity-50"
					: active
						? "bg-primary/10 text-primary"
						: danger
							? "text-muted-foreground hover:bg-primary/10 hover:text-primary active:bg-primary/15"
							: "text-muted-foreground hover:bg-muted hover:text-foreground active:bg-muted",
			)}
		>
			{children}
		</Button>
	);
}

function TemplateCard({
	template,
	onCreate,
}: {
	template: Template;
	onCreate: () => void;
}) {
	return (
		<Button
			type="button"
			onClick={onCreate}
			aria-label={`Create ${template.name}`}
			variant="ghost"
			className="group h-auto w-full justify-start p-0 text-left"
		>
			<NovaCard
				contentClassName="p-0"
				className="w-full transition-transform duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] group-hover:-translate-y-0.5"
			>
				<div
					className="relative h-[96px] overflow-hidden"
					style={{
						background: `linear-gradient(135deg, ${template.swatches[0]} 0%, ${template.swatches[0]} 42%, ${template.swatches[1]} 42%, ${template.swatches[1]} 62%, ${template.swatches[2]} 62%)`,
					}}
					aria-hidden="true"
				>
					<div className="absolute bottom-3 left-3 right-3 h-[3px] rounded-full bg-primary-foreground/35" />
					<div className="absolute bottom-6 left-3 w-10 h-[3px] rounded-full bg-primary-foreground/45" />
					{template.recommended && (
						<span
							className="absolute top-2.5 left-2.5 inline-flex items-center gap-1 h-[18px] px-1.5 rounded-[4px] text-[0.59375rem] font-semibold uppercase tracking-[0.08em]"
							style={{
								color: "var(--color-accent-foreground)",
								backgroundColor:
									"color-mix(in srgb, var(--color-oxblood) 85%, transparent)",
								backdropFilter: "blur(4px)",
							}}
						>
							<Sparkles aria-hidden="true" />
							Recommended
						</span>
					)}
				</div>
				<Separator />
				<div className="p-4 flex flex-col gap-2 flex-1">
					<div className="flex items-start justify-between gap-2">
						<span className="text-[0.84375rem] font-medium text-foreground tracking-[-0.005em] leading-[1.25]">
							{template.name}
						</span>
						<Badge tone="outline" className="shrink-0 capitalize">
							{template.cadence}
						</Badge>
					</div>
					<p className="line-clamp-2 text-sm leading-[1.45] text-muted-foreground">
						{template.description}
					</p>
					<div className="mt-auto flex items-center gap-1 pt-2 text-sm font-medium text-muted-foreground">
						Use template
						<ChevronRight aria-hidden="true" />
					</div>
				</div>
			</NovaCard>
		</Button>
	);
}
