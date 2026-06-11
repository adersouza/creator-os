/**
 * Analytics Type Definitions
 */

import type { ThreadPost } from "./index";

export interface AnalyticsDataPoint {
  date: Date;
  followers: number;
  views: number;
  likes: number;
  replies: number;
  reposts: number;
  quotes: number;
}

export interface PostPerformance {
  views: number;
  likes: number;
  replies: number;
  reposts: number;
  quotes: number;
  shares: number;
}

export interface ThreadPostWithAnalytics extends ThreadPost {
  performance?: PostPerformance | undefined;
  publishedAt?: Date | undefined;
  scheduledFor?: Date | { toDate?: () => Date | undefined } | undefined;
  accountAvatarUrl?: string | undefined;
  accountHandle?: string | undefined;
  isFavorite?: boolean | undefined;
}

export interface TopPost {
  id: string;
  content: string;
  views: number;
  likes: number;
  replies: number;
  reposts: number;
  quotes: number;
  publishedAt: Date;
  accountId: string;
  accountUsername?: string | undefined;
  mediaUrls?: string[] | undefined;
  performance?: PostPerformance | undefined;
}

// Goal Types
export type GoalType =
  | "followers"
  | "engagement_rate"
  | "weekly_posts"
  | "weekly_views"
  | "daily_replies"
  | "monthly_posts"
  | "viral_post"
  | "collaboration";

export interface Goal {
  id: string;
  name: string;
  type: GoalType;
  targetValue: number;
  currentValue?: number | undefined;
  deadline?: Date | string | undefined;
  createdAt: Date | string;
  completedAt?: Date | string | undefined;
  color?: string | undefined;
  icon?: string | undefined;
}

export interface GoalSnapshot {
  date: Date | string;
  currentValue: number;
  targetValue: number;
  progress: number; // percentage
}

export interface UserGoals {
  // Legacy fields (keep for backward compatibility)
  followerGoal?: number | undefined;
  engagementRateGoal?: number | undefined;
  dailyPostsGoal?: number | undefined;
  weeklyViewsGoal?: number | undefined;
  celebrationAnimation?: "confetti" | "fireworks" | "hearts" | "stars" | undefined;

  // New fields
  goals?: Goal[] | undefined;
  activeGoalIds?: string[] | undefined; // IDs of goals shown on dashboard (max 6)
}

export interface AnalyticsStats {
  totalFollowers: number;
  totalLikes: number;
  totalReplies: number;
  totalViews: number;
  totalReposts: number;
  totalQuotes: number;
  totalShares: number;
  totalClicks: number;
  scheduledCount: number;
  engagementRate?: number | undefined;
  totalIgImpressions?: number | undefined;
  totalIgReach?: number | undefined;
  totalIgSaved?: number | undefined;
  totalIgShares?: number | undefined;
  igNewFollows?: number | undefined;
  igUnfollows?: number | undefined;
  igAccountsEngaged?: number | undefined;
  igProfileViews?: number | undefined;
  igWebsiteClicks?: number | undefined;
  igTotalInteractions?: number | undefined;
  igNonFollowerReachPct?: number | undefined;
  /** Server-side exact count of published posts in the selected period (no client limit). */
  periodPostCount?: number | undefined;
  /** IG saves / reach. Strongest algorithm-ranking proxy Meta exposes. 0–1. */
  igSaveRate?: number | undefined;
  /** IG reels avg seconds watched per view = total_watch_time / views. */
  igReelsWatchPerView?: number | undefined;
  /** Threads quotes / replies. Signals "hot take" (>1) vs "conversation" (<1). */
  threadsQuoteReplyRatio?: number | undefined;
}



export interface ChartDataPoint {
  date: string;
  followers?: number | undefined;
  views?: number | undefined;
  likes?: number | undefined;
  replies?: number | undefined;
  reposts?: number | undefined;
  quotes?: number | undefined;
  engagement?: number | undefined;
}

export type TimeframeType = "7d" | "30d" | "90d" | "all";

// Growth Simulator Types
export interface SimulationSettings {
  postFrequency: number; // posts per day (1-10)
  useCarousels: boolean;
  useBoldHooks: boolean;
  useHashtags: boolean;
  replyToComments: boolean;
  postAtOptimalTimes: boolean;
  contentMix: "text" | "mixed" | "media-heavy";
  mediaPercentage?: number | undefined; // 0-50% media usage for forecast
}

export interface SimulationProjection {
  day: number;
  date: string;
  currentFollowers: number;
  projectedFollowers: number;
  currentViews: number;
  projectedViews: number;
  currentEngagement: number;
  projectedEngagement: number;
  upperBound?: number | undefined; // Confidence band upper limit
  lowerBound?: number | undefined; // Confidence band lower limit
}

