/**
 * Bio Audit — scan all account bios and flag missing/incorrect CTAs
 *
 * GET /api/accounts?action=bio-audit&groupId=xxx
 *
 * Returns per-account bio status with match against expected templates.
 * Templates are stored per-group in account_groups.bio_template (JSONB).
 * If no template set, reports raw bio text for manual review.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";

const db = getSupabase;

interface BioStatus {
	id: string;
	platform: "threads" | "instagram";
	username: string;
	bio: string | null;
	status: "ok" | "missing" | "no_cta" | "wrong_cta";
	detail?: string | undefined;
	groupId?: string | undefined;
	groupName?: string | undefined;
}

export default async function handler(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string },
) {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const groupId = req.query.groupId as string | undefined;
	const platform = req.query.platform as string | undefined;

	// Load bio templates from account_groups
	const templateQuery = db()
		.from("account_groups")
		.select("id, name, bio_template")
		.eq("user_id", user.id);
	if (groupId) templateQuery.eq("id", groupId);

	// biome-ignore lint/suspicious/noExplicitAny: bio_template not in generated types
	const { data: groups } = await (templateQuery as any);
	const templateMap = new Map<string, { name: string; patterns: string[] }>();
	for (const g of groups || []) {
		const tmpl = g.bio_template as { required_patterns?: string[] | undefined } | null;
		templateMap.set(g.id, {
			name: g.name || g.id,
			patterns: tmpl?.required_patterns || [],
		});
	}

	const results: BioStatus[] = [];

	// Threads accounts
	if (!platform || platform === "threads") {
		let threadsQuery = db()
			.from("accounts")
			.select("id, username, bio, group_id")
			.eq("user_id", user.id)
			.not("threads_user_id", "is", null);
		if (groupId) {
			threadsQuery = threadsQuery.eq("group_id", groupId);
		}
		const { data: threads } = await threadsQuery;

		for (const a of threads || []) {
			const tmpl = a.group_id ? templateMap.get(a.group_id) : undefined;
			results.push(
				auditBio(a.id, "threads", a.username, a.bio, a.group_id, tmpl),
			);
		}
	}

	// Instagram accounts
	if (!platform || platform === "instagram") {
		// biome-ignore lint/suspicious/noExplicitAny: bio column just added, not in generated types
		let igQuery = (db() as any)
			.from("instagram_accounts")
			.select("id, username, bio, group_id")
			.eq("user_id", user.id);
		if (groupId) {
			igQuery = igQuery.eq("group_id", groupId);
		}
		const { data: ig } = await igQuery;

		for (const a of ig || []) {
			const tmpl = a.group_id ? templateMap.get(a.group_id) : undefined;
			results.push(
				auditBio(a.id, "instagram", a.username, a.bio, a.group_id, tmpl),
			);
		}
	}

	// Summary stats
	const summary = {
		total: results.length,
		ok: results.filter((r) => r.status === "ok").length,
		missing: results.filter((r) => r.status === "missing").length,
		no_cta: results.filter((r) => r.status === "no_cta").length,
		wrong_cta: results.filter((r) => r.status === "wrong_cta").length,
	};

	return apiSuccess(res, {
		summary,
		accounts: results,
	});
}

function auditBio(
	id: string,
	platform: "threads" | "instagram",
	username: string,
	bio: string | null,
	groupId: string | null,
	template?: { name: string; patterns: string[] },
): BioStatus {
	const base: BioStatus = {
		id,
		platform,
		username,
		bio,
		status: "ok",
		groupId: groupId || undefined,
		groupName: template?.name,
	};

	if (!bio || bio.trim().length === 0) {
		return { ...base, status: "missing", detail: "Bio is empty" };
	}

	// If group has required patterns, check against them
	if (template?.patterns && template.patterns.length > 0) {
		const bioLower = bio.toLowerCase();
		const missing = template.patterns.filter((p) => {
			try {
				return !new RegExp(p, "i").test(bioLower);
			} catch {
				return !bioLower.includes(p.toLowerCase());
			}
		});

		if (missing.length > 0) {
			return {
				...base,
				status: "wrong_cta",
				detail: `Missing required patterns: ${missing.join(", ")}`,
			};
		}
		return base;
	}

	// No template — use platform defaults
	if (platform === "threads") {
		// Threads bios should reference snap
		const hasSnap = /snap|sc:|sc /i.test(bio);
		if (!hasSnap) {
			return {
				...base,
				status: "no_cta",
				detail: "No Snapchat reference in bio",
			};
		}
	} else {
		// IG bios should reference link.me or similar
		const hasLink = /link\.me|linktr\.ee|linkin\.bio|juno33\.com/i.test(bio);
		if (!hasLink) {
			return { ...base, status: "no_cta", detail: "No link-in-bio reference" };
		}
	}

	return base;
}
