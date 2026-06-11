// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Post-level recommendation checks (checks 1-10).
 * These analyze recent posts to surface quick wins around timing,
 * content format, engagement patterns, and posting consistency.
 */

import { logger } from "../logger.js";
import type { BestHourEntry, LhfPost, Recommendation } from "./shared.js";
import { db, dbAny, getConfidence } from "./shared.js";

// ── Check 1: Best times ──────────────────────────────────────────────────────

export async function checkBestTimes(
	posts: LhfPost[],
	accountId: string,
	_platform: string,
	recs: Recommendation[],
	sampleSize: number,
) {
	try {
		// Try to get best hours from trend_forecasts or account_analytics first
		let bestHours: Set<number> | null = null;
		let bestHourStr = "";

		try {
			const forecastFreshAfter = new Date(
				Date.now() - 30 * 24 * 60 * 60 * 1000,
			).toISOString();
			const { data: forecast } = await db()
				.from("trend_forecasts")
				.select("best_hours, created_at")
				.eq("account_id", accountId)
				.gte("created_at", forecastFreshAfter)
				.order("created_at", { ascending: false })
				.limit(1)
				.maybeSingle();

			if (
				forecast?.best_hours &&
				Array.isArray(forecast.best_hours) &&
				forecast.best_hours.length >= 3
			) {
				// best_hours from trendEngine: array of {dow, hour, avgEngagement}
				const bestHoursArr = forecast.best_hours as BestHourEntry[];
				const topHours = [...bestHoursArr]
					.sort(
						(a: BestHourEntry, b: BestHourEntry) =>
							(b.avgEngagement || 0) - (a.avgEngagement || 0),
					)
					.slice(0, 3);
				const uniqueHours: number[] = [
					...new Set<number>(topHours.map((h: BestHourEntry) => h.hour)),
				];
				if (uniqueHours.length >= 2) {
					bestHours = new Set<number>(uniqueHours.slice(0, 3));
					bestHourStr = uniqueHours
						.slice(0, 3)
						.map((h: number) => {
							const hr = h % 12 || 12;
							return `${hr}${h < 12 ? "AM" : "PM"}`;
						})
						.join(", ");
				}
			}
		} catch {
			// trend_forecasts may not exist — fall through to engagement-based analysis
		}

		// Fall back to computing best hours from historical engagement data
		if (!bestHours) {
			const engagementByHour: Record<number, { total: number; count: number }> =
				{};

			for (const p of posts) {
				if (!p.published_at) continue;
				const hour = new Date(p.published_at).getUTCHours();
				const engagement =
					(p.likes_count || 0) +
					(p.replies_count || 0) +
					(p.reposts_count || p.shares_count || 0);
				if (!engagementByHour[hour])
					engagementByHour[hour] = { total: 0, count: 0 };
				engagementByHour[hour].total += engagement;
				engagementByHour[hour].count++;
			}

			const hourlyAvg = Object.entries(engagementByHour).map(([h, v]) => ({
				hour: parseInt(h, 10),
				avg: v.total / v.count,
			}));

			if (hourlyAvg.length < 3) return;

			hourlyAvg.sort((a, b) => b.avg - a.avg);
			bestHours = new Set(hourlyAvg.slice(0, 3).map((h) => h.hour));
			bestHourStr = hourlyAvg
				.slice(0, 3)
				.map((h) => {
					const hr = h.hour % 12 || 12;
					return `${hr}${h.hour < 12 ? "AM" : "PM"}`;
				})
				.join(", ");
		}

		if (!bestHours) return;
		const selectedBestHours = bestHours;
		// Check what % of posts are in best hours
		const inBestHours = posts.filter((p: LhfPost) => {
			if (!p.published_at) return false;
			return selectedBestHours.has(new Date(p.published_at).getUTCHours());
		}).length;

		const ratio = inBestHours / posts.length;
		if (ratio < 0.3) {
			recs.push({
				id: "best-times",
				title: "Post at your best times",
				description: `Only ${Math.round(ratio * 100)}% of your posts go out during peak engagement hours. Try posting around ${bestHourStr} (UTC).`,
				impactScore: 8,
				effortScore: 1,
				roi: 8,
				dataPoint: `${Math.round(ratio * 100)}% of posts at peak times`,
				icon: "⏰",
				...getConfidence(sampleSize),
				ctaPath: "/compose",
				category: "timing",
				baselineValue: ratio,
			});
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to check best posting times", {
			accountId,
			error: String(err),
		});
		// Skip silently
	}
}

