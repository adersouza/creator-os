/**
 * OAuth scope drift verification.
 *
 * Long-lived Meta tokens keep their original grant set across refreshes. A
 * refresh can succeed while still missing scopes added after the user first
 * connected, so refresh paths call these helpers once per token rotation.
 */

export const EXPECTED_THREADS_SCOPES = [
	"threads_basic",
	"threads_content_publish",
	"threads_manage_replies",
	"threads_manage_insights",
	"threads_keyword_search",
	"threads_share_to_instagram",
] as const;

export const EXPECTED_IG_SCOPES = [
	"instagram_business_basic",
	"instagram_business_content_publish",
	"instagram_business_manage_messages",
	"instagram_business_manage_comments",
	"instagram_business_manage_insights",
] as const;

export const EXPECTED_FACEBOOK_IG_SCOPES = [
	"pages_show_list",
	"pages_read_engagement",
	"instagram_basic",
	"instagram_content_publish",
	"instagram_manage_contents",
	"instagram_manage_comments",
	"instagram_manage_engagement",
	"instagram_manage_insights",
] as const;

type Logger = {
	info: (message: string, context?: Record<string, unknown>) => void;
	warn: (message: string, context?: Record<string, unknown>) => void;
};

type SupabaseLike = {
	// biome-ignore lint/suspicious/noExplicitAny: shared helper accepts typed and untyped Supabase clients
	from: (table: string) => any;
};

type ScopeVerifyResult = {
	ok: boolean;
	missing: string[];
};

type PermissionEntry = {
	permission?: string | undefined;
	scope?: string | undefined;
	name?: string | undefined;
	status?: string | undefined;
};

type DebugTokenResponse = {
	data?: {
        		scopes?: string[] | undefined;
        	} | undefined;
	error?: {
        		message?: string | undefined;
        	} | undefined;
};

type PermissionsResponse = {
	data?: PermissionEntry[] | undefined;
	error?: {
        		message?: string | undefined;
        	} | undefined;
};

function grantedScopesFromPermissions(data: PermissionsResponse): string[] {
	return (data.data || [])
		.filter((entry) => !entry.status || entry.status === "granted")
		.map((entry) => entry.permission || entry.scope || entry.name)
		.filter((scope): scope is string => Boolean(scope));
}

function missingScopes(expected: readonly string[], granted: string[]): string[] {
	const grantedSet = new Set(granted);
	return expected.filter((scope) => !grantedSet.has(scope));
}

async function markScopeDrift(
	db: SupabaseLike,
	table: "accounts" | "instagram_accounts",
	accountId: string,
	platform: "threads" | "instagram",
	missing: string[],
	logger: Logger,
): Promise<void> {
	const { data: account, error: accountErr } = await db
		.from(table)
		.select("id, user_id, username")
		.eq("id", accountId)
		.maybeSingle();

	if (accountErr || !account?.user_id) {
		logger.warn("[oauth-scope] Scope drift detected but account lookup failed", {
			accountId,
			table,
			error: accountErr?.message,
		});
		return;
	}

	const now = new Date().toISOString();
	const { error: updateErr } = await db
		.from(table)
		.update({
			needs_reauth: true,
			scope_drift_detected_at: now,
			updated_at: now,
		})
		.eq("id", accountId);

	if (updateErr) {
		logger.warn("[oauth-scope] Failed to mark scope drift", {
			accountId,
			table,
			error: updateErr.message,
		});
		return;
	}

	const platformLabel = platform === "threads" ? "Threads" : "Instagram";
	const username = account.username ? ` @${account.username}` : "";
	const { error: notifErr } = await db.from("notifications").upsert(
		{
			user_id: account.user_id,
			type: "scope_drift",
			title: `${platformLabel} account needs reconnection`,
			body: `Your ${platformLabel} account${username} is missing newly required permissions. Reconnect it to restore publishing and cross-platform sharing.`,
			data: {
				account_id: accountId,
				platform,
				missing_scopes: missing,
				detected_at: now,
			},
			is_read: false,
			created_at: now,
		},
		{
			onConflict: "user_id,type,(data->>account_id)",
			ignoreDuplicates: true,
		},
	);

	if (notifErr) {
		logger.warn("[oauth-scope] Failed to create scope drift notification", {
			accountId,
			error: notifErr.message,
		});
	}
}

