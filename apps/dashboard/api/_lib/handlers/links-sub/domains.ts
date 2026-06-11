import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, badRequest } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase as _getSupabase } from "../../supabase.js";
import { getUserTier } from "../../tierGate.js";

/** Cast needed — domain_verifications + link_pages columns not yet in generated Supabase types */
// biome-ignore lint/suspicious/noExplicitAny: domain_verifications table not in generated types
const getSupabase = () => _getSupabase() as any;

/**
 * POST /api/links/domains — Custom domain management
 *
 * Actions:
 *   add     — Start verification for a custom domain
 *   verify  — Check DNS and mark verified
 *   remove  — Remove custom domain from a page
 *   status  — Get current verification status
 */
export default withAuth(async (req, res, user) => {
	if (req.method !== "POST" && req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = (
		req.method === "GET" ? req.query.action : req.body?.action
	) as string;

	try {
		switch (action) {
			case "add":
				return await addDomain(req, res, user.id);
			case "verify":
				return await verifyDomain(req, res, user.id);
			case "remove":
				return await removeDomain(req, res, user.id);
			case "status":
				return await domainStatus(req, res, user.id);
			default:
				return badRequest(res, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Domain API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});

// ── Helpers ──────────────────────────────────────────────────────────────────

function sanitizeDomain(raw: string): string | null {
	const d = raw
		.toLowerCase()
		.trim()
		.replace(/^https?:\/\//, "")
		.replace(/\/+$/, "");
	// Basic domain validation
	if (
		!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(d)
	) {
		return null;
	}
	// Block common reserved domains
	if (d.endsWith(".juno33.com") || d === "juno33.com") return null;
	return d;
}

const PAID_TIERS = ["pro", "agency", "empire"];
type DomainTargetType = "link_page" | "smart_link";

function getTargetType(req: VercelRequest): DomainTargetType | null {
	const raw = req.body?.targetType || req.query.targetType || "link_page";
	const normalized = String(Array.isArray(raw) ? raw[0] : raw).trim();
	if (
		normalized === "smart_link" ||
		normalized === "smart-link" ||
		normalized === "smartLink"
	) {
		return "smart_link";
	}
	if (
		normalized === "link_page" ||
		normalized === "link-page" ||
		normalized === "linkPage" ||
		normalized === "page"
	) {
		return "link_page";
	}
	return null;
}

function getTargetId(req: VercelRequest, targetType: DomainTargetType): string {
	return targetType === "smart_link"
		? ((req.body?.smartLinkId || req.query.smartLinkId) as string)
		: ((req.body?.pageId || req.query.pageId) as string);
}

async function resolveDomainTarget(
	supabase: ReturnType<typeof getSupabase>,
	targetType: DomainTargetType,
	targetId: string,
	userId: string,
) {
	if (targetType === "smart_link") {
		const { data } = await supabase
			.from("smart_links")
			.select("id, code, custom_domain, domain_verified")
			.eq("id", targetId)
			.eq("user_id", userId)
			.maybeSingle();
		return data ? { table: "smart_links", row: data } : null;
	}
	const { data } = await supabase
		.from("link_pages")
		.select("id, slug, custom_domain, domain_verified")
		.eq("id", targetId)
		.eq("user_id", userId)
		.maybeSingle();
	return data ? { table: "link_pages", row: data } : null;
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function addDomain(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { domain: rawDomain } = req.body || {};
	const targetType = getTargetType(req);
	if (!targetType) {
		return badRequest(res, "targetType must be link_page or smart_link");
	}
	const targetId = getTargetId(req, targetType);
	if (!targetId || !rawDomain) {
		return badRequest(
			res,
			targetType === "smart_link"
				? "smartLinkId and domain required"
				: "pageId and domain required",
		);
	}

	const domain = sanitizeDomain(rawDomain);
	if (!domain) return badRequest(res, "Invalid domain format");

	// Tier check — custom domains require Pro+
	const tier = await getUserTier(userId);
	if (!PAID_TIERS.includes(tier)) {
		return apiError(res, 403, "Custom domains require a Pro plan or higher");
	}

	const supabase = getSupabase();

	const target = await resolveDomainTarget(
		supabase,
		targetType,
		targetId,
		userId,
	);
	if (!target) {
		return apiError(
			res,
			404,
			targetType === "smart_link" ? "Smart link not found" : "Page not found",
		);
	}

	// Check domain not already in use by another link page or smart link.
	const [{ data: existingPage }, { data: existingSmartLink }] =
		await Promise.all([
			supabase
				.from("link_pages")
				.select("id")
				.eq("custom_domain", domain)
				.maybeSingle(),
			supabase
				.from("smart_links")
				.select("id")
				.eq("custom_domain", domain)
				.maybeSingle(),
		]);
	if (
		(existingPage &&
			(targetType !== "link_page" || existingPage.id !== targetId)) ||
		(existingSmartLink &&
			(targetType !== "smart_link" || existingSmartLink.id !== targetId))
	) {
		return apiError(res, 409, "Domain already in use");
	}
	// Check domain not already being verified by another user
	const { data: existingVerification } = await supabase
		.from("domain_verifications")
		.select("id, user_id")
		.eq("domain", domain)
		.maybeSingle();
	if (existingVerification && existingVerification.user_id !== userId) {
		return apiError(res, 409, "Domain already claimed by another user");
	}

	// Generate verification token
	const token = `juno33-verify-${crypto.randomBytes(16).toString("hex")}`;

	// Upsert verification record
	const { data: verification, error } = await supabase
		.from("domain_verifications")
		.upsert(
			{
				user_id: userId,
				page_id: targetType === "link_page" ? targetId : null,
				smart_link_id: targetType === "smart_link" ? targetId : null,
				domain,
				verification_token: token,
				cname_target: "cname.juno33.com",
				status: "pending",
				last_checked_at: null,
				verified_at: null,
				created_at: new Date().toISOString(),
				expires_at: new Date(
					Date.now() + 7 * 24 * 60 * 60 * 1000,
				).toISOString(),
			},
			{ onConflict: "domain" },
		)
		.select()
		.maybeSingle();

	if (error) {
		return apiError(res, 500, "Failed to create verification", {
			details: error.message,
		});
	}

	return apiSuccess(res, {
		verification: {
			id: verification.id,
			domain,
			status: "pending",
			dnsRecords: [
				{
					type: "CNAME",
					name: domain,
					value: "cname.juno33.com",
					purpose: "Route traffic to Juno33",
				},
				{
					type: "TXT",
					name: `_juno33.${domain}`,
					value: token,
					purpose: "Verify domain ownership",
				},
			],
			expiresAt: verification.expires_at,
		},
	});
}

async function verifyDomain(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { domain: rawDomain } = _req.body || {};
	if (!rawDomain) return badRequest(res, "domain required");

	const domain = sanitizeDomain(rawDomain);
	if (!domain) return badRequest(res, "Invalid domain format");

	const supabase = getSupabase();

	// Fetch verification record
	const { data: verification } = await supabase
		.from("domain_verifications")
		.select("*")
		.eq("domain", domain)
		.eq("user_id", userId)
		.maybeSingle();

	if (!verification)
		return apiError(res, 404, "No verification found for this domain");

	if (verification.status === "verified") {
		return apiSuccess(res, {
			status: "verified",
			message: "Domain already verified",
		});
	}

	// Check expiry
	if (new Date(verification.expires_at) < new Date()) {
		await supabase
			.from("domain_verifications")
			.update({ status: "expired" })
			.eq("id", verification.id);
		return apiError(res, 410, "Verification expired. Please start again.");
	}

	// DNS lookup — check TXT record for verification token
	let txtVerified = false;
	let cnameVerified = false;

	try {
		const { resolveTxt, resolveCname } = await import("node:dns/promises");

		// Check TXT record: _juno33.domain.com
		try {
			const txtRecords = await resolveTxt(`_juno33.${domain}`);
			const flat = txtRecords.flat();
			txtVerified = flat.some((r) => r === verification.verification_token);
		} catch {
			// DNS lookup failed — TXT not set yet
		}

		// Check CNAME record: domain.com → cname.juno33.com
		try {
			const cnameRecords = await resolveCname(domain);
			cnameVerified = cnameRecords.some(
				(r) => r === "cname.juno33.com" || r === "cname.juno33.com.",
			);
		} catch {
			// CNAME not set yet
		}
	} catch (dnsError) {
		logger.error("DNS resolution error", { domain, error: String(dnsError) });
	}

	// Update last_checked_at
	await supabase
		.from("domain_verifications")
		.update({ last_checked_at: new Date().toISOString() })
		.eq("id", verification.id);

	if (txtVerified && cnameVerified) {
		// Mark verified
		const now = new Date().toISOString();
		await supabase
			.from("domain_verifications")
			.update({ status: "verified", verified_at: now })
			.eq("id", verification.id);

		const targetTable = verification.smart_link_id
			? "smart_links"
			: "link_pages";
		const targetId = verification.smart_link_id || verification.page_id;
		await supabase
			.from(targetTable)
			.update({
				custom_domain: domain,
				domain_verified: true,
				domain_verified_at: now,
			})
			.eq("id", targetId)
			.eq("user_id", userId);

		return apiSuccess(res, {
			status: "verified",
			message: "Domain verified and connected",
		});
	}

	return apiSuccess(res, {
		status: "pending",
		checks: {
			txt: txtVerified,
			cname: cnameVerified,
		},
		message:
			txtVerified && !cnameVerified
				? "TXT verified. Waiting for CNAME record."
				: !txtVerified && cnameVerified
					? "CNAME verified. Waiting for TXT record."
					: "Waiting for both DNS records to propagate.",
	});
}

async function removeDomain(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const targetType = getTargetType(req);
	if (!targetType) {
		return badRequest(res, "targetType must be link_page or smart_link");
	}
	const targetId = getTargetId(req, targetType);
	if (!targetId) {
		return badRequest(
			res,
			targetType === "smart_link" ? "smartLinkId required" : "pageId required",
		);
	}

	const supabase = getSupabase();

	// Verify ownership and get current domain
	const target = await resolveDomainTarget(
		supabase,
		targetType,
		targetId,
		userId,
	);
	if (!target) {
		return apiError(
			res,
			404,
			targetType === "smart_link" ? "Smart link not found" : "Page not found",
		);
	}
	const currentDomain = target.row.custom_domain;

	if (currentDomain) {
		// Remove verification record
		const { error: verificationDeleteError } = await supabase
			.from("domain_verifications")
			.delete()
			.eq("domain", currentDomain)
			.eq("user_id", userId);
		if (verificationDeleteError) {
			logger.error("Failed to remove domain verification", {
				targetType,
				targetId,
				domain: currentDomain,
				error: String(verificationDeleteError),
			});
			return apiError(res, 500, "Failed to remove custom domain");
		}
	}
	const { error: pendingDeleteError } = await supabase
		.from("domain_verifications")
		.delete()
		.eq(targetType === "smart_link" ? "smart_link_id" : "page_id", targetId)
		.eq("user_id", userId);
	if (pendingDeleteError) {
		logger.error("Failed to remove pending domain verification", {
			targetType,
			targetId,
			error: String(pendingDeleteError),
		});
		return apiError(res, 500, "Failed to remove custom domain");
	}

	// Clear domain from page
	const { error: pageUpdateError } = await supabase
		.from(target.table)
		.update({
			custom_domain: null,
			domain_verified: false,
			domain_verified_at: null,
		})
		.eq("id", targetId)
		.eq("user_id", userId);
	if (pageUpdateError) {
		logger.error("Failed to clear custom domain from page", {
			targetType,
			targetId,
			error: String(pageUpdateError),
		});
		return apiError(res, 500, "Failed to remove custom domain");
	}

	return apiSuccess(res, { removed: true });
}

async function domainStatus(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const targetType = getTargetType(req);
	if (!targetType) {
		return badRequest(res, "targetType must be link_page or smart_link");
	}
	const targetId = getTargetId(req, targetType);
	if (!targetId) {
		return badRequest(
			res,
			targetType === "smart_link" ? "smartLinkId required" : "pageId required",
		);
	}

	const supabase = getSupabase();

	const target = await resolveDomainTarget(
		supabase,
		targetType,
		targetId,
		userId,
	);
	if (!target) {
		return apiError(
			res,
			404,
			targetType === "smart_link" ? "Smart link not found" : "Page not found",
		);
	}

	// If page has a verified domain
	if (target.row.custom_domain && target.row.domain_verified) {
		return apiSuccess(res, {
			domain: target.row.custom_domain,
			status: "verified",
		});
	}

	// Check for pending verification
	const { data: verification } = await supabase
		.from("domain_verifications")
		.select("*")
		.eq(targetType === "smart_link" ? "smart_link_id" : "page_id", targetId)
		.eq("user_id", userId)
		.order("created_at", { ascending: false })
		.limit(1)
		.maybeSingle();

	if (!verification) {
		return apiSuccess(res, { domain: null, status: "none" });
	}

	return apiSuccess(res, {
		domain: verification.domain,
		status: verification.status,
		dnsRecords: [
			{
				type: "CNAME",
				name: verification.domain,
				value: "cname.juno33.com",
			},
			{
				type: "TXT",
				name: `_juno33.${verification.domain}`,
				value: verification.verification_token,
			},
		],
		lastChecked: verification.last_checked_at,
		expiresAt: verification.expires_at,
	});
}
