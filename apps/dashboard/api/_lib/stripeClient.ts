import Stripe from "stripe";

let stripe: Stripe | null = null;

export function getStripe(): Stripe {
	if (!stripe) {
		const key = process.env.STRIPE_SECRET_KEY;
		if (!key) {
			throw new Error("[stripe] STRIPE_SECRET_KEY is not configured");
		}
		stripe = new Stripe(key, {
			// @ts-expect-error — holding wire-format on clover to keep SDK majors no-op against prod; SDK only types LatestApiVersion (dahlia).
			apiVersion: "2026-02-25.clover",
		});
	}
	return stripe;
}
