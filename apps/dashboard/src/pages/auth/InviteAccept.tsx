import type React from "react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Navigate } from "react-router-dom";
import { Check, AlertTriangle, Clock, Users } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	getInviteDetails,
	joinWorkspaceWithCode,
} from "@/services/teamService";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import { supabase } from "@/services/supabase";
import { appToast } from "@/lib/toast";
import { clearPendingInvite, writePendingInvite } from "@/lib/pendingInvite";

/**
 * Invite acceptance surface. Two modes:
 *   - Signed out → preview invite details, route to /signup?invite=<code>
 *     so the code survives the OAuth round-trip via localStorage.
 *   - Signed in  → one-click join, then bounce to /dashboard.
 *
 * Matches the Auth page register (editorial motion, oxblood whisper, solid
 * white card with inset highlight per CLAUDE.md light-mode recipe).
 */
type State =
	| { kind: "loading" }
	| { kind: "missing" }
	| { kind: "invalid" }
	| { kind: "expired" }
	| { kind: "ready"; details: InviteDetails; authed: boolean }
	| { kind: "joining"; details: InviteDetails }
	| { kind: "done"; details: InviteDetails };

interface InviteDetails {
	email?: string | undefined;
	role: string;
	workspaceName: string;
	workspaceId: string;
}

export function InviteAccept() {
	const { code } = useParams<{ code: string }>();
	const navigate = useNavigate();
	const selectWorkspace = useWorkspaceStore((s) => s.selectWorkspace);
	const refreshWorkspaces = useWorkspaceStore((s) => s.refreshWorkspaces);
	const [state, setState] = useState<State>({ kind: "loading" });
	const redirectTimerRef = useRef<number | null>(null);

	useEffect(() => {
		if (!code) {
			setState({ kind: "missing" });
			return;
		}
		let cancelled = false;
		(async () => {
			const [
				{
					data: { session },
				},
				details,
			] = await Promise.all([
				supabase.auth.getSession(),
				getInviteDetails(code),
			]);
			if (cancelled) return;
			if (!details) {
				setState({ kind: "invalid" });
				return;
			}
			setState({ kind: "ready", details, authed: !!session });
		})();
		return () => {
			cancelled = true;
		};
	}, [code]);

	const handleAccept = async () => {
		if (state.kind !== "ready" || !code) return;
		// Unauthed: stash the code, send to signup. Welcome.tsx / OAuthCallback
		// can pick this up after sign-up to auto-accept without the user needing
		// to paste the URL twice.
		if (!state.authed) {
			writePendingInvite(code);
			navigate(`/signup?invite=${encodeURIComponent(code)}`);
			return;
		}

		setState({ kind: "joining", details: state.details });
		try {
			const workspaceId = await joinWorkspaceWithCode(code);
			clearPendingInvite();
			await refreshWorkspaces();
			await selectWorkspace(workspaceId);
			appToast.success("Joined the workspace", {
				description: `You're now a member of ${state.details.workspaceName}.`,
			});
			setState({ kind: "done", details: state.details });
			redirectTimerRef.current = window.setTimeout(() => {
				navigate("/dashboard", { replace: true });
				redirectTimerRef.current = null;
			}, 800);
		} catch (err) {
			const message =
				err instanceof Error ? err.message : "Could not accept invite";
			appToast.error(message);
			// If server said "expired", surface the explicit expired state.
			if (/expired/i.test(message)) {
				setState({ kind: "expired" });
				return;
			}
			setState({ kind: "invalid" });
		}
	};

	useEffect(
		() => () => {
			if (redirectTimerRef.current) {
				window.clearTimeout(redirectTimerRef.current);
			}
		},
		[],
	);

	if (state.kind === "loading") {
		return (
			<Shell>
				<LoadingCard />
			</Shell>
		);
	}
	if (state.kind === "missing") {
		return <Navigate to="/login" replace />;
	}
	if (state.kind === "invalid") {
		return (
			<Shell>
				<ErrorCard
					icon={<AlertTriangle className="w-5 h-5" />}
					title="Invite not found"
					body="This link is no longer valid. It may have been revoked or the invite code was mistyped. Ask the workspace owner for a fresh link."
				/>
			</Shell>
		);
	}
	if (state.kind === "expired") {
		return (
			<Shell>
				<ErrorCard
					icon={<Clock className="w-5 h-5" />}
					title="Invite expired"
					body="Invites last 14 days. Ask the workspace owner to send a new one and we'll add you right up."
				/>
			</Shell>
		);
	}
	if (state.kind === "done") {
		return (
			<Shell>
				<NovaCard className="w-full max-w-md" contentClassName="p-8">
					<NovaEmpty
						icon={<Check data-icon aria-hidden="true" />}
						title="You're in"
						description="Taking you to the dashboard."
					/>
				</NovaCard>
			</Shell>
		);
	}

	const details = state.details;
	const authed = state.kind === "ready" ? state.authed : true;
	const joining = state.kind === "joining";

	return (
		<Shell>
			<NovaCard className="w-full max-w-md" contentClassName="p-8">
					<div
						className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl"
						style={{
							color: "var(--color-oxblood)",
							backgroundColor:
								"color-mix(in srgb, var(--color-oxblood) 10%, transparent)",
						}}
					>
						<Users className="h-5 w-5" />
					</div>
					<div className="mb-1 text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
						Workspace invite
					</div>
					<h1 className="mb-2 text-[1.5rem] font-medium leading-[1.15] tracking-[-0.025em] text-foreground">
						Join {details?.workspaceName}
					</h1>
					<p className="mb-5 text-[0.8125rem] leading-relaxed text-muted-foreground">
						{details?.email ? (
							<>
								You've been invited as{" "}
								<b className="text-foreground">{details.email}</b>.
							</>
						) : (
							<>You've been invited to join this workspace.</>
						)}{" "}
						You'll have{" "}
						<b className="text-foreground">
							{labelForRole(details?.role ?? "editor")}
						</b>{" "}
						access.
					</p>
					<div className="flex items-center gap-2">
						<Button
							onClick={() => void handleAccept()}
							disabled={joining}
							className="flex-1"
						>
							{joining
								? "Joining..."
								: authed
									? "Accept invite"
									: "Sign up & accept"}
						</Button>
						<Button
							type="button"
							variant="ghost"
							onClick={() => navigate(authed ? "/dashboard" : "/login")}
							className="px-3 text-muted-foreground"
						>
							Not now
						</Button>
					</div>
			</NovaCard>
		</Shell>
	);
}