// ── Check 2: Alt text ────────────────────────────────────────────────────────

export function checkAltText(
	posts: LhfPost[],
	recs: Recommendation[],
	_sampleSize: number,
) {
	const imagePosts = posts.filter(
		(p: LhfPost) =>
			p.media_type === "IMAGE" || p.media_type === "CAROUSEL_ALBUM",
	);
	if (imagePosts.length < 5) return;

	const withAlt = imagePosts.filter(
		(p: LhfPost) => p.alt_text && p.alt_text.trim().length > 0,
	).length;
	const pct = withAlt / imagePosts.length;

	if (pct < 0.2) {
		recs.push({
			id: "alt-text",
			title: "Add alt text to images",
			description: `Only ${Math.round(pct * 100)}% of your image posts have alt text. It boosts accessibility and can improve reach.`,
			impactScore: 3,
			effortScore: 1,
			roi: 3,
			dataPoint: `${Math.round(pct * 100)}% have alt text`,
			icon: "♿",
			...getConfidence(imagePosts.length),
			ctaPath: null,
			category: "accessibility",
			baselineValue: pct,
		});
	}
}

// ── Check 3: Repetitive hashtags ─────────────────────────────────────────────

export function checkRepetitiveHashtags(
	posts: LhfPost[],
	recs: Recommendation[],
	_sampleSize: number,
) {
	if (posts.length < 3) return;

	const hashtagSets: string[][] = [];
	for (const p of posts) {
		const text = p.content || "";
		const tags = (text.match(/#\w+/g) || []).map((t: string) =>
			t.toLowerCase(),
		);
		if (tags.length > 0) hashtagSets.push(tags);
	}

	if (hashtagSets.length < 3) return;

	// Check overlap: compare each pair (pre-compute sets to avoid O(n^2) allocations)
	let highOverlapCount = 0;
	const hashtagSetObjects = hashtagSets.map((tags) => new Set(tags));

	for (let i = 0; i < hashtagSetObjects.length; i++) {
		for (let j = i + 1; j < hashtagSetObjects.length; j++) {
			const setA = hashtagSetObjects[i];
			const setB = hashtagSetObjects[j];
			let intersection = 0;
			for (const t of setA!) {
				if (setB!.has(t)) intersection++;
			}
			const union = setA!.size + setB!.size - intersection;
			if (union > 0 && intersection / union > 0.7) {
				highOverlapCount++;
			}
		}
	}

	const totalPairs = (hashtagSets.length * (hashtagSets.length - 1)) / 2;
	if (totalPairs > 0 && highOverlapCount / totalPairs > 0.5) {
		recs.push({
			id: "repetitive-hashtags",
			title: "Mix up your hashtags",
			description:
				"You're using very similar hashtags across posts. Varying your hashtags can help reach new audiences.",
			impactScore: 7,
			effortScore: 2,
			roi: 3.5,
			dataPoint: `${Math.round((highOverlapCount / totalPairs) * 100)}% hashtag overlap`,
			icon: "#️⃣",
			...getConfidence(hashtagSets.length),
			ctaPath: "/compose",
			category: "content",
			baselineValue: highOverlapCount / totalPairs,
		});
	}
}

// ── Check 4: Content type mix ────────────────────────────────────────────────

export function checkContentTypeMix(
	posts: LhfPost[],
	_platform: string,
	recs: Recommendation[],
	sampleSize: number,
) {
	if (posts.length < 10) return;

	const typeEngagement: Record<string, { total: number; count: number }> = {};

	for (const p of posts) {
		const type = p.media_type || "TEXT";
		const engagement =
			(p.likes_count || 0) +
			(p.replies_count || 0) +
			(p.reposts_count || p.shares_count || 0);
		if (!typeEngagement[type]) typeEngagement[type] = { total: 0, count: 0 };
		typeEngagement[type].total += engagement;
		typeEngagement[type].count++;
	}

	const typeAvgs = Object.entries(typeEngagement)
		.filter(([_, v]) => v.count >= 5)
		.map(([type, v]) => ({
			type,
			avg: v.total / v.count,
			pct: v.count / posts.length,
		}));

	if (typeAvgs.length < 2) return;

	typeAvgs.sort((a, b) => b.avg - a.avg);
	const best = typeAvgs[0];
	const overallAvg = typeAvgs.reduce((s, t) => s + t.avg, 0) / typeAvgs.length;

	if (best!.pct < 0.3 && best!.avg > overallAvg * 1.5) {
		const multiplier = (best!.avg / overallAvg).toFixed(1);
		const typeName =
			best!.type === "VIDEO"
				? "Reels"
				: best!.type === "CAROUSEL_ALBUM"
					? "Carousels"
					: best!.type;
		recs.push({
			id: "content-type-mix",
			title: `Post more ${typeName}`,
			description: `Your ${typeName} are showing a ${multiplier}x engagement signal with enough samples to test, but only ${Math.round(best!.pct * 100)}% of your posts are ${typeName}. Treat this as an experiment, not proof of causality.`,
			impactScore: 8,
			effortScore: 2,
			roi: 4,
			dataPoint: `${typeName}: ${multiplier}x engagement, ${Math.round(best!.pct * 100)}% of posts`,
			icon: "🎬",
			...getConfidence(sampleSize),
			ctaPath: "/compose",
			category: "format",
			baselineValue: best!.pct,
		});
	}
}

// ── Check 5: Reply time ──────────────────────────────────────────────────────

export async function checkReplyTime(
	accountId: string,
	platform: string,
	recs: Recommendation[],
	sampleSize: number,
) {
	try {
		const { data } = await dbAny()
			.from("reply_response_times")
			.select("avg_response_mins")
			.eq("account_id", accountId)
			.eq("platform", platform)
			.order("computed_at", { ascending: false })
			.limit(1)
			.maybeSingle();

		if (data && data.avg_response_mins > 60) {
			const hours = Math.round(data.avg_response_mins / 60);
			recs.push({
				id: "slow-replies",
				title: "Reply faster to comments",
				description: `Your average reply time is ~${hours}h. Replying within 1 hour signals active engagement to the algorithm.`,
				impactScore: 6,
				effortScore: 2,
				roi: 3,
				dataPoint: `Avg reply: ${hours}h`,
				icon: "💬",
				...getConfidence(sampleSize),
				ctaPath: "/inbox",
				category: "engagement",
				baselineValue: data.avg_response_mins / 60, // in hours
			});
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to check reply response time", {
			accountId,
			platform,
			error: String(err),
		});
		// Table might not exist — skip
	}
}

