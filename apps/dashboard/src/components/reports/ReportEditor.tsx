import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Loader2, Plus, Send, X } from "lucide-react";
import { z } from "zod";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import type { AccountGroup } from "@/hooks/useAccountGroups";
import type {
	ReportCadence,
	ReportRecipient,
	ReportRow,
	ReportType,
} from "@/hooks/useReports";
import { apiFetch } from "@/lib/apiFetch";
import { METRIC_REGISTRY } from "@/lib/metricRegistry";
import { randomUUID } from "@/lib/uuid";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import { Button } from "@/components/ui/Button";
import { Field as JunoField } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Sheet } from "@/components/ui/Sheet";

const updateSchema = z
	.object({ success: z.boolean().optional() })
	.passthrough();
const sendSchema = z
	.object({ success: z.boolean().optional(), delivered: z.number().optional() })
	.passthrough();

const SECTION_OPTIONS = [
	{ id: "eqs_trend", label: "EQS trend" },
	{ id: "fleet_leaderboard", label: "Fleet leaderboard" },
	{ id: "top_posts", label: "Top posts" },
	{ id: "audience_growth", label: "Audience growth" },
] as const;

type DeliveryMode = "now" | "scheduled";

interface ReportConfig {
	dateRange?:
		| { start?: string | undefined; end?: string | undefined }
		| undefined;
	accountIds?: string[] | undefined;
	groupIds?: string[] | undefined;
	metrics?: string[] | undefined;
	sections?: string[] | undefined;
	delivery?: DeliveryMode | undefined;
}

interface ReportEditorProps {
	report: ReportRow;
	accounts: ConnectedAccount[];
	groups: AccountGroup[];
	onClose: () => void;
	onSaved: () => void;
}

