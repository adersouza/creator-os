import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 60,
};

const JOB_NAME = "inbox-suggestions";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { runInboxSuggestionsCron } = await import(
		"../_lib/cron/inbox-suggestions.js"
	);
	const { getSupabaseAny } = await import("../_lib/supabase.js");

	const db = getSupabaseAny();
	const lockResult = await withCronLock(
		db,
		JOB_NAME,
		() => trackCronRun(db, JOB_NAME, () => runInboxSuggestionsCron(db)),
		65,
	);

	if (!("result" in lockResult)) return res.status(200).json({ skipped: true });
	return res.status(200).json({ ok: true, ...lockResult.result });
}
