import { useCallback, useEffect, useRef, useState } from "react";
import {
	CheckCircle2,
	Copy,
	Download,
	Loader2,
	Monitor,
	MonitorSmartphone,
	RefreshCw,
	ShieldCheck,
	Smartphone,
} from "lucide-react";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import {
	countBackupCodes,
	generateBackupCodes,
} from "@/services/api/mfaBackup";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { MicroBadge } from "@/components/ui/MicroBadge";
import { cn } from "@/lib/utils";

import { Panel, SectionHeader } from "./shared";

/* ============================================================================
   Security — 2FA, active sessions, authorized apps
   ========================================================================= */

interface Session {
	id: string;
	device: string;
	browser: string;
	lastActive: string;
	current: boolean;
	Icon: typeof Monitor;
}

/**
 * Derive a best-effort description of the *current* browser session from the
 * User-Agent. We deliberately do NOT fabricate other device rows — Supabase JS
 * only exposes the active session to the client, so listing "iPhone · 3h ago"
 * etc. would be fiction. If the backend later exposes a sessions endpoint,
 * render real rows here; until then the honest answer is: you see this device.
 */
function describeCurrentSession(): Session {
	const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
	let device = "This device";
	let browser = "Browser";
	let Icon: typeof Monitor = MonitorSmartphone;
	if (/iPhone|iPad|iPod/.test(ua)) {
		device = /iPad/.test(ua) ? "iPad" : "iPhone";
		Icon = Smartphone;
	} else if (/Android/.test(ua)) {
		device = "Android device";
		Icon = Smartphone;
	} else if (/Mac OS X/.test(ua)) {
		device = "Mac";
		Icon = MonitorSmartphone;
	} else if (/Windows/.test(ua)) {
		device = "Windows PC";
		Icon = Monitor;
	} else if (/Linux/.test(ua)) {
		device = "Linux";
		Icon = Monitor;
	}
	if (/Edg\//.test(ua)) browser = "Edge";
	else if (/Chrome\//.test(ua) && !/Chromium/.test(ua)) browser = "Chrome";
	else if (/Firefox\//.test(ua)) browser = "Firefox";
	else if (/Safari\//.test(ua)) browser = "Safari";
	return {
		id: "current",
		device,
		browser,
		lastActive: "Active now",
		current: true,
		Icon,
	};
}

interface MFAFactor {
	id: string;
	friendly_name?: string | undefined;
	factor_type: string;
	status: "verified" | "unverified";
	created_at: string;
	updated_at: string;
}

export function SecurityTabContent() {
	const [factors, setFactors] = useState<MFAFactor[]>([]);
	const [mfaLoading, setMfaLoading] = useState(true);
	const [mfaError, setMfaError] = useState<string | null>(null);
	const [enrolling, setEnrolling] = useState<{
		factorId: string;
		qr: string;
		secret: string;
	} | null>(null);
	const [code, setCode] = useState("");
	const [verifying, setVerifying] = useState(false);
	const [copied, setCopied] = useState(false);
	// Newly-generated backup codes — shown once right after enrollment.
	// Persisting them anywhere else defeats the point (hashes only, server-side).
	const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
	const [backupUnused, setBackupUnused] = useState<number | null>(null);
	const [backupCopied, setBackupCopied] = useState(false);
	// Sticky flag: true once the user has copied OR downloaded at least once.
	// Gates the Dismiss action — without it, accidentally clicking dismiss
	// would silently lose the only chance to see plaintext.
	const [backupSaved, setBackupSaved] = useState(false);
	const [regenerating, setRegenerating] = useState(false);
	const [signingOutOthers, setSigningOutOthers] = useState(false);
	const [confirmDismissBackup, setConfirmDismissBackup] = useState(false);
	const [confirmRegenerate, setConfirmRegenerate] = useState(false);
	const [confirmSignOutOthers, setConfirmSignOutOthers] = useState(false);
	const [confirmUnenroll, setConfirmUnenroll] = useState(false);
	const secretCopyTimerRef = useRef<number | null>(null);
	const backupCopyTimerRef = useRef<number | null>(null);

	// We only reliably know about the *current* browser session. See
	// describeCurrentSession() for why we don't fabricate additional rows.
	const [sessions] = useState<Session[]>(() => [describeCurrentSession()]);

	const refreshFactors = useCallback(async () => {
		setMfaError(null);
		try {
			const { data, error } = await supabase.auth.mfa.listFactors();
			if (error) throw error;
			setFactors((data?.totp ?? []) as MFAFactor[]);
		} catch (e) {
			setMfaError(
				e instanceof Error ? e.message : "Failed to load authenticator factors",
			);
		} finally {
			setMfaLoading(false);
		}
	}, []);

	useEffect(() => {
		refreshFactors();
	}, [refreshFactors]);

	const verifiedFactor = factors.find((f) => f.status === "verified");
	const hasVerified = Boolean(verifiedFactor);

	// Once MFA is on, show how many backup codes remain. Stays in sync with
	// enrollment changes so disabling MFA hides the count.
	useEffect(() => {
		if (!hasVerified) {
			setBackupUnused(null);
			return;
		}
		let cancelled = false;
		(async () => {
			const result = await countBackupCodes();
			if (cancelled) return;
			if (result.ok) setBackupUnused(result.unused ?? 0);
		})();
		return () => {
			cancelled = true;
		};
	}, [hasVerified]);

	const startEnroll = async () => {
		setMfaError(null);
		const stale = factors.find((f) => f.status !== "verified");
		if (stale) {
			await supabase.auth.mfa.unenroll({ factorId: stale.id });
		}
		const { data, error } = await supabase.auth.mfa.enroll({
			factorType: "totp",
			friendlyName: `Authenticator · ${new Date().toLocaleDateString()}`,
		});
		if (error || !data) {
			setMfaError(error?.message ?? "Failed to start enrollment");
			return;
		}
		setEnrolling({
			factorId: data.id,
			qr: data.totp.qr_code,
			secret: data.totp.secret,
		});
		setCode("");
	};

	const cancelEnroll = async () => {
		if (enrolling) {
			await supabase.auth.mfa.unenroll({ factorId: enrolling.factorId });
		}
		setEnrolling(null);
		setCode("");
		setMfaError(null);
		refreshFactors();
	};

	const verifyEnroll = async () => {
		if (!enrolling || code.length !== 6) return;
		setVerifying(true);
		setMfaError(null);
		try {
			const { data: ch, error: e1 } = await supabase.auth.mfa.challenge({
				factorId: enrolling.factorId,
			});
			if (e1 || !ch) throw e1 ?? new Error("Challenge failed");
			// Race the verify with a short timeout — auth-lock contention with
			// the realtime socket occasionally hangs the verify promise even
			// though the server-side upgrade succeeded. If listFactors later
			// shows the factor as verified, the upgrade landed either way.
			const verifyPromise = supabase.auth.mfa
				.verify({ factorId: enrolling.factorId, challengeId: ch.id, code })
				.then(({ error }) => {
					if (error) throw error;
				});
			const raced = await Promise.race([
				verifyPromise.then(() => "ok" as const),
				new Promise<"timeout">((r) => setTimeout(() => r("timeout"), 2500)),
			]);
			if (raced === "timeout") {
				const { data } = await supabase.auth.mfa.listFactors();
				const verified = (data?.totp ?? []).find(
					(f) => f.id === enrolling.factorId && f.status === "verified",
				);
				if (!verified) await verifyPromise; // surface the real error
			}
			setEnrolling(null);
			setCode("");
			await refreshFactors();
			// Enrollment just hit AAL2 — generate the recovery set before the user
			// moves on. Failure here is non-fatal: MFA is still live, we surface
			// an error and the user can regenerate later.
			const codesResult = await generateBackupCodes();
			if (codesResult.ok && codesResult.codes && codesResult.codes.length > 0) {
				setBackupCodes(codesResult.codes);
				setBackupUnused(codesResult.codes.length);
			} else if (!codesResult.ok) {
				appToast.error("Could not generate backup codes", {
					description: codesResult.error ?? "You can retry from Settings.",
				});
			}
		} catch (e) {
			setMfaError(
				e instanceof Error
					? e.message
					: "Verification failed — double-check the code and try again.",
			);
		} finally {
			setVerifying(false);
		}
	};

	const copyBackupCodes = async () => {
		if (!backupCodes) return;
		try {
			await navigator.clipboard.writeText(backupCodes.join("\n"));
			setBackupCopied(true);
			setBackupSaved(true);
			if (backupCopyTimerRef.current) {
				window.clearTimeout(backupCopyTimerRef.current);
			}
			backupCopyTimerRef.current = window.setTimeout(() => {
				setBackupCopied(false);
				backupCopyTimerRef.current = null;
			}, 1600);
		} catch {
			/* ignore */
		}
	};

	const downloadBackupCodes = () => {
		if (!backupCodes) return;
		const body =
			`Juno33 — two-factor backup codes\n` +
			`Generated ${new Date().toISOString()}\n` +
			`Each code works exactly once. Store them somewhere safe.\n\n` +
			backupCodes.join("\n");
		const blob = new Blob([body], { type: "text/plain" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `juno33-backup-codes-${new Date().toISOString().slice(0, 10)}.txt`;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
		setBackupSaved(true);
	};

	const dismissBackupCodes = () => {
		if (!backupSaved) {
			setConfirmDismissBackup(true);
			return;
		}
		runDismissBackupCodes();
	};

	const runDismissBackupCodes = () => {
		setConfirmDismissBackup(false);
		setBackupCodes(null);
		setBackupCopied(false);
		setBackupSaved(false);
	};

	// Regenerating invalidates every existing code server-side. Confirm so a
	// misclick can't silently burn a recovery set the user hasn't retired.
	const regenerateBackupCodes = () => {
		if (regenerating) return;
		setConfirmRegenerate(true);
	};

	const runRegenerateBackupCodes = async () => {
		setConfirmRegenerate(false);
		setRegenerating(true);
		setMfaError(null);
		try {
			const result = await generateBackupCodes();
			if (result.ok && result.codes && result.codes.length > 0) {
				setBackupCodes(result.codes);
				setBackupUnused(result.codes.length);
				setBackupCopied(false);
				setBackupSaved(false);
			} else {
				appToast.error("Could not generate backup codes", {
					description: result.error ?? "Try again in a moment.",
				});
			}
		} finally {
			setRegenerating(false);
		}
	};

	// Revokes every refresh token for this user EXCEPT the current session —
	// useful if a phone was lost or a shared laptop was left signed in. Current
	// tab stays authenticated. "Sign out everywhere" in the Danger zone takes
	// out the current session too; that's the nuclear option.
	const signOutOtherSessions = () => {
		if (signingOutOthers) return;
		setConfirmSignOutOthers(true);
	};

	const runSignOutOtherSessions = async () => {
		setConfirmSignOutOthers(false);
		setSigningOutOthers(true);
		try {
			const { error } = await supabase.auth.signOut({ scope: "others" });
			if (error) {
				appToast.error("Could not sign out other sessions", {
					description: error.message,
				});
				return;
			}
			appToast.success("Other sessions signed out");
		} finally {
			setSigningOutOthers(false);
		}
	};

	const unenroll = () => {
		if (!verifiedFactor) return;
		setConfirmUnenroll(true);
	};

	const runUnenroll = async () => {
		if (!verifiedFactor) return;
		setConfirmUnenroll(false);
		const { error } = await supabase.auth.mfa.unenroll({
			factorId: verifiedFactor.id,
		});
		if (error) {
			setMfaError(error.message);
			return;
		}
		refreshFactors();
	};

	const copySecret = async () => {
		if (!enrolling) return;
		try {
			await navigator.clipboard.writeText(enrolling.secret);
			setCopied(true);
			if (secretCopyTimerRef.current) {
				window.clearTimeout(secretCopyTimerRef.current);
			}
			secretCopyTimerRef.current = window.setTimeout(() => {
				setCopied(false);
				secretCopyTimerRef.current = null;
			}, 1600);
		} catch {
			/* ignore */
		}
	};

	const addedLabel = verifiedFactor
		? new Date(verifiedFactor.created_at).toLocaleDateString()
		: null;

	useEffect(
		() => () => {
			if (secretCopyTimerRef.current) {
				window.clearTimeout(secretCopyTimerRef.current);
			}
			if (backupCopyTimerRef.current) {
				window.clearTimeout(backupCopyTimerRef.current);
			}
		},
		[],
	);

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="Security"
				description="Two-factor auth, active sessions, and third-party apps you've authorized to act on your behalf."
			/>

			{/* Two-factor auth */}
			<Panel>
				<div className="flex items-start justify-between gap-4">
					<div className="min-w-0">
						<div className="flex items-center gap-2">
							<span className="text-[0.84375rem] font-medium text-foreground">
								Two-factor authentication
							</span>
							{mfaLoading ? (
								<MicroBadge>Loading</MicroBadge>
							) : hasVerified ? (
								<MicroBadge
									tone="health-good"
									leading={<CheckCircle2 className="w-2.5 h-2.5" />}
								>
									On
								</MicroBadge>
							) : (
								<MicroBadge>Off</MicroBadge>
							)}
						</div>
						<p className="text-[0.75rem] text-muted-foreground mt-1 max-w-[52ch] leading-relaxed">
							Require a code from your authenticator app each time you sign in.
							Protects against credential leaks and stuffing attacks — strongly
							recommended for any account managing real brand handles.
						</p>
						{hasVerified && addedLabel && !enrolling && (
							<>
								<p className="mt-1.5 text-[0.71875rem] text-muted-foreground tabular-nums">
									{verifiedFactor?.friendly_name ?? "Authenticator"} · added{" "}
									{addedLabel}
									{typeof backupUnused === "number" && (
										<>
											{" · "}
											<span
												style={{
													color:
														backupUnused === 0
															? "var(--color-oxblood)"
															: undefined,
												}}
											>
												{backupUnused} backup{" "}
												{backupUnused === 1 ? "code" : "codes"} left
											</span>
										</>
									)}
								</p>
								{!backupCodes && (
									<Button
										type="button"
										onClick={() => void regenerateBackupCodes()}
										disabled={regenerating}
										variant="ghost"
										size="sm"
										className="mt-2 -ml-2 h-7 px-2 text-[0.71875rem]"
									>
										{regenerating ? (
											<Loader2
												data-icon="inline-start"
												className="animate-spin"
												aria-hidden="true"
											/>
										) : (
											<RefreshCw data-icon="inline-start" aria-hidden="true" />
										)}
										{regenerating ? "Generating…" : "Generate new backup codes"}
									</Button>
								)}
							</>
						)}
						{mfaError && (
							<div
								className="mt-2 text-[0.71875rem] leading-relaxed"
								style={{ color: "var(--color-oxblood)" }}
								role="alert"
							>
								{mfaError}
							</div>
						)}
					</div>
					<Button
						variant={hasVerified ? "outline" : "default"}
						className="h-9 text-[0.8125rem] shrink-0"
						disabled={mfaLoading || verifying}
						onClick={() => {
							if (hasVerified) void unenroll();
							else if (enrolling) void cancelEnroll();
							else void startEnroll();
						}}
					>
						{hasVerified ? "Disable" : enrolling ? "Cancel" : "Enable"}
					</Button>
				</div>

				{enrolling && (
					<div
						className="mt-5 pt-5 border-t border-border grid grid-cols-1 md:grid-cols-[auto_1fr] gap-5 md:gap-6 items-start"
					>
						<div className="flex flex-col items-center gap-2 shrink-0">
							<div className="w-[160px] h-[160px] p-2 rounded-md bg-white border border-border">
								<img
									src={enrolling.qr}
									alt="QR code — scan with your authenticator app"
									decoding="async"
									className="w-full h-full"
								/>
							</div>
							<Button
								type="button"
								onClick={copySecret}
								variant="ghost"
								size="sm"
								className="max-w-[160px] justify-start truncate px-1 text-[0.65625rem] tabular-nums text-muted-foreground"
								style={{
									fontFamily: "'JetBrains Mono', ui-monospace, monospace",
								}}
								title="Copy secret — paste into an authenticator app"
							>
								{copied ? (
									<CheckCircle2
										data-icon="inline-start"
										style={{ color: "var(--color-health-good)" }}
									/>
								) : (
									<Copy data-icon="inline-start" />
								)}
								<span className="truncate">{enrolling.secret}</span>
							</Button>
						</div>

						<div className="flex flex-col gap-3 min-w-0">
							<div>
								<div className="text-[0.78125rem] font-medium text-foreground">
									Scan with an authenticator app
								</div>
								<p className="mt-1 text-[0.71875rem] text-muted-foreground leading-[1.5] max-w-[52ch]">
									Open 1Password, Authy, Google Authenticator, or similar. Scan
									the QR or paste the secret. Then enter the 6-digit code the
									app generates.
								</p>
							</div>

							<label
								htmlFor="mfa-enroll-code"
								className="flex flex-col gap-1.5"
							>
								<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
									6-digit code
								</span>
								<Input
									id="mfa-enroll-code"
									type="text"
									inputMode="numeric"
									autoComplete="one-time-code"
									pattern="\d{6}"
									maxLength={6}
									value={code}
									onChange={(e) =>
										setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
									}
									onKeyDown={(e) => {
										if (e.key === "Enter" && code.length === 6 && !verifying) {
											e.preventDefault();
											void verifyEnroll();
										}
									}}
									className="w-[184px] text-base tabular-nums md:text-[0.9375rem]"
									style={{
										fontFamily: "'JetBrains Mono', ui-monospace, monospace",
										letterSpacing: "0.22em",
									}}
									placeholder="000000"
									aria-label="6-digit authenticator code"
								/>
							</label>

							<div className="flex items-center gap-2 mt-1">
								<Button
									variant="default"
									className="h-9 text-[0.8125rem]"
									disabled={code.length !== 6 || verifying}
									onClick={() => void verifyEnroll()}
								>
									{verifying ? "Verifying…" : "Verify & enable"}
								</Button>
								<Button
									type="button"
									onClick={() => void cancelEnroll()}
									disabled={verifying}
									variant="ghost"
									size="sm"
									className="h-9 text-[0.78125rem]"
								>
									Cancel
								</Button>
							</div>
						</div>
					</div>
				)}
			</Panel>

			{/* Backup codes — surfaces exactly once, right after first enrollment
          (or manual regen). Hashes are stored server-side; plaintext never
          touches the DB. Dismiss is guarded so an accidental click can't
          silently lose the only chance to see them. */}
			{backupCodes && backupCodes.length > 0 && (
				<div>
					<Panel>
						<div className="flex items-start justify-between gap-4">
							<div className="flex items-start gap-3 min-w-0">
								<span
									className="mt-0.5 w-8 h-8 rounded-full inline-flex items-center justify-center shrink-0"
									style={{
										background:
											"color-mix(in srgb, var(--color-oxblood) 12%, transparent)",
										color: "var(--color-oxblood)",
									}}
									aria-hidden="true"
								>
									<ShieldCheck className="w-4 h-4" />
								</span>
								<div className="min-w-0">
									<div className="text-[0.84375rem] font-medium text-foreground">
										Save your backup codes
									</div>
									<p className="text-[0.75rem] text-muted-foreground mt-1 max-w-[52ch] leading-relaxed">
										Each code works once if you lose your authenticator. This is
										the only time they'll be shown — copy or download before
										dismissing.
									</p>
								</div>
							</div>
							<Button
								type="button"
								onClick={dismissBackupCodes}
								variant="ghost"
								size="sm"
								className="h-9 text-[0.78125rem]"
							>
								Dismiss
							</Button>
						</div>
						<div className="mt-4 grid grid-cols-2 sm:grid-cols-5 gap-2">
							{backupCodes.map((c) => (
								<span
									key={c}
									className="inline-flex h-9 select-all items-center justify-center rounded-md border border-border bg-card text-[0.78125rem] text-foreground shadow-inner tabular-nums"
									style={{
										fontFamily: "'JetBrains Mono', ui-monospace, monospace",
										letterSpacing: "0.04em",
									}}
								>
									{c}
								</span>
							))}
						</div>
						<div className="mt-4 flex items-center gap-2">
							<Button
								type="button"
								variant="outline"
								className="h-9 text-[0.8125rem]"
								onClick={() => void copyBackupCodes()}
							>
								{backupCopied ? (
									<>
										<CheckCircle2
											className="w-3.5 h-3.5 mr-1.5"
											style={{ color: "var(--color-health-good)" }}
										/>
										Copied
									</>
								) : (
									<>
										<Copy className="w-3.5 h-3.5 mr-1.5" />
										Copy all
									</>
								)}
							</Button>
							<Button
								type="button"
								variant="outline"
								className="h-9 text-[0.8125rem]"
								onClick={downloadBackupCodes}
							>
								<Download className="w-3.5 h-3.5 mr-1.5" />
								Download .txt
							</Button>
							<span
								aria-live="polite"
								className="ml-auto inline-flex items-center gap-1 text-[0.6875rem] transition-opacity duration-200"
								style={{
									color: "var(--color-health-good)",
									opacity: backupSaved ? 1 : 0,
								}}
							>
								{backupSaved && (
									<>
										<CheckCircle2 className="w-3 h-3" aria-hidden="true" />
										Saved — safe to dismiss
									</>
								)}
							</span>
						</div>
					</Panel>
				</div>
			)}

			{/* Active sessions — Supabase JS can only introspect the current browser
          session. "Sign out other sessions" revokes every OTHER refresh token
          via signOut({ scope: 'others' }) and keeps this tab active. "Sign
          out everywhere" in Danger zone is the nuclear option that takes this
          tab out too. */}
			<div>
				<div className="flex items-start justify-between gap-3 mb-3">
					<div className="min-w-0">
						<div className="text-[0.84375rem] font-medium text-foreground">
							Active session
						</div>
						<div className="text-[0.71875rem] text-muted-foreground mt-0.5 max-w-[52ch]">
							Revoke every other device without signing out here, or use{" "}
							<span className="text-muted-foreground">Sign out everywhere</span>{" "}
							in Danger zone to fully reset.
						</div>
					</div>
					<Button
						variant="outline"
						className="h-9 text-[0.8125rem] shrink-0"
						disabled={signingOutOthers}
						onClick={() => void signOutOtherSessions()}
					>
						{signingOutOthers ? (
							<>
								<Loader2
									className="w-3.5 h-3.5 mr-1.5 animate-spin"
									aria-hidden="true"
								/>
								Signing out…
							</>
						) : (
							"Sign out other sessions"
						)}
					</Button>
				</div>
				<Panel className="!p-0">
					<ul>
						{sessions.map((s, i) => (
							<li
								key={s.id}
								className={cn(
									"flex items-center gap-4 px-5 py-4",
									i > 0 && "border-t border-border",
								)}
							>
								<span
									className={cn(
										"w-10 h-10 rounded-xl flex items-center justify-center shrink-0",
										"bg-muted text-muted-foreground border border-border",
									)}
								>
									<s.Icon className="w-4 h-4" />
								</span>
								<div className="flex-1 min-w-0">
									<div className="flex items-center gap-2 flex-wrap">
										<span className="text-[0.8125rem] font-medium text-foreground">
											{s.device}
										</span>
										<MicroBadge
											tone="ox"
											leading={
												<span
													className="w-1 h-1 rounded-full animate-pulse"
													style={{ backgroundColor: "var(--color-oxblood)" }}
												/>
											}
										>
											This device
										</MicroBadge>
									</div>
									<div className="text-[0.71875rem] text-muted-foreground mt-0.5">
										{s.browser} · {s.lastActive}
									</div>
								</div>
							</li>
						))}
					</ul>
				</Panel>
			</div>

			{/* Authorized apps — real integrations are managed via Settings →
          Connections. We don't hard-code fake OAuth scope/timestamps here. */}
			<div>
				<div className="flex items-center justify-between mb-3">
					<div>
						<div className="text-[0.84375rem] font-medium text-foreground">
							Authorized apps
						</div>
						<div className="text-[0.71875rem] text-muted-foreground mt-0.5">
							Third-party platforms with access to your data.
						</div>
					</div>
				</div>
				<Panel className="!p-0">
					<div className="p-10 text-center">
						<div className="w-10 h-10 rounded-full bg-muted border border-border mx-auto mb-3 flex items-center justify-center">
							<ShieldCheck className="w-4 h-4 text-muted-foreground" />
						</div>
						<div className="text-[0.84375rem] font-medium text-foreground">
							Managed under Connections
						</div>
						<div className="text-[0.75rem] text-muted-foreground mt-1 max-w-[44ch] mx-auto leading-relaxed">
							Meta, Stripe, and other OAuth integrations live in Settings →
							Connections. Revoke individual accounts there, or use Sign out
							everywhere to fully reset session trust.
						</div>
					</div>
				</Panel>
			</div>

			<ConfirmDialog
				open={confirmDismissBackup}
				onClose={() => setConfirmDismissBackup(false)}
				onConfirm={runDismissBackupCodes}
				title="Dismiss without saving?"
				description="Dismiss without saving? You won't see these codes again — copy or download them first."
				confirmLabel="Dismiss anyway"
				destructive
			/>
			<ConfirmDialog
				open={confirmRegenerate}
				onClose={() => setConfirmRegenerate(false)}
				onConfirm={runRegenerateBackupCodes}
				title="Generate new backup codes?"
				description="Generate a new set of backup codes? Your existing codes will stop working immediately."
				confirmLabel="Generate new codes"
				destructive
				busy={regenerating}
			/>
			<ConfirmDialog
				open={confirmSignOutOthers}
				onClose={() => setConfirmSignOutOthers(false)}
				onConfirm={runSignOutOtherSessions}
				title="Sign out every other device?"
				description="Sign out every other device? This revokes sessions on phones, other browsers, and anywhere else you're signed in. Your current tab stays active."
				confirmLabel="Sign out other devices"
				destructive
				busy={signingOutOthers}
			/>
			<ConfirmDialog
				open={confirmUnenroll}
				onClose={() => setConfirmUnenroll(false)}
				onConfirm={runUnenroll}
				title="Disable two-factor authentication?"
				description="Disable two-factor authentication? This removes your authenticator and weakens account protection."
				confirmLabel="Disable two-factor"
				destructive
			/>
		</div>
	);
}
