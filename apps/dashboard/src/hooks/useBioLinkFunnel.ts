import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { getApiAuthHeaders } from "@/lib/apiAuth";
import { apiUrl } from "@/lib/apiUrl";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

export interface BioLinkRollup {
	smartLinkId: string;
	code: string;
	title: string | null;
	targetUrl: string;
	estConversionRate: number;
	estConversionValue: number;
	clicks: number;
	clicksBySource: Record<string, number>;
	deepLinkAttempts: number;
	interstitialViews: number;
	destinationClicks: number;
	directRedirects: number;
	dropoffRate: number;
	conversions: number;
	conversionValue: number;
}

export interface BioLinkTotals {
	clicks: number;
	clicksBySource: Record<string, number>;
	deepLinkAttempts: number;
	interstitialViews: number;
	destinationClicks: number;
	directRedirects: number;
	dropoffRate: number;
	conversions: number;
	conversionValue: number;
	estimatedRevenue: number;
}

interface BioLinkFunnelResponse {
	links: BioLinkRollup[];
	totals: BioLinkTotals;
	periodDays: number;
	activeLinkCount: number;
	totalLinkCount: number;
}

interface BioLinkFunnelState extends BioLinkFunnelResponse {
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY_TOTALS: BioLinkTotals = {
	clicks: 0,
	clicksBySource: {},
	deepLinkAttempts: 0,
	interstitialViews: 0,
	destinationClicks: 0,
	directRedirects: 0,
	dropoffRate: 0,
	conversions: 0,
	conversionValue: 0,
	estimatedRevenue: 0,
};

const EMPTY: BioLinkFunnelResponse = {
	links: [],
	totals: EMPTY_TOTALS,
	periodDays: 30,
	activeLinkCount: 0,
	totalLinkCount: 0,
};

async function fetchBioLinkFunnel(
	periodDays: number,
	scopedAccount: AccountScopeValue | null,
	accountIds?: string[],
): Promise<BioLinkFunnelResponse> {
	const params = new URLSearchParams({
		action: "bio-link-funnel",
		periodDays: String(periodDays),
	});
	if (scopedAccount) {
		params.set("accountId", scopedAccount.id);
		params.set("platform", scopedAccount.platform);
	} else if (accountIds && accountIds.length > 0) {
		params.set("accountIds", accountIds.join(","));
	}
	const response = await fetch(apiUrl(`/api/analytics?${params}`), {
		headers: await getApiAuthHeaders(),
	});
	if (!response.ok) throw new Error("Failed to fetch bio-link funnel");
	const data = (await response.json()) as Partial<BioLinkFunnelResponse>;
	return {
		links: data.links ?? [],
		totals: data.totals ?? EMPTY_TOTALS,
		periodDays: data.periodDays ?? periodDays,
		activeLinkCount: data.activeLinkCount ?? 0,
		totalLinkCount: data.totalLinkCount ?? 0,
	};
}

export function useBioLinkFunnel(
	periodDays = 30,
	scopedAccount: AccountScopeValue | null = null,
	accountIds?: string[],
	groupId?: string | null,
): BioLinkFunnelState {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;

	const { data, isPending, isError } = useQuery<BioLinkFunnelResponse>({
		queryKey: [
			"bioLinkFunnel",
			userKey,
			periodDays,
			scopedAccount?.id ?? "fleet",
			groupId ?? "all",
			accountIds?.join(",") ?? null,
		],
		enabled: !!userKey,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: () => fetchBioLinkFunnel(periodDays, scopedAccount, accountIds),
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
