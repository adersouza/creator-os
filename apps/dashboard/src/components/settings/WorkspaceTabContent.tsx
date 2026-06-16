import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Link2, Upload } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import {
	getUserSetting,
	upsertUserSetting,
} from "@/services/userSettingsService";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Form, FormField, FormInputField, FormSelectField } from "@/components/ui/Form";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Separator } from "@/components/ui/Separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import { cn } from "@/lib/utils";

import { Field, Panel, SectionHeader } from "./shared";

/* ============================================================================
   Workspace preferences
   ========================================================================= */

interface WorkspacePrefs {
	name: string;
	tz: string;
	defaultWindow: string;
	week: "sun" | "mon";
}

interface WhiteLabelPrefs {
	logoUrl?: string | null | undefined;
	primaryHex?: string | null | undefined;
	domain?: string | null | undefined;
}

const WORKSPACE_PREFS_KEY = "workspace_preferences";
const WHITELABEL_PREFS_KEY = "whitelabel_preferences";

const workspacePrefsSchema = z.object({
	name: z.string().trim().min(1, "Workspace name cannot be empty."),
	tz: z.string().trim().min(1, "Choose a timezone."),
	defaultWindow: z.string().trim().min(1, "Choose a default posting window."),
	week: z.enum(["sun", "mon"]),
});

const DEFAULT_POSTING_WINDOW_OPTIONS = [
	{ value: "6-8am", label: "Morning · 6 – 8am" },
	{ value: "9-11am", label: "Morning · 9 – 11am" },
	{ value: "12-2pm", label: "Midday · 12 – 2pm" },
	{ value: "4-6pm", label: "Afternoon · 4 – 6pm" },
	{ value: "7-9pm", label: "Evening · 7 – 9pm" },
	{ value: "10pm", label: "Late · 10pm +" },
];

const TIMEZONE_OPTIONS = [
	{ value: "America/New_York", label: "America / New York (ET)" },
	{ value: "America/Chicago", label: "America / Chicago (CT)" },
	{ value: "America/Los_Angeles", label: "America / Los Angeles (PT)" },
	{ value: "Europe/London", label: "Europe / London (BST)" },
	{ value: "UTC", label: "UTC" },
];

