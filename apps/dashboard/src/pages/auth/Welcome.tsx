// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { appToast } from "@/lib/toast";
import {
	readLocalOnboardingComplete,
	writeLocalOnboardingComplete,
} from "@/lib/onboarding";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import { supabase } from "@/services/supabase";
import { safeRedirectPath } from "@/utils/sanitize";
import { initiateLogin, initiateInstagramLogin } from "@/services/api/accounts";
import { labelFor } from "@/lib/socialPlatform";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import {
	Check,
	ArrowRight,
	ArrowLeft,
	Plus,
	X,
	Sparkles,
	Clock,
} from "lucide-react";

/* =========================================================================
   Onboarding wizard — 3 steps per CLAUDE.md:
     1. Connect your accounts (Threads + IG OAuth)
     2. Organize into networks (drag/tap accounts into named groups)
     3. Set your schedule (timezone + posting windows)
   Non-blocking: skip links everywhere; "finish later" always available.
   Persists to Supabase user metadata when the user finishes.
   ========================================================================= */

const AUTH_REDIRECT_STORAGE_KEY = "juno33-auth-redirect";
const TOTAL_STEPS = 3;

type Platform = "threads" | "instagram";
interface ConnectedAccount {
	id: string;
	handle: string;
	platform: Platform;
	followers: number;
	networkId: string | null; // null = unassigned
}

interface Network {
	id: string;
	name: string;
	color: string;
}

const NETWORK_COLORS = [
	{ id: "ray", hex: "#E5484D", label: "Ray" },
	{ id: "signal", hex: "#B33A3F", label: "Signal" },
	{ id: "slate", hex: "#5F6670", label: "Slate" },
	{ id: "graphite", hex: "#6F7078", label: "Graphite" },
	{ id: "ink", hex: "#1A1A1C", label: "Ink" },
	{ id: "amber", hex: "#A67C2D", label: "Amber" },
	{ id: "sage", hex: "#4F7661", label: "Sage" },
	{ id: "mist", hex: "#8A8D94", label: "Mist" },
];

const TIME_WINDOW_GROUPS: {
	group: "Morning" | "Afternoon" | "Evening";
	windows: { id: string; label: string }[];
}[] = [
	{
		group: "Morning",
		windows: [
			{ id: "morning-6-8", label: "6–8 AM" },
			{ id: "morning-8-10", label: "8–10 AM" },
			{ id: "morning-10-12", label: "10 AM–12 PM" },
		],
	},
	{
		group: "Afternoon",
		windows: [
			{ id: "afternoon-12-2", label: "12–2 PM" },
			{ id: "afternoon-2-4", label: "2–4 PM" },
			{ id: "afternoon-4-6", label: "4–6 PM" },
		],
	},
	{
		group: "Evening",
		windows: [
			{ id: "evening-6-8", label: "6–8 PM" },
			{ id: "evening-8-10", label: "8–10 PM" },
			{ id: "evening-10+", label: "10 PM+" },
		],
	},
];

const _TIME_WINDOWS = TIME_WINDOW_GROUPS.flatMap((g) => g.windows);

const FALLBACK_TIMEZONES = [
	"UTC",
	"America/Adak",
	"America/Anchorage",
	"America/Los_Angeles",
	"America/Phoenix",
	"America/Denver",
	"America/Chicago",
	"America/New_York",
	"America/Toronto",
	"America/Vancouver",
	"America/Mexico_City",
	"America/Bogota",
	"America/Lima",
	"America/Sao_Paulo",
	"America/Buenos_Aires",
	"America/Santiago",
	"Europe/London",
	"Europe/Dublin",
	"Europe/Lisbon",
	"Europe/Paris",
	"Europe/Berlin",
	"Europe/Madrid",
	"Europe/Rome",
	"Europe/Amsterdam",
	"Europe/Stockholm",
	"Europe/Warsaw",
	"Europe/Athens",
	"Europe/Istanbul",
	"Africa/Cairo",
	"Africa/Johannesburg",
	"Africa/Lagos",
	"Asia/Dubai",
	"Asia/Jerusalem",
	"Asia/Kolkata",
	"Asia/Bangkok",
	"Asia/Singapore",
	"Asia/Hong_Kong",
	"Asia/Shanghai",
	"Asia/Tokyo",
	"Asia/Seoul",
	"Asia/Jakarta",
	"Australia/Perth",
	"Australia/Adelaide",
	"Australia/Brisbane",
	"Australia/Sydney",
	"Pacific/Auckland",
	"Pacific/Honolulu",
] as const;

const SUPPORTED_TIMEZONES = (() => {
	const intlWithSupportedValues = Intl as typeof Intl & {
		supportedValuesOf?: (key: "timeZone") => string[];
	};
	try {
		const zones = intlWithSupportedValues.supportedValuesOf?.("timeZone");
		if (zones?.length) return Array.from(new Set(["UTC", ...zones]));
	} catch {
		// Fall back below.
	}
	return [...FALLBACK_TIMEZONES];
})();

const SUPPORTED_TIMEZONE_SET = new Set(SUPPORTED_TIMEZONES);

function normalizeWelcomeStep(value: string | null): number {
	const parsed = Number(value);
	return Number.isInteger(parsed) && parsed >= 1 && parsed <= TOTAL_STEPS
		? parsed
		: 1;
}

