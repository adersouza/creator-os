import type React from "react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Field, FieldGroup } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Mail, Key, ArrowRight, User } from "lucide-react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { appToast } from "@/lib/toast";
import {
	clearPendingInvite,
	readPendingInvite,
	writePendingInvite,
} from "@/lib/pendingInvite";
import { supabase } from "@/services/supabase";
import { joinWorkspaceWithCode } from "@/services/teamService";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";

// Tiers offered on /juno33_pricing.html — keep labels in sync with that page
const PLAN_LABELS: Record<string, string> = {
	free: "Free",
	creator: "Creator · $19/mo",
	pro: "Pro · $59/mo",
	agency: "Agency · $149/mo (14-day trial)",
	"white-label": "White-Label · $349/mo",
	empire: "Empire · $699/mo",
};

export function Signup() {
	const [fullName, setFullName] = useState("");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [oauthLoading, setOauthLoading] = useState<"github" | "google" | null>(
		null,
	);
	const navigate = useNavigate();
	const [searchParams] = useSearchParams();
	const refreshWorkspaces = useWorkspaceStore((s) => s.refreshWorkspaces);
	const selectWorkspace = useWorkspaceStore((s) => s.selectWorkspace);
	const planParam = searchParams.get("plan");
	const inviteParam = searchParams.get("invite");
	const selectedPlan = planParam && PLAN_LABELS[planParam] ? planParam : null;

	const stashPendingPlan = () => {
		if (selectedPlan) {
			try {
				localStorage.setItem("juno33-pending-plan", selectedPlan);
			} catch {}
		}
	};

	const stashPendingInvite = () => {
		if (inviteParam) writePendingInvite(inviteParam);
	};

	const completePendingInvite = async (): Promise<boolean> => {
		const inviteCode = readPendingInvite();
		if (!inviteCode) return false;

		try {
			const workspaceId = await joinWorkspaceWithCode(inviteCode);
			clearPendingInvite();
			await refreshWorkspaces();
			await selectWorkspace(workspaceId);
			appToast.success("Joined the workspace");
			navigate("/dashboard", { replace: true });
			return true;
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Could not accept invite.";
			appToast.error("Invite acceptance failed", { description });
			return false;
		}
	};

	const handleSignup = async (e: React.FormEvent) => {
		e.preventDefault();
		setIsLoading(true);
		stashPendingPlan();
		stashPendingInvite();
		try {
			const { data, error } = await supabase.auth.signUp({
				email,
				password,
				options: {
					data: { full_name: fullName },
					emailRedirectTo: `${window.location.origin}/auth/callback`,
				},
			});
			if (error) throw error;
			if (data.session) {
				// Email confirmation disabled — logged in immediately
				if (await completePendingInvite()) return;
				navigate("/welcome");
			} else {
				// Email confirmation required
				appToast.success("Confirm your email", {
					description: `We sent a verification link to ${email}.`,
				});
				navigate("/login");
			}
		} catch (err) {
			const message =
				err instanceof Error ? err.message : "Unable to create account.";
			appToast.error("Sign-up failed", { description: message });
			setIsLoading(false);
		}
	};

	const handleOAuth = async (provider: "github" | "google") => {
		setOauthLoading(provider);
		stashPendingPlan();
		stashPendingInvite();
		try {
			const { error } = await supabase.auth.signInWithOAuth({
				provider,
				options: { redirectTo: `${window.location.origin}/auth/callback` },
			});
			if (error) throw error;
		} catch (err) {
			const providerLabel = provider === "github" ? "GitHub" : "Google";
			const message =
				err instanceof Error ? err.message : `${providerLabel} sign-up failed.`;
			appToast.error(`${providerLabel} sign-up failed`, {
				description: message,
			});
			setOauthLoading(null);
		}
	};

	return (
		<NovaCard className="w-full max-w-md" contentClassName="p-8">
			<div className="mb-6 text-center">
				<h1>Create your Juno33 account</h1>
				<p>
					Start your 14-day free trial. No credit card required.
				</p>
			</div>

			{selectedPlan && (
				<div
					className="mb-5 flex items-center justify-between gap-3 rounded-md px-3 py-2.5 text-[0.78125rem]"
					style={{
						backgroundColor:
							"color-mix(in srgb, var(--color-oxblood) 8%, transparent)",
						border:
							"0.5px solid color-mix(in srgb, var(--color-oxblood) 22%, transparent)",
						color: "var(--color-oxblood)",
					}}
				>
					<span className="flex items-center gap-2">
						<span className="w-1.5 h-1.5 rounded-full bg-current" />
						<span className="font-medium">{PLAN_LABELS[selectedPlan]}</span>
					</span>
					<Link
						to="/juno33_pricing.html"
						reloadDocument
						className="text-[0.6875rem] font-medium opacity-80 hover:opacity-100"
					>
						Change
					</Link>
				</div>
			)}

			<div className="mb-6 flex flex-col gap-3">
				<Button
					type="button"
					variant="outline"
					disabled={oauthLoading !== null}
					onClick={() => handleOAuth("google")}
					className="w-full"
				>
					<BrandLogo name="google" size="xs" />
					{oauthLoading === "google" ? "Redirecting…" : "Continue with Google"}
				</Button>
				<Button
					type="button"
					variant="outline"
					disabled={oauthLoading !== null}
					onClick={() => handleOAuth("github")}
					className="w-full"
				>
					<BrandLogo name="github" size="xs" monochrome />
					{oauthLoading === "github" ? "Redirecting…" : "Continue with GitHub"}
				</Button>
			</div>

			<div className="relative mb-6">
				<div className="absolute inset-0 flex items-center">
					<div className="w-full border-t border-border"></div>
				</div>
				<div className="relative flex justify-center text-[0.625rem] uppercase tracking-widest font-bold">
					<span className="bg-background px-2 text-muted-foreground">Or sign up with email</span>
				</div>
			</div>

			<form onSubmit={handleSignup}>
				<FieldGroup>
					<Field label="Full name">
						<Input
							id="signup-name"
							type="text"
							autoComplete="name"
							required
							value={fullName}
							onChange={(e) => setFullName(e.target.value)}
							leadingIcon={<User data-icon="inline-start" />}
							placeholder="Jane Doe"
						/>
					</Field>

					<Field label="Email address">
						<Input
							id="signup-email"
							type="email"
							autoComplete="email"
							required
							value={email}
							onChange={(e) => setEmail(e.target.value)}
							leadingIcon={<Mail data-icon="inline-start" />}
							placeholder="you@example.com"
						/>
					</Field>

					<Field label="Create password" hint="At least 6 characters.">
						<Input
							id="signup-password"
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
				</FieldGroup>

				<Button
					type="submit"
					disabled={isLoading}
					className="mt-2 w-full"
				>
					{isLoading ? "Creating account..." : "Start free trial"}
					{!isLoading && <ArrowRight data-icon="inline-end" />}
				</Button>
			</form>

			<div className="mt-8 text-center text-sm text-muted-foreground">
				Already have an account?{" "}
				<Link
					to="/login"
					className="inline-flex min-h-8 items-center rounded-md px-1 text-foreground font-medium hover:underline transition-all outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
				>
					Sign in
				</Link>
			</div>

			<p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
				By signing up, you agree to our{" "}
				<Link to="/terms">Terms of Service</Link> and{" "}
				<Link to="/privacy">Privacy Policy</Link>.
			</p>
		</NovaCard>
	);
}