export function WorkspaceTabContent() {
	const browserTz = (() => {
		try {
			return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC";
		} catch {
			return "UTC";
		}
	})();
	const initialPrefs: WorkspacePrefs = {
		name: "Juno33 Global",
		tz: browserTz,
		defaultWindow: "7-9pm",
		week: "mon",
	};
	const workspaceForm = useForm<WorkspacePrefs>({
		resolver: zodResolver(workspacePrefsSchema),
		defaultValues: initialPrefs,
	});
	const workspaceValues = workspaceForm.watch();
	const [savedPrefs, setSavedPrefs] = useState<WorkspacePrefs>(initialPrefs);
	const [workspaceId, setWorkspaceId] = useState<string | null>(null);
	const [hydrated, setHydrated] = useState(false);
	const [saving, setSaving] = useState(false);
	const timezoneOptions = TIMEZONE_OPTIONS.some(
		(option) => option.value === workspaceValues.tz,
	)
		? TIMEZONE_OPTIONS
		: [...TIMEZONE_OPTIONS, { value: workspaceValues.tz, label: workspaceValues.tz }];

	// Pull the active workspace + per-user scheduling prefs into the form.
	useEffect(() => {
		let cancelled = false;
		(async () => {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user || cancelled) return;

			const [membersRes, settingsRes] = await Promise.all([
				supabase
					.from("workspace_members")
					.select("workspace_id, workspaces:workspace_id(id, name)")
					.eq("user_id", user.id)
					.limit(1)
					.maybeSingle(),
				getUserSetting(user.id, WORKSPACE_PREFS_KEY),
			]);

			if (cancelled) return;

			const ws = (
				membersRes.data as {
					workspaces?:
						| { id?: string | undefined; name?: string | undefined }
						| null
						| undefined;
				} | null
			)?.workspaces;
			const row = (
				settingsRes &&
				typeof settingsRes === "object" &&
				!Array.isArray(settingsRes)
					? settingsRes
					: {}
			) as {
				timezone?: string | null | undefined;
				defaultWindow?: string | null | undefined;
				week?: "sun" | "mon" | null | undefined;
			};
			const hydratedPrefs: WorkspacePrefs = {
				name: ws?.name ?? initialPrefs.name,
				tz: row.timezone ?? browserTz,
				defaultWindow: row.defaultWindow ?? initialPrefs.defaultWindow,
				week: row.week ?? initialPrefs.week,
			};
			workspaceForm.reset(hydratedPrefs);
			setSavedPrefs(hydratedPrefs);
			setWorkspaceId(ws?.id ?? null);
			setHydrated(true);
		})();
		return () => {
			cancelled = true;
		};
	}, [
		initialPrefs.week,
		initialPrefs.name,
		initialPrefs.defaultWindow,
		browserTz,
		workspaceForm,
	]);

	const dirty = hydrated && workspaceForm.formState.isDirty;

	const reset = () => {
		workspaceForm.reset(savedPrefs);
	};

	const save = async (values: WorkspacePrefs) => {
		if (!dirty || saving) return;
		const trimmedName = values.name.trim();
		setSaving(true);
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not authenticated");

			await upsertUserSetting(user.id, WORKSPACE_PREFS_KEY, {
				timezone: values.tz,
				defaultWindow: values.defaultWindow,
				week: values.week,
			});

			if (workspaceId && trimmedName !== savedPrefs.name) {
				const wsRes = await supabase
					.from("workspaces")
					.update({ name: trimmedName })
					.eq("id", workspaceId);
				if (wsRes.error) throw wsRes.error;
			}

			const nextPrefs = {
				name: trimmedName,
				tz: values.tz,
				defaultWindow: values.defaultWindow,
				week: values.week,
			};
			workspaceForm.reset(nextPrefs);
			setSavedPrefs(nextPrefs);
			appToast.success("Workspace preferences saved");
		} catch (err) {
			appToast.error("Could not save workspace preferences", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="Workspace"
				description="Global settings for everyone on this workspace. Individual preferences live under Profile."
			/>

			<Panel>
				<Form form={workspaceForm} onSubmit={save} className="gap-5">
					<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
						<FormInputField
							name="name"
							label="Workspace name"
							disabled={saving}
						/>
						<FormSelectField
							name="tz"
							label="Timezone"
							hint="Auto-detected from your browser."
							options={timezoneOptions}
							disabled={saving}
						/>
						<FormSelectField
							name="defaultWindow"
							label="Default posting window"
							hint="Used as the fallback when scheduling without a pick."
							options={DEFAULT_POSTING_WINDOW_OPTIONS}
							disabled={saving}
						/>
						<FormField name="week" label="Week starts on" disabled={saving}>
							{({ field }) => (
								<ToggleGroup
									type="single"
									value={field.value}
									onValueChange={(next) => {
										if (next === "sun" || next === "mon") {
											field.onChange(next);
										}
									}}
									className="w-full rounded-md"
									aria-label="Week starts on"
								>
									{(["sun", "mon"] as const).map((d) => (
										<ToggleGroupItem
											key={d}
											value={d}
											className="flex-1 rounded-md"
											disabled={saving}
										>
											{d === "sun" ? "Sunday" : "Monday"}
										</ToggleGroupItem>
									))}
								</ToggleGroup>
							)}
						</FormField>
					</div>

					<div className="flex items-center justify-end gap-2 border-t border-border pt-6">
						<Button
							type="button"
							variant="ghost"
							className="h-9 text-[0.8125rem]"
							onClick={reset}
							disabled={!dirty || saving}
						>
							Reset
						</Button>
						<Button
							type="submit"
							className="h-9 text-[0.8125rem]"
							disabled={!dirty || saving}
						>
							{saving ? "Saving…" : "Save preferences"}
						</Button>
					</div>
				</Form>
			</Panel>
		</div>
	);
}

/* ============================================================================
   White-label
   ========================================================================= */

const WHITELABEL_DEFAULTS = { hex: "#E5484D", domain: "" };

