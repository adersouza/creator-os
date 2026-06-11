// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Report Builder — pure PDF generation, no req/res coupling.
 *
 * Used by:
 *   - api/reports.ts (user-triggered HTTP)
 *   - api/cron/weekly-reports.ts (scheduled email attachment)
 */

import { followerColForPlatform } from "./followerCount.js";
import { logger } from "./logger.js";
import { getSupabase, getSupabaseAny } from "./supabase.js";

export interface ReportParams {
	accountId?: string | undefined;
	reportType: "weekly" | "monthly" | "custom" | "consolidated";
	dateRange: { start: string; end: string };
	includeRecommendations?: boolean | undefined;
	clientName?: string | undefined;
	platform?: "threads" | "instagram" | undefined;
	accountIds?: string[] | undefined;
}

export interface ReportStats {
	totalPosts: number;
	totalViews: number;
	totalLikes: number;
	totalReplies: number;
	avgEngagement: string;
	followerChange?: number | undefined;
	followerChangePct?: number | undefined;
	viewsTrendPct?: number | undefined;
	engagementTrendPct?: number | undefined;
	bestDay?: string | null | undefined;
	bestDayAvgViews?: number | undefined;
	mostActiveHour?: number | null | undefined;
}

export type ReportBuildResult =
	| {
			success: true;
			pdfBase64: string;
			pdfBuffer: Buffer;
			filename: string;
			stats: ReportStats;
	  }
	| { success: false; status: number; error: string };

interface PostRow {
	content?: string | undefined;
	published_at?: string | undefined;
	views_count?: number | undefined;
	likes_count?: number | undefined;
	replies_count?: number | undefined;
	reposts_count?: number | undefined;
}

interface DailyAnalyticsRow {
	date?: string | undefined;
	account_id?: string | undefined;
	followers_count?: number | undefined;
	total_views?: number | undefined;
	total_likes?: number | undefined;
	total_replies?: number | undefined;
}

interface PeriodTrends {
	followerChange: number;
	followerStart: number;
	followerEnd: number;
	followerChangePct: number;
	viewsTrendPct: number;
	engagementTrendPct: number;
	bestDay: string | null;
	bestDayAvgViews: number;
	mostActiveHour: number | null;
}

