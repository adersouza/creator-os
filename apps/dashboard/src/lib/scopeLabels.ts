import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

type PlatformLabel = "All accounts" | "Threads" | "Instagram" | string;

interface ScopeGroup {
	id?: string | null | undefined;
	name?: string | null | undefined;
	accountIds?: string[] | null | undefined;
}

export interface ScopeCopy {
	kind: "account" | "group" | "all";
	short: string;
	header: string;
	operator: string;
	chip: string;
	noun: string;
	snapshotTitle: string;
	emptySubject: string;
	exportLabel: string;
}

export function formatAccountHandle(handle: string | null | undefined): string {
	if (!handle) return "Selected account";
	return handle.startsWith("@") ? handle : `@${handle}`;
}

export function buildScopeCopy({
	scopedAccount,
	group,
	accountCount,
	platformLabel = "All accounts",
}: {
	scopedAccount?: AccountScopeValue | null | undefined;
	group?: ScopeGroup | null | undefined;
	accountCount?: number | null | undefined;
	platformLabel?: PlatformLabel | undefined;
}): ScopeCopy {
	if (scopedAccount) {
		const handle = formatAccountHandle(scopedAccount.handle);
		const platform =
			scopedAccount.platform === "instagram" ? "Instagram" : "Threads";
		return {
			kind: "account",
			short: handle,
			header: handle,
			operator: `OPERATOR · ${handle} · ${platform.toUpperCase()} ACCOUNT`,
			chip: handle,
			noun: "selected account",
			snapshotTitle: "Account snapshot",
			emptySubject: "this account",
			exportLabel: `${handle} ${platform}`,
		};
	}

	if (group?.name) {
		const count = group.accountIds?.length ?? accountCount ?? 0;
		const countLabel =
			count > 0 ? ` · ${count} account${count === 1 ? "" : "s"}` : "";
		return {
			kind: "group",
			short: group.name,
			header: group.name,
			operator: `OPERATOR · ${group.name}${countLabel}`.toUpperCase(),
			chip: `${group.name}${countLabel}`,
			noun: `${group.name} group`,
			snapshotTitle: `${group.name} snapshot`,
			emptySubject: `${group.name} group`,
			exportLabel: group.name,
		};
	}

	const count = accountCount ?? 0;
	const accountLabel =
		count > 0 ? `${count} account${count === 1 ? "" : "s"}` : "all accounts";
	return {
		kind: "all",
		short: platformLabel,
		header: platformLabel === "Fleet overview" ? "All accounts" : platformLabel,
		operator: `OPERATOR · ${accountLabel.toUpperCase()}`,
		chip: accountLabel,
		noun: "all accounts",
		snapshotTitle: "All accounts snapshot",
		emptySubject: "all accounts",
		exportLabel: platformLabel === "Fleet overview" ? "All accounts" : platformLabel,
	};
}
