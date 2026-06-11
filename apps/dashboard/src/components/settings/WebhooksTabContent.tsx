import { useCallback, useEffect, useState } from "react";
import { Send, Trash2, Webhook } from "lucide-react";
import { appToast } from "@/lib/toast";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	createUserWebhook,
	deleteUserWebhook,
	listUserWebhooks,
	testUserWebhook,
	type UserWebhookRow,
} from "@/services/api/settingsDeveloper";
import { Field, Panel, SectionHeader } from "./shared";

const EVENTS = [
	"post_published",
	"post_failed",
	"account_reconnect_needed",
	"report_sent",
];

function formatDate(value: string | null) {
	return value ? new Date(value).toLocaleString() : "Never";
}

export function WebhooksTabContent() {
	const [webhooks, setWebhooks] = useState<UserWebhookRow[]>([]);
	const [url, setUrl] = useState("");
	const [events, setEvents] = useState<string[]>(["post_published"]);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);

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

	const toggleEvent = (event: string) => {
		setEvents((prev) =>
			prev.includes(event)
				? prev.filter((item) => item !== event)
				: [...prev, event],
		);
	};

	const addWebhook = async () => {
		if (!url.trim() || events.length === 0 || saving) return;
		setSaving(true);
		try {
			const result = await createUserWebhook({ url: url.trim(), events });
			setWebhooks((prev) => [result.webhook, ...prev]);
			setUrl("");
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
				<Field label="Endpoint URL">
					<Input
						type="url"
						value={url}
						onChange={(event) => setUrl(event.target.value)}
						placeholder="https://example.com/juno33/webhook"
					/>
				</Field>
				<div>
					<div className="text-[0.75rem] font-medium text-muted-foreground mb-2">
						Events
					</div>
					<div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
						{EVENTS.map((event) => (
							<label
								key={event}
								htmlFor={`webhook-event-${event}`}
								className="h-8 px-3 rounded-md border border-border inline-flex items-center gap-2 text-[0.75rem]"
							>
								<Checkbox
									id={`webhook-event-${event}`}
									checked={events.includes(event)}
									onCheckedChange={() => toggleEvent(event)}
								/>
								{event}
							</label>
						))}
					</div>
				</div>
				<Button
					type="button"
					onClick={addWebhook}
					disabled={!url.trim() || events.length === 0 || saving}
					className="self-start"
				>
					{saving ? "Adding..." : "Add webhook"}
				</Button>
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
