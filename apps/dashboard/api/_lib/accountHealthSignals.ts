import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";

type AccountPlatform = "threads" | "instagram";

interface PingAccountHealthParams {
	userId: string;
	accountId: string;
	platform?: AccountPlatform | undefined;
}

interface TokenAccountRow {
	id: string;
	user_id: string;
	username: string | null;
	needs_reauth: boolean | null;
	token_expires_at: string | null;
}

interface ActiveSignalRow {
	id: string;
	account_id: string;
	signal_type: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

export async function pingAccountHealth({
	userId,
	accountId,
	platform,
}: PingAccountHealthParams) {
	const db = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.accountHealthSignals,
	);
	const table =
		platform === "instagram" ? "instagram_accounts" : "accounts";
	const { data: account, error } = await db
		.from(table)
		.select("id, user_id, username, needs_reauth, token_expires_at")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) throw error;
	if (!account) {
		return { ok: false, reason: "not_found" };
	}

	const tokenStatus = computeTokenStatus(account as TokenAccountRow);

	// account_health_signals references public.accounts, so Instagram rows cannot
	// be persisted there until the schema grows a unified account id.
	if (table === "instagram_accounts") {
		return { ok: true, platform: "instagram", tokenStatus, persisted: false };
	}

	await syncTokenExpiringSignal(account as TokenAccountRow, tokenStatus);
	return { ok: true, platform: "threads", tokenStatus, persisted: true };
}

export async function computeTokenExpirySignals() {
	const db = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.accountHealthSignals,
	);
	const { data, error } = await db
		.from("accounts")
		.select("id, user_id, username, needs_reauth, token_expires_at")
		.eq("is_active", true)
		.eq("is_retired", false);

	if (error) throw error;

	const rows = (data ?? []) as TokenAccountRow[];
	let processed = 0;
	for (const row of rows) {
		const tokenStatus = computeTokenStatus(row);
		await syncTokenExpiringSignal(row, tokenStatus);
		processed += 1;
	}
	return processed;
}

function computeTokenStatus(account: TokenAccountRow) {
	const now = Date.now();
	const expiresAt = account.token_expires_at
		? Date.parse(account.token_expires_at)
		: null;
	const daysLeft =
		expiresAt === null ? null : Math.floor((expiresAt - now) / DAY_MS);
	const needsAction =
		account.needs_reauth === true ||
		(daysLeft !== null && daysLeft <= 7);
	const severity =
		account.needs_reauth === true || (daysLeft !== null && daysLeft < 0)
			? "critical"
			: "warn";
	return { needsAction, severity, daysLeft, expiresAt: account.token_expires_at };
}

async function syncTokenExpiringSignal(
	account: TokenAccountRow,
	tokenStatus: ReturnType<typeof computeTokenStatus>,
) {
	const db = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.accountHealthSignals,
	);
	const { data: existing, error } = await db
		.from("account_health_signals")
		.select("id, account_id, signal_type")
		.eq("account_id", account.id)
		.eq("signal_type", "token_expiring")
		.is("resolved_at", null)
		.limit(1);

	if (error) throw error;
	const active = ((existing ?? []) as ActiveSignalRow[])[0] ?? null;

	if (!tokenStatus.needsAction) {
		if (active) {
			const { error: updateError } = await db
				.from("account_health_signals")
				.update({ resolved_at: new Date().toISOString() })
				.eq("id", active.id);
			if (updateError) throw updateError;
		}
		return;
	}

	const payload = {
		severity: tokenStatus.severity,
		metadata: {
			username: account.username,
			days_left: tokenStatus.daysLeft,
			expires_at: tokenStatus.expiresAt,
		},
		detected_at: new Date().toISOString(),
		resolved_at: null,
	};

	if (active) {
		const { error: updateError } = await db
			.from("account_health_signals")
			.update(payload)
			.eq("id", active.id);
		if (updateError) throw updateError;
		return;
	}

	const { error: insertError } = await db
		.from("account_health_signals")
		.insert({
			account_id: account.id,
			signal_type: "token_expiring",
			...payload,
		});
	if (insertError) throw insertError;
}
