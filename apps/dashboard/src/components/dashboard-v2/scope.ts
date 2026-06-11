import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

export interface DashboardScopeProps {
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	scopeLabel?: string | undefined;
}

export function scopeKey(
	scopedAccount?: AccountScopeValue | null,
	accountIds?: string[] | null,
	groupId?: string | null,
): string {
	if (scopedAccount) return scopedAccount.id;
	if (groupId) return `group:${groupId}`;
	return accountIds && accountIds.length > 0 ? accountIds.join(",") : "fleet";
}
