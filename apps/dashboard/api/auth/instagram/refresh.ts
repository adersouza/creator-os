/**
 * Instagram Token Refresh API Route
 *
 * Refreshes an existing Instagram access token.
 * Long-lived tokens can be refreshed within 60 days.
 */

import { createRefreshHandler } from "../../_lib/refreshHandler.js";
import { refreshTokenByLoginType } from "../../_lib/tokenRefresh.js";

export default createRefreshHandler({
	platform: "instagram",
	table: "instagram_accounts",
	tokenField: "instagram_access_token_encrypted",
	refreshFn: (currentToken, account) =>
		refreshTokenByLoginType(
			currentToken,
			(account.login_type as string) || "instagram",
		),
});
