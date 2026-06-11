/**
 * API Service - Unified re-export
 * Maintains backward compatibility: apiService.methodName() works as before
 */

import * as accounts from "./accounts.js";
import * as analytics from "./analytics.js";
import * as instagram from "./instagram.js";
import * as media from "./media.js";
import * as posts from "../../src/services/api/posts.js";

export const apiService = {
	// Auth
	initiateLogin: accounts.initiateLogin,
	initiateInstagramLogin: accounts.initiateInstagramLogin,
	initiateFacebookLogin: accounts.initiateFacebookLogin,
	exchangeToken: accounts.exchangeToken,
	checkAuthStatus: accounts.checkAuthStatus,

	// Accounts
	getAccounts: accounts.getAccounts,
	getAccount: accounts.getAccount,
	getAccountThreads: accounts.getAccountThreads,
	syncAccount: (id: string) => analytics.syncAnalytics(id),

	// Instagram accounts
	getInstagramAccounts: instagram.getInstagramAccounts,
	getInstagramInsights: instagram.getInstagramInsights,
	getInstagramPostInsights: instagram.getInstagramPostInsights,

	// Posts
	getPosts: posts.getPosts,
	getPostsLegacy: posts.getPostsLegacy,
	subscribeToPostsRealtime: posts.subscribeToPostsRealtime,
	getPost: posts.getPost,
	createPost: posts.createPost,
	updatePost: posts.updatePost,
	deletePost: posts.deletePost,
	duplicatePost: posts.duplicatePost,
	publishPostNow: posts.publishPostNow,
	lookupPostByUrl: posts.lookupPostByUrl,
	cleanupDuplicatePosts: posts.cleanupDuplicatePosts,
	getQueuedPostsForCalendar: posts.getQueuedPostsForCalendar,

	// Analytics
	getAnalytics: analytics.getAnalytics,
	getAggregatedAnalytics: analytics.getAggregatedAnalytics,
	getAnalyticsStats: analytics.getAnalyticsStats,
	getAnalyticsWithDeltas: analytics.getAnalyticsWithDeltas,
	syncAnalytics: analytics.syncAnalytics,
	syncInstagramAnalytics: analytics.syncInstagramAnalytics,
	syncAllAnalytics: analytics.syncAllAnalytics,
	queueSync: analytics.queueSync,
	backfillHistoricalAnalytics: analytics.backfillHistoricalAnalytics,
	rebackfillAnalytics: analytics.rebackfillAnalytics,
	fixAccountBaselines: analytics.fixAccountBaselines,
	fetchFollowerDemographics: analytics.fetchFollowerDemographics,
	backfillAllHistoricalAnalytics: analytics.backfillAllHistoricalAnalytics,
	getDailyActivity: analytics.getDailyActivity,

	// Media
	refreshPostMedia: media.refreshPostMedia,
};
