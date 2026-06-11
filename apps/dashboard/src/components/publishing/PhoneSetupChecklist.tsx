import { BellRing, CheckCircle2, ExternalLink, Smartphone } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { pwaSetupCopy } from "@/lib/pwaSetup";
import type { PwaInstallState } from "@/types/publishingReadiness";

type PushState =
	| "checking"
	| "unsupported"
	| "denied"
	| "subscribed"
	| "not-subscribed"
	| "permission-needed"
	| string;

function pushTone(
	pushState: PushState,
): "secondary" | "outline" | "danger" | "oxblood" {
	if (pushState === "subscribed") return "secondary";
	if (pushState === "denied" || pushState === "unsupported") return "outline";
	if (pushState === "checking") return "outline";
	return "oxblood";
}

function pushLabel(pushState: PushState): string {
	if (pushState === "subscribed") return "push ready";
	if (pushState === "denied") return "blocked";
	if (pushState === "unsupported") return "fallback";
	if (pushState === "checking") return "checking";
	return "needs push";
}

export function PhoneSetupChecklist({
	pwaState,
	pushState,
	instagramConfirmed = false,
	busy = false,
	onEnablePush,
	onSendTestPush,
	onConfirmInstagram,
	compact = false,
}: {
	pwaState: PwaInstallState;
	pushState: PushState;
	instagramConfirmed?: boolean | undefined;
	busy?: boolean | undefined;
	onEnablePush?: (() => void) | undefined;
	onSendTestPush?: (() => void) | undefined;
	onConfirmInstagram?: (() => void) | undefined;
	compact?: boolean | undefined;
}) {
	const copy = pwaSetupCopy(pwaState);
	const checklist = [
		...copy.steps,
		instagramConfirmed
			? "Instagram login confirmed"
			: "Confirm Instagram is installed and logged in",
	];
	return (
		<NovaCard
			eyebrow={
				<span className="inline-flex items-center gap-2">
					<Smartphone className="h-4 w-4" aria-hidden="true" />
					Phone setup
				</span>
			}
			title={copy.label}
			description={copy.detail}
			action={<Badge tone={pushTone(pushState)}>{pushLabel(pushState)}</Badge>}
		>
			<ul className="mt-3 flex flex-col gap-1.5 text-xs text-muted-foreground">
				{checklist.slice(0, compact ? 4 : checklist.length).map((step) => (
					<li key={step} className="flex items-start gap-2">
						<CheckCircle2
							className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
								step === "Instagram login confirmed"
									? "text-[var(--color-health-good)]"
									: "text-muted-foreground"
							}`}
							aria-hidden="true"
						/>
						<span>{step}</span>
					</li>
				))}
			</ul>

			<div className="mt-4 grid gap-2 sm:grid-cols-3">
				<Button
					type="button"
					variant="outline"
					onClick={onEnablePush}
					disabled={
						busy ||
						!onEnablePush ||
						pushState === "subscribed" ||
						pushState === "unsupported"
					}
					className="min-h-10"
				>
					<BellRing data-icon="inline-start" aria-hidden="true" />
					Enable push
				</Button>
				<Button
					type="button"
					variant="default"
					onClick={onSendTestPush}
					disabled={busy || !onSendTestPush || pushState !== "subscribed"}
					className="min-h-10"
				>
					Test push
				</Button>
				<Button
					type="button"
					variant="outline"
					onClick={onConfirmInstagram}
					disabled={busy || !onConfirmInstagram || instagramConfirmed}
					className="min-h-10"
				>
					<ExternalLink data-icon="inline-start" aria-hidden="true" />
					Confirm Instagram
				</Button>
			</div>
		</NovaCard>
	);
}
