// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Thompson Sampling Bandit for Link Page A/B Testing
 *
 * Beta distribution-based multi-armed bandit:
 * - Converges to optimal with 200-300 observations (vs 3,466 for frequentist)
 * - Automatically allocates traffic to winning variants
 * - Supports hierarchical priors (global → persona → account)
 *
 * Reference: Link Page Conversion 2026, Section 7
 */

// ─── Beta Distribution Sampling ───────────────────────────────────

/**
 * Standard normal via Box-Muller transform.
 */
function normalRandom(): number {
	const u1 = Math.random();
	const u2 = Math.random();
	return Math.sqrt(-2 * Math.log(u1 || 1e-10)) * Math.cos(2 * Math.PI * u2);
}

/**
 * Sample from Gamma(alpha, 1) using Marsaglia-Tsang method.
 * O(1) regardless of alpha size.
 */
function sampleGamma(alpha: number): number {
	if (alpha < 1) {
		return sampleGamma(alpha + 1) * (Math.random() || 1e-10) ** (1 / alpha);
	}

	const d = alpha - 1 / 3;
	const c = 1 / Math.sqrt(9 * d);

	for (;;) {
		let x: number;
		let v: number;
		do {
			x = normalRandom();
			v = 1 + c * x;
		} while (v <= 0);

		v = v * v * v;
		const u = Math.random();

		if (u < 1 - 0.0331 * x * x * x * x) return d * v;
		if (Math.log(u || 1e-10) < 0.5 * x * x + d * (1 - v + Math.log(v)))
			return d * v;
	}
}

/**
 * Sample from Beta(alpha, beta) distribution.
 * Uses: Beta(a,b) = X/(X+Y) where X~Gamma(a,1), Y~Gamma(b,1)
 */
export function sampleBeta(alpha: number, beta: number): number {
	if (alpha <= 0 || beta <= 0) return 0.5;
	const x = sampleGamma(alpha);
	const y = sampleGamma(beta);
	if (x + y === 0) return 0.5;
	return x / (x + y);
}

// ─── Core Bandit Types ────────────────────────────────────────────

export interface BanditVariant {
	id: string;
	alpha: number;
	beta: number;
	impressions: number;
	conversions: number;
}

export interface VariantConfig {
	cta_text?: string | undefined;
	brand_color?: string | undefined;
	bio_text?: string | undefined;
	promo_text?: string | undefined;
	link_order?: string[] | undefined;
	max_links?: number | undefined;
	show_social_proof?: boolean | undefined;
}

// ─── Thompson Sampling Decision ───────────────────────────────────

/**
 * Select the variant with highest sampled CTR.
 */
export function selectVariant(variants: BanditVariant[]): string {
	if (variants.length === 0) throw new Error("No variants");
	if (variants.length === 1) return variants[0]!.id;

	let bestId = variants[0]!.id;
	let bestSample = -1;

	for (const v of variants) {
		const sample = sampleBeta(v.alpha, v.beta);
		if (sample > bestSample) {
			bestSample = sample;
			bestId = v.id;
		}
	}

	return bestId;
}

// ─── Statistical Analysis ─────────────────────────────────────────

/**
 * Monte Carlo estimation of P(variant is best) for each variant.
 */
export function probabilityOfBest(
	variants: BanditVariant[],
	trials = 10_000,
): Map<string, number> {
	const wins = new Map<string, number>();
	for (const v of variants) wins.set(v.id, 0);

	for (let t = 0; t < trials; t++) {
		let bestId = variants[0]!.id;
		let bestSample = -1;

		for (const v of variants) {
			const sample = sampleBeta(v.alpha, v.beta);
			if (sample > bestSample) {
				bestSample = sample;
				bestId = v.id;
			}
		}

		wins.set(bestId, (wins.get(bestId) || 0) + 1);
	}

	const result = new Map<string, number>();
	for (const [id, w] of wins) result.set(id, w / trials);
	return result;
}

/**
 * Expected loss: how much CTR we'd lose by picking this variant vs actual best.
 * Lower = better. Declare winner when loss < 0.005 (0.5 ppts).
 */
export function expectedLoss(
	variant: BanditVariant,
	allVariants: BanditVariant[],
	trials = 5_000,
): number {
	let totalLoss = 0;

	for (let t = 0; t < trials; t++) {
		const mySample = sampleBeta(variant.alpha, variant.beta);
		let bestSample = mySample;

		for (const other of allVariants) {
			if (other.id === variant.id) continue;
			const s = sampleBeta(other.alpha, other.beta);
			if (s > bestSample) bestSample = s;
		}

		totalLoss += bestSample - mySample;
	}

	return totalLoss / trials;
}