export async function buildPdfReport(
	userId: string,
	params: ReportParams,
): Promise<ReportBuildResult> {
	const supabase = getSupabase();

	const {
		accountId,
		reportType,
		dateRange,
		includeRecommendations,
		clientName,
		platform,
		accountIds,
	} = params;

	if (new Date(dateRange.start) > new Date(dateRange.end)) {
		return {
			success: false,
			status: 400,
			error: "dateRange.start must be before dateRange.end",
		};
	}
	const rangeDays =
		(new Date(dateRange.end).getTime() - new Date(dateRange.start).getTime()) /
		(1000 * 60 * 60 * 24);
	if (rangeDays > 365) {
		return {
			success: false,
			status: 400,
			error: "Date range cannot exceed 365 days",
		};
	}

	if (
		reportType === "consolidated" &&
		(!accountIds || accountIds.length === 0)
	) {
		return {
			success: false,
			status: 400,
			error: "accountIds required for consolidated reports",
		};
	}
	if (reportType !== "consolidated" && !accountId) {
		return { success: false, status: 400, error: "accountId is required" };
	}

	const requestedAccountIds =
		reportType === "consolidated"
			? Array.from(new Set(accountIds || []))
			: [accountId as string];

	const accountTable =
		platform === "instagram" ? "instagram_accounts" : "accounts";
	const followerCol = followerColForPlatform(platform ?? "threads");

	const { data: accountRowsRaw } = await getSupabaseAny()
		.from(accountTable)
		.select(`id, username, ${followerCol}`)
		.in("id", requestedAccountIds)
		.eq("user_id", userId)
		.order("username", { ascending: true });

	const accountRows = (accountRowsRaw || []) as Array<Record<string, unknown>>;
	if (accountRows.length !== requestedAccountIds.length) {
		return { success: false, status: 404, error: "Account not found" };
	}
	const ownedAccountIds = new Set(
		accountRows.map((row) => String(row.id || "")),
	);
	if (requestedAccountIds.some((id) => !ownedAccountIds.has(id))) {
		return { success: false, status: 404, error: "Account not found" };
	}

	const usernames = accountRows
		.map((row) => String(row.username || "Unknown"))
		.filter(Boolean);
	const username =
		reportType === "consolidated"
			? usernames.slice(0, 3).join(", ") + (usernames.length > 3 ? ", +" : "")
			: usernames[0] || "Unknown";
	const followerCount = accountRows.reduce(
		(sum, row) => sum + (Number(row[followerCol]) || 0),
		0,
	);

	const { data: branding } = await supabase
		.from("agency_branding")
		.select("agency_name, agency_logo_url, brand_color")
		.eq("user_id", userId)
		.maybeSingle();

	let postsQuery = getSupabaseAny()
		.from("posts")
		.select(
			"content, published_at, views_count, likes_count, replies_count, reposts_count",
		);
	if (reportType === "consolidated") {
		if (platform === "instagram") {
			postsQuery = postsQuery.in("instagram_account_id", requestedAccountIds);
		} else {
			postsQuery = postsQuery.in("account_id", requestedAccountIds);
		}
	} else {
		postsQuery =
			platform === "instagram"
				? postsQuery.eq("instagram_account_id", accountId as string)
				: postsQuery.eq("account_id", accountId as string);
	}
	const { data: posts } = await postsQuery
		.gte("published_at", dateRange.start)
		.lte("published_at", dateRange.end)
		.eq("status", "published")
		.order("published_at", { ascending: false })
		.limit(1000);

	const typedPosts = (posts || []) as unknown as PostRow[];
	const totalPosts = typedPosts.length;
	const totalViews = typedPosts.reduce(
		(s: number, p: PostRow) => s + (p.views_count || 0),
		0,
	);
	const totalLikes = typedPosts.reduce(
		(s: number, p: PostRow) => s + (p.likes_count || 0),
		0,
	);
	const totalReplies = typedPosts.reduce(
		(s: number, p: PostRow) => s + (p.replies_count || 0),
		0,
	);
	const totalReposts = typedPosts.reduce(
		(s: number, p: PostRow) => s + (p.reposts_count || 0),
		0,
	);
	const avgEngagement =
		totalViews > 0
			? (
					((totalLikes + totalReplies + totalReposts) / totalViews) *
					100
				).toFixed(2)
			: "0.00";

	// biome-ignore lint/suspicious/noExplicitAny: lazy import requires any for dynamic module type
	let jsPDF: any;
	// biome-ignore lint/suspicious/noExplicitAny: lazy import requires any for dynamic module type
	let autoTable: any;
	try {
		({ jsPDF } = await import("jspdf"));
		({ default: autoTable } = await import("jspdf-autotable"));
	} catch (err) {
		logger.error("Failed to load PDF libraries", { error: String(err) });
		return {
			success: false,
			status: 500,
			error: "PDF generation unavailable",
		};
	}

	const doc = new jsPDF();
	const pageWidth = doc.internal.pageSize.getWidth();

	const brandHex = branding?.brand_color || "#0930ef";
	const brandR = parseInt(brandHex.slice(1, 3), 16) || 9;
	const brandG = parseInt(brandHex.slice(3, 5), 16) || 48;
	const brandB = parseInt(brandHex.slice(5, 7), 16) || 239;

	doc.setFontSize(24);
	doc.setTextColor(brandR, brandG, brandB);
	doc.text(clientName || branding?.agency_name || "Juno33", pageWidth / 2, 30, {
		align: "center",
	});

	doc.setFontSize(16);
	doc.setTextColor(0);
	doc.text(
		`${reportType.charAt(0).toUpperCase() + reportType.slice(1)} Performance Report`,
		pageWidth / 2,
		45,
		{ align: "center" },
	);

	doc.setFontSize(12);
	doc.setTextColor(100);
	const reportSubject =
		reportType === "consolidated"
			? `${requestedAccountIds.length} accounts`
			: `@${username}`;
	doc.text(
		`${reportSubject} | ${dateRange.start} to ${dateRange.end}`,
		pageWidth / 2,
		55,
		{ align: "center" },
	);

	doc.setFontSize(14);
	doc.setTextColor(0);
	doc.text("Key Metrics", 20, 75);

	autoTable(doc, {
		startY: 80,
		head: [["Metric", "Value"]],
		body: [
			["Total Posts", totalPosts.toString()],
			["Total Views", totalViews.toLocaleString()],
			["Total Likes", totalLikes.toLocaleString()],
			["Total Replies", totalReplies.toLocaleString()],
			["Total Reposts", totalReposts.toLocaleString()],
			["Avg Engagement Rate", `${avgEngagement}%`],
			["Followers", followerCount?.toLocaleString() || "N/A"],
		],
		theme: "striped",
		headStyles: { fillColor: [brandR, brandG, brandB] },
	});

	let periodTrends: PeriodTrends | null = null;

	try {
		const startDate = dateRange.start;
		const endDate = dateRange.end;

		const { data: dailyStatsRaw } = await getSupabaseAny()
			.from("account_analytics")
			.select(
				"date, account_id, followers_count, total_views, total_likes, total_replies",
			)
			.in("account_id", requestedAccountIds)
			.gte("date", startDate)
			.lte("date", endDate)
			.order("date", { ascending: true });

		const dailyStatsMap = new Map<string, DailyAnalyticsRow>();
		for (const row of (dailyStatsRaw || []) as DailyAnalyticsRow[]) {
			if (!row.date) continue;
			const existing = dailyStatsMap.get(row.date) || {
				date: row.date,
				followers_count: 0,
				total_views: 0,
				total_likes: 0,
				total_replies: 0,
			};
			existing.followers_count =
				(existing.followers_count || 0) + (row.followers_count || 0);
			existing.total_views =
				(existing.total_views || 0) + (row.total_views || 0);
			existing.total_likes =
				(existing.total_likes || 0) + (row.total_likes || 0);
			existing.total_replies =
				(existing.total_replies || 0) + (row.total_replies || 0);
			dailyStatsMap.set(row.date, existing);
		}
		const dailyStats = Array.from(dailyStatsMap.values()).sort((a, b) =>
			(a.date || "").localeCompare(b.date || ""),
		);

		if (dailyStats.length >= 2) {
			const followerStart = dailyStats[0]!.followers_count || 0;
			const followerEnd =
				dailyStats[dailyStats.length - 1]!.followers_count || 0;
			const followerChange = followerEnd - followerStart;
			const followerChangePct =
				followerStart > 0
					? Math.round((followerChange / followerStart) * 1000) / 10
					: 0;

			const midpoint = Math.floor(dailyStats.length / 2);
			const firstHalf = dailyStats.slice(0, midpoint);
			const secondHalf = dailyStats.slice(midpoint);

			const firstHalfViews = firstHalf.reduce(
				(s, d) => s + (d.total_views || 0),
				0,
			);
			const secondHalfViews = secondHalf.reduce(
				(s, d) => s + (d.total_views || 0),
				0,
			);
			const viewsTrendPct =
				firstHalfViews > 0
					? Math.round(
							((secondHalfViews - firstHalfViews) / firstHalfViews) * 100,
						)
					: 0;

			const firstHalfEngagement = firstHalf.reduce(
				(s, d) => s + (d.total_likes || 0) + (d.total_replies || 0),
				0,
			);
			const secondHalfEngagement = secondHalf.reduce(
				(s, d) => s + (d.total_likes || 0) + (d.total_replies || 0),
				0,
			);
			const engagementTrendPct =
				firstHalfEngagement > 0
					? Math.round(
							((secondHalfEngagement - firstHalfEngagement) /
								firstHalfEngagement) *
								100,
						)
					: 0;

			const dayNames = [
				"Sunday",
				"Monday",
				"Tuesday",
				"Wednesday",
				"Thursday",
				"Friday",
				"Saturday",
			];
			const viewsByDay: Record<number, { total: number; count: number }> = {};
			for (const d of dailyStats) {
				if (!d.date) continue;
				const dow = new Date(d.date).getUTCDay();
				if (!viewsByDay[dow]) viewsByDay[dow] = { total: 0, count: 0 };
				viewsByDay[dow].total += d.total_views || 0;
				viewsByDay[dow].count++;
			}
			let bestDay: string | null = null;
			let bestDayAvgViews = 0;
			for (const [dow, v] of Object.entries(viewsByDay)) {
				const avg = v.total / v.count;
					if (avg > bestDayAvgViews) {
						bestDayAvgViews = Math.round(avg);
						bestDay = dayNames[parseInt(dow, 10)] ?? null;
					}
			}

			const hourCounts: Record<number, number> = {};
			for (const p of typedPosts) {
				if (!p.published_at) continue;
				const hour = new Date(p.published_at).getUTCHours();
				hourCounts[hour] = (hourCounts[hour] || 0) + 1;
			}
			let mostActiveHour: number | null = null;
			let maxHourCount = 0;
			for (const [h, count] of Object.entries(hourCounts)) {
				if (count > maxHourCount) {
					maxHourCount = count;
					mostActiveHour = parseInt(h, 10);
				}
			}

			periodTrends = {
				followerChange,
				followerStart,
				followerEnd,
				followerChangePct,
				viewsTrendPct,
				engagementTrendPct,
				bestDay,
				bestDayAvgViews,
				mostActiveHour,
			};
		}
	} catch (err) {
		logger.debug("Failed to compute period trends for report", {
			error: String(err),
			accountIds: requestedAccountIds,
		});
	}

	if (periodTrends) {
		// biome-ignore lint/suspicious/noExplicitAny: jspdf-autotable finalY accessor
		const metricsTableEndY = (doc as any).lastAutoTable?.finalY ?? 160;
		const trendsStartY = metricsTableEndY + 12;

		doc.setFontSize(14);
		doc.setTextColor(0);
		doc.text("Period Trends", 20, trendsStartY);

		const trendLines: string[] = [];
		const sign = periodTrends.followerChange >= 0 ? "+" : "";
		trendLines.push(
			`Followers: ${sign}${periodTrends.followerChange.toLocaleString()} (from ${periodTrends.followerStart.toLocaleString()} to ${periodTrends.followerEnd.toLocaleString()}) — ${sign}${periodTrends.followerChangePct}%`,
		);
		const viewsArrow = periodTrends.viewsTrendPct >= 0 ? "↑" : "↓";
		trendLines.push(
			`Views trend: ${viewsArrow} ${Math.abs(periodTrends.viewsTrendPct)}% (second half vs first half)`,
		);
		const engArrow = periodTrends.engagementTrendPct >= 0 ? "↑" : "↓";
		trendLines.push(
			`Engagement trend: ${engArrow} ${Math.abs(periodTrends.engagementTrendPct)}% ${periodTrends.engagementTrendPct >= 0 ? "improvement" : "decline"}`,
		);
		if (periodTrends.bestDay) {
			trendLines.push(
				`Best day: ${periodTrends.bestDay} (avg ${periodTrends.bestDayAvgViews.toLocaleString()} views)`,
			);
		}
		if (periodTrends.mostActiveHour !== null) {
			const hr = periodTrends.mostActiveHour % 12 || 12;
			const ampm = periodTrends.mostActiveHour < 12 ? "AM" : "PM";
			trendLines.push(`Most active hour: ${hr} ${ampm} UTC`);
		}

		doc.setFontSize(10);
		doc.setTextColor(60);
		let lineY = trendsStartY + 8;
		for (const line of trendLines) {
			doc.text(`• ${line}`, 24, lineY);
			lineY += 6;
		}
	}

	const topPosts = [...typedPosts]
		.sort(
			(a: PostRow, b: PostRow) =>
				(b.likes_count || 0) +
				(b.replies_count || 0) -
				((a.likes_count || 0) + (a.replies_count || 0)),
		)
		.slice(0, 10);

	if (topPosts.length > 0) {
		doc.addPage();
		doc.setFontSize(14);
		doc.setTextColor(0);
		doc.text("Top Performing Posts", 20, 20);

		autoTable(doc, {
			startY: 25,
			head: [["Content", "Views", "Likes", "Replies", "Reposts"]],
			body: topPosts.map((p: PostRow) => [
				(p.content || "").substring(0, 60) +
					((p.content?.length || 0) > 60 ? "..." : ""),
				(p.views_count || 0).toLocaleString(),
				(p.likes_count || 0).toLocaleString(),
				(p.replies_count || 0).toLocaleString(),
				(p.reposts_count || 0).toLocaleString(),
			]),
			theme: "striped",
			headStyles: { fillColor: [brandR, brandG, brandB] },
			columnStyles: { 0: { cellWidth: 80 } },
		});
	}

	if (includeRecommendations && totalPosts > 0) {
		doc.addPage();
		doc.setFontSize(14);
		doc.setTextColor(0);
		doc.text("AI Recommendations", 20, 20);

		const recommendations: string[] = [];
		if (parseFloat(avgEngagement) < 2) {
			recommendations.push(
				"Your engagement rate is below average. Try asking questions in your posts to drive more replies.",
			);
		}
		if (totalPosts < 7 && reportType === "weekly") {
			recommendations.push(
				"You posted less than once per day this week. Consistent posting helps grow reach.",
			);
		}
		if (totalPosts < 20 && reportType === "monthly") {
			recommendations.push(
				"Aim for at least 20 posts per month to maintain algorithm visibility.",
			);
		}
		const bestPost = topPosts[0];
		if (bestPost) {
			const contentLength = (bestPost.content || "").length;
			if (contentLength < 100) {
				recommendations.push(
					"Your best performing post was short. Keep posts concise and punchy.",
				);
			} else {
				recommendations.push(
					"Your best performing post was longer-form. Your audience values detailed content.",
				);
			}
		}
		if (recommendations.length === 0) {
			recommendations.push(
				"Great work! Keep up the consistent posting and engagement.",
			);
		}

		autoTable(doc, {
			startY: 25,
			head: [["Recommendation"]],
			body: recommendations.map((r) => [r]),
			theme: "striped",
			headStyles: { fillColor: [brandR, brandG, brandB] },
		});
	}

	const pageCount = doc.getNumberOfPages();
	for (let i = 1; i <= pageCount; i++) {
		doc.setPage(i);
		doc.setFontSize(8);
		doc.setTextColor(150);
		const footerLabel = branding?.agency_name
			? `Report by ${branding.agency_name}`
			: "Powered by Juno33 — juno33.com";
		doc.text(
			`${footerLabel} | Page ${i} of ${pageCount}`,
			pageWidth / 2,
			doc.internal.pageSize.getHeight() - 10,
			{ align: "center" },
		);
	}

	const pdfArrayBuffer = doc.output("arraybuffer") as ArrayBuffer;
	const pdfBuffer = Buffer.from(pdfArrayBuffer);
	const pdfBase64 = `data:application/pdf;base64,${pdfBuffer.toString("base64")}`;

	const filename = `${reportType === "consolidated" ? "consolidated-report" : username}-${reportType}-${dateRange.start}-to-${dateRange.end}.pdf`;

	const stats: ReportStats = {
		totalPosts,
		totalViews,
		totalLikes,
		totalReplies,
		avgEngagement,
		...(periodTrends
			? {
					followerChange: periodTrends.followerChange,
					followerChangePct: periodTrends.followerChangePct,
					viewsTrendPct: periodTrends.viewsTrendPct,
					engagementTrendPct: periodTrends.engagementTrendPct,
					bestDay: periodTrends.bestDay,
					bestDayAvgViews: periodTrends.bestDayAvgViews,
					mostActiveHour: periodTrends.mostActiveHour,
				}
			: {}),
	};

	return { success: true, pdfBase64, pdfBuffer, filename, stats };
}
