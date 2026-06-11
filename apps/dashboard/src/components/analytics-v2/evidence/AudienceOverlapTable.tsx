import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useAudienceOverlap } from "@/hooks/useAudienceOverlap";
import type { OverlapEngager } from "@/hooks/useAudienceOverlap";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { DataTable } from "@/components/ui/DataTable";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { EvidenceTile } from "../EvidenceTile";

interface Props {
	/** Optional override for the account scope. Defaults to all Threads accounts. */
	accountIds?: string[] | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	groupId?: string | null | undefined;
}

/**
 * §17 Audience overlap — pairwise repeat-engager overlap between accounts.
 * Endpoint caps at 20 accounts; we trim to the most-active 20 Threads accounts
 * by default. v1 renders the top pairs as a table sorted by overlap %.
 *
 * Sankey/network viz comes in a follow-up; the table form is the highest
 * info density and avoids the §9 anti-pattern penalty for legends.
 */
export function AudienceOverlapTable({
	accountIds,
	scopedAccount: scopedAccountProp,
	groupId,
}: Props) {
	const { accounts } = useConnectedAccounts();
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount =
		scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;

	// Default: top 20 Threads accounts (overlap is repliers-based, IG-only
	// accounts wouldn't add signal here).
	const ids = useMemo(() => {
		if (accountIds && accountIds.length > 0) return accountIds.slice(0, 20);
		if (scopedAccount?.platform === "threads") return [scopedAccount.id];
		if (scopedAccount?.platform === "instagram") return [];
		return accounts
			.filter((a) => a.platform === "threads")
			.slice(0, 20)
			.map((a) => a.id);
	}, [accountIds, scopedAccount, accounts]);

	const { data, isLoading, hasError } = useAudienceOverlap(ids, groupId);

	// Username lookup for the table.
	const usernameById = useMemo(() => {
		const map = new Map<string, string>();
		for (const a of accounts) map.set(a.id, a.handle);
		return map;
	}, [accounts]);

	const columns = useMemo<ColumnDef<OverlapEngager>[]>(
		() => [
			{
				accessorKey: "username",
				header: "Engager",
				cell: ({ row }) => (
					<span className="block truncate">@{row.original.username}</span>
				),
				meta: {
					headerClassName: "analytics-col-engager px-6",
					cellClassName: "analytics-col-engager px-6 py-2 text-foreground",
				},
			},
			{
				id: "accounts",
				header: "Accounts",
				accessorFn: (overlap) =>
					overlap.accountIds
						.map((id) => usernameById.get(id) ?? id.slice(0, 8))
						.join(" "),
				cell: ({ row }) => {
					const labels = row.original.accountIds.map(
						(id) => usernameById.get(id) ?? id.slice(0, 8),
					);
					return (
						<span className="block truncate">
							{labels.map((label) => `@${label}`).join(" · ")}
						</span>
					);
				},
				meta: {
					headerClassName: "analytics-col-accounts",
					cellClassName: "analytics-col-accounts px-3 py-2 text-foreground",
				},
			},
			{
				id: "shared",
				header: "Shared",
				accessorFn: (overlap) => overlap.accountIds.length,
				cell: ({ row }) => row.original.accountIds.length.toLocaleString(),
				meta: {
					headerClassName: "analytics-col-shared text-right",
					cellClassName:
						"analytics-col-shared px-3 py-2 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				accessorKey: "totalInteractions",
				header: "Interactions",
				cell: ({ row }) => {
					const accountCount = row.original.accountIds.length;
					const tone =
						accountCount >= 4
							? "var(--color-oxblood)"
							: accountCount >= 3
								? "var(--color-gold)"
								: "var(--color-foreground)";
					return (
						<span style={{ color: tone }}>
							{row.original.totalInteractions.toLocaleString()}
						</span>
					);
				},
				meta: {
					headerClassName: "analytics-col-interactions px-6 text-right",
					cellClassName:
						"analytics-col-interactions px-6 py-2 text-right tabular-nums",
				},
			},
		],
		[usernameById],
	);

	if (ids.length < 2) {
		return (
			<EvidenceTile
				state="empty"
				label="Audience"
				title="Audience overlap"
				note="Connect at least two Threads accounts to see how much your engager bases share."
				variant="network"
			/>
		);
	}

	if (hasError) {
		return (
			<EvidenceTile
				state="empty"
				label="Audience"
				title="Audience overlap"
				note="Audience overlap could not be computed for the selected account set. The tile retries on refresh and stays empty rather than inventing shared-engager data."
				variant="network"
			/>
		);
	}

	if (isLoading || !data) {
		return (
			<EvidenceTile
				state="loading"
				index={17}
				title="Audience overlap"
				hint={`Across ${ids.length} accounts · pairwise repeat-engagers`}
				variant="table"
			/>
		);
	}

	const sorted = [...data.overlaps]
		.sort(
			(a, b) =>
				b.accountIds.length - a.accountIds.length ||
				b.totalInteractions - a.totalInteractions,
		)
		.slice(0, 8);

	if (sorted.length === 0) {
		return (
			<EvidenceTile
				state="empty"
				label="Audience"
				title="Audience overlap"
				note="No repeat engagers currently overlap across these accounts. That is a valid result; the table opens once the same captured commenter or replier appears on two or more accounts."
				variant="network"
				statusLabel="No overlap detected"
			/>
		);
	}

	return (
		<EvidenceCard
			title="Audience overlap"
			description={`${data.overlapCount.toLocaleString()} shared engagers across ${ids.length} accounts`}
			action={
				<InvestigateButton
					accountId={
						scopedAccount?.platform === "threads" ? scopedAccount.id : null
					}
					metric="engagement"
					metricLabel="Audience overlap"
					periodDays={30}
				/>
			}
			className="h-full"
			contentClassName="flex h-full flex-col p-0"
			footer={
				<p className="text-[0.6875rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
					SOURCE · post_replies + ig_comments unique engagers, computed
					pairwise. Higher % = audience cannibalization risk; ~0% =
					independent reach.
				</p>
			}
		>
			<DataTable
				data={sorted}
				columns={columns}
				ariaLabel="Audience overlap"
				className="flex-1 overflow-hidden"
				tableClassName="analytics-overlap-table"
			/>
		</EvidenceCard>
	);
}