// ─── Auto-Declaration ─────────────────────────────────────────────

/**
 * Check if a variant should be declared winner.
 *
 * Criteria (Link Page Conversion 2026, Section 7):
 * - P(best) > 95%
 * - ≥200 total observations
 * - ≥100 observations for this variant
 * - ≥7 days elapsed
 * - Expected loss < 0.005 (0.5 CTR ppts)
 */
export function shouldDeclareWinner(
	variant: BanditVariant,
	allVariants: BanditVariant[],
	testStartDate: Date,
): { declare: boolean; probBest: number; loss: number; reason?: string | undefined } {
	const daysElapsed =
		(Date.now() - testStartDate.getTime()) / (1000 * 60 * 60 * 24);
	const totalObs = allVariants.reduce((s, v) => s + v.impressions, 0);

	if (daysElapsed < 7)
		return { declare: false, probBest: 0, loss: 1, reason: "min_7_days" };
	if (variant.impressions < 100)
		return {
			declare: false,
			probBest: 0,
			loss: 1,
			reason: "min_100_obs_variant",
		};
	if (totalObs < 200)
		return {
			declare: false,
			probBest: 0,
			loss: 1,
			reason: "min_200_obs_total",
		};

	const probs = probabilityOfBest(allVariants);
	const probBest = probs.get(variant.id) || 0;

	if (probBest < 0.95)
		return { declare: false, probBest, loss: 1, reason: "prob_below_95" };

	const loss = expectedLoss(variant, allVariants);
	if (loss > 0.005)
		return { declare: false, probBest, loss, reason: "loss_above_threshold" };

	return { declare: true, probBest, loss };
}

// ─── Hierarchical Prior ───────────────────────────────────────────

/**
 * Get warm-start prior from parent level.
 *
 * Three-level hierarchy:
 * - Global: pooled across all pages → uninformative Beta(1,1) start
 * - Persona: per account group → uses global posterior as prior
 * - Account: per individual → uses persona posterior as prior
 *
 * Returns {alpha, beta} to use as prior for a new variant at the given level.
 */
export async function getHierarchicalPrior(
	// biome-ignore lint/suspicious/noExplicitAny: Supabase client
	db: any,
	pageId: string,
	level: "global" | "persona" | "account",
	groupId?: string,
): Promise<{ alpha: number; beta: number }> {
	if (level === "global") {
		return { alpha: 1, beta: 1 }; // Uninformative prior
	}

	if (level === "persona" && groupId) {
		// Use global-level variants for this page as prior
		const { data } = await db
			.from("link_page_variants")
			.select("alpha, beta")
			.eq("page_id", pageId)
			.eq("level", "global")
			.eq("is_active", true);

		if (data?.length) {
			// Pool global posteriors: sum alpha and beta across global variants
			const totalAlpha = data.reduce(
				(s: number, v: { alpha: number }) => s + v.alpha,
				0,
			);
			const totalBeta = data.reduce(
				(s: number, v: { beta: number }) => s + v.beta,
				0,
			);
			// Normalize to reasonable prior strength (cap at 100 to avoid over-domination)
			const scale = Math.min(1, 100 / (totalAlpha + totalBeta));
			return {
				alpha: Math.max(1, Math.round(totalAlpha * scale)),
				beta: Math.max(1, Math.round(totalBeta * scale)),
			};
		}
	}

	if (level === "account" && groupId) {
		// Use persona-level variants as prior
		const { data } = await db
			.from("link_page_variants")
			.select("alpha, beta")
			.eq("page_id", pageId)
			.eq("level", "persona")
			.eq("group_id", groupId)
			.eq("is_active", true);

		if (data?.length) {
			const totalAlpha = data.reduce(
				(s: number, v: { alpha: number }) => s + v.alpha,
				0,
			);
			const totalBeta = data.reduce(
				(s: number, v: { beta: number }) => s + v.beta,
				0,
			);
			const scale = Math.min(1, 100 / (totalAlpha + totalBeta));
			return {
				alpha: Math.max(1, Math.round(totalAlpha * scale)),
				beta: Math.max(1, Math.round(totalBeta * scale)),
			};
		}
	}

	return { alpha: 1, beta: 1 }; // Fallback
}
