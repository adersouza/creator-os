import { useCallback, useEffect, useState } from "react";
import { Copy, Key, Trash2 } from "lucide-react";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	createApiKey,
	listApiKeys,
	revokeApiKey,
	type ApiKeyRow,
} from "@/services/api/settingsDeveloper";
import { Field, Panel, SectionHeader } from "./shared";

const SCOPES = [
	{ id: "read", label: "Read" },
	{ id: "write", label: "Write" },
	{ id: "admin", label: "Admin" },
];

function formatDate(value: string | null) {
	return value ? new Date(value).toLocaleDateString() : "Never";
}

export function APITabContent() {
	const [keys, setKeys] = useState<ApiKeyRow[]>([]);
	const [name, setName] = useState("Production integration");
	const [scopes, setScopes] = useState<string[]>(["read"]);
	const [loading, setLoading] = useState(true);
	const [creating, setCreating] = useState(false);
	const [shownKey, setShownKey] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			setKeys(await listApiKeys());
		} catch (err) {
			appToast.error("Could not load API keys", {
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

	const toggleScope = (scope: string) => {
		setScopes((prev) =>
			prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
		);
	};

	const createKey = async () => {
		if (!name.trim() || creating || scopes.length === 0) return;
		setCreating(true);
		try {
			const result = await createApiKey({ name: name.trim(), scopes });
			setKeys((prev) => [result.key, ...prev]);
			setShownKey(result.rawKey);
			setName("");
		} catch (err) {
			appToast.error("Could not create API key", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		} finally {
			setCreating(false);
		}
	};

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="API keys"
				description="Create scoped keys for server-side integrations. Full keys are shown once and only the SHA-256 hash is stored."
			/>

			<Panel>
				<Field label="Key name">
					<Input
						value={name}
						onChange={(event) => setName(event.target.value)}
					/>
				</Field>
				<div>
					<div className="text-[0.75rem] font-medium text-muted-foreground mb-2">
						Scopes
					</div>
					<div className="flex flex-wrap gap-2">
						{SCOPES.map((scope) => (
							<label
								key={scope.id}
								htmlFor={`api-scope-${scope.id}`}
								className={cn(
									"h-8 px-3 rounded-md border border-border inline-flex items-center gap-2 text-[0.75rem] font-medium cursor-pointer",
									scopes.includes(scope.id) &&
										"bg-foreground text-background border-foreground",
								)}
							>
								<Checkbox
									id={`api-scope-${scope.id}`}
									checked={scopes.includes(scope.id)}
									onCheckedChange={() => toggleScope(scope.id)}
								/>
								{scope.label}
							</label>
						))}
					</div>
				</div>
				<Button
					type="button"
					onClick={createKey}
					disabled={!name.trim() || scopes.length === 0 || creating}
					className="self-start"
				>
					{creating ? "Generating..." : "Generate key"}
				</Button>
			</Panel>

			<Panel>
				<div className="text-[0.8125rem] font-medium text-foreground mb-3">
					Existing keys
				</div>
				{loading ? (
					<div
						className="grid gap-3"
						role="status"
						aria-label="Loading API keys"
					>
						<Skeleton className="h-14" />
						<Skeleton className="h-14" />
					</div>
				) : keys.length === 0 ? (
					<NovaEmpty
						icon={<Key data-icon aria-hidden="true" />}
						title="No API keys yet"
						description="Generate a scoped key when a server-side integration needs access."
					/>
				) : (
					<div className="divide-y divide-border">
						{keys.map((key) => (
							<div key={key.id} className="py-3 flex items-center gap-3">
								<div className="w-8 h-8 rounded-md bg-muted border border-border inline-flex items-center justify-center">
									<Key className="w-4 h-4 text-muted-foreground" />
								</div>
								<div className="min-w-0 flex-1">
									<div className="text-[0.8125rem] font-medium text-foreground">
										{key.name}
									</div>
									<div className="text-[0.71875rem] text-muted-foreground">
										{key.key_prefix}... · created {formatDate(key.created_at)} ·
										last used {formatDate(key.last_used_at)}
									</div>
									{key.allowed_account_ids?.length ? (
										<div className="mt-1 text-[0.6875rem] text-muted-foreground">
											Limited to {key.allowed_account_ids.length} account
											{key.allowed_account_ids.length === 1 ? "" : "s"}
										</div>
									) : null}
								</div>
								<div className="hidden sm:flex gap-1">
									{key.scopes.map((scope) => (
										<Badge key={scope} tone="secondary">
											{scope}
										</Badge>
									))}
								</div>
								<Button
									type="button"
									onClick={() =>
										void revokeApiKey(key.id)
											.then(() =>
												setKeys((prev) =>
													prev.filter((item) => item.id !== key.id),
												),
											)
											.catch((err) =>
												appToast.error("Could not revoke key", {
													description:
														err instanceof Error
															? err.message
															: "Try again in a moment.",
												}),
											)
									}
									variant="outline"
									size="icon"
									aria-label={`Revoke ${key.name}`}
								>
									<Trash2 data-icon aria-hidden="true" />
								</Button>
							</div>
						))}
					</div>
				)}
			</Panel>

			<Modal
				open={shownKey !== null}
				onClose={() => setShownKey(null)}
				title="Copy your API key"
				description="This is the only time the full key is shown."
				footer={
					shownKey ? (
						<div className="flex justify-end gap-2">
							<Button
								type="button"
								variant="outline"
								onClick={() =>
									void navigator.clipboard
										.writeText(shownKey)
										.then(() => appToast.success("Copied"))
								}
							>
								<Copy data-icon="inline-start" aria-hidden="true" />
								Copy
							</Button>
							<Button type="button" onClick={() => setShownKey(null)}>
								Close
							</Button>
						</div>
					) : null
				}
			>
				{shownKey ? (
					<code className="block rounded-md border border-border bg-muted p-3 text-[0.75rem] break-all">
						{shownKey}
					</code>
				) : null}
			</Modal>
		</div>
	);
}
