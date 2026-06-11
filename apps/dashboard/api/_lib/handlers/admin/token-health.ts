// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAdminRole } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

interface TokenCheckResult {
	username: string;
	group: string;
	token_status:
		| "valid"
		| "expired"
		| "suspended"
		| "no_token"
		| "decrypt_error"
		| "error";
	error_detail?: string | undefined;
	total_views_7d: number;
	needs_reauth: boolean;
	is_shadowbanned: boolean;
	is_retired: boolean;
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase types don't include is_shadowbanned/is_retired columns
type AccountRow = Record<string, any>;

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, _user) => {
		if (req.method !== "GET" && req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const db = getSupabase;
		const sendDiscord = req.query.discord !== "false";

		try {
			// 1. Fetch all Threads accounts with group names
			// is_shadowbanned and is_retired exist in DB but not in generated Supabase types
			const { data: rawAccounts, error: accErr } = await (
				db() as ReturnType<typeof getSupabase>
			)
				.from("accounts")
				.select(
					"id, user_id, username, threads_user_id, threads_access_token_encrypted, group_id, needs_reauth, status",
				)
				.order("username", { ascending: true });

			if (accErr) return serverError(res, accErr.message);
			if (!rawAccounts || rawAccounts.length === 0) {
				return apiSuccess(res, { results: [], summary: "No accounts found" });
			}

			// Fetch shadowban + retired flags separately (not in generated types)
			const accountIds = rawAccounts.map((a) => a.id) as string[];
			const { data: flagRows } = await (
				db() as ReturnType<typeof getSupabase>
			).rpc(
				"execute_sql" as never,
				{
					query: `SELECT id, is_shadowbanned, is_retired FROM accounts WHERE id = ANY($1)`,
					params: [accountIds],
				} as never,
			);

			// Build flag map from RPC result, falling back to empty if RPC not available
			const flagMap = new Map<
				string,
				{ is_shadowbanned: boolean; is_retired: boolean }
			>();
			if (Array.isArray(flagRows)) {
				for (const row of flagRows as AccountRow[]) {
					flagMap.set(row.id, {
						is_shadowbanned: !!row.is_shadowbanned,
						is_retired: !!row.is_retired,
					});
				}
			}

			const accounts: AccountRow[] = rawAccounts.map((a) => ({
				...a,
				is_shadowbanned: flagMap.get(a.id)?.is_shadowbanned ?? false,
				is_retired: flagMap.get(a.id)?.is_retired ?? false,
			}));

			// Fetch group names
			const groupIds = [
				...new Set(accounts.map((a) => a.group_id).filter(Boolean)),
			] as string[];
			const groupMap = new Map<string, string>();
			if (groupIds.length > 0) {
				const { data: groups } = await db()
					.from("account_groups")
					.select("id, name")
					.in("id", groupIds);
				for (const g of groups || []) {
					groupMap.set(g.id, g.name);
				}
			}

			// 2. Fetch 7-day views per account (batch query)
			const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
				.toISOString()
				.split("T")[0]!;
			const { data: analyticsRows } = await db()
				.from("account_analytics")
				.select("account_id, total_views")
				.in("account_id", accountIds)
				.gte("date", sevenDaysAgo);

			const viewsMap = new Map<string, number>();
			for (const row of analyticsRows || []) {
				const current = viewsMap.get(row.account_id) || 0;
				viewsMap.set(row.account_id, current + (row.total_views ?? 0));
			}

			// 3. Decrypt tokens and test each account (concurrency-limited)
			const { decrypt } = await import("../../encryption.js");

			const results: TokenCheckResult[] = [];
			const CONCURRENCY = 5;

			for (let i = 0; i < accounts.length; i += CONCURRENCY) {
				const batch = accounts.slice(i, i + CONCURRENCY);
				const batchResults = await Promise.allSettled(
					batch.map(async (account: AccountRow) => {
						const username = (account.username as string) || "unknown";
						const groupName = account.group_id
							? groupMap.get(account.group_id as string) || "ungrouped"
							: "ungrouped";
						const views7d = viewsMap.get(account.id as string) || 0;

						const base: TokenCheckResult = {
							username,
							group: groupName,
							token_status: "no_token",
							total_views_7d: views7d,
							needs_reauth: !!account.needs_reauth,
							is_shadowbanned: !!account.is_shadowbanned,
							is_retired: !!account.is_retired,
						};

						if (
							!account.threads_access_token_encrypted ||
							!account.threads_user_id
						) {
							return base;
						}

						// Decrypt token
						let token: string;
						try {
							token = decrypt(account.threads_access_token_encrypted as string);
						} catch (err) {
							return {
								...base,
								token_status: "decrypt_error" as const,
								error_detail: err instanceof Error ? err.message : String(err),
							};
						}

						// Lightweight profile fetch
						try {
							const url = `https://graph.threads.net/v1.0/${account.threads_user_id}?fields=id,username`;
							const response = await fetch(url, {
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(10000),
							});
							const data = await response.json();

							if (response.ok && !data.error) {
								return { ...base, token_status: "valid" as const };
							}

							const errorCode = data.error?.code;
							const errorMsg = data.error?.message || "Unknown error";

							if (errorCode === 190) {
								return {
									...base,
									token_status: "expired" as const,
									error_detail: errorMsg,
								};
							}

							if (
								errorCode === 100 ||
								errorCode === 10 ||
								errorMsg.toLowerCase().includes("suspended") ||
								errorMsg.toLowerCase().includes("not found")
							) {
								return {
									...base,
									token_status: "suspended" as const,
									error_detail: errorMsg,
								};
							}

							return {
								...base,
								token_status: "error" as const,
								error_detail: `Code ${errorCode}: ${errorMsg}`,
							};
						} catch (err) {
							return {
								...base,
								token_status: "error" as const,
								error_detail: err instanceof Error ? err.message : String(err),
							};
						}
					}),
				);

				for (const r of batchResults) {
					if (r.status === "fulfilled") {
						results.push(r.value);
					}
				}
			}

			// 4. Build summary
			const valid = results.filter((r) => r.token_status === "valid").length;
			const expired = results.filter(
				(r) => r.token_status === "expired",
			).length;
			const suspended = results.filter(
				(r) => r.token_status === "suspended",
			).length;
			const errors = results.filter(
				(r) => r.token_status === "error" || r.token_status === "decrypt_error",
			).length;
			const noToken = results.filter(
				(r) => r.token_status === "no_token",
			).length;
			const shadowbanned = results.filter((r) => r.is_shadowbanned).length;

			const summary = {
				total: results.length,
				valid,
				expired,
				suspended,
				errors,
				noToken,
				shadowbanned,
			};

			// 5. Send to Discord
			if (sendDiscord) {
				const webhookUrl = process.env.DISCORD_ALERT_WEBHOOK_URL;
				if (webhookUrl) {
					try {
						// Build ASCII table for Discord
						const lines: string[] = [];
						lines.push("```");
						lines.push(
							`${"Username".padEnd(22)} ${"Group".padEnd(18)} ${"Token".padEnd(14)} ${"Views 7d".padStart(10)} Flags`,
						);
						lines.push("-".repeat(80));

						for (const r of results) {
							const flags: string[] = [];
							if (r.is_shadowbanned) flags.push("SB");
							if (r.needs_reauth) flags.push("RA");
							if (r.is_retired) flags.push("RET");

							const statusLabel =
								r.token_status === "valid"
									? "OK"
									: r.token_status === "expired"
										? "EXPIRED"
										: r.token_status === "suspended"
											? "SUSPENDED"
											: r.token_status === "no_token"
												? "NO TOKEN"
												: r.token_status === "decrypt_error"
													? "DECRYPT ERR"
													: "ERROR";

							lines.push(
								`@${r.username.padEnd(21)} ${r.group.substring(0, 17).padEnd(18)} ${statusLabel.padEnd(14)} ${r.total_views_7d.toLocaleString().padStart(10)} ${flags.join(",") || "-"}`,
							);
						}
						lines.push("```");
						lines.push(
							`**Summary:** ${valid} valid, ${expired} expired, ${suspended} suspended, ${errors} errors, ${shadowbanned} shadowbanned`,
						);

						// Discord embed has 4096 char limit for description — split if needed
						const tableText = lines.join("\n");
						const chunks: string[] = [];
						if (tableText.length > 4000) {
							// Send as content (2000 char limit per message) in chunks
							for (let c = 0; c < tableText.length; c += 1900) {
								chunks.push(tableText.substring(c, c + 1900));
							}
						}

						if (chunks.length > 0) {
							for (const chunk of chunks) {
								await fetch(webhookUrl, {
									method: "POST",
									headers: { "Content-Type": "application/json" },
									body: JSON.stringify({ content: chunk }),
									signal: AbortSignal.timeout(5000),
								});
							}
						} else {
							const color = expired + suspended > 0 ? 0xe74c3c : 0x2ecc71;
							await fetch(webhookUrl, {
								method: "POST",
								headers: { "Content-Type": "application/json" },
								body: JSON.stringify({
									embeds: [
										{
											title: `Token Health Check — ${results.length} accounts`,
											description: tableText,
											color,
											timestamp: new Date().toISOString(),
											footer: { text: "Juno33 Token Health" },
										},
									],
								}),
								signal: AbortSignal.timeout(5000),
							});
						}

						logger.info("Token health report sent to Discord", {
							total: results.length,
						});
					} catch (discordErr) {
						logger.error("Failed to send token health to Discord", {
							error:
								discordErr instanceof Error
									? discordErr.message
									: String(discordErr),
						});
					}
				}
			}

			// 6. Flag accounts that need attention
			const accountsToFlag = results.filter(
				(r) => r.token_status === "expired" || r.token_status === "suspended",
			);
			if (accountsToFlag.length > 0) {
				for (const flagged of accountsToFlag) {
					const acc = accounts.find(
						(a: AccountRow) => a.username === flagged.username,
					);
					if (acc && !acc.needs_reauth) {
						await db()
							.from("accounts")
							.update({
								needs_reauth: true,
								status:
									flagged.token_status === "suspended"
										? "suspended"
										: "needs_reauth",
							})
							.eq("id", acc.id);
					}
				}
				logger.warn("Flagged accounts for reauth", {
					count: accountsToFlag.length,
					usernames: accountsToFlag.map((a) => a.username),
				});
			}

			return apiSuccess(res, { results, summary, scope: "platform" });
		} catch (err) {
			logger.error("Token health check failed", {
				error: err instanceof Error ? err.message : String(err),
			});
			return serverError(res, err instanceof Error ? err.message : String(err));
		}
	},
);