// ── Check 6: Posting consistency ─────────────────────────────────────────────

export function checkPostingConsistency(
	posts: LhfPost[],
	recs: Recommendation[],
	sampleSize: number,
) {
	// Count posts per week over last 4 weeks
	const now = Date.now();
	const weekCounts: number[] = [0, 0, 0, 0];

	for (const p of posts) {
		if (!p.published_at) continue;
		const age = now - new Date(p.published_at).getTime();
		const weekIndex = Math.floor(age / (7 * 24 * 60 * 60 * 1000));
		if (weekIndex >= 0 && weekIndex < 4) {
			weekCounts[weekIndex]!++;
		}
	}

	const mean = weekCounts.reduce((a, b) => a + b, 0) / 4;
	if (mean < 1) return;

	const variance = weekCounts.reduce((s, c) => s + (c - mean) ** 2, 0) / 4;
	const stdDev = Math.sqrt(variance);

	if (stdDev / mean > 0.5) {
		const minWeek = Math.min(...weekCounts);
		const maxWeek = Math.max(...weekCounts);
		recs.push({
			id: "inconsistent-posting",
			title: "Post more consistently",
			description: `Your posting varies from ${minWeek} to ${maxWeek} posts/week. Consistent posting helps the algorithm surface your content.`,
			impactScore: 7,
			effortScore: 3,
			roi: 7 / 3,
			dataPoint: `${minWeek}-${maxWeek} posts/week variance`,
			icon: "📅",
			...getConfidence(sampleSize),
			ctaPath: "/calendar",
			category: "frequency",
			baselineValue: stdDev / mean, // coefficient of variation
		});
	}
}

