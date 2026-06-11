import { useEffect, useMemo, useState } from "react";
import {
	ArrowRight,
	Camera,
	CheckCircle2,
	Circle,
	ImagePlus,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PhoneSetupChecklist } from "@/components/publishing/PhoneSetupChecklist";
import { PublishingReadinessPanel } from "@/components/publishing/PublishingReadinessPanel";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import {
	NovaCard,
	NovaHeader,
	NovaSection,
} from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { buildPublishingReadinessIssues } from "@/lib/publishingReadiness";
import { detectPwaInstallState } from "@/lib/pwaSetup";
import { apiUrl } from "@/lib/apiUrl";
import { appToast } from "@/lib/toast";
import { trackClientEvent } from "@/services/clientTelemetry";
import {
	getPermissionState,
	isCurrentlySubscribed,
	isPushSupported,
	subscribeToPush,
} from "@/services/pushSubscriptionService";
import { supabase } from "@/services/supabase";
import type {
	FirstPostWizardStep,
	PwaInstallState,
} from "@/types/publishingReadiness";

const STEPS: Array<{ id: FirstPostWizardStep; label: string; detail: string }> =
	[
		{
			id: "connect",
			label: "Connect Instagram",
			detail: "Pick the account Juno33 will schedule for.",
		},
		{
			id: "mode",
			label: "Choose mode",
			detail:
				"Auto-publish for API-safe posts, Notify Me for native Reels/Stories.",
		},
		{
			id: "media",
			label: "Add media",
			detail: "Start with a 9:16 Reel or an image post.",
		},
		{
			id: "readiness",
			label: "Fix readiness",
			detail: "Resolve blocked items before scheduling.",
		},
		{
			id: "phone",
			label: "Phone setup",
			detail: "Enable push and confirm Instagram is logged in.",
		},
		{
			id: "schedule",
			label: "Schedule",
			detail: "Pick a real time and review the preview.",
		},
		{
			id: "handoff",
			label: "Handoff",
			detail: "Copy, share/download, open Instagram, and mark posted.",
		},
	];

function setupProgress({
	hasInstagram,
	pushState,
	phoneConfirmed,
}: {
	hasInstagram: boolean;
	pushState: string;
	phoneConfirmed: boolean;
}) {
	return new Set<FirstPostWizardStep>([
		...(hasInstagram ? (["connect"] as const) : []),
		"mode",
		"media",
		"readiness",
		...(pushState === "subscribed" || phoneConfirmed
			? (["phone"] as const)
			: []),
	]);
}

async function authHeaders(): Promise<Record<string, string>> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) throw new Error("Not authenticated");
	return {
		Authorization: `Bearer ${session.access_token}`,
		"Content-Type": "application/json",
	};
}