export async function verifyThreadsScopes(
	plaintextToken: string,
	accountId: string,
	db: SupabaseLike,
	logger: Logger,
): Promise<ScopeVerifyResult> {
	try {
		const response = await fetch(
			`https://graph.threads.net/me/permissions?access_token=${encodeURIComponent(plaintextToken)}`,
			{ signal: AbortSignal.timeout(10000) },
		);
		const data = (await response.json()) as PermissionsResponse;

		if (!response.ok || data.error) {
			logger.warn("[oauth-scope] Threads permissions check failed open", {
				accountId,
				status: response.status,
				error: data.error?.message,
			});
			return { ok: true, missing: [] };
		}

		const missing = missingScopes(
			EXPECTED_THREADS_SCOPES,
			grantedScopesFromPermissions(data),
		);
		if (missing.length > 0) {
			await markScopeDrift(db, "accounts", accountId, "threads", missing, logger);
		}

		return { ok: missing.length === 0, missing };
	} catch (error) {
		logger.warn("[oauth-scope] Threads permissions check failed open", {
			accountId,
			error: String(error),
		});
		return { ok: true, missing: [] };
	}
}

export async function verifyInstagramScopes(
	plaintextToken: string,
	accountId: string,
	loginType: string | null | undefined,
	db: SupabaseLike,
	logger: Logger,
): Promise<ScopeVerifyResult> {
	try {
		let grantedScopes: string[];
		if (loginType === "facebook") {
			const appId = process.env.FACEBOOK_APP_ID;
			const appSecret = process.env.FACEBOOK_APP_SECRET;
			if (!appId || !appSecret) {
				logger.warn("[oauth-scope] Facebook debug_token skipped", {
					accountId,
					reason: "missing_app_credentials",
				});
				return { ok: true, missing: [] };
			}

			const params = new URLSearchParams({
				input_token: plaintextToken,
				access_token: `${appId}|${appSecret}`,
			});
			const response = await fetch(
				`https://graph.facebook.com/v25.0/debug_token?${params}`,
				{ signal: AbortSignal.timeout(10000) },
			);
			const data = (await response.json()) as DebugTokenResponse;
			if (!response.ok || data.error) {
				logger.warn("[oauth-scope] Facebook debug_token failed open", {
					accountId,
					status: response.status,
					error: data.error?.message,
				});
				return { ok: true, missing: [] };
			}
			grantedScopes = data.data?.scopes || [];
		} else {
			const response = await fetch(
				`https://graph.instagram.com/me/permissions?access_token=${encodeURIComponent(plaintextToken)}`,
				{ signal: AbortSignal.timeout(10000) },
			);
			const data = (await response.json()) as PermissionsResponse;
			if (!response.ok || data.error) {
				logger.warn("[oauth-scope] Instagram permissions check failed open", {
					accountId,
					status: response.status,
					error: data.error?.message,
				});
				return { ok: true, missing: [] };
			}
			grantedScopes = grantedScopesFromPermissions(data);
		}

		const expectedScopes =
			loginType === "facebook" ? EXPECTED_FACEBOOK_IG_SCOPES : EXPECTED_IG_SCOPES;
		const missing = missingScopes(expectedScopes, grantedScopes);
		if (missing.length > 0) {
			await markScopeDrift(
				db,
				"instagram_accounts",
				accountId,
				"instagram",
				missing,
				logger,
			);
		}

		return { ok: missing.length === 0, missing };
	} catch (error) {
		logger.warn("[oauth-scope] Instagram scope check failed open", {
			accountId,
			loginType,
			error: String(error),
		});
		return { ok: true, missing: [] };
	}
}