// ── Check 7: Stories ─────────────────────────────────────────────────────────

export async function checkStories(
	accountId: string,
	sevenDaysAgo: string,
	recs: Recommendation[],
	sampleSize: number,
) {
	try {
		const { count } = await dbAny()
			.from("instagram_posts")
			.select("id", { count: "exact", head: true })
			.eq("instagram_account_id", accountId)
			.eq("media_type", "STORY")
			.gte("published_at", sevenDaysAgo);

		if (count === 0) {
			recs.push({
				id: "no-stories",
				title: "Post stories regularly",
				description:
					"You haven't posted any stories in the last 7 days. Stories keep you visible at the top of followers' feeds.",
				impactScore: 5,
				effortScore: 3,
				roi: 5 / 3,
				dataPoint: "0 stories in 7 days",
				icon: "📱",
				...getConfidence(sampleSize),
				ctaPath: "/compose",
				category: "format",
				baselineValue: 0,
			});
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to check recent story count", {
			accountId,
			error: String(err),
		});
		// Skip
	}
}

// ── Check 8: Reply Window (author replies within 30 min) ─────────────────────

export async function checkReplyWindow(
	accountId: string,
	platform: string,
	posts: LhfPost[],
	recs: Recommendation[],
	sampleSize: number,
) {
	try {
		const recentPosts = posts.slice(0, 10);
		let postsWithEarlyAuthorReply = 0;

		// #610: Batch query instead of N+1 (was 10 separate DB calls)
		const postIds = recentPosts.map((p: LhfPost) => p.id ?? "").filter(Boolean);
		const { data: allReplies } = await dbAny()
			.from("post_replies")
			.select("post_id, created_at")
			.in("post_id", postIds)
			.eq("is_author", true)
			.order("created_at", { ascending: true });

		// Group earliest author reply per post
		const earliestReplyByPost = new Map<string, string>();
		for (const reply of allReplies || []) {
			if (
				reply.post_id &&
				reply.created_at &&
				!earliestReplyByPost.has(reply.post_id)
			) {
				earliestReplyByPost.set(reply.post_id, reply.created_at);
			}
		}

		for (const post of recentPosts) {
			const replyCreatedAt = earliestReplyByPost.get(post.id ?? "");
			if (replyCreatedAt && post.published_at) {
				const postTime = new Date(post.published_at).getTime();
				const replyTime = new Date(replyCreatedAt).getTime();
				if (replyTime - postTime < 30 * 60 * 1000) {
					postsWithEarlyAuthorReply++;
				}
			}
		}

		const earlyReplyRate =
			postsWithEarlyAuthorReply / Math.max(recentPosts.length, 1);

		if (earlyReplyRate < 0.5) {
			recs.push({
				id: "reply-window-30min",
				title: "Stay online for 30 min after posting",
				description: `You reply to your own threads early only ${Math.round(earlyReplyRate * 100)}% of the time. The algorithm heavily rewards author participation in the first 30 minutes — early author participation significantly boosts reach.`,
				impactScore: 9,
				effortScore: 2,
				roi: 4.5,
				dataPoint: `${Math.round(earlyReplyRate * 100)}% early reply rate`,
				icon: "⏰",
				...getConfidence(sampleSize),
				ctaPath: null,
				category: "engagement",
				baselineValue: earlyReplyRate,
			});
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to check early author reply window", {
			accountId,
			platform,
			error: String(err),
		});
		// Tables might not exist — skip
	}
}

// ── Check 9: Question Opener ─────────────────────────────────────────────────

