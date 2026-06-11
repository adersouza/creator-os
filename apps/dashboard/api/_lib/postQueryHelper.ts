/**
 * Applies the correct account filter for post queries based on platform.
 * Instagram posts use `instagram_account_id`, all others use `account_id`.
 */
export function postAccountFilter<
	TQuery extends { eq: (column: string, value: string) => TQuery },
>(query: TQuery, platform: string, accountId: string): TQuery {
	if (platform === "instagram") {
		return query.eq("instagram_account_id", accountId);
	}
	return query.eq("account_id", accountId);
}
