/**
 * useUserTier — reads the current workspace subscription tier from the
 * already-loaded workspace store. No API call — data is populated at login.
 *
 * Usage:
 *   const { tier, isAtLeast, isLoading } = useUserTier();
 *   if (!isAtLeast("pro")) return <UpgradePrompt />;
 */

import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import type { SubscriptionTier } from "@/types/team";

const TIER_RANK: Record<SubscriptionTier, number> = {
	free: 0,
	pro: 1,
	agency: 2,
	empire: 3,
};

export function useUserTier() {
	const { currentWorkspace, isLoading } = useWorkspaceStore();
	const tier = (currentWorkspace?.subscriptionTier ??
		"free") as SubscriptionTier;

	return {
		tier,
		isLoading,
		isAtLeast: (min: SubscriptionTier) => TIER_RANK[tier] >= TIER_RANK[min],
	};
}