function labelForRole(role: string): string {
	return role.charAt(0).toUpperCase() + role.slice(1);
}

function Shell({ children }: { children: React.ReactNode }) {
	return (
		<div className=" min-h-[100dvh] flex items-center justify-center px-4 py-10 bg-background">
			{children}
		</div>
	);
}

function LoadingCard() {
	return (
		<NovaCard className="w-full max-w-md" contentClassName="p-8">
			<Skeleton className="mb-4 h-11 w-11 rounded-xl" />
			<Skeleton className="mb-3 h-3 w-24 rounded" />
			<Skeleton className="mb-3 h-6 w-48 rounded" />
			<Skeleton className="mb-2 h-3 w-full rounded" />
			<Skeleton className="mb-6 h-3 w-3/4 rounded" />
			<Skeleton className="h-9 w-full rounded-md" />
		</NovaCard>
	);
}

function ErrorCard({
	icon,
	title,
	body,
}: {
	icon: React.ReactNode;
	title: string;
	body: string;
}) {
	const navigate = useNavigate();
	return (
		<NovaCard className="w-full max-w-md" contentClassName="p-8">
				<div
					className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl"
					style={{
						color: "var(--color-oxblood)",
						backgroundColor:
							"color-mix(in srgb, var(--color-oxblood) 10%, transparent)",
					}}
				>
					{icon}
				</div>
				<h1 className="mb-1.5 text-[1.25rem] font-medium tracking-[-0.025em] text-foreground">
					{title}
				</h1>
				<p className="mb-5 text-[0.8125rem] leading-relaxed text-muted-foreground">
					{body}
				</p>
				<Button
					onClick={() => navigate("/login")}
					variant="secondary"
					className="w-full"
				>
					Back to sign in
				</Button>
		</NovaCard>
	);
}
