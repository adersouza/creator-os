/**
 * Influencer collaborations API Route.
 * Public route stays stable; collaboration handlers load lazily per request.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	return (await import("./_lib/handlers/influencer-collabs/index.js")).default(
		req,
		res,
	);
}
