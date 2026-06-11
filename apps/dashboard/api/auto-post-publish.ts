/**
 * QStash Delayed Publish Endpoint
 *
 * Called by QStash at the exact scheduled_for time to publish a single post.
 * Auth and publish behavior live in the lazy handler so this route stays thin.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	return (await import("./_lib/handlers/auto-post-publish/publish.js")).default(
		req,
		res,
	);
}
