import { Users } from "lucide-react";
import { useState } from "react";
import { appToast } from "@/lib/toast";
import {
	CANONICAL_NICHES,
	NICHE_LABELS,
	type CanonicalNiche,
} from "@/lib/cohorts";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { Separator } from "@/components/ui/Separator";
import { Switch } from "@/components/ui/Switch";
import { useDataContribution } from "@/hooks/useDataContribution";
import { trackEvent, withScopePayload } from "@/services/analyticsService";

export function CohortSharingCard() {
	const { optedIn, niche, loading, saving, setContribution } =
		useDataContribution();
	const [pendingNiche, setPendingNiche] = useState<CanonicalNiche | "">("");

	const effectiveNiche: CanonicalNiche | "" = niche ?? pendingNiche;

	const handleToggle = async (next: boolean) => {
		if (next) {
			const chosen: CanonicalNiche | "" = niche ?? pendingNiche;
			if (!chosen) {
				appToast.warn("Pick your niche first", {
					description:
						"Cohort sharing needs a niche so we can aggregate you with the right peers.",
				});
				return;
			}
			try {
				await setContribution(true, chosen);
				trackEvent(
					"cohort_sharing_opt_in_toggled",
					withScopePayload({ enabled: true, niche: chosen }),
				);
				appToast.success("Cohort sharing on", {
					description: "Your data starts contributing tomorrow at 2 AM UTC.",
				});
			} catch (err) {
				appToast.error("Could not enable cohort sharing", {
					description: err instanceof Error ? err.message : "Please try again.",
				});
			}
			return;
		}

		try {
			await setContribution(false, niche ?? null);
			trackEvent(
				"cohort_sharing_opt_in_toggled",
				withScopePayload({ enabled: false }),
			);
			appToast.info("Cohort sharing off", {
				description: "You stop contributing on tomorrow’s 2 AM refresh.",
			});
		} catch (err) {
			appToast.error("Could not disable cohort sharing", {
				description: err instanceof Error ? err.message : "Please try again.",
			});
		}
	};

	const handleNichePick = async (value: CanonicalNiche) => {
		setPendingNiche(value);
		if (optedIn) {
			try {
				await setContribution(true, value);
				trackEvent(
					"cohort_sharing_niche_changed",
					withScopePayload({ niche: value }),
				);
				appToast.success("Niche updated", {
					description: "Your next daily aggregation will use the new niche.",
				});
			} catch (err) {
				appToast.error("Could not update niche", {
					description: err instanceof Error ? err.message : "Please try again.",
				});
			}
		}
	};

	const disabled = loading || saving;

	return (
		<NovaCard
			title="Anonymized cohort benchmarking"
			description="Contribute your account metrics to the anonymized peer cohort. Cohort benchmarks unlock on Analytics so you can compare your fleet to matched peers."
			action={
				<Switch
					checked={optedIn}
					onCheckedChange={handleToggle}
					disabled={disabled}
					aria-label="Toggle anonymized cohort sharing"
				/>
			}
		>
			<div className="flex flex-col gap-4">
				<div className="flex items-start gap-3">
					<span
						className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] text-[color:var(--color-oxblood)]"
						aria-hidden="true"
					>
						<Users />
					</span>
					<Field
						label={`Your niche ${optedIn ? "(active)" : "(required to enable)"}`}
						hint="Used only to place your metrics into the correct anonymized cohort."
					>
						<Select
							id="cohort-niche"
							value={effectiveNiche}
							onChange={(e) =>
								handleNichePick(e.target.value as CanonicalNiche)
							}
							disabled={disabled}
							className="max-w-xs"
						>
							<option value="" disabled>
								Pick a niche…
							</option>
							{CANONICAL_NICHES.map((n) => (
								<option key={n} value={n}>
									{NICHE_LABELS[n]}
								</option>
							))}
						</Select>
					</Field>
				</div>

				<Separator />

				<ul className="flex flex-col gap-1.5 text-[0.71875rem] text-muted-foreground leading-relaxed">
					<li className="flex gap-2">
						<span aria-hidden="true" className="text-muted-foreground">
							•
						</span>
						<span>
							We share bucket aggregates only — count, p25, median, p75, p90.
							Never account IDs, names, or individual posts.
						</span>
					</li>
					<li className="flex gap-2">
						<span aria-hidden="true" className="text-muted-foreground">
							•
						</span>
						<span>
							Minimum cohort: 30 accounts and 10 distinct users for medians. 50
							and 15 for the full distribution. Smaller cohorts stay hidden.
						</span>
					</li>
					<li className="flex gap-2">
						<span aria-hidden="true" className="text-muted-foreground">
							•
						</span>
						<span>
							Opt out any time. You stop contributing on the next 2 AM refresh;
							anonymized aggregates age out after 90 days.
						</span>
					</li>
				</ul>
			</div>
		</NovaCard>
	);
}