export function ReportEditor({
	report,
	accounts,
	groups,
	onClose,
	onSaved,
}: ReportEditorProps) {
	const config = report.config as ReportConfig;
	const defaultRange = useMemo(
		() => defaultDateRange(report.cadence),
		[report.cadence],
	);
	const [name, setName] = useState(report.name);
	const [start, setStart] = useState(
		config.dateRange?.start ?? defaultRange.start,
	);
	const [end, setEnd] = useState(config.dateRange?.end ?? defaultRange.end);
	const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(
		new Set(config.accountIds ?? []),
	);
	const [selectedGroups, setSelectedGroups] = useState<Set<string>>(
		new Set(config.groupIds ?? []),
	);
	const [metrics, setMetrics] = useState<Set<string>>(
		new Set(
			config.metrics ?? METRIC_REGISTRY.slice(0, 6).map((metric) => metric.key),
		),
	);
	const [sections, setSections] = useState<Set<string>>(
		new Set(config.sections ?? SECTION_OPTIONS.map((section) => section.id)),
	);
	const [recipients, setRecipients] = useState<ReportRecipient[]>(
		report.recipients,
	);
	const [recipientInput, setRecipientInput] = useState("");
	const [delivery, setDelivery] = useState<DeliveryMode>(
		config.delivery ?? "now",
	);
	const [cadence, setCadence] = useState<ReportCadence>(
		report.cadence === "one-off" ? "weekly" : report.cadence,
	);
	const [busy, setBusy] = useState<"save" | "send" | "preview" | null>(null);

	useEffect(() => {
		setName(report.name);
	}, [report.name]);

	const save = async (mode: "draft" | "send" | "preview" = "draft") => {
		const recipientRows = normalizeRecipients(recipients);
		const nextConfig: ReportConfig = {
			dateRange: { start, end },
			accountIds: Array.from(selectedAccounts),
			groupIds: Array.from(selectedGroups),
			metrics: Array.from(metrics),
			sections: Array.from(sections),
			delivery,
		};
		const isScheduled = delivery === "scheduled" && mode === "draft";
		const nextCadence = isScheduled
			? cadence
			: report.cadence === "one-off"
				? "one-off"
				: cadence;
		const nextType: ReportType = isScheduled ? "scheduled" : report.type;
		const nextRunAt = isScheduled ? nextWeeklyRun() : report.nextRunAt;

		await apiFetch("/api/reports?action=update", updateSchema, {
			method: "PUT",
			json: {
				report_id: report.id,
				name: name.trim() || "Untitled report",
				type: nextType,
				cadence: nextCadence,
				status: isScheduled ? "active" : "draft",
				network: Array.from(selectedGroups)[0] ?? null,
				recipients: recipientRows,
				next_run_at: nextRunAt,
				config: nextConfig,
			},
		});
		onSaved();
	};

	const saveDraft = async () => {
		setBusy("save");
		try {
			await save("draft");
			appToast.success(
				delivery === "scheduled" ? "Schedule saved" : "Draft saved",
			);
		} catch (error) {
			appToast.error("Could not save report", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	const sendNow = async () => {
		const recipientRows = normalizeRecipients(recipients);
		if (recipientRows.length === 0) {
			appToast.warn("Add at least one recipient before sending.");
			return;
		}
		setBusy("send");
		try {
			await save("send");
			const result = await apiFetch("/api/reports?action=send", sendSchema, {
				method: "POST",
				json: { report_id: report.id },
			});
			appToast.success(
				`Sent to ${result.delivered ?? recipientRows.length} recipient${recipientRows.length === 1 ? "" : "s"}`,
			);
			onSaved();
		} catch (error) {
			appToast.error("Could not send report", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	const preview = async () => {
		setBusy("preview");
		try {
			await save("preview");
			const token = randomUUID();
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not signed in");
			const { error } = await supabase.from("shared_reports").insert({
				user_id: user.id,
				share_token: token,
				expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
				view_count: 0,
				report_data: {
					reportId: report.id,
					name: name.trim() || "Untitled report",
					headline: name.trim() || "Untitled report",
					description: `Preview for ${start} to ${end}.`,
					stats: [
						{ label: "Metrics", value: String(metrics.size) },
						{ label: "Sections", value: String(sections.size) },
						{
							label: "Recipients",
							value: String(normalizeRecipients(recipients).length),
						},
						{ label: "Delivery", value: delivery },
					],
				},
			});
			if (error) throw error;
			window.open(
				`/share/${encodeURIComponent(token)}?preview=1`,
				"_blank",
				"noopener,noreferrer",
			);
		} catch (error) {
			appToast.error("Could not open preview", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setBusy(null);
		}
	};

	const addRecipient = () => {
		const email = recipientInput.trim().toLowerCase();
		if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return;
		setRecipients((current) =>
			current.some((recipient) => recipient.email.toLowerCase() === email)
				? current
				: [...current, { email }],
		);
		setRecipientInput("");
	};

	return (
		<Sheet
			open
			onClose={onClose}
			title={report.name}
			description="Report editor"
			ariaLabel="Report editor"
			widthClass="w-full sm:w-[620px]"
		>
			<div className="flex min-h-full flex-col">
				<div className="flex flex-1 flex-col gap-5 px-6 py-5">
					<Field label="Report name">
						<Input
							value={name}
							onChange={(event) => setName(event.target.value)}
						/>
					</Field>

					<section className="grid grid-cols-2 gap-3">
						<Field label="Start date">
							<Input
								type="date"
								value={start}
								onChange={(event) => setStart(event.target.value)}
							/>
						</Field>
						<Field label="End date">
							<Input
								type="date"
								value={end}
								onChange={(event) => setEnd(event.target.value)}
							/>
						</Field>
					</section>

					<Field label="Groups">
						<div className="grid grid-cols-2 gap-2">
							{groups.map((group) => (
								<CheckButton
									key={group.id}
									checked={selectedGroups.has(group.id)}
									label={group.name}
									onClick={() =>
										toggleSet(selectedGroups, setSelectedGroups, group.id)
									}
								/>
							))}
						</div>
					</Field>

					<Field label="Accounts">
						<div className="grid grid-cols-2 gap-2 max-h-44 overflow-y-auto pr-1">
							{accounts.map((account) => (
								<CheckButton
									key={account.id}
									checked={selectedAccounts.has(account.id)}
									label={`${account.handle} (${account.platform})`}
									onClick={() =>
										toggleSet(selectedAccounts, setSelectedAccounts, account.id)
									}
								/>
							))}
						</div>
					</Field>

					<Field label="Metrics">
						<div className="grid grid-cols-2 gap-2">
							{METRIC_REGISTRY.filter((metric) => metric.dbColumn).map(
								(metric) => (
									<CheckButton
										key={metric.key}
										checked={metrics.has(metric.key)}
										label={metricLabel(metric.key)}
										onClick={() => toggleSet(metrics, setMetrics, metric.key)}
									/>
								),
							)}
						</div>
					</Field>

					<Field label="Include sections">
						<div className="grid grid-cols-2 gap-2">
							{SECTION_OPTIONS.map((section) => (
								<CheckButton
									key={section.id}
									checked={sections.has(section.id)}
									label={section.label}
									onClick={() => toggleSet(sections, setSections, section.id)}
								/>
							))}
						</div>
					</Field>

					<Field label="Recipients">
						<div className="flex flex-wrap gap-2 rounded-md border border-border p-2">
							{recipients.map((recipient) => (
								<Button
									key={recipient.email}
									type="button"
									variant="outline"
									size="sm"
									onClick={() =>
										setRecipients((current) =>
											current.filter((item) => item.email !== recipient.email),
										)
									}
									className="rounded-full"
								>
									{recipient.email}
									<X data-icon="inline-end" aria-hidden="true" />
								</Button>
							))}
							<Input
								value={recipientInput}
								onChange={(event) => setRecipientInput(event.target.value)}
								onKeyDown={(event) => {
									if (event.key === "Enter") {
										event.preventDefault();
										addRecipient();
									}
								}}
								onBlur={addRecipient}
								placeholder="email@domain.com"
								className="min-w-[180px] flex-1"
							/>
						</div>
					</Field>

					<Field label="Delivery">
						<div className="inline-flex rounded-md bg-muted p-[3px]">
							<Segment
								active={delivery === "now"}
								onClick={() => setDelivery("now")}
							>
								Now
							</Segment>
							<Segment
								active={delivery === "scheduled"}
								onClick={() => setDelivery("scheduled")}
							>
								Scheduled
							</Segment>
						</div>
						{delivery === "scheduled" && (
							<div className="mt-3 max-w-[220px]">
								<Select
									value={cadence}
									onChange={(event) =>
										setCadence(event.target.value as ReportCadence)
									}
									options={[
										{ value: "weekly", label: "Weekly" },
										{ value: "monthly", label: "Monthly" },
										{ value: "quarterly", label: "Quarterly" },
									]}
								/>
							</div>
						)}
					</Field>
				</div>

				<footer className="px-6 py-4 border-t border-border flex items-center gap-2">
					<Button
						type="button"
						variant="outline"
						onClick={() => void preview()}
						disabled={busy !== null}
						className="gap-1.5"
					>
						<ExternalLink data-icon="inline-start" aria-hidden="true" />
						Preview
					</Button>
					<Button
						type="button"
						variant="outline"
						onClick={() => void sendNow()}
						disabled={busy !== null}
						className="gap-1.5"
					>
						{busy === "send" ? (
							<Loader2
								data-icon="inline-start"
								className="animate-spin"
								aria-hidden="true"
							/>
						) : (
							<Send data-icon="inline-start" aria-hidden="true" />
						)}
						Send now
					</Button>
					<Button
						type="button"
						onClick={() => void saveDraft()}
						disabled={busy !== null}
						className="ml-auto gap-1.5"
					>
						{busy === "save" ? (
							<Loader2
								data-icon="inline-start"
								className="animate-spin"
								aria-hidden="true"
							/>
						) : (
							<Plus data-icon="inline-start" aria-hidden="true" />
						)}
						{delivery === "scheduled" ? "Save schedule" : "Save draft"}
					</Button>
				</footer>
			</div>
		</Sheet>
	);
}

function Field({
	label,
	children,
}: {
	label: string;
	children: React.ReactNode;
}) {
	return <JunoField label={label}>{children}</JunoField>;
}

function CheckButton({
	checked,
	label,
	onClick,
}: {
	checked: boolean;
	label: string;
	onClick: () => void;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			aria-pressed={checked}
			variant={checked ? "secondary" : "outline"}
			size="sm"
			className="min-h-9 justify-start py-2 text-left text-[0.78125rem]"
		>
			{label}
		</Button>
	);
}

function Segment({
	active,
	onClick,
	children,
}: {
	active: boolean;
	onClick: () => void;
	children: React.ReactNode;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			aria-pressed={active}
			variant={active ? "default" : "ghost"}
			size="sm"
			className="h-7 px-3 text-[0.75rem]"
		>
			{children}
		</Button>
	);
}

function toggleSet<T>(
	source: Set<T>,
	setSource: (next: Set<T>) => void,
	value: T,
) {
	const next = new Set(source);
	if (next.has(value)) next.delete(value);
	else next.add(value);
	setSource(next);
}

function normalizeRecipients(recipients: ReportRecipient[]): ReportRecipient[] {
	return recipients.filter((recipient) =>
		/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient.email),
	);
}

function defaultDateRange(cadence: ReportCadence) {
	const end = new Date();
	const start = new Date();
	start.setDate(
		start.getDate() -
			(cadence === "weekly" ? 7 : cadence === "quarterly" ? 90 : 30),
	);
	return { start: toDay(start), end: toDay(end) };
}

function nextWeeklyRun() {
	const next = new Date();
	next.setDate(next.getDate() + 7);
	next.setHours(8, 0, 0, 0);
	return next.toISOString();
}

function toDay(date: Date) {
	return date.toISOString().slice(0, 10);
}

function metricLabel(key: string) {
	return key
		.replace(/^total/, "")
		.replace(/^ig/, "IG ")
		.replace(/([a-z])([A-Z])/g, "$1 $2")
		.trim();
}
