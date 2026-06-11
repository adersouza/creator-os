import { useEffect, useMemo, useState } from "react";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import {
	fetchComposerHealthPills,
	type AccountHealthPill,
} from "@/services/api/composer";

const SIGNAL_LABEL: Record<string, string> = {
	engagement_spike: "Engagement spike",
	reach_anomaly: "Reach anomaly",
	token_expiring: "Token expiring",
	rate_limit: "Rate limit",
	shadowban_risk: "Shadowban risk",
};

const SEVERITY_CLASS: Record<string, string> = {
	good: "bg-[var(--color-positive)]",
	warn: "bg-[var(--color-gold)]",
	critical: "bg-[var(--color-negative)]",
};

export function ChannelHealthPills({
	accounts,
}: {
	accounts: ConnectedAccount[];
}) {
	const [rows, setRows] = useState<AccountHealthPill[]>([]);
	const [loading, setLoading] = useState(false);
	const idsKey = useMemo(
		() => accounts.map((account) => account.id).join(","),
		[accounts],
	);

	useEffect(() => {
		const ids = idsKey ? idsKey.split(",") : [];
		if (ids.length === 0) {
			setRows([]);
			setLoading(false);
			return;
		}
		let cancelled = false;
		setLoading(true);
		fetchComposerHealthPills(ids)
			.then((next) => {
				if (!cancelled) setRows(next);
			})
			.catch(() => {
				if (!cancelled) setRows([]);
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [idsKey]);

	if (accounts.length === 0) return null;

	const byAccount = new Map(rows.map((row) => [row.account_id, row.signals]));
	return (
		<div className="mt-2 flex flex-wrap items-center gap-1.5">
			{accounts.map((account) => {
				const signals = byAccount.get(account.id) ?? [];
				const max = maxSeverity(signals.map((signal) => signal.severity));
				return (
					<div
						key={account.id}
						className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-1 text-[0.65625rem] text-muted-foreground"
						title={`${account.handle}: ${signals.length ? signals.map((s) => `${s.signal_type}:${s.severity}`).join(", ") : "no active signals"}`}
					>
						<span
							className={`w-1.5 h-1.5 rounded-full ${SEVERITY_CLASS[max]}`}
						/>
						<span className="font-mono">
							{account.handle.replace(/^@/, "")}
						</span>
						<span className="text-muted-foreground">
							{loading
								? "…"
								: signals.length
									? signals
											.slice(0, 2)
											.map(
												(signal) =>
													SIGNAL_LABEL[signal.signal_type] ??
													signal.signal_type.replace(/_/g, " "),
											)
											.join(" / ")
									: "ok"}
						</span>
					</div>
				);
			})}
		</div>
	);
}

function maxSeverity(severities: string[]): "good" | "warn" | "critical" {
	if (severities.includes("critical")) return "critical";
	if (severities.includes("warn")) return "warn";
	return "good";
}
