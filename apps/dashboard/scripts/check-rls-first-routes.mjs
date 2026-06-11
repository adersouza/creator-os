#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const migratedRoutes = [
	"api/saved-views.ts",
	"api/accounts.ts",
	"api/competitors.ts",
	"api/auth/disconnect.ts",
	"api/tags.ts",
	"api/webhooks.ts",
	"api/_lib/handlers/analytics-sub/fleet-health-accounts.ts",
	"api/_lib/handlers/analytics-sub/health-snapshots.ts",
	"api/_lib/handlers/agent/approvals.ts",
	"api/_lib/handlers/agent/content-strategy.ts",
	"api/_lib/handlers/agent/log.ts",
	"api/_lib/handlers/agent/notes.ts",
	"api/_lib/handlers/agent/settings.ts",
	"api/_lib/handlers/agent/weekly-state.ts",
	"api/_lib/handlers/ai/dismiss-recommendation.ts",
	"api/_lib/handlers/ai/feedback.ts",
	"api/_lib/handlers/beta/feedback.ts",
	"api/_lib/handlers/composer/diffs.ts",
	"api/_lib/handlers/composer/health-pills.ts",
	"api/_lib/handlers/composer/variants.ts",
	"api/_lib/handlers/composer/voice-file.ts",
	"api/_lib/handlers/crisis/status.ts",
	"api/_lib/handlers/developer/keys.ts",
	"api/_lib/handlers/instagram/auto-responders.ts",
	"api/_lib/handlers/instagram/dm-templates.ts",
	"api/_lib/handlers/listening/alerts.ts",
	"api/_lib/handlers/media/index.ts",
	"api/_lib/handlers/media-sub/share.ts",
	"api/_lib/handlers/misc/trending-config.ts",
	"api/replies.ts",
	"api/_lib/handlers/settings/user-webhooks.ts",
	"api/_lib/handlers/inbox/mark-read.ts",
	"api/_lib/handlers/inbox/rules.ts",
	"api/_lib/handlers/posts-sub/comments.ts",
	"api/_lib/handlers/posts-sub/draft-folders.ts",
	"api/_lib/handlers/posts-sub/sentiment-summary.ts",
	"api/_lib/handlers/posts-sub/signal.ts",
	"api/_lib/handlers/posts-sub/templates.ts",
	"api/_lib/handlers/threads/profile.ts",
	"api/_lib/handlers/user/annual-recap.ts",
	"api/_lib/handlers/user/branding.ts",
	"api/_lib/handlers/user/data-contribution.ts",
	"api/_lib/handlers/user/export.ts",
	"api/_lib/handlers/user/export-status.ts",
	"api/_lib/handlers/user/growth-journal.ts",
];
const violations = [];

for (const route of migratedRoutes) {
	const source = readFileSync(join(root, route), "utf8");
	if (!source.includes("withAuthDb") && !source.includes("createDbContext")) {
		violations.push(
			`${route} must use withAuthDb() or createDbContext() for RLS-first user access`,
		);
	}
	if (/getSupabase(?:Any)?\s*\(/.test(source)) {
		violations.push(
			`${route} must not call getSupabase()/getSupabaseAny() directly; use DbContext adminDb/adminDbAny for explicit privileged branches`,
		);
	}
	if (/from\s+["'](?![^"']*types\/supabase\.js)[^"']*supabase\.js["']/.test(source)) {
		violations.push(
			`${route} must not import the service-role Supabase helper directly`,
		);
	}
}

if (violations.length > 0) {
	console.error("ERROR: RLS-first migrated route boundary violation.");
	for (const violation of violations) console.error(`- ${violation}`);
	process.exit(1);
}
