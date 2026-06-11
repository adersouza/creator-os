import type React from "react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Field, FieldGroup } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Mail, Key, ArrowRight, ShieldCheck } from "lucide-react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { appToast } from "@/lib/toast";
import { supabase, supabaseAuth } from "@/services/supabase";
import { verifyBackupCode } from "@/services/api/mfaBackup";
import { safeRedirectPath } from "@/utils/sanitize";

const AUTH_REDIRECT_STORAGE_KEY = "juno33-auth-redirect";

export function Login() {
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [oauthLoading, setOauthLoading] = useState<"github" | "google" | null>(
		null,
	);
	const [showReset, setShowReset] = useState(false);
	const [resetEmail, setResetEmail] = useState("");
	const [resetLoading, setResetLoading] = useState(false);
	// MFA challenge state. When a verified TOTP factor exists but the session
	// is still AAL1, we freeze the password form and prompt for a 6-digit code.
	const [mfaFactorId, setMfaFactorId] = useState<string | null>(null);
	const [mfaCode, setMfaCode] = useState("");
	const [mfaVerifying, setMfaVerifying] = useState(false);
	const [mfaError, setMfaError] = useState<string | null>(null);
	// When the user lost their authenticator, they can switch this view to
	// accept a 12-hex-char backup code instead. Server-side verify deletes
	// the TOTP factor so the AAL1 session clears the gate.
	const [mfaMode, setMfaMode] = useState<"totp" | "backup">("totp");
	const [backupCode, setBackupCode] = useState("");
	const navigate = useNavigate();
	const location = useLocation();
	const from = (
		location.state as {
			from?:
				| {
						pathname?: string | undefined;
						search?: string | undefined;
						hash?: string | undefined;
				  }
				| undefined;
		} | null
	)?.from;
	const redirectTo = safeRedirectPath(
		from
			? `${from.pathname ?? ""}${from.search ?? ""}${from.hash ?? ""}`
			: "/dashboard",
	);

	const persistRedirect = () => {
		try {
			localStorage.setItem(AUTH_REDIRECT_STORAGE_KEY, redirectTo);
		} catch {}
	};

	const clearRedirect = () => {
		try {
			localStorage.removeItem(AUTH_REDIRECT_STORAGE_KEY);
		} catch {}
	};

	// Visiting /login with an existing AAL1 session (previously signed in but
	// bailed before completing MFA) should skip the password form and show the
	// challenge directly. PublicOnlyRoute only bounces fully-signed-in (AAL2)
	// sessions to /dashboard, so we reliably land here with one to resume.
	useEffect(() => {
		let cancelled = false;
		(async () => {
			const mfa = await supabaseAuth.getMfaStatus();
			if (cancelled) return;
			if (mfa.needsMfa) setMfaFactorId(mfa.factorId);
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	const handleLogin = async (e: React.FormEvent) => {
		e.preventDefault();
		setIsLoading(true);
		try {
			const result = await supabaseAuth.signIn(email, password);
			if (result.status === "mfa-required") {
				setMfaFactorId(result.factorId);
				setMfaError(null);
				setMfaCode("");
				setIsLoading(false);
				return;
			}
			clearRedirect();
			navigate(redirectTo, { replace: true });
		} catch (err) {
			const message =
				err instanceof Error
					? err.message
					: "Unable to sign in. Check your credentials.";
			appToast.error("Sign-in failed", { description: message });
			setIsLoading(false);
		}
	};

	const handleMfaSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!mfaFactorId || mfaCode.length !== 6) return;
		setMfaVerifying(true);
		setMfaError(null);
		try {
			await supabaseAuth.verifyMfa(mfaFactorId, mfaCode);
			clearRedirect();
			navigate(redirectTo, { replace: true });
		} catch (err) {
			setMfaError(
				err instanceof Error
					? err.message
					: "Verification failed — double-check the code and try again.",
			);
		} finally {
			setMfaVerifying(false);
		}
	};

	const handleMfaCancel = async () => {
		// Back out of a half-completed login by dropping the AAL1 session.
		try {
			await supabase.auth.signOut({ scope: "local" });
		} catch {
			/* ignore */
		}
		setMfaFactorId(null);
		setMfaCode("");
		setMfaError(null);
		setMfaMode("totp");
		setBackupCode("");
	};

	const handleBackupSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		const normalized = backupCode.trim().toLowerCase().replace(/[\s-]/g, "");
		if (!/^[0-9a-f]{12}$/.test(normalized)) {
			setMfaError("Backup codes are 12 hex characters.");
			return;
		}
		setMfaVerifying(true);
		setMfaError(null);
		try {
			const result = await verifyBackupCode(normalized);
			if (!result.ok) {
				setMfaError(result.error || "Backup code did not match.");
				return;
			}
			appToast.success("Backup code accepted", {
				description: "Re-enroll your authenticator from Settings when you can.",
			});
			clearRedirect();
			navigate(redirectTo, { replace: true });
		} finally {
			setMfaVerifying(false);
		}
	};

	const handleOAuth = async (provider: "github" | "google") => {
		setOauthLoading(provider);
		try {
			persistRedirect();
			const { error } = await supabase.auth.signInWithOAuth({
				provider,
				options: { redirectTo: `${window.location.origin}/auth/callback` },
			});
			if (error) throw error;
			// Browser will redirect; no navigate needed.
		} catch (err) {
			const message =
				err instanceof Error ? err.message : "OAuth sign-in failed.";
			appToast.error(
				`${provider === "github" ? "GitHub" : "Google"} sign-in failed`,
				{ description: message },
			);
			setOauthLoading(null);
		}
	};

	const handleSendReset = async (e: React.FormEvent) => {
		e.preventDefault();
		setResetLoading(true);
		try {
			await supabaseAuth.resetPassword(resetEmail);
			appToast.success("Reset link sent", {
				description: `Check ${resetEmail} for instructions.`,
			});
			setShowReset(false);
			setResetEmail("");
		} catch (err) {
			const message =
				err instanceof Error ? err.message : "Unable to send reset email.";
			appToast.error("Reset failed", { description: message });
		} finally {
			setResetLoading(false);
		}
	};

	return (
		<div className="w-full max-w-md rounded-lg border border-border bg-card p-8 shadow-sm">
			{mfaFactorId ? (
				<div key="mfa">
					<div className="mb-6 text-center">
						<div
							className="mx-auto mb-3 w-10 h-10 rounded-full inline-flex items-center justify-center"
							style={{
								background:
									"color-mix(in srgb, var(--color-oxblood) 12%, transparent)",
								color: "var(--color-oxblood)",
							}}
						>
							<ShieldCheck className="w-5 h-5" aria-hidden="true" />
						</div>
						<h1>Verify it's you</h1>
						<p
							id={mfaMode === "totp" ? "mfa-totp-hint" : "mfa-backup-hint"}
						>
							{mfaMode === "totp"
								? "Enter the 6-digit code from your authenticator app."
								: "Enter one of your 12-character backup codes. Each works once."}
						</p>
					</div>
					{mfaMode === "totp" ? (
						<form key="totp" onSubmit={handleMfaSubmit}>
							<FieldGroup>
								<Field label="Authentication code">
									<Input
									id="mfa-totp-code"
									type="text"
									inputMode="numeric"
									autoComplete="one-time-code"
									pattern="[0-9]{6}"
									maxLength={6}
									required
									value={mfaCode}
									onChange={(e) =>
										setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))
									}
									aria-describedby="mfa-totp-hint"
									className="h-12 text-center text-lg tracking-[0.5em] tabular-nums"
									placeholder="000000"
								/>
								</Field>
							{mfaError && (
								<div
									className="text-xs text-[color:var(--color-oxblood)] bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)] rounded-md px-2.5 py-2 leading-snug"
									role="alert"
								>
									{mfaError}
								</div>
							)}
							</FieldGroup>
							<Button
								type="submit"
								disabled={mfaVerifying || mfaCode.length !== 6}
								className="mt-4 w-full"
							>
								{mfaVerifying ? "Verifying…" : "Verify"}
								{!mfaVerifying && <ArrowRight data-icon="inline-end" />}
							</Button>
							<div className="mt-2 flex flex-col gap-0.5 border-t border-border/60 pt-2">
								<Button
									type="button"
									variant="ghost"
									onClick={() => {
										setMfaMode("backup");
										setMfaError(null);
										setBackupCode("");
									}}
									className="w-full text-center text-xs py-2 text-muted-foreground hover:text-foreground transition-colors rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
								>
									Lost your authenticator? Use a backup code
								</Button>
								<Button
									type="button"
									variant="ghost"
									onClick={handleMfaCancel}
									className="w-full text-center text-xs py-2 text-muted-foreground hover:text-foreground transition-colors rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
								>
									← Use a different account
								</Button>
							</div>
						</form>
					) : (
						<form
							key="backup"
							onSubmit={handleBackupSubmit}
						>
							<FieldGroup>
								<Field label="Backup code">
									<Input
									id="mfa-backup-code"
									type="text"
									inputMode="text"
									autoComplete="off"
									required
									value={backupCode}
									onChange={(e) => setBackupCode(e.target.value)}
									aria-describedby="mfa-backup-hint mfa-backup-warning"
									className="h-12 text-center text-base tracking-[0.15em] tabular-nums"
									style={{
										fontFamily: "'JetBrains Mono', ui-monospace, monospace",
									}}
									placeholder="xxxx-xxxx-xxxx"
								/>
								</Field>
							<div
								id="mfa-backup-warning"
								className="text-[0.6875rem] leading-relaxed rounded-md px-2.5 py-2"
								style={{
									color: "var(--color-oxblood)",
									background:
										"color-mix(in_srgb,var(--color-oxblood)_6%,transparent)",
								}}
							>
								Using a backup code removes your current authenticator.
								Re-enroll from Settings after you sign in.
							</div>
							{mfaError && (
								<div
									className="text-xs text-[color:var(--color-oxblood)] bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)] rounded-md px-2.5 py-2 leading-snug"
									role="alert"
								>
									{mfaError}
								</div>
							)}
							</FieldGroup>
							<Button
								type="submit"
								disabled={mfaVerifying || backupCode.trim().length === 0}
								className="mt-4 w-full"
							>
								{mfaVerifying ? "Verifying…" : "Use backup code"}
								{!mfaVerifying && <ArrowRight data-icon="inline-end" />}
							</Button>
							<div className="mt-2 flex flex-col gap-0.5 border-t border-border/60 pt-2">
								<Button
									type="button"
									variant="ghost"
									onClick={() => {
										setMfaMode("totp");
										setMfaError(null);
										setBackupCode("");
									}}
									className="w-full text-center text-xs py-2 text-muted-foreground hover:text-foreground transition-colors rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
								>
									← Back to authenticator code
								</Button>
								<Button
									type="button"
									variant="ghost"
									onClick={handleMfaCancel}
									className="w-full text-center text-xs py-2 text-muted-foreground hover:text-foreground transition-colors rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
								>
									Use a different account
								</Button>
							</div>
						</form>
					)}
				</div>
			) : showReset ? (
				<div key="reset">
					<div className="mb-6 text-center">
						<h1>Reset your password</h1>
						<p>
							We'll email you a secure link.
						</p>
					</div>
					<form onSubmit={handleSendReset}>
						<FieldGroup>
							<Field label="Email address">
								<Input
									id="reset-email"
									type="email"
									autoComplete="email"
									required
									value={resetEmail}
									onChange={(e) => setResetEmail(e.target.value)}
									leadingIcon={<Mail data-icon="inline-start" />}
									placeholder="you@example.com"
								/>
							</Field>
						</FieldGroup>
						<Button
							type="submit"
							disabled={resetLoading}
							className="mt-4 w-full"
						>
							{resetLoading ? "Sending…" : "Send reset link"}
							{!resetLoading && <ArrowRight data-icon="inline-end" />}
						</Button>
						<Button
							type="button"
							variant="ghost"
							onClick={() => setShowReset(false)}
							className="mt-2 w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors"
						>
							← Back to sign in
						</Button>
					</form>
				</div>
			) : (
				<div key="signin">
					<div className="mb-6 text-center">
						<h1>Welcome back</h1>
						<p>
							Sign in to your Juno33 account
						</p>
					</div>

					<div className="mb-6 flex flex-col gap-3">
						<Button
							type="button"
							variant="outline"
							disabled={oauthLoading !== null}
							onClick={() => handleOAuth("github")}
							className="w-full"
						>
							<BrandLogo name="github" size="xs" monochrome />
							{oauthLoading === "github"
								? "Redirecting…"
								: "Continue with GitHub"}
						</Button>
						<Button
							type="button"
							variant="outline"
							disabled={oauthLoading !== null}
							onClick={() => handleOAuth("google")}
							className="w-full"
						>
							<BrandLogo name="google" size="xs" />
							{oauthLoading === "google"
								? "Redirecting…"
								: "Continue with Google"}
						</Button>
					</div>

					<div className="relative mb-6">
						<div className="absolute inset-0 flex items-center">
							<div className="w-full border-t border-border"></div>
						</div>
						<div className="relative flex justify-center text-[0.625rem] uppercase tracking-widest font-bold">
							<span className="bg-background px-2 text-muted-foreground">Or sign in with email</span>
						</div>
					</div>

					<form onSubmit={handleLogin}>
						<FieldGroup>
							<Field label="Email address">
								<Input
									id="login-email"
									type="email"
									autoComplete="email"
									required
									value={email}
									onChange={(e) => setEmail(e.target.value)}
									leadingIcon={<Mail data-icon="inline-start" />}
									placeholder="you@example.com"
								/>
							</Field>

							<Field
								label={
									<div className="flex w-full items-center justify-between gap-3">
										<span>Password</span>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											onClick={() => {
												setResetEmail(email);
												setShowReset(true);
											}}
											className="h-8 px-1 text-xs font-medium text-muted-foreground hover:text-foreground"
										>
											Forgot?
										</Button>
									</div>
								}
							>
								<Input
									id="login-password"
									type="password"
									autoComplete="current-password"
									required
									value={password}
									onChange={(e) => setPassword(e.target.value)}
									leadingIcon={<Key data-icon="inline-start" />}
									placeholder="••••••••"
								/>
							</Field>
						</FieldGroup>

						<Button
							type="submit"
							disabled={isLoading}
							className="mt-2 w-full"
						>
							{isLoading ? "Signing in..." : "Sign In"}
							{!isLoading && <ArrowRight data-icon="inline-end" />}
						</Button>
					</form>

					<div className="mt-8 text-center text-sm text-muted-foreground">
						Don't have an account?{" "}
						<Link
							to="/signup"
							className="inline-flex min-h-8 items-center rounded-md px-1 text-foreground font-medium hover:underline transition-all outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
						>
							Create an account
						</Link>
					</div>
				</div>
			)}
		</div>
	);
}
