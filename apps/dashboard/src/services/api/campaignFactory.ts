/**
 * Campaign Factory API operations
 */

import { z } from "zod";
import { apiFetch } from "@/lib/apiFetch";

export interface AICostSummaryResponse {
	total_calls: number;
	total_cost_usd: number;
	by_provider: Record<
		string,
		{
			operation: string;
			calls: number;
			input_tokens: number | null;
			output_tokens: number | null;
			generations: number | null;
			cost_usd: number;
		}[]
	>;
	filters: {
		campaign_id: string | null;
		days: number | null;
	};
}

const aiCostSummaryResponseSchema = z.object({
	total_calls: z.number(),
	total_cost_usd: z.number(),
	by_provider: z.record(
		z.string(),
		z.array(
			z.object({
				operation: z.string(),
				calls: z.number(),
				input_tokens: z.number().nullable(),
				output_tokens: z.number().nullable(),
				generations: z.number().nullable(),
				cost_usd: z.number(),
			})
		)
	),
	filters: z.object({
		campaign_id: z.string().nullable(),
		days: z.number().nullable(),
	}),
});

/**
 * Fetches the AI cost summary from Campaign Factory.
 * Defaults to 30 days unless specified otherwise.
 */
export async function getCostSummary({
	days = 30,
	campaignId,
}: {
	days?: number;
	campaignId?: string;
} = {}): Promise<AICostSummaryResponse> {
	const params = new URLSearchParams();
	if (days) params.append("days", String(days));
	if (campaignId) params.append("campaign_id", campaignId);

	const query = params.toString() ? `?${params.toString()}` : "";
	
	// Assuming /api/cost-summary routes correctly via your proxy or Next/Vite config to CF.
	return apiFetch<AICostSummaryResponse>(
		`/api/cost-summary${query}`,
		aiCostSummaryResponseSchema,
		{ auth: false }
	);
}
