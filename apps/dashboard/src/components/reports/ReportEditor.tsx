import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { ExternalLink, Loader2, Plus, Send, X } from "lucide-react";
import { useForm } from "react-hook-form";
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
import { Form, FormField, FormInputField, FormSelectField } from "@/components/ui/Form";
import { Input } from "@/components/ui/Input";
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

const reportEditorFormSchema = z.object({
	name: z.string().trim().min(1, "Report name is required."),
	start: z.string().trim().min(1, "Choose a start date."),
	end: z.string().trim().min(1, "Choose an end date."),
	delivery: z.enum(["now", "scheduled"]),
	cadence: z.enum(["weekly", "monthly", "quarterly"]),
});

type ReportEditorFormValues = z.infer<typeof reportEditorFormSchema>;

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
	const reportForm = useForm<ReportEditorFormValues>({
		resolver: zodResolver(reportEditorFormSchema),
		defaultValues: {
			name: report.name,
			start: config.dateRange?.start ?? defaultRange.start,
			end: config.dateRange?.end ?? defaultRange.end,
			delivery: config.delivery ?? "now",
			cadence: report.cadence === "one-off" ? "weekly" : report.cadence,
		},
	});
	const delivery = reportForm.watch("delivery");
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
	const [busy, setBusy] = useState<"save" | "send" | "preview" | null>(null);

	useEffect(() => {
		reportForm.reset({
			name: report.name,
			start: config.dateRange?.start ?? defaultRange.start,
			end: config.dateRange?.end ?? defaultRange.end,
			delivery: config.delivery ?? "now",
			cadence: report.cadence === "one-off" ? "weekly" : report.cadence,
		});
	}, [
		report.name,
		report.cadence,
		config.dateRange?.start,
		config.dateRange?.end,
		config.delivery,
		defaultRange.start,
		defaultRange.end,
		reportForm,
	]);

	const save = async (
		mode: "draft" | "send" | "preview" = "draft",
	): Promise<boolean> => {
		const formIsValid = await reportForm.trigger();
		if (!formIsValid) return false;
		const values = reportForm.getValues();
		const recipientRows = normalizeRecipients(recipients);
		const nextConfig: ReportConfig = {
			dateRange: { start: values.start, end: values.end },
			accountIds: Array.from(selectedAccounts),
			groupIds: Array.from(selectedGroups),
			metrics: Array.from(metrics),
			sections: Array.from(sections),
			delivery: values.delivery,
		};
		const isScheduled = values.delivery === "scheduled" && mode === "draft";
		const nextCadence = isScheduled
			? values.cadence
			: report.cadence === "one-off"
				? "one-off"
				: values.cadence;
		const nextType: ReportType = isScheduled ? "scheduled" : report.type;
		const nextRunAt = isScheduled ? nextWeeklyRun() : report.nextRunAt;
		const trimmedName = values.name.trim() || "Untitled report";

		await apiFetch("/api/reports?action=update", updateSchema, {
			method: "PUT",
			json: {
				report_id: report.id,
				name: trimmedName,
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
		reportForm.reset({ ...values, name: trimmedName });
		return true;
	};

	const saveDraft = async () => {
		setBusy("save");
		try {
			const saved = await save("draft");
			if (!saved) return;
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
			const saved = await save("send");
			if (!saved) return;
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
			const saved = await save("preview");
			if (!saved) return;
			const values = reportForm.getValues();
			const trimmedName = values.name.trim() || "Untitled report";
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
					name: trimmedName,
					headline: trimmedName,
					description: `Preview for ${values.start} to ${values.end}.`,
					stats: [
						{ label: "Metrics", value: String(metrics.size) },
						{ label: "Sections", value: String(sections.size) },
						{
							label: "Recipients",
							value: String(normalizeRecipients(recipients).length),
						},
						{ label: "Delivery", value: values.delivery },
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
					<Form form={reportForm} onSubmit={() => void saveDraft()} className="gap-5">
						<FormInputField
							name="name"
							label="Report name"
							disabled={busy !== null}
						/>
						<section className="grid grid-cols-2 gap-3">
							<FormInputField
								name="start"
								label="Start date"
								type="date"
								disabled={busy !== null}
							/>
							<FormInputField
								name="end"
								label="End date"
								type="date"
								disabled={busy !== null}
							/>
						</section>

						<FormField name="delivery" label="Delivery" disabled={busy !== null}>
							{({ field }) => (
								<>
									<div className="inline-flex rounded-md bg-muted p-[3px]">
										<Segment
											active={field.value === "now"}
											onClick={() => field.onChange("now")}
										>
											Now
										</Segment>
										<Segment
											active={field.value === "scheduled"}
											onClick={() => field.onChange("scheduled")}
										>
											Scheduled
										</Segment>
									</div>
									{field.value === "scheduled" && (
										<div className="mt-3 max-w-[220px]">
											<FormSelectField
												name="cadence"
												label="Cadence"
												disabled={busy !== null}
												options={[
													{ value: "weekly", label: "Weekly" },
													{ value: "monthly", label: "Monthly" },
													{ value: "quarterly", label: "Quarterly" },
												]}
											/>
										</div>
									)}
								</>
							)}
						</FormField>
					</Form>

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
