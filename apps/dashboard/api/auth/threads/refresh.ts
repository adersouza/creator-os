/**
 * Threads Token Refresh API Route
 *
 * Refreshes an existing Threads access token.
 * Long-lived tokens can be refreshed within 60 days.
 */

import { createRefreshHandler } from "../../_lib/refreshHandler.js";
import { refreshThreadsToken } from "../../_lib/tokenRefresh.js";

export default createRefreshHandler({
	platform: "threads",
	table: "accounts",
	tokenField: "threads_access_token_encrypted",
	refreshFn: (currentToken) => refreshThreadsToken(currentToken),
});
