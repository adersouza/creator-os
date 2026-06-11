// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * GET /api/recap/image?account_id=X&period=7d
 *
 * Generates a shareable 1080x1080 recap card image using @vercel/og.
 * Content-Type: image/png
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { verifyAnyAccountOwnership } from "../helpers/verifyOwnership.js";

const db = () => getSupabaseAny();

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const accountId = req.query.account_id as string;
	const period = (req.query.period as string) || "7d";

	if (!accountId) return apiError(res, 400, "account_id is required");

	try {
		// Auth check
		const authHeader = req.headers.authorization;
		if (!authHeader?.startsWith("Bearer "))
			return apiError(res, 401, "Unauthorized");

		const token = authHeader.slice(7);
		const {
			data: { user },
		} = await db().auth.getUser(token);
		if (!user) return apiError(res, 401, "Unauthorized");

		// #637: Verify account ownership to prevent IDOR
		const owned = await verifyAnyAccountOwnership(res, accountId, user.id);
		if (!owned) return;

		// Lazy import @vercel/og (available at runtime in Vercel, not locally)
		// @ts-expect-error — @vercel/og is provided by Vercel runtime
		const { ImageResponse } = await import("@vercel/og");

		// Fetch recap data by calling our own generate logic inline
		const periodDays = period === "30d" ? 30 : period === "all" ? 365 : 7;
		const now = new Date();
		const startDate = new Date(now.getTime() - periodDays * 86400000);

		const { data: account } = await db()
			.from("accounts")
			.select("username")
			.eq("id", accountId)
			.maybeSingle();

		const handle = account?.username || "user";

		const { data: posts } = await db()
			.from("posts")
			.select(
				"views_count, likes_count, replies_count, reposts_count, published_at",
			)
			.eq("account_id", accountId)
			.gte("published_at", startDate.toISOString())
			.not("published_at", "is", null)
			.order("published_at", { ascending: false });

		const postList = posts || [];
		let totalViews = 0;
		let totalEngagement = 0;
		const publishDates = new Set<string>();

		for (const post of postList) {
			totalViews += post.views_count || 0;
			totalEngagement +=
				(post.likes_count || 0) +
				(post.replies_count || 0) +
				(post.reposts_count || 0);
			if (post.published_at)
				publishDates.add(
					new Date(post.published_at).toISOString().slice(0, 10),
				);
		}

		// Streak
		let streak = 0;
		const sortedDates = Array.from(publishDates).sort().reverse();
		if (sortedDates.length > 0) {
			streak = 1;
			for (let i = 1; i < sortedDates.length; i++) {
				const diff =
					(new Date(sortedDates[i - 1]!).getTime() -
						new Date(sortedDates[i]!).getTime()) /
					86400000;
				if (diff <= 1.5) streak++;
				else break;
			}
		}

		const cesScore =
			totalViews > 0
				? Math.round((totalEngagement / totalViews) * 1000) / 10
				: 0;
		const formatOpts: Intl.DateTimeFormatOptions = {
			month: "short",
			day: "numeric",
		};
		const periodStr = `${startDate.toLocaleDateString("en-US", formatOpts)}-${now.toLocaleDateString("en-US", formatOpts)}, ${now.getFullYear()}`;

		// Headline
		let headline = `${postList.length} posts, ${totalEngagement} engagements — keep building`;
		if (totalViews > 10000)
			headline = `${(totalViews / 1000).toFixed(1)}K people saw your content`;
		if (streak > 5)
			headline = `${streak}-day posting streak — consistency wins`;

		// Generate image
		const image = new ImageResponse(
			{
				type: "div",
				props: {
					style: {
						width: "1080px",
						height: "1080px",
						display: "flex",
						flexDirection: "column",
						justifyContent: "space-between",
						padding: "80px",
						background:
							"linear-gradient(135deg, #09090b 0%, #18181b 50%, #09090b 100%)",
						fontFamily: "sans-serif",
						color: "#ffffff",
					},
					children: [
						{
							type: "div",
							props: {
								style: { display: "flex", flexDirection: "column", gap: "8px" },
								children: [
									{
										type: "div",
										props: {
											style: { fontSize: "36px", color: "#a1a1aa" },
											children: `@${handle}'s Growth Story`,
										},
									},
									{
										type: "div",
										props: {
											style: { fontSize: "24px", color: "#71717a" },
											children: periodStr,
										},
									},
								],
							},
						},
						{
							type: "div",
							props: {
								style: {
									display: "flex",
									flexWrap: "wrap",
									gap: "40px",
									justifyContent: "center",
								},
								children: [
									{
										type: "div",
										props: {
											style: {
												display: "flex",
												flexDirection: "column",
												alignItems: "center",
												gap: "8px",
											},
											children: [
												{
													type: "div",
													props: {
														style: { fontSize: "56px", fontWeight: "bold" },
														children:
															totalViews >= 1000
																? `${(totalViews / 1000).toFixed(1)}K`
																: String(totalViews),
													},
												},
												{
													type: "div",
													props: {
														style: { fontSize: "20px", color: "#71717a" },
														children: "views",
													},
												},
											],
										},
									},
									{
										type: "div",
										props: {
											style: {
												display: "flex",
												flexDirection: "column",
												alignItems: "center",
												gap: "8px",
											},
											children: [
												{
													type: "div",
													props: {
														style: { fontSize: "56px", fontWeight: "bold" },
														children: String(totalEngagement),
													},
												},
												{
													type: "div",
													props: {
														style: { fontSize: "20px", color: "#71717a" },
														children: "engagements",
													},
												},
											],
										},
									},
									{
										type: "div",
										props: {
											style: {
												display: "flex",
												flexDirection: "column",
												alignItems: "center",
												gap: "8px",
											},
											children: [
												{
													type: "div",
													props: {
														style: { fontSize: "56px", fontWeight: "bold" },
														children: String(cesScore),
													},
												},
												{
													type: "div",
													props: {
														style: { fontSize: "20px", color: "#71717a" },
														children: "CES",
													},
												},
											],
										},
									},
									{
										type: "div",
										props: {
											style: {
												display: "flex",
												flexDirection: "column",
												alignItems: "center",
												gap: "8px",
											},
											children: [
												{
													type: "div",
													props: {
														style: { fontSize: "56px", fontWeight: "bold" },
														children: `${streak}d`,
													},
												},
												{
													type: "div",
													props: {
														style: { fontSize: "20px", color: "#71717a" },
														children: "streak",
													},
												},
											],
										},
									},
								],
							},
						},
						{
							type: "div",
							props: {
								style: {
									fontSize: "40px",
									fontWeight: "bold",
									textAlign: "center",
									color: "#e4e4e7",
									lineHeight: "1.3",
								},
								children: `"${headline}"`,
							},
						},
						{
							type: "div",
							props: {
								style: {
									display: "flex",
									justifyContent: "flex-end",
									alignItems: "center",
									gap: "8px",
								},
								children: [
									{
										type: "div",
										props: {
											style: { fontSize: "18px", color: "#52525b" },
											children: "Powered by Juno33 — juno33.com",
										},
									},
								],
							},
						},
					],
				},
			},
			{ width: 1080, height: 1080 },
		);

		// Stream the image
		const headers = image.headers;
		for (const [key, value] of headers) {
			res.setHeader(key, value);
		}

		const body = await image.arrayBuffer();
		return res.status(200).end(Buffer.from(body));
	} catch (err) {
		logger.error("[recap/image] Failed to generate recap image", {
			error: String(err),
		});
		return apiError(res, 500, "Internal server error");
	}
}
