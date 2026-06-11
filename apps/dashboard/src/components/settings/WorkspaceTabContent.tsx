import { useEffect, useState } from "react";
import { Link2, Upload } from "lucide-react";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import {
	getUserSetting,
	upsertUserSetting,
} from "@/services/userSettingsService";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Separator } from "@/components/ui/Separator";
import { Select } from "@/components/ui/Select";
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
	const [wsName, setWsName] = useState(initialPrefs.name);
	const [tz, setTz] = useState(initialPrefs.tz);
	const [defaultWindow, setDefaultWindow] = useState(
		initialPrefs.defaultWindow,
	);
	const [week, setWeek] = useState<"sun" | "mon">(initialPrefs.week);
	const [savedPrefs, setSavedPrefs] = useState<WorkspacePrefs>(initialPrefs);
	const [workspaceId, setWorkspaceId] = useState<string | null>(null);
	const [hydrated, setHydrated] = useState(false);
	const [saving, setSaving] = useState(false);

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
			setWsName(hydratedPrefs.name);
			setTz(hydratedPrefs.tz);
			setDefaultWindow(hydratedPrefs.defaultWindow);
			setWeek(hydratedPrefs.week);
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
	]); // eslint-disable-line react-hooks/exhaustive-deps

	const dirty =
		hydrated &&
		(wsName !== savedPrefs.name ||
			tz !== savedPrefs.tz ||
			defaultWindow !== savedPrefs.defaultWindow ||
			week !== savedPrefs.week);

	const reset = () => {
		setWsName(savedPrefs.name);
		setTz(savedPrefs.tz);
		setDefaultWindow(savedPrefs.defaultWindow);
		setWeek(savedPrefs.week);
	};

	const save = async () => {
		if (!dirty || saving) return;
		const trimmedName = wsName.trim();
		if (!trimmedName) {
			appToast.error("Workspace name cannot be empty.");
			return;
		}
		setSaving(true);
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not authenticated");

			await upsertUserSetting(user.id, WORKSPACE_PREFS_KEY, {
				timezone: tz,
				defaultWindow,
				week,
			});

			if (workspaceId && trimmedName !== savedPrefs.name) {
				const wsRes = await supabase
					.from("workspaces")
					.update({ name: trimmedName })
					.eq("id", workspaceId);
				if (wsRes.error) throw wsRes.error;
			}

			setWsName(trimmedName);
			setSavedPrefs({ name: trimmedName, tz, defaultWindow, week });
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
				<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
					<Field label="Workspace name">
						<Input value={wsName} onChange={(e) => setWsName(e.target.value)} />
					</Field>
					<Field label="Timezone" hint="Auto-detected from your browser.">
						<Select value={tz} onChange={(e) => setTz(e.target.value)}>
							<option value="America/New_York">America / New York (ET)</option>
							<option value="America/Chicago">America / Chicago (CT)</option>
							<option value="America/Los_Angeles">
								America / Los Angeles (PT)
							</option>
							<option value="Europe/London">Europe / London (BST)</option>
							<option value="UTC">UTC</option>
							<option value={tz}>{tz}</option>
						</Select>
					</Field>
					<Field
						label="Default posting window"
						hint="Used as the fallback when scheduling without a pick."
					>
						<Select
							value={defaultWindow}
							onChange={(e) => setDefaultWindow(e.target.value)}
						>
							<option value="6-8am">Morning · 6 – 8am</option>
							<option value="9-11am">Morning · 9 – 11am</option>
							<option value="12-2pm">Midday · 12 – 2pm</option>
							<option value="4-6pm">Afternoon · 4 – 6pm</option>
							<option value="7-9pm">Evening · 7 – 9pm</option>
							<option value="10pm">Late · 10pm +</option>
						</Select>
					</Field>
					<Field label="Week starts on">
						<ToggleGroup
							type="single"
							value={week}
							onValueChange={(next) => {
								if (next === "sun" || next === "mon") setWeek(next);
							}}
							className="w-full rounded-md"
						>
							{(["sun", "mon"] as const).map((d) => (
								<ToggleGroupItem
									key={d}
									value={d}
									className="flex-1 rounded-md"
								>
									{d === "sun" ? "Sunday" : "Monday"}
								</ToggleGroupItem>
							))}
						</ToggleGroup>
					</Field>
				</div>

				<div className="flex items-center justify-end gap-2 pt-6 mt-6 border-t border-border">
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
						{saving ? "Saving…" : "Save preferences"}
					</Button>
				</div>
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
