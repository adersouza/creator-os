import { useCallback, useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Send, Trash2, Webhook } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { appToast } from "@/lib/toast";
import { Button } from "@/components/ui/Button";
import { Form, FormCheckboxField, FormInputField } from "@/components/ui/Form";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	createUserWebhook,
	deleteUserWebhook,
	listUserWebhooks,
	testUserWebhook,
	type UserWebhookRow,
} from "@/services/api/settingsDeveloper";
import { Panel, SectionHeader } from "./shared";

const EVENTS = [
	{ id: "post_published", label: "Post published" },
	{ id: "post_failed", label: "Post failed" },
	{ id: "account_reconnect_needed", label: "Reconnect needed" },
	{ id: "report_sent", label: "Report sent" },
] as const;

const webhookSchema = z
	.object({
		url: z.string().url("Use a valid HTTPS endpoint URL."),
		post_published: z.boolean(),
		post_failed: z.boolean(),
		account_reconnect_needed: z.boolean(),
		report_sent: z.boolean(),
	})
	.refine((values) => EVENTS.some((event) => values[event.id]), {
		path: ["post_published"],
		message: "Choose at least one event.",
	});

type WebhookFormValues = z.infer<typeof webhookSchema>;

function selectedWebhookEvents(values: WebhookFormValues) {
	return EVENTS.filter((event) => values[event.id]).map((event) => event.id);
}

function formatDate(value: string | null) {
	return value ? new Date(value).toLocaleString() : "Never";
}

export function WebhooksTabContent() {
	const [webhooks, setWebhooks] = useState<UserWebhookRow[]>([]);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const webhookForm = useForm<WebhookFormValues>({
		resolver: zodResolver(webhookSchema),
		defaultValues: {
			url: "",
			post_published: true,
			post_failed: false,
			account_reconnect_needed: false,
			report_sent: false,
		},
	});
	const watchedWebhookForm = webhookForm.watch();
	const selectedEvents = selectedWebhookEvents(watchedWebhookForm);

	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			setWebhooks(await listUserWebhooks());
		} catch (err) {
			appToast.error("Could not load webhooks", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void refresh();
	}, [refresh]);

	const addWebhook = async (values: WebhookFormValues) => {
		const events = selectedWebhookEvents(values);
		const url = values.url.trim();
		if (!url || events.length === 0 || saving) return;
		setSaving(true);
		try {
			const result = await createUserWebhook({ url, events });
			setWebhooks((prev) => [result.webhook, ...prev]);
			webhookForm.reset({
				url: "",
				post_published: true,
				post_failed: false,
				account_reconnect_needed: false,
				report_sent: false,
			});
			appToast.success("Webhook added", {
				description: "Signing secret generated and stored securely.",
			});
		} catch (err) {
			appToast.error("Could not add webhook", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="Webhooks"
				description="Send signed POST callbacks when publishing and account lifecycle events happen."
			/>

			<Panel>
				<Form
					form={webhookForm}
					onSubmit={(values) => void addWebhook(values)}
					className="gap-4"
					aria-label="Add webhook endpoint"
				>
					<FormInputField
						name="url"
						label="Endpoint URL"
						type="url"
						placeholder="https://example.com/juno33/webhook"
						disabled={saving}
					/>
					<div>
						<div className="mb-2 text-[0.75rem] font-medium text-muted-foreground">
							Events
						</div>
						<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
							{EVENTS.map((event) => (
								<FormCheckboxField
									key={event.id}
									name={event.id}
									label={event.label}
									disabled={saving}
									className="rounded-md border border-border bg-card px-3 py-2"
								/>
							))}
						</div>
					</div>
					<Button
						type="submit"
						disabled={
							!watchedWebhookForm.url.trim() ||
							selectedEvents.length === 0 ||
							saving
						}
						className="self-start"
					>
						{saving ? "Adding..." : "Add webhook"}
					</Button>
				</Form>
			</Panel>

			<Panel>
				<div className="text-[0.8125rem] font-medium text-foreground mb-3">
					Endpoints
				</div>
				{loading ? (
					<div
						className="grid gap-3"
						role="status"
						aria-label="Loading webhooks"
					>
						<Skeleton className="h-14" />
						<Skeleton className="h-14" />
					</div>
				) : webhooks.length === 0 ? (
					<NovaEmpty
						icon={<Webhook data-icon aria-hidden="true" />}
						title="No webhooks yet"
						description="Add an endpoint to receive signed publishing and account lifecycle callbacks."
					/>
				) : (
					<div className="divide-y divide-border">
						{webhooks.map((hook) => (
							<div key={hook.id} className="py-3 flex items-center gap-3">
								<div className="w-8 h-8 rounded-md bg-muted border border-border inline-flex items-center justify-center">
									<Webhook className="w-4 h-4 text-muted-foreground" />
								</div>
								<div className="min-w-0 flex-1">
									<div className="text-[0.8125rem] font-medium text-foreground truncate">
										{hook.url}
									</div>
									<div className="text-[0.71875rem] text-muted-foreground">
										{hook.events.join(", ")} · last triggered{" "}
										{formatDate(hook.last_triggered_at)}
									</div>
								</div>
								<Button
									type="button"
									onClick={() =>
										void testUserWebhook(hook.id)
											.then((result) =>
												appToast.success(`Test returned ${result.status}`, {
													description: result.ok
														? "Endpoint responded successfully."
														: "Endpoint returned a non-2xx status.",
												}),
											)
											.catch((err) =>
												appToast.error("Webhook test failed", {
													description:
														err instanceof Error
															? err.message
															: "Try again in a moment.",
												}),
											)
									}
									variant="outline"
									size="icon"
									aria-label={`Test ${hook.url}`}
								>
									<Send data-icon aria-hidden="true" />
								</Button>
								<Button
									type="button"
									onClick={() =>
										void deleteUserWebhook(hook.id)
											.then(() =>
												setWebhooks((prev) =>
													prev.filter((item) => item.id !== hook.id),
												),
											)
											.catch((err) =>
												appToast.error("Could not delete webhook", {
													description:
														err instanceof Error
															? err.message
															: "Try again in a moment.",
												}),
											)
									}
									variant="outline"
									size="icon"
									aria-label={`Delete ${hook.url}`}
								>
									<Trash2 data-icon aria-hidden="true" />
								</Button>
							</div>
						))}
					</div>
				)}
			</Panel>
		</div>
	);
}