export function Welcome() {
	const navigate = useNavigate();
	const [searchParams, setSearchParams] = useSearchParams();
	const [step, setStep] = useState(() =>
		normalizeWelcomeStep(searchParams.get("step")),
	);

	// Step 1 state — connected accounts (hydrated from Supabase on mount + after OAuth return)
	const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
	const [connectingPlatform, setConnectingPlatform] = useState<Platform | null>(
		null,
	);

	// Step 2 state — networks
	const [networks, setNetworks] = useState<Network[]>([]);
	const [newNetworkName, setNewNetworkName] = useState("");
	const [newNetworkColor, setNewNetworkColor] = useState(
		NETWORK_COLORS[0]!.hex,
	);
	const [openAssignAccountId, setOpenAssignAccountId] = useState<string | null>(
		null,
	);

	// Step 3 state — schedule
	const browserTimezone = useMemo(() => {
		try {
			const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
			return SUPPORTED_TIMEZONE_SET.has(detected) ? detected : "UTC";
		} catch {
			return "UTC";
		}
	}, []);
	const [timezone, setTimezone] = useState(browserTimezone);
	const [selectedWindows, setSelectedWindows] = useState<Set<string>>(
		new Set(["morning-8-10", "evening-8-10"]),
	);

	const [isFinishing, setIsFinishing] = useState(false);
	const [accountPendingRemoval, setAccountPendingRemoval] =
		useState<ConnectedAccount | null>(null);
	const [isRemovingAccount, setIsRemovingAccount] = useState(false);

	// Tracks whether the user is already onboarded (metadata flag, localStorage,
	// or existing accounts) — when true, we render a "You're already set up"
	// escape hatch instead of forcing them back through the wizard.
	const [alreadyOnboarded, setAlreadyOnboarded] = useState(false);

	useEffect(() => {
		setSearchParams(
			(prev) => {
				if (prev.get("step") === String(step)) return prev;
				const next = new URLSearchParams(prev);
				next.set("step", String(step));
				return next;
			},
			{ replace: true },
		);
	}, [step, setSearchParams]);

	useEffect(() => {
		let cancelled = false;
		(async () => {
			if (searchParams.get("force") === "1") return;
			try {
				const {
					data: { user },
				} = await supabase.auth.getUser();
				if (!user || cancelled) return;
				const meta = user.user_metadata as {
					onboarding_completed_at?: string | undefined;
					onboarding_complete?: boolean | undefined;
				} | null;
				const metaComplete = Boolean(
					meta?.onboarding_completed_at ?? meta?.onboarding_complete,
				);
				const localFlag = readLocalOnboardingComplete(user.id);
				if (metaComplete || localFlag) {
					if (!cancelled) setAlreadyOnboarded(true);
					return;
				}
				const [threadsRes, igRes] = await Promise.all([
					supabase
						.from("accounts")
						.select("id", { count: "exact", head: true })
						.eq("user_id", user.id)
						.eq("is_retired", false),
					supabase
						.from("instagram_accounts")
						.select("id", { count: "exact", head: true })
						.eq("user_id", user.id),
				]);
				if (cancelled) return;
				if ((threadsRes.count ?? 0) + (igRes.count ?? 0) > 0) {
					setAlreadyOnboarded(true);
				}
			} catch {
				/* stay silent — fall through to regular wizard */
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [searchParams]);

	const goToDashboard = async () => {
		try {
			localStorage.removeItem(AUTH_REDIRECT_STORAGE_KEY);
		} catch {}
		// Await the metadata write so AuthGate reads fresh user_metadata on the
		// next render. Force a full reload (not react-router navigate) so any
		// in-memory state on this page can't bounce us back before AuthGate
		// re-evaluates with the fresh flags.
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			await supabase.auth.updateUser({
				data: { onboarding_completed_at: new Date().toISOString() },
			});
			writeLocalOnboardingComplete(user?.id);
		} catch {}
		queryClient.removeQueries({ queryKey: queryKeys.onboarding.all });
		queryClient.removeQueries({ queryKey: queryKeys.accounts.connectedAll });
		queryClient.removeQueries({ queryKey: queryKeys.accounts.groupsAll });
		window.location.replace("/dashboard");
	};

	useEffect(() => {
		let cancelled = false;

		const hydrate = async () => {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user || cancelled) return;

			const [threadsRes, igRes, groupsRes] = await Promise.all([
				supabase
					.from("accounts")
					.select("id, username, followers_count, group_id")
					.eq("user_id", user.id)
					.eq("is_retired", false),
				supabase
					.from("instagram_accounts")
					.select("id, username, follower_count, group_id")
					.eq("user_id", user.id),
				supabase
					.from("account_groups")
					.select("id, name, color")
					.eq("user_id", user.id)
					.order("created_at", { ascending: true }),
			]);

			if (cancelled) return;

			const groups = Array.isArray(groupsRes.data)
				? groupsRes.data.map((row) => ({
						id: row.id,
						name: row.name,
						color: row.color ?? NETWORK_COLORS[0]!.hex,
					}))
				: [];

			const hydrated: ConnectedAccount[] = [
				...(threadsRes.data ?? []).map((row) => ({
					id: row.id,
					handle: row.username ? `@${row.username}` : "Unnamed Threads account",
					platform: "threads" as Platform,
					followers: row.followers_count ?? 0,
					networkId: row.group_id ?? null,
				})),
				...(igRes.data ?? []).map((row) => ({
					id: row.id,
					handle: row.username
						? `@${row.username}`
						: "Unnamed Instagram account",
					platform: "instagram" as Platform,
					followers: row.follower_count ?? 0,
					networkId: row.group_id ?? null,
				})),
			];
			setNetworks(groups);
			setAccounts(hydrated);
		};

		hydrate();
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		if (searchParams.get("connected") !== "true") return;
		const platform = searchParams.get("platform");
		const label =
			platform === "instagram"
				? "Instagram"
				: platform === "facebook"
					? "Facebook"
					: "Threads";
		appToast.success(`${label} connected`);
		setSearchParams(
			(prev) => {
				const next = new URLSearchParams(prev);
				next.delete("connected");
				next.delete("platform");
				return next;
			},
			{ replace: true },
		);
	}, [searchParams, setSearchParams]);

	const handleConnect = async (platform: Platform) => {
		setConnectingPlatform(platform);
		try {
			localStorage.setItem("juno33-oauth-source", "onboarding");
			const { authUrl } =
				platform === "threads"
					? await initiateLogin()
					: await initiateInstagramLogin();
			window.location.href = authUrl;
		} catch (err) {
			setConnectingPlatform(null);
			const description =
				err instanceof Error ? err.message : "Could not start OAuth.";
			appToast.error(`Couldn't connect ${labelFor(platform)}`, { description });
		}
	};

	const removeAccount = async (account: ConnectedAccount) => {
		setAccountPendingRemoval(account);
	};

	const confirmRemoveAccount = async () => {
		if (!accountPendingRemoval) return;
		const account = accountPendingRemoval;
		setIsRemovingAccount(true);
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not authenticated");

			if (account.platform === "threads") {
				const { error } = await supabase
					.from("accounts")
					.update({
						is_active: false,
						is_retired: true,
						group_id: null,
					})
					.eq("id", account.id)
					.eq("user_id", user.id);
				if (error) throw error;
			} else {
				const { error } = await supabase
					.from("instagram_accounts")
					.update({
						is_active: false,
						group_id: null,
					})
					.eq("id", account.id)
					.eq("user_id", user.id);
				if (error) throw error;
			}

			setAccounts((prev) => prev.filter((a) => a.id !== account.id));
			setOpenAssignAccountId((current) =>
				current === account.id ? null : current,
			);
			setAccountPendingRemoval(null);
			appToast.success(`${account.handle} disconnected`);
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Could not disconnect account.";
			appToast.error(`Couldn't remove ${account.handle}`, { description });
		} finally {
			setIsRemovingAccount(false);
		}
	};

	// Step 2
	const addNetwork = () => {
		const name = newNetworkName.trim();
		if (!name) return;
		const id = `net-${Date.now()}`;
		setNetworks((prev) => [...prev, { id, name, color: newNetworkColor }]);
		setNewNetworkName("");
		setNewNetworkColor(
			NETWORK_COLORS[(networks.length + 1) % NETWORK_COLORS.length]!.hex,
		);
	};

	const assignAccount = (accountId: string, networkId: string | null) => {
		setAccounts((prev) =>
			prev.map((a) => (a.id === accountId ? { ...a, networkId } : a)),
		);
		setOpenAssignAccountId(null);
	};

	// Step 3
	const toggleWindow = (id: string) => {
		setSelectedWindows((prev) => {
			const next = new Set(prev);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			return next;
		});
	};

	const canAdvance =
		(step === 1 && accounts.length >= 1) ||
		step === 2 || // organizing is optional
		(step === 3 &&
			selectedWindows.size >= 1 &&
			SUPPORTED_TIMEZONE_SET.has(timezone));

	const handleNext = () => {
		if (step < TOTAL_STEPS) setStep(step + 1);
		else persistAndFinish();
	};

	const handleBack = () => {
		if (step > 1) setStep(step - 1);
	};

	const persistAndFinish = async () => {
		setIsFinishing(true);
		const nextPath = (() => {
			try {
				return safeRedirectPath(
					localStorage.getItem(AUTH_REDIRECT_STORAGE_KEY),
				);
			} catch {
				return "/dashboard";
			}
		})();
		const clearRedirect = () => {
			try {
				localStorage.removeItem(AUTH_REDIRECT_STORAGE_KEY);
			} catch {
				// noop
			}
		};

		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not authenticated");

			const existingGroupsRes = await supabase
				.from("account_groups")
				.select("id, name, color")
				.eq("user_id", user.id);
			if (existingGroupsRes.error) throw existingGroupsRes.error;

			const existingGroups = existingGroupsRes.data ?? [];
			const groupIdMap = new Map<string, string>();

			for (const network of networks) {
				if (existingGroups.some((group) => group.id === network.id)) {
					const { error } = await supabase
						.from("account_groups")
						.update({
							name: network.name,
							color: network.color,
							updated_at: new Date().toISOString(),
						})
						.eq("id", network.id)
						.eq("user_id", user.id);
					if (error) throw error;
					groupIdMap.set(network.id, network.id);
					continue;
				}

				const matchedByName = existingGroups.find(
					(group) => group.name === network.name,
				);
				if (matchedByName) {
					const { error } = await supabase
						.from("account_groups")
						.update({
							color: network.color,
							updated_at: new Date().toISOString(),
						})
						.eq("id", matchedByName.id)
						.eq("user_id", user.id);
					if (error) throw error;
					groupIdMap.set(network.id, matchedByName.id);
					continue;
				}

				const { data: createdGroup, error } = await supabase
					.from("account_groups")
					.insert({
						user_id: user.id,
						name: network.name,
						color: network.color,
						category: "uncategorized",
						account_ids: [],
					})
					.select("id")
					.single();
				if (error || !createdGroup)
					throw error ?? new Error("Failed to create account group");
				groupIdMap.set(network.id, createdGroup.id);
			}

			const threadAccounts = accounts.filter(
				(account) => account.platform === "threads",
			);
			const instagramAccounts = accounts.filter(
				(account) => account.platform === "instagram",
			);
			const threadIds = threadAccounts.map((account) => account.id);
			const instagramIds = instagramAccounts.map((account) => account.id);

			if (threadIds.length > 0) {
				const { error } = await supabase
					.from("accounts")
					.update({ group_id: null })
					.eq("user_id", user.id)
					.in("id", threadIds);
				if (error) throw error;
			}

			if (instagramIds.length > 0) {
				const { error } = await supabase
					.from("instagram_accounts")
					.update({ group_id: null })
					.eq("user_id", user.id)
					.in("id", instagramIds);
				if (error) throw error;
			}

			for (const network of networks) {
				const persistedGroupId = groupIdMap.get(network.id);
				if (!persistedGroupId) continue;

				const assignedThreads = threadAccounts
					.filter((account) => account.networkId === network.id)
					.map((account) => account.id);
				const assignedInstagram = instagramAccounts
					.filter((account) => account.networkId === network.id)
					.map((account) => account.id);
				const assignedIds = [...assignedThreads, ...assignedInstagram];

				if (assignedThreads.length > 0) {
					const { error } = await supabase
						.from("accounts")
						.update({ group_id: persistedGroupId })
						.eq("user_id", user.id)
						.in("id", assignedThreads);
					if (error) throw error;
				}

				if (assignedInstagram.length > 0) {
					const { error } = await supabase
						.from("instagram_accounts")
						.update({ group_id: persistedGroupId })
						.eq("user_id", user.id)
						.in("id", assignedInstagram);
					if (error) throw error;
				}

				const { error } = await supabase
					.from("account_groups")
					.update({
						account_ids: assignedIds,
						updated_at: new Date().toISOString(),
					})
					.eq("id", persistedGroupId)
					.eq("user_id", user.id);
				if (error) throw error;
			}

			const { error } = await supabase.auth.updateUser({
				data: {
					onboarding_completed_at: new Date().toISOString(),
					connected_account_count: accounts.length,
					networks: networks.map((n) => ({
						id: groupIdMap.get(n.id) ?? n.id,
						name: n.name,
						color: n.color,
					})),
					timezone,
					posting_windows: Array.from(selectedWindows),
				},
			});
			if (error) throw error;
			writeLocalOnboardingComplete(user.id);

			await Promise.all([
				queryClient.invalidateQueries({ queryKey: queryKeys.onboarding.all }),
				queryClient.invalidateQueries({ queryKey: queryKeys.accounts.connectedAll }),
				queryClient.invalidateQueries({ queryKey: queryKeys.accounts.groupsAll }),
			]);
			clearRedirect();
			navigate(nextPath);
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Saving your preferences failed.";
			appToast.error("Onboarding save failed", { description });
		} finally {
			setIsFinishing(false);
		}
	};

	// "Skip for now" means skip — don't run the full persist chain. Write
	// the completion flag directly (same path as the already-onboarded
	// banner's escape hatch) and go to the dashboard. Previously this
	// called persistAndFinish, so any transient DB failure in the
	// account-group loop trapped the user in a /welcome redirect loop on
	// every subsequent login.
	const skipAll = async () => {
		appToast.info("You can finish setup anytime from Settings.");
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (user) {
				try {
					await supabase.auth.updateUser({
						data: { onboarding_completed_at: new Date().toISOString() },
					});
				} catch {
					/* cloud write failed — local fallback below still unsticks AuthGate */
				}
				writeLocalOnboardingComplete(user.id);
			}
		} catch {
			/* if even getUser fails the wizard stays — AuthGate will still retry next time */
		}
		try {
			localStorage.removeItem(AUTH_REDIRECT_STORAGE_KEY);
		} catch {}
		queryClient.removeQueries({ queryKey: queryKeys.onboarding.all });
		queryClient.removeQueries({ queryKey: queryKeys.accounts.connectedAll });
		queryClient.removeQueries({ queryKey: queryKeys.accounts.groupsAll });
		window.location.replace("/dashboard");
	};

	return (
		<>
			<div className="md:hidden w-full min-h-[100svh] bg-background text-foreground flex flex-col">
				<div className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b border-border">
					<div className="h-[3px] bg-muted overflow-hidden">
						<div
							className="h-full w-full origin-left"
							style={{
								backgroundColor: "var(--color-oxblood)",
								transform: `scaleX(${step / TOTAL_STEPS})`,
								transition: "transform 180ms ease",
							}}
						/>
					</div>
					<div className="px-4 pt-4 pb-3">
						<div className="flex items-center justify-between gap-3">
							<span className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground tabular-nums">
								Step {step} of {TOTAL_STEPS}
							</span>
							<Button
								type="button"
								onClick={skipAll}
								className="min-h-10 px-2 text-[0.78125rem] font-medium text-muted-foreground active:text-foreground transition-colors"
							>
								Skip
							</Button>
						</div>
						<div className="mt-3 grid grid-cols-3 gap-1.5">
							{[1, 2, 3].map((item) => (
								<Button
									key={item}
									type="button"
									onClick={() => setStep(item)}
									aria-label={`Go to step ${item}`}
									aria-current={item === step ? "step" : undefined}
									className={`h-1.5 rounded-full transition-colors ${
										item <= step
											? "bg-[color:var(--color-oxblood)]"
											: "bg-muted"
									}`}
								/>
							))}
						</div>
					</div>
				</div>

				{alreadyOnboarded && (
					<div
						className="mx-4 mt-4 rounded-md px-4 py-3"
						style={{
							backgroundColor:
								"color-mix(in srgb, var(--color-oxblood) 10%, transparent)",
							border:
								"0.5px solid color-mix(in srgb, var(--color-oxblood) 22%, transparent)",
						}}
					>
						<div className="text-[0.8125rem] font-medium text-foreground">
							You're already set up.
						</div>
						<div className="mt-1 text-[0.75rem] leading-relaxed text-muted-foreground">
							Head to the dashboard, or keep editing this setup.
						</div>
						<Button
							type="button"
							onClick={goToDashboard}
							className="mt-3 h-10 w-full rounded-md text-[0.8125rem] font-semibold text-white"
							style={{ backgroundColor: "var(--color-oxblood)" }}
						>
							Go to dashboard
						</Button>
					</div>
				)}

				<div className="flex-1 overflow-y-auto px-4 py-5 pb-28">
						{step === 1 && (
							<div className="flex flex-col gap-5">
								<div>
									<h2 className="text-[1.625rem] leading-tight font-medium tracking-[-0.02em] text-foreground">
										Connect accounts
									</h2>
									<p className="mt-2 text-[0.875rem] leading-relaxed text-muted-foreground">
										Add at least one Threads or Instagram account. You can
										connect the rest later.
									</p>
								</div>

								<div className="grid grid-cols-1 gap-2.5">
									<ConnectButton
										platform="threads"
										loading={connectingPlatform === "threads"}
										onClick={() => handleConnect("threads")}
									/>
									<ConnectButton
										platform="instagram"
										loading={connectingPlatform === "instagram"}
										onClick={() => handleConnect("instagram")}
									/>
								</div>

								{accounts.length > 0 && (
									<div className="flex flex-col gap-2.5">
										<div className="flex items-baseline justify-between">
											<span className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
												Connected
											</span>
											<span className="text-[0.75rem] text-muted-foreground tabular-nums">
												{accounts.length}{" "}
												{accounts.length === 1 ? "account" : "accounts"}
											</span>
										</div>
										<div className="flex flex-col gap-2">
											{accounts.map((a) => (
												<div
													key={a.id}
													className="flex min-h-14 items-center gap-3 rounded-md border border-border bg-background px-3 py-2"
												>
													<span
														className="w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center text-[0.8125rem] font-semibold text-white"
														style={{
															background: `linear-gradient(135deg, var(${a.platform === "threads" ? "--color-aurora" : "--color-meridian"}), var(--color-ink))`,
														}}
													>
														{a.handle.startsWith("@")
															? (
																	a.handle[1] ??
																	labelFor(a.platform)[0] ??
																	"?"
																).toUpperCase()
															: (labelFor(a.platform)[0] ?? "?")}
													</span>
													<div className="min-w-0 flex-1">
														<div className="truncate text-[0.875rem] font-medium text-foreground">
															{a.handle}
														</div>
														<div className="text-[0.71875rem] text-muted-foreground tabular-nums">
															{labelFor(a.platform)} ·{" "}
															{a.followers.toLocaleString()} followers
														</div>
													</div>
													<Button
														type="button"
														onClick={() => removeAccount(a)}
														aria-label={`Remove ${a.handle}`}
														className="h-11 w-11 -mr-2 rounded-md inline-flex items-center justify-center text-muted-foreground active:bg-foreground/[0.06] active:text-foreground"
													>
														<X className="w-4 h-4" />
													</Button>
												</div>
											))}
										</div>
									</div>
								)}
							</div>
						)}

						{step === 2 && (
							<div className="flex flex-col gap-5">
								<div>
									<h2 className="text-[1.625rem] leading-tight font-medium tracking-[-0.02em] text-foreground">
										Organize networks
									</h2>
									<p className="mt-2 text-[0.875rem] leading-relaxed text-muted-foreground">
										Create groups for brands, clients, or personas. Assignment
										uses phone-native controls here.
									</p>
								</div>

								<div className="flex flex-col gap-3 rounded-md border border-border bg-background p-3">
									<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
										Add a network
									</div>
									<Input
										type="text"
										value={newNetworkName}
										onChange={(e) => setNewNetworkName(e.target.value)}
										onKeyDown={(e) => {
											if (e.key === "Enter" && newNetworkName.trim()) {
												e.preventDefault();
												addNetwork();
											}
										}}
										placeholder="Brand, client, or persona"
										className="min-h-10 rounded-md border border-input bg-background text-foreground px-3"
									/>
									<div className="flex flex-wrap gap-2">
										{NETWORK_COLORS.map((c) => (
											<Button
												key={c.id}
												type="button"
												onClick={() => setNewNetworkColor(c.hex)}
												aria-label={c.label}
												aria-pressed={newNetworkColor === c.hex}
												className={`w-9 h-9 rounded-full transition-[transform,box-shadow] ${
													newNetworkColor === c.hex
														? "scale-105 ring-2 ring-offset-2 ring-offset-background ring-foreground/50"
														: ""
												}`}
												style={{ backgroundColor: c.hex }}
											/>
										))}
									</div>
									<Button
										type="button"
										onClick={addNetwork}
										disabled={!newNetworkName.trim()}
										className=" w-full disabled:opacity-40 disabled:pointer-events-none"
									>
										<Plus className="w-4 h-4" /> Add network
									</Button>
								</div>

								{networks.length > 0 && (
									<div className="flex flex-col gap-2">
										<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
											Networks
										</div>
										{networks.map((n) => {
											const assigned = accounts.filter(
												(a) => a.networkId === n.id,
											);
											return (
												<div
													key={n.id}
													className="rounded-md border border-border bg-background px-3 py-2.5"
												>
													<div className="flex items-center gap-2">
														<span
															className="w-2.5 h-2.5 rounded-full flex-shrink-0"
															style={{ backgroundColor: n.color }}
														/>
														<span className="min-w-0 flex-1 truncate text-[0.875rem] font-medium text-foreground">
															{n.name}
														</span>
														<span className="text-[0.71875rem] text-muted-foreground tabular-nums">
															{assigned.length}
														</span>
													</div>
													{assigned.length > 0 && (
														<div className="mt-2 flex flex-wrap gap-1.5">
															{assigned.map((a) => (
																<Button
																	key={a.id}
																	type="button"
																	onClick={() => assignAccount(a.id, null)}
																	className="min-h-8 rounded-full bg-muted px-2.5 text-[0.75rem] text-foreground inline-flex items-center gap-1.5"
																>
																	{a.handle}
																	<X className="w-3 h-3" />
																</Button>
															))}
														</div>
													)}
												</div>
											);
										})}
									</div>
								)}

								{accounts.length > 0 && (
									<div className="flex flex-col gap-2">
										<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
											Assign accounts
										</div>
										{accounts.map((a) => (
											<label
												key={a.id}
												htmlFor={`welcome-account-network-${a.id}`}
												className="block rounded-md border border-border bg-background p-3"
											>
												<span className="block text-[0.875rem] font-medium text-foreground">
													{a.handle}
												</span>
												<span className="mb-2 block text-[0.71875rem] text-muted-foreground">
													{labelFor(a.platform)}
												</span>
												<Select
													id={`welcome-account-network-${a.id}`}
													value={a.networkId ?? ""}
													onChange={(e) =>
														assignAccount(a.id, e.target.value || null)
													}
													className="min-h-10 rounded-md border border-input bg-background text-foreground px-3"
												>
													<option value="">Unassigned</option>
													{networks.map((n) => (
														<option key={n.id} value={n.id}>
															{n.name}
														</option>
													))}
												</Select>
											</label>
										))}
									</div>
								)}
							</div>
						)}

						{step === 3 && (
							<div className="flex flex-col gap-5">
								<div>
									<h2 className="text-[1.625rem] leading-tight font-medium tracking-[-0.02em] text-foreground">
										Set schedule
									</h2>
									<p className="mt-2 text-[0.875rem] leading-relaxed text-muted-foreground">
										Choose the timezone and posting windows Juno33 should start
										with.
									</p>
								</div>

								<div>
									<label
										htmlFor="welcome-timezone-mobile"
										className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 block"
									>
										Timezone
									</label>
									<div className="flex items-center gap-2">
										<Clock className="w-4 h-4 text-muted-foreground flex-shrink-0" />
										<Select
											id="welcome-timezone-mobile"
											value={timezone}
											onChange={(e) => setTimezone(e.target.value)}
											className="min-h-10 rounded-md border border-input bg-background text-foreground min-w-0 flex-1 px-3 font-mono tabular-nums"
										>
											{SUPPORTED_TIMEZONES.map((zone) => (
												<option key={zone} value={zone}>
													{zone}
												</option>
											))}
										</Select>
									</div>
								</div>

								<div className="flex flex-col gap-4">
									<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
										Posting windows
									</div>
									{TIME_WINDOW_GROUPS.map((group) => (
										<div key={group.group}>
											<div className="text-[0.6875rem] font-medium uppercase tracking-[0.14em] text-[color:var(--color-oxblood)] mb-2 flex items-center gap-1.5">
												<span className="w-1 h-1 rounded-full bg-[color:var(--color-oxblood)]" />
												{group.group}
											</div>
											<div className="grid grid-cols-1 gap-2">
												{group.windows.map((w) => {
													const active = selectedWindows.has(w.id);
													return (
														<Button
															key={w.id}
															type="button"
															onClick={() => toggleWindow(w.id)}
															className={`min-h-11 rounded-md border px-3 text-left transition-colors inline-flex items-center gap-2.5 ${
																active
																	? "border-[color-mix(in_srgb,var(--color-oxblood)_50%,transparent)] bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)]"
																	: "border-border bg-background active:border-input"
															}`}
														>
															<span
																className={`w-5 h-5 rounded flex-shrink-0 inline-flex items-center justify-center transition-colors ${
																	active ? "" : "border border-border"
																}`}
																style={{
																	backgroundColor: active
																		? "var(--color-oxblood)"
																		: undefined,
																}}
															>
																{active && (
																	<Check
																		className="w-3 h-3 text-white"
																		strokeWidth={3}
																	/>
																)}
															</span>
															<span className="text-[0.875rem] font-medium text-foreground tabular-nums">
																{w.label}
															</span>
														</Button>
													);
												})}
											</div>
										</div>
									))}
								</div>

								<div
									className="rounded-md p-3 flex gap-2.5"
									style={{
										backgroundColor:
											"color-mix(in srgb, var(--color-oxblood) 5%, transparent)",
										border:
											"0.5px solid color-mix(in srgb, var(--color-oxblood) 22%, transparent)",
									}}
								>
									<Sparkles
										className="w-4 h-4 mt-0.5 flex-shrink-0"
										style={{ color: "var(--color-oxblood)" }}
									/>
									<p className="text-[0.8125rem] text-muted-foreground leading-relaxed">
										Once you have enough published posts, Juno33 shows your
										best-performing posting windows in Composer and Calendar.
									</p>
								</div>
							</div>
						)}
				</div>

				<div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-background/95 px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur">
					<div className="flex items-center gap-2">
						<Button
							type="button"
							onClick={handleBack}
							disabled={step === 1}
							className="h-11 px-3 rounded-md text-[0.875rem] font-medium text-muted-foreground active:text-foreground transition-colors disabled:opacity-30 disabled:pointer-events-none inline-flex items-center gap-1"
						>
							<ArrowLeft className="w-4 h-4" />
							Back
						</Button>
						<Button
							type="button"
							onClick={handleNext}
							disabled={!canAdvance || isFinishing}
							className=" flex-1 disabled:opacity-40 disabled:pointer-events-none"
						>
							{isFinishing
								? "Saving..."
								: step === TOTAL_STEPS
									? "Open dashboard"
									: "Continue"}
							{!isFinishing && <ArrowRight className="w-4 h-4" />}
						</Button>
					</div>
				</div>
			</div>

			<div className="hidden w-full max-w-xl overflow-hidden rounded-lg border border-border bg-card shadow-sm md:block">
				{/* Progress bar */}
				<div className="h-[3px] bg-muted overflow-hidden">
					<div
						className="h-full w-full origin-left"
						style={{
							backgroundColor: "var(--color-oxblood)",
							transform: `scaleX(${step / TOTAL_STEPS})`,
							transition: "transform 180ms ease",
						}}
					/>
				</div>

				{/* Already-onboarded banner — appears when the user lands on /welcome
          but their metadata / localStorage / connected accounts indicate they
          already completed setup. Manual click avoids the redirect loop we hit
          when auto-redirecting during auth hydration. */}
				{alreadyOnboarded && (
					<div
						className="mx-6 mt-5 mb-2 flex items-center justify-between gap-3 rounded-md px-4 py-3"
						style={{
							backgroundColor:
								"color-mix(in srgb, var(--color-oxblood) 10%, transparent)",
							border:
								"0.5px solid color-mix(in srgb, var(--color-oxblood) 22%, transparent)",
						}}
					>
						<div className="text-[0.78125rem] text-foreground">
							<span className="font-medium">You're already set up.</span>
							<span className="text-muted-foreground">
								{" "}
								Skip the wizard and head to the dashboard.
							</span>
						</div>
						<Button
							type="button"
							onClick={goToDashboard}
							className="shrink-0 h-8 px-3 rounded-md text-[0.78125rem] font-semibold text-white transition-colors"
							style={{ backgroundColor: "var(--color-oxblood)" }}
						>
							Go to dashboard →
						</Button>
					</div>
				)}

				{/* Step indicator */}
				<div className="flex items-center justify-between px-6 pt-5">
					<span className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground tabular-nums">
						Step {step} of {TOTAL_STEPS}
					</span>
					<Button
						type="button"
						onClick={skipAll}
						className="text-[0.71875rem] font-medium text-muted-foreground hover:text-foreground transition-colors"
					>
						Skip for now
					</Button>
				</div>

				<div className="px-6 py-6">
						{step === 1 && (
							<div className="flex flex-col gap-6">
								<div>
									<h2 className="text-[1.5rem] font-medium tracking-[-0.025em] text-foreground mb-1.5">
										Connect your accounts
									</h2>
									<p className="text-[0.8125rem] text-muted-foreground leading-relaxed">
										Juno33 schedules and analyzes your Threads + Instagram
										accounts. Connect at least one to get started — you can add
										more later.
									</p>
								</div>

								<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
									<ConnectButton
										platform="threads"
										loading={connectingPlatform === "threads"}
										onClick={() => handleConnect("threads")}
									/>
									<ConnectButton
										platform="instagram"
										loading={connectingPlatform === "instagram"}
										onClick={() => handleConnect("instagram")}
									/>
								</div>

								{/* Connected list */}
								{accounts.length > 0 && (
									<div>
										<div className="flex items-baseline justify-between mb-2">
											<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
												Connected
											</span>
											<span className="text-[0.71875rem] text-muted-foreground tabular-nums">
												{accounts.length}{" "}
												{accounts.length === 1 ? "account" : "accounts"}
											</span>
										</div>
										<div className="flex max-h-[220px] overflow-y-auto hide-scrollbar">
											{accounts.map((a) => (
												<div
													key={a.id}
													className="flex items-center gap-3 px-3 py-2 rounded-md bg-muted"
												>
													<span
														className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center text-[0.625rem] font-semibold text-white"
														style={{
															background: `linear-gradient(135deg, var(${a.platform === "threads" ? "--color-aurora" : "--color-meridian"}), var(--color-ink))`,
														}}
													>
														{a.handle.startsWith("@")
															? a.handle[1]!.toUpperCase()
															: labelFor(a.platform)[0]}
													</span>
													<div className="flex-1 min-w-0">
														<div className="text-[0.8125rem] font-medium text-foreground truncate">
															{a.handle}
														</div>
														<div className="text-[0.65625rem] text-muted-foreground tabular-nums">
															{labelFor(a.platform)} ·{" "}
															{a.followers.toLocaleString()} followers
														</div>
													</div>
													<Check
														className="w-3.5 h-3.5 flex-shrink-0"
														style={{ color: "var(--color-gold)" }}
													/>
													<Button
														type="button"
														onClick={() => removeAccount(a)}
														aria-label={`Remove ${a.handle}`}
														className="w-9 h-9 -mr-2 rounded-md inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors"
													>
														<X className="w-3.5 h-3.5" />
													</Button>
												</div>
											))}
										</div>
									</div>
								)}
							</div>
						)}

						{step === 2 && (
							<div className="flex flex-col gap-6">
								<div>
									<h2 className="text-[1.5rem] font-medium tracking-[-0.025em] text-foreground mb-1.5">
										Organize into networks
									</h2>
									<p className="text-[0.8125rem] text-muted-foreground leading-relaxed">
										Group accounts by brand, client, or persona. Skip this if
										you just have a handful — you can organize later.
									</p>
								</div>

								{/* Add network */}
								<div className="flex flex-col gap-2.5 rounded-md bg-muted p-3">
									<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
										Add a network
									</div>
									<div className="flex gap-2">
										<Input
											type="text"
											value={newNetworkName}
											onChange={(e) => setNewNetworkName(e.target.value)}
											onKeyDown={(e) => {
												if (e.key === "Enter" && newNetworkName.trim()) {
													e.preventDefault();
													addNetwork();
												}
											}}
											placeholder="e.g. Miami Models, Client Nike, Personal"
											className="flex-1 min-h-10 rounded-md border border-input bg-background text-foreground px-3"
										/>
										<Button
											type="button"
											onClick={addNetwork}
											disabled={!newNetworkName.trim()}
											className=" disabled:opacity-40 disabled:pointer-events-none"
										>
											<Plus className="w-3.5 h-3.5" /> Add
										</Button>
									</div>
									<div className="flex flex-wrap gap-2">
										{NETWORK_COLORS.map((c) => (
											<Button
												key={c.id}
												type="button"
												onClick={() => setNewNetworkColor(c.hex)}
												aria-label={c.label}
												aria-pressed={newNetworkColor === c.hex}
												className={`w-7 h-7 rounded-full transition-[transform,box-shadow] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] ${
													newNetworkColor === c.hex
														? "scale-110 ring-2 ring-offset-2 ring-offset-muted ring-foreground/50"
														: "hover:scale-105"
												}`}
												style={{ backgroundColor: c.hex }}
											/>
										))}
									</div>
								</div>

								{/* Networks */}
								<div className="flex flex-col gap-2">
									{networks.length === 0 && (
										<div className="text-center py-4 text-[0.78125rem] text-muted-foreground">
											No networks yet. Add one above — or skip and organize
											later.
										</div>
									)}
									{networks.map((n) => {
										const assigned = accounts.filter(
											(a) => a.networkId === n.id,
										);
										return (
											<div
												key={n.id}
												className="border border-border rounded-md p-3"
											>
												<div className="flex items-center gap-2 mb-2">
													<span
														className="w-2 h-2 rounded-full flex-shrink-0"
														style={{ backgroundColor: n.color }}
													/>
													<span className="text-[0.8125rem] font-medium text-foreground flex-1">
														{n.name}
													</span>
													<span className="text-[0.65625rem] text-muted-foreground tabular-nums">
														{assigned.length}{" "}
														{assigned.length === 1 ? "account" : "accounts"}
													</span>
												</div>
												{assigned.length > 0 && (
													<div className="flex flex-wrap gap-1.5 mb-2">
														{assigned.map((a) => (
															<Button
																key={a.id}
																type="button"
																onClick={() => assignAccount(a.id, null)}
																className="text-[0.71875rem] px-2 h-6 rounded-full bg-muted text-foreground hover:bg-foreground/[0.06] transition-colors inline-flex items-center gap-1"
															>
																{a.handle}
																<X className="w-2.5 h-2.5" />
															</Button>
														))}
													</div>
												)}
											</div>
										);
									})}
								</div>

								{/* Unassigned pool */}
								{networks.length > 0 &&
									accounts.filter((a) => !a.networkId).length > 0 && (
										<div>
											<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
												Unassigned · tap to assign
											</div>
											<div className="flex flex-col gap-2">
												{accounts
													.filter((a) => !a.networkId)
													.map((a) => (
														<div
															key={a.id}
															className="rounded-md border border-border bg-background p-2"
														>
															<Button
																type="button"
																onClick={() =>
																	setOpenAssignAccountId((current) =>
																		current === a.id ? null : a.id,
																	)
																}
																aria-expanded={openAssignAccountId === a.id}
																className="w-full flex items-center justify-between gap-3 text-left"
															>
																<span className="text-[0.71875rem] px-2 h-7 rounded-full bg-muted text-muted-foreground inline-flex items-center">
																	{a.handle}
																</span>
																<span className="text-[0.6875rem] text-muted-foreground">
																	{openAssignAccountId === a.id
																		? "Hide networks"
																		: "Choose network"}
																</span>
															</Button>

															{openAssignAccountId === a.id && (
																<div className="mt-2 flex flex-wrap gap-1.5">
																	{networks.map((n) => (
																		<Button
																			key={n.id}
																			type="button"
																			onClick={() => assignAccount(a.id, n.id)}
																			className="px-2.5 py-1.5 text-[0.71875rem] rounded-md inline-flex items-center gap-1.5 border border-border hover:bg-muted transition-colors"
																		>
																			<span
																				className="w-1.5 h-1.5 rounded-full"
																				style={{ backgroundColor: n.color }}
																			/>
																			{n.name}
																		</Button>
																	))}
																</div>
															)}
														</div>
													))}
											</div>
										</div>
									)}
							</div>
						)}

						{step === 3 && (
							<div className="flex flex-col gap-6">
								<div>
									<h2 className="text-[1.5rem] font-medium tracking-[-0.025em] text-foreground mb-1.5">
										Set your schedule
									</h2>
									<p className="text-[0.8125rem] text-muted-foreground leading-relaxed">
										When should your posts typically run? We'll suggest smarter
										times once you have 7 days of data.
									</p>
								</div>

								{/* Timezone */}
								<div>
									<label
										htmlFor="welcome-timezone"
										className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5 block"
									>
										Timezone
									</label>
									<div className="flex items-center gap-2">
										<Clock className="w-4 h-4 text-muted-foreground flex-shrink-0" />
										<Select
											id="welcome-timezone"
											value={timezone}
											onChange={(e) => setTimezone(e.target.value)}
											className="flex-1 min-h-10 rounded-md border border-input bg-background text-foreground px-3 font-mono tabular-nums"
										>
											{SUPPORTED_TIMEZONES.map((zone) => (
												<option key={zone} value={zone}>
													{zone}
												</option>
											))}
										</Select>
									</div>
									<p className="text-[0.6875rem] text-muted-foreground mt-1">
										Auto-detected from your browser. Change if you manage
										accounts in another region.
									</p>
								</div>

								{/* Posting windows */}
								<div>
									<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
										Posting windows
									</div>
									<div className="flex flex-col gap-4">
										{TIME_WINDOW_GROUPS.map((group) => (
											<div key={group.group}>
												<div className="text-[0.625rem] font-medium uppercase tracking-[0.14em] text-[color:var(--color-oxblood)] mb-2 flex items-center gap-1.5">
													<span className="w-1 h-1 rounded-full bg-[color:var(--color-oxblood)]" />
													{group.group}
												</div>
												<div className="grid grid-cols-3 gap-1.5">
													{group.windows.map((w) => {
														const active = selectedWindows.has(w.id);
														return (
															<Button
																key={w.id}
																type="button"
																onClick={() => toggleWindow(w.id)}
																className={`flex items-center justify-center gap-1.5 px-2 py-2 rounded-md border text-center transition-colors ${
																	active
																		? "border-[color-mix(in_srgb,var(--color-oxblood)_50%,transparent)] bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)]"
																		: "border-border hover:border-input"
																}`}
															>
																<span
																	className={`w-3.5 h-3.5 rounded flex-shrink-0 inline-flex items-center justify-center transition-colors ${
																		active ? "" : "border border-border"
																	}`}
																	style={{
																		backgroundColor: active
																			? "var(--color-oxblood)"
																			: undefined,
																	}}
																>
																	{active && (
																		<Check
																			className="w-2 h-2 text-white"
																			strokeWidth={3}
																		/>
																	)}
																</span>
																<span className="text-[0.75rem] font-medium text-foreground tabular-nums">
																	{w.label}
																</span>
															</Button>
														);
													})}
												</div>
											</div>
										))}
									</div>
								</div>

								{/* AI hint card */}
								<div
									className="rounded-md p-3 flex gap-2.5"
									style={{
										backgroundColor:
											"color-mix(in srgb, var(--color-oxblood) 5%, transparent)",
										border:
											"0.5px solid color-mix(in srgb, var(--color-oxblood) 22%, transparent)",
									}}
								>
									<Sparkles
										className="w-3.5 h-3.5 mt-0.5 flex-shrink-0"
										style={{ color: "var(--color-oxblood)" }}
									/>
									<p className="text-[0.75rem] text-muted-foreground leading-relaxed">
										Once you have enough published posts, Juno33 shows your
										best-performing posting windows in Composer and Calendar.
									</p>
								</div>
							</div>
						)}
				</div>

				{/* Footer actions */}
				<div className="flex items-center gap-2 px-6 py-4 border-t border-border">
					<Button
						type="button"
						onClick={handleBack}
						disabled={step === 1}
						className=" text-muted-foreground disabled:opacity-30 disabled:pointer-events-none"
					>
						<ArrowLeft className="w-3.5 h-3.5" />
						Back
					</Button>
					<div className="flex-1" />
					<Button
						type="button"
						onClick={handleNext}
						disabled={!canAdvance || isFinishing}
						className=" disabled:pointer-events-none"
					>
						{isFinishing
							? "Saving…"
							: step === TOTAL_STEPS
								? "Open dashboard"
								: "Continue"}
						{!isFinishing && <ArrowRight className="w-3.5 h-3.5" />}
					</Button>
				</div>
			</div>
			<ConfirmDialog
				open={accountPendingRemoval !== null}
				onClose={() => {
					if (!isRemovingAccount) setAccountPendingRemoval(null);
				}}
				onConfirm={confirmRemoveAccount}
				title={
					accountPendingRemoval
						? `Disconnect ${accountPendingRemoval.handle}?`
						: "Disconnect account?"
				}
				description={
					accountPendingRemoval
						? `Disconnect ${accountPendingRemoval.handle}? You'll need to re-authorize OAuth to reconnect.`
						: "You'll need to re-authorize OAuth to reconnect."
				}
				confirmLabel="Disconnect"
				destructive
				busy={isRemovingAccount}
			/>
		</>
	);
}