export function WhiteLabelTabContent() {
	const [hex, setHex] = useState(WHITELABEL_DEFAULTS.hex);
	const [domain, setDomain] = useState(WHITELABEL_DEFAULTS.domain);
	const [savedHex, setSavedHex] = useState(WHITELABEL_DEFAULTS.hex);
	const [savedDomain, setSavedDomain] = useState(WHITELABEL_DEFAULTS.domain);
	const [logoUrl, setLogoUrl] = useState<string | null>(null);
	const [logoUploading, setLogoUploading] = useState(false);
	const [saving, setSaving] = useState(false);

	// Hydrate from user_settings so saved config survives reloads.
	useEffect(() => {
		let cancelled = false;
		(async () => {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user || cancelled) return;
			const data = await getUserSetting(user.id, WHITELABEL_PREFS_KEY).catch(
				() => null,
			);
			if (!data || cancelled) return;
			const row = (
				typeof data === "object" && !Array.isArray(data) ? data : {}
			) as WhiteLabelPrefs;
			if (row.logoUrl) setLogoUrl(row.logoUrl);
			if (row.primaryHex) {
				setHex(row.primaryHex);
				setSavedHex(row.primaryHex);
			}
			if (row.domain) {
				setDomain(row.domain);
				setSavedDomain(row.domain);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	const dirty = hex !== savedHex || domain !== savedDomain;

	const reset = () => {
		setHex(savedHex);
		setDomain(savedDomain);
	};

	const save = async () => {
		if (!dirty || saving) return;
		const normalizedHex = hex.trim();
		const normalizedDomain = domain.trim();
		if (!/^#[0-9a-fA-F]{6}$/.test(normalizedHex)) {
			appToast.error("Primary color must be a 6-digit hex (e.g. #E5484D).");
			return;
		}
		if (normalizedDomain && !/^[a-z0-9.-]+$/i.test(normalizedDomain)) {
			appToast.error("Custom domain contains invalid characters.");
			return;
		}
		setSaving(true);
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not authenticated");
			await upsertUserSetting(user.id, WHITELABEL_PREFS_KEY, {
				logoUrl,
				primaryHex: normalizedHex,
				domain: normalizedDomain,
			});
			setHex(normalizedHex);
			setDomain(normalizedDomain);
			setSavedHex(normalizedHex);
			setSavedDomain(normalizedDomain);
			appToast.success("White-label configuration saved");
		} catch (err) {
			appToast.error("Could not save white-label config", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setSaving(false);
		}
	};

	const handleLogoUpload = async (file: File) => {
		const isImage = file.type.startsWith("image/");
		if (!isImage) {
			appToast.error("Logo must be an image.");
			return;
		}
		if (file.size > 2 * 1024 * 1024) {
			appToast.error("Logo must be under 2 MB.");
			return;
		}
		setLogoUploading(true);
		try {
			const [{ uploadToBucket }, { compressImage }] = await Promise.all([
				import("@/services/mediaService"),
				import("@/utils/imageCompress"),
			]);
			// Keep SVGs uncompressed (compressImage skips them); bitmaps go through canvas.
			const prepared = await compressImage(file, {
				maxDimension: 1024,
				quality: 0.9,
			});
			const url = await uploadToBucket("whitelabel", prepared, "logo");
			setLogoUrl(url);
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (user) {
				await upsertUserSetting(user.id, WHITELABEL_PREFS_KEY, {
					logoUrl: url,
					primaryHex: hex,
					domain,
				});
			}
			appToast.success("Logo uploaded");
		} catch (err) {
			appToast.error("Logo upload failed", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setLogoUploading(false);
		}
	};

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="White-label"
				description="Brand exported reports and public dashboards with your agency's identity."
			/>

			<div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 items-start">
				<Panel>
					<div className="flex flex-col gap-5">
						<Field label="Brand logo" hint="PNG or SVG, max 2MB.">
							<label
								className={cn(
									"flex cursor-pointer flex-col items-center justify-center rounded-md text-center",
									"border border-dashed border-border bg-muted/35 px-4 py-6",
									"hover:border-[color:var(--color-oxblood)] hover:bg-[color-mix(in_srgb,var(--color-oxblood)_4%,transparent)]",
									"transition-colors",
									logoUploading && "opacity-60 pointer-events-none",
								)}
							>
								{logoUrl ? (
									<>
										<img
											src={logoUrl}
											alt="Brand logo"
											loading="lazy"
											decoding="async"
											className="h-12 object-contain mb-2"
										/>
										<span className="text-[0.6875rem] text-[color:var(--color-oxblood)] font-medium">
											Replace logo
										</span>
									</>
								) : (
									<>
										<span className="mb-2 flex size-10 items-center justify-center rounded-full border border-border bg-card">
											<Upload data-icon aria-hidden="true" />
										</span>
										<span className="text-[0.78125rem] font-medium text-foreground">
											{logoUploading ? "Uploading…" : "Upload logo"}
										</span>
										<span className="text-[0.6875rem] text-muted-foreground mt-0.5">
											Drag a file, or click to browse
										</span>
									</>
								)}
								<input
									type="file"
									accept="image/png,image/svg+xml,image/jpeg"
									className="sr-only"
									disabled={logoUploading}
									onChange={(e) => {
										const f = e.target.files?.[0];
										if (f) handleLogoUpload(f);
										e.currentTarget.value = "";
									}}
								/>
							</label>
						</Field>

						<Field
							label="Primary color"
							hint="Applied to chart fills, accents, and PDF header bars."
						>
							<div className="flex gap-2 items-stretch">
								<div
									role="img"
									className="w-9 h-9 rounded-md border border-border shrink-0"
									style={{ backgroundColor: hex }}
									aria-label={`Current color ${hex}`}
								/>
								<Input
									className="app-data font-mono uppercase"
									value={hex}
									onChange={(e) => setHex(e.target.value)}
									maxLength={7}
								/>
							</div>
						</Field>

						<Field
							label="Custom domain"
							hint={
								<span>
									Point a CNAME to{" "}
									<span className="font-mono">cname.juno33.com</span>. Contact
									support to complete domain verification before the domain goes
									live.
								</span>
							}
						>
							<Input
								value={domain}
								placeholder="reports.youragency.com"
								onChange={(e) => setDomain(e.target.value)}
								leadingIcon={<Link2 aria-hidden="true" />}
							/>
						</Field>
					</div>

					<Separator className="mt-6" />
					<div className="flex items-center justify-end gap-2 pt-1">
						<Button
							variant="ghost"
							className="h-9 text-[0.8125rem]"
							onClick={reset}
							disabled={!dirty || saving}
						>
							Reset
						</Button>
						<Button
							className="h-9 text-[0.8125rem]"
							onClick={() => void save()}
							disabled={!dirty || saving}
						>
							{saving ? "Saving…" : "Save configuration"}
						</Button>
					</div>
				</Panel>

				{/* Live preview */}
				<NovaCard
					role="region"
					aria-label="Report preview"
					title="Report preview"
					description="White-label output"
					action={<Badge tone="outline">PDF</Badge>}
					contentClassName="pt-0"
				>
					<div className="aspect-[210/297] w-full rounded-md border border-border bg-card relative overflow-hidden">
						<div
							className="absolute top-0 left-0 right-0 h-[5px]"
							style={{ backgroundColor: hex }}
						/>
						<div className="p-3 pt-5">
							<div className="h-3 w-12 rounded-sm bg-border mb-4" />
							<div className="h-2 w-3/4 rounded-sm bg-muted mb-1.5" />
							<div className="h-2 w-1/2 rounded-sm bg-muted mb-5" />
							<div className="flex items-end gap-1.5 h-20 rounded-md bg-muted/40 p-2">
								<div
									className="flex-1 rounded-t-sm"
									style={{ backgroundColor: hex, opacity: 0.7, height: "60%" }}
								/>
								<div
									className="flex-1 rounded-t-sm"
									style={{ backgroundColor: hex, opacity: 0.45, height: "40%" }}
								/>
								<div
									className="flex-1 rounded-t-sm"
									style={{ backgroundColor: hex, opacity: 0.9, height: "80%" }}
								/>
								<div
									className="flex-1 rounded-t-sm"
									style={{ backgroundColor: hex, opacity: 0.55, height: "50%" }}
								/>
								<div
									className="flex-1 rounded-t-sm"
									style={{ backgroundColor: hex, opacity: 0.75, height: "70%" }}
								/>
							</div>
						</div>
					</div>
				</NovaCard>
			</div>
		</div>
	);
}