export interface SimulationResult {
  projections: SimulationProjection[];
  summary: {
    followerUplift: number; // percentage
    viewsUplift: number;
    engagementUplift: number;
    projectedFollowers30d: number;
    projectedFollowers90d: number;
    projectedViews30d: number;
    keyInsights: string[];
  };
  bestTimeHeatmap: {
    day: number; // 0-6 (Sun-Sat)
    hour: number; // 0-23
    score: number; // 0-100
  }[];
}

export interface GrowthSimulatorData {
  currentFollowers: number;
  currentViews: number;
  currentEngagement: number;
  avgDailyPosts: number;
  topPostFormats: string[];
  bestPerformingDays: string[];
  avgLikesPerPost: number;
  avgRepliesPerPost: number;
}

// ============================================
// Trending Topics Widget Types
// ============================================

export interface TrendingTopic {
  id: string;
  name: string; // hashtag or topic name
  engagementScore: number; // calculated engagement score
  postCount: number; // number of posts using this topic
  trend: "up" | "down" | "stable";
  percentChange: number; // % change from previous period
  category?: string | undefined; // optional category (tech, lifestyle, etc.)
}

// ============================================
// Conversation Tracker Widget Types
// ============================================

export type SentimentType = "positive" | "neutral" | "negative" | "question" | "toxic";


export interface ConversationThread {
  id: string;
  postId: string;
  accountId: string; // account that owns the post
  postContent: string; // truncated ~100 chars
  latestReplyContent?: string | undefined; // the actual reply text from someone else
  latestReplyId?: string | undefined; // threads_reply_id for replying to
  replyCount: number;
  sentRepliesCount: number; // replies user has sent
  sentimentTags: SentimentType[];
  latestReplyAt: Date;
  unreadCount: number;
  topRepliers: {
    username: string;
    avatarUrl?: string | undefined;
    replyCount: number;
  }[];
}

// ============================================
// Engagement Forecast Types
// ============================================

export interface EngagementForecast {
  expectedFollowersPerWeek: number;
  expectedViewsPerWeek: number;
  confidenceLevel: "low" | "medium" | "high";
  summary: string; // e.g., "+15 followers/week"
}

export interface HistoricalGrowthData {
  date: string;
  followers: number;
  views: number;
  likes: number;
  engagementRate: number;
}

// ============================================
// Database Row Types
// ============================================

export interface AccountAnalyticsRow {
  id: string;
  account_id: string;
  date: string;
  followers_count: number;
  following_count: number;
  total_views: number;
  total_likes: number;
  total_replies: number;
  total_reposts: number;
  total_quotes: number;
  total_shares: number;
  total_clicks?: number | undefined;
  total_reach?: number | undefined;
  total_saves?: number | undefined;
  ig_impressions?: number | undefined;
  ig_new_follows?: number | undefined;
  ig_unfollows?: number | undefined;
  ig_accounts_engaged?: number | undefined;
  ig_profile_views?: number | undefined;
  ig_website_clicks?: number | undefined;
  ig_total_interactions?: number | undefined;
  ig_non_follower_reach_pct?: number | undefined;
  engagement_rate: number;
  follower_growth: number;
  created_at: string;
  updated_at: string;
}

export interface MappedAnalyticsRow extends Partial<AccountAnalyticsRow> {
  accountId?: string | undefined;
  accountHandle?: string | undefined;
  date: string; // Formatted date string
  rawDate: Date;
  followers: number; // Alias for followersCount
  followersCount: number;
  followingCount: number;

  views: number;
  likes: number;
  replies: number;
  reposts: number;
  quotes: number;
  shares: number;
  clicks: number;
  engagementRate: number;
  followerGrowth: number;
  isBackfilled: boolean;
}

export interface SyncJobStatus {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  current_progress: number;
  account_count: number;
  success_count: number;
  failed_count: number;
  suspended_accounts: string[];
  reactivated_accounts: string[];
  created_at: string;
}

export interface SyncJobProgress {
  current: number;
  total: number;
  status: string;
}

export interface SyncResultSingle {
  success: boolean;
  skipped?: boolean | undefined;
  error?: string | undefined;
  suspended?: boolean | undefined;
  reactivated?: boolean | undefined;
  username?: string | undefined;
}

export interface SyncResult {
  results: SyncResultSingle[];
  suspendedAccounts: string[];
  reactivatedAccounts: string[];
  error?: string | undefined;
  summary?: {
            total: number;
            success: number;
            failed: number;
            suspended: number;
          } | undefined;
}