/* =========================================================================
   CONNECT BUTTON — platform tile in step 1
   ========================================================================= */
function ConnectButton({
	platform,
	loading,
	onClick,
}: {
	platform: Platform;
	loading: boolean;
	onClick: () => void;
}) {
	const label = labelFor(platform);
	const description =
		platform === "threads" ? "Meta Threads API" : "Instagram Graph API";
	const accentVar =
		platform === "threads" ? "--color-aurora" : "--color-meridian";

	return (
		<Button
			type="button"
			onClick={onClick}
			disabled={loading}
			className="relative h-[84px] rounded-md border border-border bg-background hover:bg-muted hover:border-input transition-all text-left p-3 flex flex-col justify-between disabled:pointer-events-none group"
		>
			<div
				className="w-8 h-8 rounded-md flex items-center justify-center text-[0.9375rem] font-semibold text-white mb-1"
				style={{
					background: `linear-gradient(135deg, var(${accentVar}), var(--color-ink))`,
				}}
			>
				{platform === "threads" ? "@" : "◎"}
			</div>
			<div>
				<div className="text-[0.8125rem] font-medium text-foreground">
					{loading ? "Connecting…" : `Connect ${label}`}
				</div>
				<div className="text-[0.65625rem] text-muted-foreground">
					{description}
				</div>
			</div>
			{loading && (
				<div className="absolute inset-0 bg-foreground/[0.04] rounded-md inline-flex items-center justify-center">
					<div
						className="h-4 w-4 animate-spin rounded-full border-2 border-transparent"
						style={{ borderTopColor: "var(--color-oxblood)" }}
					/>
				</div>
			)}
		</Button>
	);
}
