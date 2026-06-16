import type React from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AuthCard } from "@/components/ui/AuthCard";
import { Button } from "@/components/ui/Button";
import { Field, FieldGroup } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Key, ArrowRight } from "lucide-react";
import { appToast } from "@/lib/toast";
import { supabase, supabaseAuth } from "@/services/supabase";

/**
 * Landing page for the recovery link Supabase emails.
 *
 * The link carries a `code` (PKCE) that we exchange for a recovery session,
 * at which point `supabase.auth.updateUser({ password })` is allowed.
 * On success we sign the user out and bounce to /login so they re-auth
 * with the new credentials.
 */
export function ResetPassword() {
	const navigate = useNavigate();
	const [password, setPassword] = useState("");
	const [confirm, setConfirm] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [ready, setReady] = useState(false);

	useEffect(() => {
		let cancelled = false;
		(async () => {
			const url = new URL(window.location.href);
			const code = url.searchParams.get("code");
			const hashParams = new URLSearchParams(url.hash.replace(/^#/, ""));
			const accessToken = hashParams.get("access_token");
			const refreshToken = hashParams.get("refresh_token");
			const errorDescription =
				url.searchParams.get("error_description") ||
				hashParams.get("error_description");

			if (errorDescription) {
				appToast.error("Reset link invalid", { description: errorDescription });
				navigate("/login", { replace: true });
				return;
			}

			if (!code && !(accessToken && refreshToken)) {
				appToast.error("Reset link required", {
					description:
						"Request a new password reset link from the sign-in page.",
				});
				navigate("/login", { replace: true });
				return;
			}

			try {
				if (code) {
					const { error } = await supabase.auth.exchangeCodeForSession(code);
					if (error) throw error;
				} else if (accessToken && refreshToken) {
					const { error } = await supabase.auth.setSession({
						access_token: accessToken,
						refresh_token: refreshToken,
					});
					if (error) throw error;
				}
				const {
					data: { session },
				} = await supabase.auth.getSession();
				if (cancelled) return;
				if (!session) {
					appToast.error("Reset link expired", {
						description: "Request a new one from the sign-in page.",
					});
					navigate("/login", { replace: true });
					return;
				}
				setReady(true);
			} catch (err) {
				const description =
					err instanceof Error ? err.message : "Unable to verify reset link.";
				appToast.error("Reset link invalid", { description });
				navigate("/login", { replace: true });
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [navigate]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (password !== confirm) {
			appToast.error("Passwords don't match");
			return;
		}
		setIsLoading(true);
		try {
			await supabaseAuth.updatePassword(password);
			await supabase.auth.signOut();
			appToast.success("Password updated", {
				description: "Sign in with your new password.",
			});
			navigate("/login", { replace: true });
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Unable to update password.";
			appToast.error("Update failed", { description });
			setIsLoading(false);
		}
	};

	return (
		<AuthCard
			icon={<Key data-icon aria-hidden="true" />}
			title="Set a new password"
			description={
				ready
					? "Pick something you haven't used before."
					: "Verifying your reset link…"
			}
		>
			{ready && (
				<form onSubmit={handleSubmit}>
					<FieldGroup>
						<Field label="New password">
							<Input
								id="reset-new-password"
								type="password"
								autoComplete="new-password"
								required
								minLength={6}
								value={password}
								onChange={(e) => setPassword(e.target.value)}
								leadingIcon={<Key data-icon="inline-start" />}
								placeholder="••••••••"
							/>
						</Field>

						<Field label="Confirm password">
							<Input
								id="reset-confirm-password"
								type="password"
								autoComplete="new-password"
								required
								minLength={6}
								value={confirm}
								onChange={(e) => setConfirm(e.target.value)}
								leadingIcon={<Key data-icon="inline-start" />}
								placeholder="••••••••"
							/>
						</Field>
					</FieldGroup>

					<Button
						type="submit"
						disabled={isLoading}
						className="mt-4 w-full"
					>
						{isLoading ? "Updating…" : "Update password"}
						{!isLoading && <ArrowRight data-icon="inline-end" />}
					</Button>
				</form>
			)}
		</AuthCard>
	);
}
