import { useMemo } from 'react';
import { useAccountGroups } from '@/hooks/useAccountGroups';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export function useSelectedGroupAccountIds(scopedAccount: AccountScopeValue | null) {
  const selectedGroupId = useWorkspaceStore((s) => s.selectedGroupId);
  const { groups } = useAccountGroups();

  const accountIds = useMemo(() => {
    if (scopedAccount || !selectedGroupId) return undefined;
    const ids = groups.find((group) => group.id === selectedGroupId)?.accountIds ?? [];
    return ids.length > 0 ? ids : undefined;
  }, [groups, scopedAccount, selectedGroupId]);

  return {
    selectedGroupId,
    accountIds,
    groupId: scopedAccount ? null : selectedGroupId,
  };
}
