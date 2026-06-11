import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Check, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Spinner } from "@/components/ui/Spinner";
import { supabase } from "@/services/supabase";

type Platform = "threads" | "instagram" | "facebook";

interface OAuthCallbackProps {
	platform: Platform;
}

const PLATFORM_CONFIG: Record<
	Platform,
	{
		label: string;
		stateKey: string;
		endpoint: string;
	}
> = {
	threads: {
		label: "Threads",
		stateKey: "threads_oauth_state",
		endpoint: "/api/auth/threads/callback",
	},
	instagram: {
		label: "Instagram",
		stateKey: "instagram_oauth_state",
		endpoint: "/api/auth/instagram/callback",
	},
	facebook: {
		label: "Facebook",
		stateKey: "facebook_oauth_state",
		endpoint: "/api/auth/instagram/fb-callback",
	},
};

type Status = "processing" | "success" | "error" | "account_limit";

interface LimitInfo {
	tier: string;
	currentCount: number;
	maxAllowed: number;
}

export function OAuthCallback({ platform }: OAuthCallbackProps) {
	const config = PLATFORM_CONFIG[platform];
	const [searchParams] = useSearchParams();
	const navigate = useNavigate();
	const [status, setStatus] = useState<Status>("processing");
	const [errorMessage, setErrorMessage] = useState("");
	const [limitInfo, setLimitInfo] = useState<LimitInfo | null>(null);

	useEffect(() => {
		let cancelled = false;
		let redirectTimer: number | null = null;

		const exchange = async () => {
			const code = searchParams.get("code");
			const state = searchParams.get("state");
			const oauthError = searchParams.get("error");
			const oauthErrorDescription = searchParams.get("error_description");

			if (oauthError) {
				setStatus("error");
				setErrorMessage(oauthErrorDescription || oauthError);
				return;
			}
			if (!code || !state) {
				setStatus("error");
				setErrorMessage("Missing OAuth code or state.");
				return;
			}

			const storedState = localStorage.getItem(config.stateKey);
			if (!storedState || state !== storedState) {
				setStatus("error");
				setErrorMessage(
					"Invalid state parameter. Please try connecting again.",
				);
				localStorage.removeItem(config.stateKey);
				return;
			}
			localStorage.removeItem(config.stateKey);

			try {
				let session = (await supabase.auth.getSession()).data.session;
				if (!session?.user) {
					throw new Error("Sign in first, then reconnect your account.");
				}
				if (
					session.expires_at &&
					session.expires_at < Math.floor(Date.now() / 1000) + 30
				) {
					const { data } = await supabase.auth.refreshSession();
					session = data.session;
					if (!session) throw new Error("Session expired. Sign in again.");
				}

				const response = await fetch(config.endpoint, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${session.access_token}`,
					},
					body: JSON.stringify({ code, state }),
				});

				if (!response.ok) {
					let errorData: {
						code?: string | undefined;
						error?: string | undefined;
						tier?: string | undefined;
						currentCount?: number | undefined;
						maxAllowed?: number | undefined;
					} = {};
					try {
						errorData = await response.json();
					} catch {
						/* ignore parse */
					}

					if (
						errorData.code === "ACCOUNT_LIMIT_REACHED" &&
						response.status === 403
					) {
						if (cancelled) return;
						setStatus("account_limit");
						setErrorMessage(errorData.error ?? "Account limit reached.");
						setLimitInfo({
							tier: errorData.tier || "free",
							currentCount: errorData.currentCount || 0,
							maxAllowed: errorData.maxAllowed || 1,
						});
						return;
					}
					throw new Error(
						errorData.error || `Token exchange failed (${response.status})`,
					);
				}

				if (cancelled) return;
				setStatus("success");

				const oauthSource = localStorage.getItem("juno33-oauth-source");
				localStorage.removeItem("juno33-oauth-source");
				const reconnectRaw = sessionStorage.getItem("juno33:oauth-reconnect");
				sessionStorage.removeItem("juno33:oauth-reconnect");
				let reconnectReturnTo: string | null = null;
				if (reconnectRaw) {
					try {
						const parsed = JSON.parse(reconnectRaw) as { returnTo?: unknown };
						if (
							typeof parsed.returnTo === "string" &&
							parsed.returnTo.startsWith("/accounts")
						) {
							reconnectReturnTo = parsed.returnTo;
						}
					} catch {
						reconnectReturnTo = null;
					}
				}

				const destination =
					oauthSource === "onboarding"
						? `/welcome?connected=true&platform=${platform}`
						: oauthSource === "accounts" && reconnectReturnTo
							? reconnectReturnTo
						: "/dashboard?auth=success";

				redirectTimer = window.setTimeout(() => {
					if (!cancelled) navigate(destination, { replace: true });
					redirectTimer = null;
				}, 900);
			} catch (err) {
				if (cancelled) return;
				setStatus("error");
				setErrorMessage(
					err instanceof Error ? err.message : "Connection failed.",
				);
			}
		};

		exchange();
		return () => {
			cancelled = true;
			if (redirectTimer) {
				window.clearTimeout(redirectTimer);
			}
		};
	}, [searchParams, navigate, platform, config.endpoint, config.stateKey]);

	return (
		<NovaCard className="w-full max-w-md" contentClassName="p-8 text-center">
			{status === "processing" && (
				<>
					<Spinner className="mx-auto mb-5 size-10 text-[var(--color-oxblood)]" />
					<h2 className="text-[1.25rem] font-medium tracking-[-0.02em] text-foreground mb-1.5">
						Connecting {config.label}
					</h2>
					<p className="text-[0.8125rem] text-muted-foreground">
						Hold on — exchanging credentials and hooking up your account.
					</p>
				</>
			)}

			{status === "success" && (
				<>
					<div
						className="size-10 rounded-full flex items-center justify-center mx-auto mb-5"
						style={{ backgroundColor: "var(--color-oxblood)" }}
					>
						<Check data-icon="inline" className="text-white" strokeWidth={3} />
					</div>
					<h2 className="text-[1.25rem] font-medium tracking-[-0.02em] text-foreground mb-1.5">
						{config.label} connected
					</h2>
					<p className="text-[0.8125rem] text-muted-foreground">Redirecting…</p>
				</>
			)}

			{status === "account_limit" && (
				<>
					<div
						className="size-10 rounded-full flex items-center justify-center mx-auto mb-5"
						style={{
							backgroundColor:
								"color-mix(in srgb, var(--color-gold) 15%, transparent)",
						}}
					>
						<AlertCircle
							data-icon="inline"
							style={{ color: "var(--color-gold)" }}
						/>
					</div>
					<h2 className="text-[1.25rem] font-medium tracking-[-0.02em] text-foreground mb-1.5">
						Account limit reached
					</h2>
					<p className="text-[0.8125rem] text-muted-foreground mb-5">
						Your{" "}
						<span className="font-medium text-foreground capitalize">
							{limitInfo?.tier}
						</span>{" "}
						plan allows {limitInfo?.maxAllowed} account
						{limitInfo?.maxAllowed === 1 ? "" : "s"}. You currently have{" "}
						{limitInfo?.currentCount} connected.
					</p>
					<div className="flex flex-col gap-2">
						<Button
							type="button"
							onClick={() => navigate("/billing")}
							className=" w-full"
						>
							Upgrade plan
						</Button>
						<Button
							type="button"
							variant="secondary"
							onClick={() => navigate("/dashboard")}
							className=" w-full"
						>
							Back to dashboard
						</Button>
					</div>
				</>
			)}

			{status === "error" && (
				<>
					<div className="size-10 rounded-full flex items-center justify-center mx-auto mb-5 bg-destructive/15">
						<AlertCircle data-icon="inline" className="text-destructive" />
					</div>
					<h2 className="text-[1.25rem] font-medium tracking-[-0.02em] text-foreground mb-1.5">
						Connection failed
					</h2>
					<p className="text-[0.8125rem] text-muted-foreground mb-5">
						{errorMessage}
					</p>
					<div className="flex flex-col gap-2">
						<Button
							type="button"
							onClick={() => navigate("/welcome")}
							className=" w-full"
						>
							Try again
						</Button>
						<Button
							type="button"
							variant="secondary"
							onClick={() => navigate("/dashboard")}
							className=" w-full"
						>
							Back to dashboard
						</Button>
					</div>
				</>
			)}
		</NovaCard>
	);
}
