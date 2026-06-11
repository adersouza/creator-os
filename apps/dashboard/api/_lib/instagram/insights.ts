/**
 * Instagram Insights & Analytics — post metrics, story metrics, account insights,
 * follower count, demographics, online followers, and carousel child insights.
 */

import {
	decrypt,
	getGraphBaseUrl,
	type IGAccountInsights,
	type IGCarouselChild,
	type IGCarouselChildRaw,
	type IGDemographicsBreakdown,
	type IGPostMetrics,
	type IGStoryMetrics,
	igFetch,
	logger,
} from "./shared.js";
import {
	INSTAGRAM_METRICS_CONTRACT_VERSION,
	resolveInstagramMetricContract,
} from "./metricContracts.js";

// ============================================================================
// Get Post Metrics
// ============================================================================

/** Requires `instagram_business_manage_insights` permission scope. */
export async function getInstagramPostMetrics(
	encryptedToken: string,
	mediaId: string,
	loginType?: string,
	mediaType?: string,
	contentSurface?: string,
): Promise<{
	success: boolean;
	metrics?: IGPostMetrics | undefined;
	error?: string | undefined;
	notFound?: boolean | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const contract = resolveInstagramMetricContract({
			contentSurface,
			igMediaType: mediaType,
		});
		if (!contract.ok) {
			logger.warn("IG post metrics contract blocked", {
				mediaId,
				mediaType,
				contentSurface,
				blockers: contract.blockers,
			});
			return {
				success: false,
				error: `unsupported_metric_for_surface:${contract.blockers.join(",")}`,
			};
		}

		if (contract.surface === "story") {
			const storyResult = await getInstagramStoryMetrics(
				encryptedToken,
				mediaId,
				loginType,
			);
			if (!storyResult.success || !storyResult.metrics) {
				return {
					success: false,
					error: storyResult.error || "surface_metric_query_failed:story",
				};
			}
			const storyMetrics = storyResult.metrics;
			return {
				success: true,
				metrics: {
					metricContractVersion: INSTAGRAM_METRICS_CONTRACT_VERSION,
					metricSurface: "story",
					metricFallbackUsed: false,
					metricNames: contract.metrics,
					views: storyMetrics.views,
					impressions: storyMetrics.views,
					reach: storyMetrics.reach,
					likes: 0,
					comments: storyMetrics.replies,
					shares: storyMetrics.shares,
					saved: 0,
					engagementRate: storyMetrics.reach
						? ((storyMetrics.replies + storyMetrics.shares) / storyMetrics.reach) * 100
						: 0,
					plays: 0,
					video_views: 0,
					facebook_views: 0,
					reposts: 0,
					total_likes: 0,
					total_comments: storyMetrics.replies,
					total_views: storyMetrics.views,
					reels_skip_rate: 0,
					crossposted_views: 0,
					ig_reels_avg_watch_time: 0,
					ig_reels_video_view_total_time: 0,
					clips_replays_count: 0,
					ig_reels_aggregated_all_plays_count: 0,
					follows: storyMetrics.follows,
					profileActivity: storyMetrics.profile_activity,
					profile_visits: storyMetrics.profile_visits,
				},
			};
		}

		// Use appropriate Graph API base (graph.instagram.com for Business Login, graph.facebook.com for Facebook Login)
		const metricList = contract.metrics.join(",");
		const insightsUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=${metricList}`;
		logger.info("IG getPostMetrics", {
			mediaId,
			graphBase,
			loginType,
			metricSurface: contract.surface,
			metricContractVersion: contract.version,
		});
		let insightsResponse = await igFetch(
			insightsUrl,
			undefined,
			"igApi:postMetrics",
			token,
		);
		let insightsData = await insightsResponse.json();
		let metricFallbackUsed = false;

		// Fallback: if metrics are rejected, try truly minimal set
		if (!insightsResponse.ok && insightsData.error?.code === 100) {
			logger.warn("IG post metrics rejected, retrying with minimal set", {
				mediaId,
				metricSurface: contract.surface,
			});
			const fallbackMetrics = contract.fallbackMetrics.join(",");
			const fallbackUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=${fallbackMetrics}`;
			insightsResponse = await igFetch(
				fallbackUrl,
				undefined,
				"igApi:postMetricsFallback",
				token,
			);
			insightsData = await insightsResponse.json();
			metricFallbackUsed = true;
		}

		if (!insightsResponse.ok || insightsData.error) {
			const errCode = insightsData.error?.code;
			const errSubcode = insightsData.error?.error_subcode;
			const isNotFound = errCode === 100 && errSubcode === 33;
			logger.error("IG post insights error", {
				mediaId,
				error: JSON.stringify(insightsData.error || insightsData),
				...(isNotFound && { notFound: true }),
			});
			return {
				success: false,
				error: insightsData.error?.message || "Failed to fetch insights",
				notFound: isNotFound,
			};
		}

		const metrics: IGPostMetrics = {
			metricContractVersion: INSTAGRAM_METRICS_CONTRACT_VERSION,
			metricSurface: contract.surface,
			metricFallbackUsed,
			metricNames: metricFallbackUsed ? contract.fallbackMetrics : contract.metrics,
			views: 0,
			impressions: 0, // backwards compatibility
			reach: 0,
			likes: 0,
			comments: 0,
			shares: 0,
			saved: 0,
			engagementRate: 0,
			plays: 0,
			video_views: 0, // Alias for plays (backwards compatibility)
			facebook_views: 0,
			reposts: 0,
			total_likes: 0,
			total_comments: 0,
			total_views: 0,
			reels_skip_rate: 0,
			crossposted_views: 0,
			ig_reels_avg_watch_time: 0,
			ig_reels_video_view_total_time: 0,
			clips_replays_count: 0,
			ig_reels_aggregated_all_plays_count: 0,
			follows: 0,
		};

		if (insightsData.data) {
			for (const item of insightsData.data) {
				const name = item.name?.toLowerCase();
				const value = item.values?.[0]?.value || 0;

				switch (name) {
					case "views":
						// v21+ primary metric
						metrics.views = value;
						metrics.impressions = value; // backwards compatibility
						break;
					case "impressions":
						// deprecated in v21, but still returned by some endpoints
						metrics.impressions = value;
						if (!metrics.views) metrics.views = value;
						break;
					case "reach":
						metrics.reach = value;
						break;
					case "likes":
						metrics.likes = value;
						break;
					case "comments":
						metrics.comments = value;
						break;
					case "shares":
						metrics.shares = value;
						break;
					case "saved":
						metrics.saved = value;
						break;
					case "ig_reels_avg_watch_time":
						metrics.ig_reels_avg_watch_time = value;
						break;
					case "crossposted_views":
						metrics.crossposted_views = value;
						break;
					case "facebook_views":
						metrics.facebook_views = value;
						break;
					case "reposts":
						metrics.reposts = value;
						break;
					case "total_likes":
						metrics.total_likes = value;
						break;
					case "total_comments":
						metrics.total_comments = value;
						break;
					case "total_views":
						metrics.total_views = value;
						break;
					case "reels_skip_rate":
						metrics.reels_skip_rate = typeof value === "number" ? value : 0;
						break;
					case "ig_reels_video_view_total_time":
						metrics.ig_reels_video_view_total_time = value;
						break;
					case "clips_replays_count":
						metrics.clips_replays_count = value;
						break;
					case "ig_reels_aggregated_all_plays_count":
						metrics.ig_reels_aggregated_all_plays_count = value;
						break;
					case "follows":
						metrics.follows = value;
						break;
				}
			}
		}

		if (contract.surface === "reel") {
			try {
				const { REEL_CROSSPOST_INSIGHT_METRICS } = await import(
					"../metaApiConfig.js"
				);
				const crosspostUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=${REEL_CROSSPOST_INSIGHT_METRICS}`;
				const crosspostRes = await igFetch(
					crosspostUrl,
					undefined,
					"igApi:reelCrosspostMetrics",
					token,
				);
				const crosspostData = await crosspostRes.json();
				if (crosspostRes.ok && !crosspostData.error && crosspostData.data) {
					for (const item of crosspostData.data) {
						const name = item.name?.toLowerCase();
						const value = item.values?.[0]?.value || 0;
						if (name === "crossposted_views") metrics.crossposted_views = value;
						if (name === "facebook_views") metrics.facebook_views = value;
					}
				} else if (!crosspostRes.ok || crosspostData.error) {
					logger.debug("IG Reel crosspost metrics unavailable", {
						mediaId,
						status: crosspostRes.status,
						error: JSON.stringify(crosspostData?.error || {}).slice(0, 240),
					});
				}
			} catch (crosspostErr) {
				logger.debug("IG Reel crosspost metrics fetch threw", {
					mediaId,
					error:
						crosspostErr instanceof Error
							? crosspostErr.message
							: String(crosspostErr),
				});
			}
		}

		// Facebook Login exposes richer media-node engagement fields directly on
		// /{ig_media_id}. Keep this non-fatal so Instagram Login or older
		// permission grants still sync via insights.
		if (loginType === "facebook") {
			try {
				const mediaFields = [
					"reposts_count",
					"saved_count",
					"shares_count",
					"total_like_count",
					"total_comments_count",
					"total_views_count",
				].join(",");
				const mediaRes = await igFetch(
					`${graphBase}/v25.0/${mediaId}?fields=${mediaFields}`,
					undefined,
					"igApi:mediaEngagementFields",
					token,
				);
				const mediaData = await mediaRes.json();
				if (mediaRes.ok && !mediaData.error) {
					metrics.reposts = mediaData.reposts_count ?? metrics.reposts;
					metrics.saved = mediaData.saved_count ?? metrics.saved;
					metrics.shares = mediaData.shares_count ?? metrics.shares;
					metrics.total_likes =
						mediaData.total_like_count ?? metrics.total_likes;
					metrics.total_comments =
						mediaData.total_comments_count ?? metrics.total_comments;
					metrics.total_views =
						mediaData.total_views_count ?? metrics.total_views;
				} else {
					logger.warn("IG media engagement fields non-ok", {
						mediaId,
						status: mediaRes.status,
						error: JSON.stringify(mediaData?.error || {}).slice(0, 240),
					});
				}
			} catch (mediaFieldsErr) {
				logger.warn("IG media engagement fields fetch threw", {
					mediaId,
					error:
						mediaFieldsErr instanceof Error
							? mediaFieldsErr.message
							: String(mediaFieldsErr),
				});
			}
		}

		// profile_activity is Feed + Story only (not Reels). Drives the
		// per-post Story → profile activity tile and the ig_profile_visits
		// column. Errors here are non-fatal but always logged so scope-missing
		// failures stay visible (they used to be silently swallowed).
		if (contract.surface === "feed_single") {
			try {
				const paUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=profile_activity&breakdown=action_type`;
				const paRes = await igFetch(
					paUrl,
					undefined,
					"igApi:profileActivity",
					token,
				);
				const paData = await paRes.json();
				if (
					paRes.ok &&
					paData.data?.[0]?.total_value?.breakdowns?.[0]?.results
				) {
					const profileActivity =
						paData.data[0].total_value.breakdowns[0].results.map(
							(r: {
								dimension_values?: string[] | undefined;
								value?: number | undefined;
							}) => ({
								action_type: r.dimension_values?.[0] || "unknown",
								value: r.value || 0,
							}),
						);
					metrics.profileActivity = profileActivity;
					// Derive ig_profile_visits as a top-level field from the
					// breakdown — frontend tiles read posts.ig_profile_visits
					// directly instead of unpacking the JSONB.
					const profileVisitsRow = profileActivity.find(
						(r: { action_type: string; value: number }) =>
							r.action_type === "profile_visits",
					);
					if (profileVisitsRow) {
						metrics.profile_visits = profileVisitsRow.value;
					}
				} else if (!paRes.ok) {
					logger.warn("IG profile_activity insights non-ok", {
						mediaId,
						status: paRes.status,
						error: JSON.stringify(paData?.error || {}).slice(0, 240),
					});
				}
			} catch (paErr) {
				// Don't fail the whole getInstagramPostMetrics call — but log
				// so we can spot scope/permission issues across the fleet.
				logger.warn("IG profile_activity fetch threw", {
					mediaId,
					error: paErr instanceof Error ? paErr.message : String(paErr),
				});
			}
		}

		if (metrics.reach > 0) {
			metrics.engagementRate =
				((metrics.likes + metrics.comments + metrics.shares + metrics.saved) /
					metrics.reach) *
				100;
		}

		return { success: true, metrics };
	} catch (error: unknown) {
		logger.error("IG get metrics error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Get Story Insights
// ============================================================================

/**
 * Get insights for an Instagram Story.
 * Stories have different metrics than regular posts.
 * Requires `instagram_business_manage_insights` permission scope.
 */
export async function getInstagramStoryMetrics(
	encryptedToken: string,
	mediaId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	metrics?: IGStoryMetrics | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// Story-specific metrics (v21+: `views` replaces `impressions`;
		// v18.0+: `navigation` replaces deprecated `taps_forward`/`taps_back`/`exits`)
		const { STORY_INSIGHT_METRICS } = await import("../metaApiConfig.js");
		const insightsUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=${STORY_INSIGHT_METRICS}`;

		logger.info("IG getStoryMetrics", { mediaId, loginType });

		const response = await igFetch(
			insightsUrl,
			undefined,
			"igApi:storyMetrics",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			logger.error("IG story insights error", {
				mediaId,
				error: JSON.stringify(data.error || data),
			});
			return {
				success: false,
				error: data.error?.message || "Failed to fetch story insights",
			};
		}

		const metrics: IGStoryMetrics = {
			views: 0,
			reach: 0,
			replies: 0,
			navigation: 0,
			follows: 0,
			shares: 0,
			total_interactions: 0,
			exits: 0,
			taps_forward: 0,
			taps_back: 0,
		};

		if (data.data) {
			for (const item of data.data) {
				const name = item.name?.toLowerCase();
				const value = item.values?.[0]?.value || 0;

				switch (name) {
					case "views":
						metrics.views = value;
						break;
					case "reach":
						metrics.reach = value;
						break;
					case "replies":
						metrics.replies = value;
						break;
					case "navigation":
						metrics.navigation = value;
						break;
					case "follows":
						metrics.follows = value;
						break;
					case "shares":
						metrics.shares = value;
						break;
					case "total_interactions":
						metrics.total_interactions = value;
						break;
				}
			}
		}

		// Backfill the legacy taps_back/taps_forward/exits columns from the v25
		// `navigation` breakdown so the dashboard's Story navigation tile keeps
		// rendering individual action counts. The base call returns only the
		// rolled-up `navigation` total — the per-action breakdown requires a
		// separate call. Errors are logged but non-fatal.
		try {
			const navUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=navigation&breakdown=story_navigation_action_type`;
			const navRes = await igFetch(
				navUrl,
				undefined,
				"igApi:storyNavigationBreakdown",
				token,
			);
			const navData = await navRes.json();
			if (
				navRes.ok &&
				navData.data?.[0]?.total_value?.breakdowns?.[0]?.results
			) {
				const results = navData.data[0].total_value.breakdowns[0]
					.results as Array<{
					dimension_values?: string[] | undefined;
					value?: number | undefined;
				}>;
				for (const r of results) {
					const action = (r.dimension_values?.[0] ?? "").toLowerCase();
					const v = r.value || 0;
					if (action === "tap_forward" || action === "swipe_forward") {
						metrics.taps_forward += v;
					} else if (action === "tap_back") {
						metrics.taps_back += v;
					} else if (action === "tap_exit" || action === "exit") {
						metrics.exits += v;
					}
				}
			} else if (!navRes.ok) {
				logger.warn("IG story navigation breakdown non-ok", {
					mediaId,
					status: navRes.status,
					error: JSON.stringify(navData?.error || {}).slice(0, 240),
				});
			}
		} catch (navErr) {
			logger.warn("IG story navigation breakdown threw", {
				mediaId,
				error: navErr instanceof Error ? navErr.message : String(navErr),
			});
		}

		// profile_activity + profile_visits require action_type breakdown (separate call).
		// Errors are non-fatal but always logged — silent swallowing was hiding
		// fleet-wide scope failures (instagram_business_manage_insights).
		try {
			const paUrl = `${graphBase}/v25.0/${mediaId}/insights?metric=profile_activity,profile_visits&breakdown=action_type`;
			const paRes = await igFetch(
				paUrl,
				undefined,
				"igApi:storyProfileActivity",
				token,
			);
			const paData = await paRes.json();
			if (paRes.ok && paData.data) {
				for (const item of paData.data) {
					if (item.name === "profile_visits") {
						metrics.profile_visits = item.values?.[0]?.value || 0;
					} else if (item.name === "profile_activity") {
						if (item.total_value?.breakdowns?.[0]?.results) {
							metrics.profile_activity =
								item.total_value.breakdowns[0].results.map(
									(r: {
										dimension_values?: string[] | undefined;
										value?: number | undefined;
									}) => ({
										action_type: r.dimension_values?.[0] || "unknown",
										value: r.value || 0,
									}),
								);
						}
					}
				}
			} else if (!paRes.ok) {
				logger.warn("IG story profile_activity insights non-ok", {
					mediaId,
					status: paRes.status,
					error: JSON.stringify(paData?.error || {}).slice(0, 240),
				});
			}
		} catch (paErr) {
			logger.warn("IG story profile_activity fetch threw", {
				mediaId,
				error: paErr instanceof Error ? paErr.message : String(paErr),
			});
		}

		return { success: true, metrics };
	} catch (error: unknown) {
		logger.error("IG get story metrics error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Follower Count (profile node — no insights permission required)
// ============================================================================

/**
 * Fetches `followers_count` directly from the IG User profile node.
 * Works for all Business/Creator accounts regardless of insights permissions.
 * Use as fallback when the insights API omits `follower_count`.
 */
export async function getIgFollowerCount(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<number | null> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}?fields=followers_count`;
		const res = await igFetch(url, undefined, "igApi:followerCount", token);
		if (!res.ok) return null;
		const data = (await res.json()) as { followers_count?: number | undefined };
		return typeof data.followers_count === "number"
			? data.followers_count
			: null;
	} catch {
		return null;
	}
}

// ============================================================================
// Get Account Insights
// ============================================================================

/** Requires `instagram_business_manage_insights` permission scope. */
export async function getInstagramAccountInsights(
	encryptedToken: string,
	igUserId: string,
	period: "day" | "week" | "days_28" = "day",
	loginType?: string,
): Promise<{
	success: boolean;
	insights?: IGAccountInsights | undefined;
	error?: string | undefined;
	partial?: boolean | undefined;
	missingMetrics?: string[] | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// Meta API requires metric_type parameter — see metaApiConfig.ts for details
		const { getTimeSeriesMetrics, getTotalValueMetrics } = await import(
			"../metaApiConfig.js"
		);

		interface InsightsApiResponse {
			data?:
				| Array<{
						name: string;
						values?: Array<{ value: number }> | undefined;
						total_value?: { value: number } | undefined;
						period?: string | undefined;
				  }>
				| undefined;
			error?:
				| {
						message?: string | undefined;
						code?: number | undefined;
						type?: string | undefined;
				  }
				| undefined;
		}

		const timeSeriesMetrics = getTimeSeriesMetrics(period);
		const totalValueMetrics = getTotalValueMetrics(loginType);

		const timeSeriesUrl = `${graphBase}/v25.0/${igUserId}/insights?metric=${timeSeriesMetrics}&period=${period}&metric_type=time_series`;
		const totalValueUrl = `${graphBase}/v25.0/${igUserId}/insights?metric=${totalValueMetrics}&period=${period}&metric_type=total_value`;

		logger.debug("IG getAccountInsights request", {
			igUserId,
			period,
			loginType,
			timeSeriesMetrics,
			totalValueMetrics,
		});

		// Fetch both metric types in parallel
		const [timeSeriesRes, totalValueRes] = await Promise.all([
			igFetch(timeSeriesUrl, undefined, "igApi:accountInsights", token),
			igFetch(totalValueUrl, undefined, "igApi:accountInsights", token),
		]);

		const timeSeriesData = (await timeSeriesRes.json()) as InsightsApiResponse;
		const totalValueData = (await totalValueRes.json()) as InsightsApiResponse;

		// Merge results from both calls
		const allMetricData = [
			...(timeSeriesData.data || []),
			...(totalValueData.data || []),
		];

		const timeSeriesFailed = !timeSeriesRes.ok || !!timeSeriesData.error;
		const totalValueFailed = !totalValueRes.ok || !!totalValueData.error;

		if (timeSeriesFailed) {
			logger.warn("IG time_series insights failed", {
				igUserId,
				status: timeSeriesRes.status,
				error: timeSeriesData.error?.message,
			});
		}
		if (totalValueFailed) {
			logger.warn("IG total_value insights failed", {
				igUserId,
				status: totalValueRes.status,
				error: totalValueData.error?.message,
			});
		}

		// If both API calls returned errors, return failure — don't silently return zeros.
		// Previously this only checked allMetricData.length === 0, which missed 401s
		// where Meta returns { error: {...} } with no data array.
		if (timeSeriesFailed && totalValueFailed) {
			const errorMsg =
				timeSeriesData.error?.message ||
				totalValueData.error?.message ||
				"Failed to fetch account insights";
			logger.error("IG account insights error — both calls failed", {
				igUserId,
				timeSeriesStatus: timeSeriesRes.status,
				totalValueStatus: totalValueRes.status,
				timeSeriesError: timeSeriesData.error?.message,
				totalValueError: totalValueData.error?.message,
			});
			return { success: false, error: errorMsg };
		}

		const allRequestedMetrics = `${timeSeriesMetrics},${totalValueMetrics}`;
		const returnedMetricNames = new Set(allMetricData.map((m) => m.name));
		const missingMetrics = allRequestedMetrics
			.split(",")
			.filter((m) => !returnedMetricNames.has(m));

		if (missingMetrics.length > 0) {
			logger.warn("IG insights partial response — some metrics missing", {
				igUserId,
				loginType,
				requested: allRequestedMetrics,
				returnedCount: allMetricData.length,
				returnedMetrics: [...returnedMetricNames].join(","),
				missingMetrics,
			});
		} else {
			logger.debug("IG getAccountInsights success", {
				igUserId,
				metricCount: allMetricData.length,
			});
		}

		// Track for aggregated alerting (flushPartialInsightsAlert at end of sync job)
		const { trackInsightsResponse } = await import("../alerting.js");
		trackInsightsResponse(missingMetrics.length > 0, missingMetrics);

		// Combine into insightsData for the parsing block below
		const insightsData: InsightsApiResponse = { data: allMetricData };

		const insights: IGAccountInsights = {
			reach: 0,
			views: 0,
			followerCount: 0,
			accountsEngaged: 0,
			totalInteractions: 0,
			profileLinksTaps: 0,
			reposts: 0,
			// Deprecated fields (backwards compatibility)
			impressions: 0,
			profileViews: 0,
			websiteClicks: 0,
			emailContacts: 0,
		};

		if (insightsData.data) {
			for (const item of insightsData.data) {
				const name = item.name?.toLowerCase();
				// time_series returns values[0].value, total_value returns total_value.value
				const value = item.values?.[0]?.value ?? item.total_value?.value ?? 0;
				logger.debug("IG insight metric", { name, value });

				switch (name) {
					case "reach":
						insights.reach = value;
						// P1 diagnostic (2026-04-24): ig_reach is zero across all accounts.
						// Log raw item shape so we can tell Meta-suppressed-zero from parser mismatch.
						logger.info("IG reach parse", {
							igUserId,
							period,
							loginType,
							parsedValue: value,
							hasValues: Array.isArray(item.values),
							valuesLen: item.values?.length ?? 0,
							firstValue: item.values?.[0],
							totalValue: item.total_value,
						});
						break;
					case "follower_count":
						insights.followerCount = value;
						break;
					case "accounts_engaged":
						insights.accountsEngaged = value;
						break;
					case "total_interactions":
						insights.totalInteractions = value;
						break;
					case "profile_links_taps":
						// v21+ metric
						insights.profileLinksTaps = value;
						insights.websiteClicks = value; // backwards compatibility
						break;
					case "reposts":
						insights.reposts = value;
						break;
					case "views":
						// v21+ primary metric (replaces deprecated impressions)
						insights.views = value;
						insights.impressions = value; // backwards compatibility
						break;
					// Deprecated metrics (may still be returned by some endpoints)
					case "impressions":
						insights.impressions = value;
						break;
					case "profile_views":
						insights.profileViews = value;
						break;
					case "website_clicks":
						insights.websiteClicks = value;
						insights.profileLinksTaps = value;
						break;
					case "email_contacts":
						insights.emailContacts = value;
						break;
				}
			}
		}

		// Fetch follower vs non-follower reach breakdown
		try {
			const breakdownUrl = `${graphBase}/v25.0/${igUserId}/insights?metric=reach&period=${period}&metric_type=total_value&breakdown=follower_type`;
			const breakdownRes = await igFetch(
				breakdownUrl,
				undefined,
				"igApi:reachBreakdown",
				token,
			);
			const breakdownData = await breakdownRes.json();
			if (
				breakdownRes.ok &&
				breakdownData.data?.[0]?.total_value?.breakdowns?.[0]?.results
			) {
				const results = breakdownData.data[0].total_value.breakdowns[0].results;
				let followerReach = 0;
				let nonFollowerReach = 0;
				for (const r of results) {
					const val = r.dimension_values?.[0]?.toUpperCase();
					if (val === "FOLLOWER") followerReach = r.value || 0;
					if (val === "NON_FOLLOWER") nonFollowerReach = r.value || 0;
				}
				const totalBreakdown = followerReach + nonFollowerReach;
				if (totalBreakdown > 0) {
					insights.nonFollowerReachPct = nonFollowerReach / totalBreakdown;
					insights.followerReach = followerReach;
					insights.nonFollowerReach = nonFollowerReach;
				}
			}
		} catch (breakdownErr) {
			logger.warn("IG follower reach breakdown failed (non-critical)", {
				error: String(breakdownErr),
			});
		}

		// Fetch follows_and_unfollows with follow_type breakdown (day-only)
		if (period === "day") {
			try {
				const followsUrl = `${graphBase}/v25.0/${igUserId}/insights?metric=follows_and_unfollows&period=day&metric_type=total_value&breakdown=follow_type`;
				const followsRes = await igFetch(
					followsUrl,
					undefined,
					"igApi:followsBreakdown",
					token,
				);
				const followsData = await followsRes.json();
				if (
					followsRes.ok &&
					followsData.data?.[0]?.total_value?.breakdowns?.[0]?.results
				) {
					const results = followsData.data[0].total_value.breakdowns[0].results;
					for (const r of results) {
						const val = r.dimension_values?.[0]?.toUpperCase();
						if (val === "FOLLOW") insights.newFollows = r.value || 0;
						if (val === "UNFOLLOW") insights.unfollows = r.value || 0;
					}
				}
			} catch (followsErr) {
				logger.warn("IG follows_and_unfollows failed (non-critical)", {
					error: String(followsErr),
				});
			}
		}

		// Fetch media_product_type breakdown (content type performance: Feed vs Reels vs Stories)
		try {
			const contentBreakdownUrl = `${graphBase}/v25.0/${igUserId}/insights?metric=reach,views,likes,comments,shares,saves&period=day&metric_type=total_value&breakdown=media_product_type`;
			const contentRes = await igFetch(
				contentBreakdownUrl,
				undefined,
				"igApi:contentTypeBreakdown",
				token,
			);
			const contentData = await contentRes.json();
			if (contentRes.ok && contentData.data?.length) {
				const breakdown: Record<string, Record<string, number>> = {};
				for (const metric of contentData.data) {
					const metricName = metric.name?.toLowerCase();
					const results = metric.total_value?.breakdowns?.[0]?.results;
					if (!metricName || !results) continue;
					for (const r of results) {
						const productType = r.dimension_values?.[0]?.toLowerCase();
						if (!productType) continue;
						if (!breakdown[productType]) breakdown[productType] = {};
						breakdown[productType][metricName] = r.value || 0;
					}
				}
				if (Object.keys(breakdown).length > 0) {
					insights.contentTypeBreakdown = {
						feed: breakdown.feed,
						reels: breakdown.reels,
						story: breakdown.story,
					};
				}
			}
		} catch (contentErr) {
			logger.warn("IG content type breakdown failed (non-critical)", {
				error: String(contentErr),
			});
		}

		return {
			success: true,
			insights,
			...(missingMetrics.length > 0 && { partial: true, missingMetrics }),
		};
	} catch (error: unknown) {
		logger.error("IG account insights error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Follower Demographics
// ============================================================================

/**
 * Fetch follower demographics from Instagram API.
 * Breakdown types: age, gender, city, country
 */
export async function getInstagramDemographics(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	breakdowns?: IGDemographicsBreakdown[] | undefined;
	engagedBreakdowns?: IGDemographicsBreakdown[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const breakdowns: IGDemographicsBreakdown[] = [];

		const breakdownTypes = ["age", "gender", "city", "country"] as const;
		const results = await Promise.allSettled(
			breakdownTypes.map(async (breakdown) => {
				const url = `${graphBase}/v25.0/${igUserId}/insights?metric=follower_demographics&metric_type=total_value&breakdown=${breakdown}&period=lifetime&timeframe=this_month`;
				const response = await igFetch(
					url,
					undefined,
					`igApi:demographics:${breakdown}`,
					token,
				);
				const data = await response.json();

				if (!response.ok || data.error) {
					logger.warn("IG demographics error", {
						breakdown,
						error: data.error?.message,
					});
					return null;
				}

				const values: { value: string; count: number }[] = [];
				if (data.data?.[0]?.total_value?.breakdowns?.[0]?.results) {
					for (const result of data.data[0].total_value.breakdowns[0].results) {
						const dimensionValue = result.dimension_values?.[0] || "unknown";
						values.push({ value: dimensionValue, count: result.value || 0 });
					}
				}

				if (values.length > 0) {
					return {
						breakdown_type: breakdown,
						values,
					} as IGDemographicsBreakdown;
				}
				return null;
			}),
		);

		for (const result of results) {
			if (result.status === "fulfilled" && result.value) {
				breakdowns.push(result.value);
			}
		}

		// Fetch engaged_audience_demographics (requires 100+ engagements in timeframe)
		let engagedBreakdowns: IGDemographicsBreakdown[] | undefined;
		try {
			const engagedResults = await Promise.allSettled(
				breakdownTypes.map(async (breakdown) => {
					const url = `${graphBase}/v25.0/${igUserId}/insights?metric=engaged_audience_demographics&metric_type=total_value&breakdown=${breakdown}&period=lifetime&timeframe=this_month`;
					const response = await igFetch(
						url,
						undefined,
						`igApi:engagedDemographics:${breakdown}`,
						token,
					);
					const data = await response.json();

					if (!response.ok || data.error) {
						return null;
					}

					const values: { value: string; count: number }[] = [];
					if (data.data?.[0]?.total_value?.breakdowns?.[0]?.results) {
						for (const result of data.data[0].total_value.breakdowns[0]
							.results) {
							const dimensionValue = result.dimension_values?.[0] || "unknown";
							values.push({ value: dimensionValue, count: result.value || 0 });
						}
					}

					if (values.length > 0) {
						return {
							breakdown_type: breakdown,
							values,
						} as IGDemographicsBreakdown;
					}
					return null;
				}),
			);

			const collected: IGDemographicsBreakdown[] = [];
			for (const result of engagedResults) {
				if (result.status === "fulfilled" && result.value) {
					collected.push(result.value);
				}
			}
			if (collected.length > 0) {
				engagedBreakdowns = collected;
			}
		} catch (engagedErr) {
			logger.warn("IG engaged_audience_demographics failed (non-critical)", {
				error: String(engagedErr),
			});
		}

		return { success: true, breakdowns, engagedBreakdowns };
	} catch (error: unknown) {
		logger.error("IG demographics error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Online Followers
// ============================================================================

/**
 * Get online followers (hours 0-23 UTC) — audience activity data.
 * Returns last 30 days of hourly follower online counts.
 */
export async function getOnlineFollowers(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	data?: Record<string, number> | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const url = `${graphBase}/v25.0/${igUserId}/insights?metric=online_followers&period=lifetime`;
		const response = await igFetch(
			url,
			undefined,
			"igApi:onlineFollowers",
			token,
		);
		const result = await response.json();

		if (!response.ok || result.error) {
			return {
				success: false,
				error: result.error?.message || "Failed to fetch online followers",
			};
		}

		// Extract hourly data from the response
		const metric = (
			result.data as
				| Array<{
						name: string;
						values?: Array<{ value: Record<string, number> }> | undefined;
				  }>
				| undefined
		)?.find((d) => d.name === "online_followers");
		if (!metric?.values?.[0]?.value) {
			return { success: false, error: "No online followers data available" };
		}

		return { success: true, data: metric.values[0].value };
	} catch (error: unknown) {
		logger.error("IG getOnlineFollowers error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Carousel Child Insights
// ============================================================================

/**
 * Get carousel children and their individual insights.
 */
export async function getCarouselChildInsights(
	encryptedToken: string,
	carouselMediaId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	children?: IGCarouselChild[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// Fetch children
		const childrenUrl = `${graphBase}/v25.0/${carouselMediaId}/children?fields=id,media_type,media_url,timestamp`;
		const childrenRes = await igFetch(
			childrenUrl,
			undefined,
			"igApi:carouselChildren",
			token,
		);
		const childrenData = await childrenRes.json();

		if (!childrenRes.ok || childrenData.error) {
			return {
				success: false,
				error:
					childrenData.error?.message || "Failed to fetch carousel children",
			};
		}

		const kids = childrenData.data || [];
		if (kids.length === 0) {
			return { success: true, children: [] };
		}

		// Fetch insights for each child (limit concurrency to 3)
		const results: IGCarouselChild[] = [];
		for (let i = 0; i < kids.length; i += 3) {
			const chunk = kids.slice(i, i + 3) as IGCarouselChildRaw[];
			const chunkResults = await Promise.all(
				chunk.map(async (child: IGCarouselChildRaw, j: number) => {
					try {
						const { POST_INSIGHT_METRICS: childMetrics } = await import(
							"../metaApiConfig.js"
						);
						const insightsUrl = `${graphBase}/v25.0/${child.id}/insights?metric=${childMetrics}`;
						const insightsRes = await igFetch(
							insightsUrl,
							undefined,
							"igApi:carouselChildInsights",
							token,
						);
						const insightsData = await insightsRes.json();

						const metrics: Record<string, number> = {};
						if (insightsRes.ok && insightsData.data) {
							for (const m of insightsData.data) {
								metrics[m.name] = m.values?.[0]?.value ?? 0;
							}
						}

						return {
							id: child.id,
							mediaType: child.media_type,
							mediaUrl: child.media_url,
							position: i + j,
							metrics: {
								impressions: metrics.views ?? 0,
								reach: metrics.reach ?? 0,
								likes: metrics.likes ?? 0,
								comments: metrics.comments ?? 0,
								shares: metrics.shares ?? 0,
								saved: metrics.saved ?? 0,
							},
						};
					} catch (err) {
						logger.debug("Failed to fetch insights for carousel child media", {
							childId: child.id,
							error: String(err),
						});
						return {
							id: child.id,
							mediaType: child.media_type,
							mediaUrl: child.media_url,
							position: i + j,
							metrics: {
								impressions: 0,
								reach: 0,
								likes: 0,
								comments: 0,
								shares: 0,
								saved: 0,
							},
						};
					}
				}),
			);
			results.push(...chunkResults);
		}

		return { success: true, children: results };
	} catch (error: unknown) {
		logger.error("IG getCarouselChildInsights error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