export function checkQuestionOpener(
	posts: LhfPost[],
	recs: Recommendation[],
	sampleSize: number,
) {
	if (posts.length < 5) return;

	const questionPosts = posts.filter((p: LhfPost) => {
		const content = (p.content || "").trim();
		const firstLine = content.split("\n")[0] || "";
		return (
			firstLine.endsWith("?") ||
			/^(what|why|how|who|when|where|which|do you|have you|would you)/i.test(
				firstLine,
			)
		);
	});

	const nonQuestionPosts = posts.filter(
		(p: LhfPost) => !questionPosts.includes(p),
	);

	if (questionPosts.length < 5 || nonQuestionPosts.length < 5) return;

	const avgEngagementQ =
		questionPosts.reduce(
			(s: number, p: LhfPost) =>
				s + (p.replies_count || 0) + (p.likes_count || 0),
			0,
		) / questionPosts.length;
	const avgEngagementNQ =
		nonQuestionPosts.reduce(
			(s: number, p: LhfPost) =>
				s + (p.replies_count || 0) + (p.likes_count || 0),
			0,
		) / nonQuestionPosts.length;

	if (avgEngagementNQ > 0 && avgEngagementQ / avgEngagementNQ > 1.3) {
		const boost = Math.round((avgEngagementQ / avgEngagementNQ - 1) * 100);
		recs.push({
			id: "question-opener",
			title: "Test question-led openings",
			description: `Your question-led posts show a ${boost}% engagement lift in this sample. Run this as a controlled test before treating it as a durable pattern.`,
			impactScore: 8,
			effortScore: 1,
			roi: 8,
			dataPoint: `${boost}% engagement lift on questions`,
			icon: "❓",
			...getConfidence(sampleSize),
			ctaPath: "/ai-studio",
			category: "content",
			baselineValue: avgEngagementNQ,
		});
	}
}

// ── Check 10: Posting Gaps ───────────────────────────────────────────────────

export function checkPostingGaps(
	posts: LhfPost[],
	recs: Recommendation[],
	sampleSize: number,
) {
	if (posts.length < 5) return;

	const sorted = [...posts]
		.filter(
			(p: LhfPost): p is LhfPost & { published_at: string } => !!p.published_at,
		)
		.sort(
			(
				a: LhfPost & { published_at: string },
				b: LhfPost & { published_at: string },
			) =>
				new Date(b.published_at).getTime() - new Date(a.published_at).getTime(),
		);

	let gapCount = 0;
	let postAfterGapAvgReach = 0;
	let normalPostAvgReach = 0;
	let postAfterGapCount = 0;
	let normalCount = 0;

	for (let i = 0; i < sorted.length - 1; i++) {
		const current = new Date(sorted[i]!.published_at).getTime();
		const prev = new Date(sorted[i + 1]!.published_at).getTime();
		const gapDays = (current - prev) / (24 * 60 * 60 * 1000);

		if (gapDays > 3) {
			gapCount++;
			postAfterGapAvgReach += sorted[i]!.views_count || 0;
			postAfterGapCount++;
		} else {
			normalPostAvgReach += sorted[i]!.views_count || 0;
			normalCount++;
		}
	}

	if (gapCount >= 3 && postAfterGapCount >= 3 && normalCount >= 5) {
		const avgAfterGap = postAfterGapAvgReach / postAfterGapCount;
		const avgNormal = normalPostAvgReach / normalCount;

		if (avgNormal > 0 && avgAfterGap < avgNormal * 0.7) {
			const dropPct = Math.round((1 - avgAfterGap / avgNormal) * 100);
			recs.push({
				id: "posting-gaps-kill-momentum",
				title: "Gaps are killing your momentum",
				description: `You've had ${gapCount} gaps of 3+ days. Posts after gaps show ${dropPct}% less reach in this sample. Keep a light baseline cadence and recheck the next 30 days.`,
				impactScore: 8,
				effortScore: 3,
				roi: 8 / 3,
				dataPoint: `${dropPct}% reach drop after gaps`,
				icon: "📉",
				...getConfidence(sampleSize),
				ctaPath: "/auto-poster",
				category: "frequency",
				baselineValue: dropPct,
			});
		}
	}
}