export function PublishingSetup() {
	const navigate = useNavigate();
	const { accounts } = useConnectedAccounts();
	const instagramAccounts = accounts.filter(
		(account) => account.platform === "instagram",
	);
	const [pushState, setPushState] = useState("checking");
	const [phoneConfirmed, setPhoneConfirmed] = useState(false);
	const [busy, setBusy] = useState(false);
	const [pwaState, setPwaState] = useState<PwaInstallState>("desktop");

	useEffect(() => {
		trackClientEvent("first_post_wizard_opened", {
			surface: "setup_publishing",
		});
		setPwaState(detectPwaInstallState());
		let cancelled = false;
		(async () => {
			if (!isPushSupported()) {
				if (!cancelled) setPushState("unsupported");
				return;
			}
			const permission = getPermissionState();
			if (permission === "denied") {
				if (!cancelled) setPushState("denied");
				return;
			}
			const subscribed = await isCurrentlySubscribed();
			if (!cancelled)
				setPushState(
					subscribed
						? "subscribed"
						: permission === "granted"
							? "not-subscribed"
							: "permission-needed",
				);
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	const completed = useMemo(
		() =>
			setupProgress({
				hasInstagram: instagramAccounts.length > 0,
				pushState,
				phoneConfirmed,
			}),
		[instagramAccounts.length, phoneConfirmed, pushState],
	);
	const readinessIssues = buildPublishingReadinessIssues({
		hasInstagramAccount: instagramAccounts.length > 0,
		pushState,
		pwaState,
		instagramReady: phoneConfirmed,
		lastHandoffCompleted: false,
	}).map((issue) => ({
		...issue,
		action:
			issue.id === "instagram-account"
				? () => navigate("/accounts")
				: issue.id === "notify-push"
					? () => void enablePush()
					: issue.id === "pwa-install" || issue.id === "instagram-app"
						? () => setPhoneConfirmed(true)
						: undefined,
	}));

	async function enablePush() {
		setBusy(true);
		try {
			const ok = await subscribeToPush();
			setPushState(
				ok
					? "subscribed"
					: getPermissionState() === "denied"
						? "denied"
						: "not-subscribed",
			);
			if (ok) appToast.success("Notifications enabled");
			else appToast.error("Could not enable notifications");
			if (ok)
				trackClientEvent("pwa_setup_step_completed", { step: "enable_push" });
		} finally {
			setBusy(false);
		}
	}

	async function sendTestPush() {
		setBusy(true);
		try {
			const response = await fetch(
				apiUrl("/api/notifications?action=test-push"),
				{
					method: "POST",
					headers: await authHeaders(),
				},
			);
			if (!response.ok) throw new Error("Test notification failed");
			appToast.success("Test notification sent");
			trackClientEvent("pwa_setup_step_completed", { step: "test_push" });
		} catch (err) {
			appToast.error("Could not send test notification", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setBusy(false);
		}
	}

	const openComposer = (mode: "auto" | "notify") => {
		trackClientEvent("first_post_wizard_step_completed", {
			step: "open_composer",
			mode,
		});
		const qs = new URLSearchParams({
			fromWizard: "1",
			platform: "instagram",
			postType: "reels",
			publishMode: mode,
			sample: "1",
		});
		if (instagramAccounts[0]) qs.set("accountId", instagramAccounts[0].id);
		navigate(`/composer?${qs.toString()}`);
	};
	const progressValue = Math.round((completed.size / STEPS.length) * 100);

	return (
		<NovaScreen width="wide" density="compact">
			<NovaHeader
				eyebrow="Setup"
				title="Publishing readiness"
				meta="Instagram · Notify Me · PWA"
				description="A guided path from zero setup to your first scheduled Instagram post."
				actions={
					<Button
						type="button"
						variant="default"
						size="sm"
						onClick={() => openComposer("notify")}
					>
						Open Composer
						<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
					</Button>
				}
			/>

			<div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
				<main className="flex flex-col gap-4">
					<NovaCard
						eyebrow="First post wizard"
						title="Build the first post path before you schedule."
						description="This does not create posts by itself. It checks the setup, then opens Composer with the right Instagram/Reel/Notify Me defaults."
						action={
							<Badge
								tone={instagramAccounts.length > 0 ? "secondary" : "oxblood"}
							>
								{instagramAccounts.length > 0
									? "account ready"
									: "needs account"}
							</Badge>
						}
					>
						<Progress
							value={progressValue}
							tone={progressValue >= 70 ? "good" : "warn"}
							aria-label="Publishing setup progress"
						/>
						<div className="mt-5 grid gap-2 overflow-hidden rounded-md border border-border md:grid-cols-2">
							{STEPS.map((step, index) => {
								const done = completed.has(step.id);
								return (
									<ListRow key={step.id} density="compact" separator={false}>
										<div className="flex items-start gap-2">
											<span
												className={
													done
														? "text-[var(--color-health-good)]"
														: "text-muted-foreground"
												}
											>
												{done ? (
													<CheckCircle2
														className="h-4 w-4"
														aria-hidden="true"
													/>
												) : (
													<Circle className="h-4 w-4" aria-hidden="true" />
												)}
											</span>
											<div>
												<div className="text-[0.8125rem] font-semibold text-foreground">
													{index + 1}. {step.label}
												</div>
												<div className="mt-1 text-[0.71875rem] text-muted-foreground">
													{step.detail}
												</div>
											</div>
										</div>
									</ListRow>
								);
							})}
						</div>
					</NovaCard>

					<NovaSection className="grid gap-4 lg:grid-cols-2">
						<NovaCard
							eyebrow={
								<span className="inline-flex items-center gap-2">
									<Camera className="h-4 w-4" aria-hidden="true" />
									Publishing path
								</span>
							}
							contentClassName="p-0"
						>
							<div className="overflow-hidden">
								<Button
									type="button"
									variant="ghost"
									onClick={() => openComposer("auto")}
									className="h-auto w-full justify-start rounded-none border-b border-border p-3 text-left"
								>
									<div>
										<div className="text-sm font-semibold text-foreground">
											Auto-publish
										</div>
										<div className="mt-1 text-xs text-muted-foreground">
											Best for API-safe Feed/Reel posts with strict validation.
										</div>
									</div>
								</Button>
								<Button
									type="button"
									variant="ghost"
									onClick={() => openComposer("notify")}
									className="h-auto w-full justify-start rounded-none border-l-2 border-l-[var(--color-oxblood)] bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)] p-3 text-left hover:bg-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)]"
								>
									<div>
										<div className="text-sm font-semibold text-foreground">
											Notify Me
										</div>
										<div className="mt-1 text-xs text-muted-foreground">
											Best for native Reels/Stories, music, stickers, and final
											Instagram editing.
										</div>
									</div>
								</Button>
							</div>
						</NovaCard>

						<PhoneSetupChecklist
							pwaState={pwaState}
							pushState={pushState}
							instagramConfirmed={phoneConfirmed}
							busy={busy}
							onEnablePush={() => void enablePush()}
							onSendTestPush={() => void sendTestPush()}
							onConfirmInstagram={() => {
								setPhoneConfirmed(true);
								trackClientEvent("pwa_setup_step_completed", {
									step: "instagram_confirmed",
								});
							}}
						/>
					</NovaSection>

					<NovaCard
						eyebrow={
							<span className="inline-flex items-center gap-2">
								<ImagePlus className="h-4 w-4" aria-hidden="true" />
								Starter media guidance
							</span>
						}
					>
						<div className="grid gap-3 md:grid-cols-3">
							{[
								"9:16 Reel video",
								"4:5 or square Feed image",
								"9:16 Story asset",
							].map((label) => (
								<NovaCard
									key={label}
									variant="panel"
									contentClassName="p-3"
								>
									<div className="text-[0.8125rem] font-medium text-foreground">
										{label}
									</div>
									<div className="mt-1 text-[0.71875rem] text-muted-foreground">
										Composer will recommend the right surface and validation
										path.
									</div>
								</NovaCard>
							))}
						</div>
					</NovaCard>
				</main>

				<aside className="flex flex-col gap-4 xl:sticky xl:top-4">
					<PublishingReadinessPanel
						issues={readinessIssues}
						onIssueAction={(issue) =>
							trackClientEvent("account_readiness_action_clicked", {
								issue_id: issue.id,
								surface: "setup_publishing",
							})
						}
					/>
				</aside>
			</div>
		</NovaScreen>
	);
}
