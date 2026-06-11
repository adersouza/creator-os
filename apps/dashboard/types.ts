// Helper type for timestamp fields (supports Date, ISO string, or objects with toDate method)
export type TimestampLike = Date | string | { toDate?: () => Date | undefined };

// Type guard to check if value has toDate method (e.g., Supabase or legacy Firestore timestamps)
export function hasToDateMethod(
  value: unknown,
): value is { toDate: () => Date } {
  return (
    value !== null &&
    typeof value === "object" &&
    "toDate" in value &&
    typeof (value as { toDate?: unknown | undefined }).toDate === "function"
  );
}

// Convert TimestampLike to Date
export function toDate(value: TimestampLike): Date {
  if (value instanceof Date) return value;
  if (hasToDateMethod(value)) return value.toDate();
  return new Date(value as string);
}

export type Platform = "threads" | "instagram" | "bluesky" | "tiktok";

export type IGMediaType = "IMAGE" | "VIDEO" | "REELS" | "CAROUSEL" | "CAROUSEL_ALBUM" | "STORIES";

export enum PostStatus {
  PUBLISHED = "published",
  SCHEDULED = "scheduled",
  DRAFT = "draft",
  PUBLISHING = "publishing",
  FAILED = "failed",
  PENDING_APPROVAL = "pending_approval",
}

// Text spoiler entity for Threads API
export interface SpoilerEntity {
  entity_type: "SPOILER";
  offset: number;
  length: number;
}

// Text styling for long-form content
export type TextStylingType =
  | "bold"
  | "italic"
  | "highlight"
  | "underline"
  | "strikethrough";

export interface TextStylingInfo {
  offset: number;
  length: number;
  styling_info: TextStylingType[];
}

// Text attachment for long-form content (up to 10K characters)
export interface TextAttachment {
  plaintext: string;
  link_attachment_url?: string | undefined;
  text_with_styling_info?: TextStylingInfo[] | undefined;
}

// Poll attachment for Threads polls
export interface PollAttachment {
  option_a: string;
  option_b: string;
  option_c?: string | undefined;
  option_d?: string | undefined;
}

// Post settings
export interface PostSettings {
  allowReplies: boolean;
  whoCanReply: "everyone" | "followers" | "mentioned" | "author_only" | "followers_only";
}

export interface ThreadPost {
  id: string;
  content: string;
  mediaUrls: string[];
  scheduledDate?: string | undefined; // ISO string
  status: PostStatus;
  likes: number;
  replies: number;
  accountId: string;
  accountHandle?: string | undefined;
  accountAvatarUrl?: string | undefined;
  threadId?: string | undefined; // The actual Threads post ID for external link
  permalink?: string | undefined; // Full URL to the Threads post
  // Platform discriminator
  platform?: Platform | undefined;
  // Instagram-specific fields
  instagramPostId?: string | undefined; // Instagram media ID
  instagramAccountId?: string | undefined; // FK to instagram_accounts
  igMediaType?: IGMediaType | undefined; // Instagram media type
  altText?: string | undefined; // Instagram image accessibility text
  isTrialReel?: boolean | undefined; // Instagram Trial Reel (test without full publish)
  // Advanced posting features
  topics?: string[] | undefined; // Hashtag topics
  linkUrl?: string | undefined; // Link attachment URL
  locationId?: string | undefined; // Location tag ID
  collaborators?: string[] | undefined; // Instagram usernames to invite as collaborators (max 3, Facebook Login only)
  quotePostId?: string | undefined; // Post ID being quoted
  pollAttachment?: PollAttachment | undefined; // Poll options (text-only posts)
  isSpoiler?: boolean | undefined; // Mark media as spoiler
  textSpoilers?: SpoilerEntity[] | undefined; // Text spoiler entities (max 10)
  allowlistedCountryCodes?: string[] | undefined; // ISO 3166-1 alpha-2 country codes for geo-gating
  textAttachment?: TextAttachment | undefined; // Long-form content (up to 10K chars)
  settings?: PostSettings | undefined; // Reply controls
  publishedAt?: TimestampLike | undefined; // When the post was published
  views?: number | undefined; // Legacy field - prefer performance.views
  performance?: {
            // Performance metrics from Threads API
            views?: number | undefined;
            likes?: number | undefined;
            replies?: number | undefined;
            reposts?: number | undefined;
            quotes?: number | undefined;
            shares?: number | undefined;
          } | undefined;
  // Instagram-specific metrics
  igImpressions?: number | undefined;
  igReach?: number | undefined;
  igSaved?: number | undefined;
  igShares?: number | undefined;
  igPlays?: number | undefined;
  igReplays?: number | undefined;
  igReelsAvgWatchTime?: number | undefined;
  igClipsReplays?: number | undefined;
  storyExpiresAt?: Date | null | undefined;
  contentCategory?: string | null | undefined;
  metadata?: Record<string, unknown> | null | undefined;
  createdAt?: string | undefined;
  // Cross-posting
  crossPostGroupId?: string | undefined; // UUID linking Threads + Instagram posts in a cross-post pair
  isGhostPost?: boolean | undefined; // Ghost-mode publish (no feed appearance)
  crossreshareToIg?: boolean | undefined; // Reshare Threads post to IG Story
  crossreshareToIgDarkMode?: boolean | undefined; // Dark mode for IG Story reshare
  shareToFeed?: boolean | undefined; // Share Reel to main feed
  // Favorites
  isFavorite?: boolean | undefined;
  // Evergreen recycling
  isEvergreen?: boolean | undefined;
  evergreenIntervalDays?: number | undefined;
  evergreenMinEngagement?: number | undefined;
  recycleCount?: number | undefined;
  maxRecycles?: number | undefined;
  lastRecycledAt?: string | undefined;
  // Snake-case DB field aliases (present when raw rows are spread)
  media_urls?: string[] | undefined;
  media_type?: string | undefined;
  media_url?: string | undefined;
  thumbnail_url?: string | undefined;
}

export interface InstagramAccount {
  id: string;
  platform: "instagram";
  handle: string;
  username?: string | undefined;
  displayName?: string | undefined;
  avatarUrl: string;
  accountType?: string | undefined; // 'PERSONAL' | 'BUSINESS' | 'CREATOR'
  followers: number;
  followersCount?: number | undefined;
  followingCount?: number | undefined;
  mediaCount?: number | undefined;
  instagramUserId: string;
  isActive: boolean;
  status?: "active" | "suspended" | "pending" | undefined;
  needsReauth?: boolean | undefined;
  loginType?: "instagram" | "facebook" | undefined;
  facebookPageId?: string | undefined;
  createdAt?: string | undefined;
  updatedAt?: string | undefined;
  lastSyncedAt?: Date | null | undefined;
  tokenExpiresAt?: Date | null | undefined;
}

// Reply from Threads API
export interface ThreadReply {
  id: string;
  postId: string; // Parent post ID in our system
  threadsReplyId: string; // Threads API reply ID
  text: string;
  username: string;
  profilePicUrl?: string | undefined; // User's profile picture URL
  timestamp: TimestampLike;
  // NOTE: likeCount and replyCount on reply objects are undocumented Threads API fields.
  // They may be removed without notice — always use fallback (e.g. ?? 0) when consuming.
  likeCount?: number | undefined;
  replyCount?: number | undefined;
  isRead: boolean;
  isHidden: boolean; // Whether the reply is hidden on Threads
  // Account info for display
  accountId: string;
  accountHandle?: string | undefined;
  // Original post preview
  originalPostContent?: string | undefined;
}

// Mention from Threads API - when someone mentions your account
export interface ThreadMention {
  id: string;
  threadsMentionId: string; // Threads API mention ID
  text: string;
  username: string;
  timestamp: TimestampLike;
  mediaType?: "IMAGE" | "VIDEO" | null | undefined;
  mediaUrl?: string | null | undefined;
  permalink?: string | null | undefined;
  isReply: boolean; // Whether this mention is a reply
  accountId: string;
  accountHandle: string;
  isRead: boolean;
  fetchedAt: TimestampLike;
}

// Threaded conversation - groups replies by parent post
export interface ThreadedConversation {
  postId: string;
  accountId: string;
  accountHandle: string;
  parentPost: {
    id: string;
    content: string;
    mediaUrls: string[];
    publishedAt: Date;
    metrics: {
      likes: number;
      replies: number;
    };
  };
  replies: ThreadReply[];
  unreadCount: number;
  latestReplyAt: Date;
}

// Sort options for threaded inbox view
export type ThreadSortOption = "latest" | "oldest" | "unread" | "engagement";

export interface ThreadAccount {
  id: string;
  handle: string;
  username?: string | undefined;
  avatarUrl: string;
  followers: number;
  followersCount?: number | undefined; // Legacy field, use followers
  isActive: boolean;
  status?: "active" | "suspended" | "pending" | undefined; // Account status
  groupId?: string | undefined; // Optional reference to parent group
  threadsUserId?: string | undefined; // Threads API user ID
  igUserId?: string | undefined; // Instagram user ID (for IG-associated accounts)
  platform?: Platform | undefined; // Which platform this account belongs to
  // Snake-case DB field aliases (present when raw rows are spread)
  threads_user_id?: string | undefined;
  ig_user_id?: string | undefined;
  lastSyncedAt?: { toDate?: () => Date | undefined } | Date | undefined; // Last analytics sync
}

export interface AnalyticsData {
  date: string;
  followers: number;
  engagement: number;
}

export interface GeminiResponse {
  text: string;
}

export enum ViewMode {
  DASHBOARD = "Dashboard",
  CALENDAR = "Calendar",
  POSTS = "Posts",
  REPLIES = "Replies",
  ANALYTICS = "Analytics",
  DISCOVER = "Discover",
  COMPETITORS = "Competitors",
  MEDIA = "Media Library",
  GROUPS = "Groups",
  TEAM = "Team & Access",
  SETTINGS = "Settings",
  AUTO_POSTER = "Auto-Poster",
  IG_ANALYTICS = "IG Analytics",
  IG_HASHTAGS = "IG Hashtags",
  IG_MENTIONS = "IG Mentions",
  IG_INBOX = "IG Inbox",
  IG_COLLABS = "IG Collabs",
  IG_STORIES = "IG Stories",
  IG_DM_TEMPLATES = "DM Templates",
  OVERVIEW = "Overview",
  APPROVAL_QUEUE = "Approval Queue",
  SOCIAL_LISTENING = "Social Listening",
  CREATOR_TOOLS = "Creator Tools",
  UNIFIED_INBOX = "Unified Inbox",
  SYSTEM_HEALTH = "System Health",
  REPORTS = "Reports",
  LINK_IN_BIO = "Link in Bio",
  EXPLORE = "Explore",
  CREATOR_HUB = "Creator Hub",
  AI_STUDIO = "AI Studio",
}

// Group categories for fleet organization
export type GroupCategory =
  | "personal"
  | "clients"
  | "high-performers"
  | "uncategorized";

// Group for organizing accounts (e.g., by creator/influencer)
export interface Group {
  id: string;
  name: string;
  accountIds: string[];
  category?: GroupCategory | undefined; // Category for tab filtering
  color?: string | undefined; // Optional theme color for visual grouping
  voiceProfile?: Record<string, unknown> | null | undefined; // Group-level voice profile for AI content
  createdAt: Date;
  updatedAt: Date;
}

export type TeamRole = "Admin" | "Editor" | "Viewer";

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: TeamRole;
  avatarUrl: string;
  status: "Active" | "Pending";
}

// Notification Types
export enum NotificationType {
  // Post-related
  POST_PUBLISHED = "post_published",
  POST_FAILED = "post_failed",
  POST_SCHEDULED = "post_scheduled",

  // Reply-related
  NEW_REPLY = "new_reply",

  // Analytics-related
  FOLLOWER_MILESTONE = "follower_milestone",
  ENGAGEMENT_SPIKE = "engagement_spike",
  TREND_SPIKE = "trend_spike",

  // Goal-related
  GOAL_MILESTONE = "goal_milestone",
  GOAL_COMPLETED = "goal_completed",
  GOAL_AT_RISK = "goal_at_risk",

  // Account-related
  ACCOUNT_CONNECTED = "account_connected",
  ACCOUNT_DISCONNECTED = "account_disconnected",
  TOKEN_EXPIRING = "token_expiring",

  // Team-related
  TEAM_MEMBER_JOINED = "team_member_joined",
  TEAM_MEMBER_LEFT = "team_member_left",
  TEAM_INVITE_RECEIVED = "team_invite_received",

  // Competitor
  COMPETITOR_VIRAL = "competitor_viral",

  // Auto-poster
  QUEUE_LOW = "queue_low",

  // Reports
  REPORT_READY = "report_ready",

  // Subscription
  TRIAL_ENDING = "trial_ending",

  // System
  SYSTEM_ANNOUNCEMENT = "system_announcement",
  FEATURE_UPDATE = "feature_update",

  // Quick Win results
  QUICK_WIN_RESULT = "quick_win_result",
  QUICK_WIN_REGRESSED = "quick_win_regressed",
  QUICK_WIN_FADED = "quick_win_faded",
}

// ============================================================================
// Instagram Advanced Feature Types
// ============================================================================

export interface IGComment {
  id: string;
  text: string;
  username: string;
  timestamp: string;
  like_count: number;
  hidden: boolean;
  replies?: {
            data: IGComment[];
          } | undefined;
}

export interface IGHashtag {
  id: string;
  name: string;
}

export interface IGHashtagMedia {
  id: string;
  caption?: string | undefined;
  media_type: string;
  media_url?: string | undefined;
  permalink: string;
  timestamp: string;
  like_count?: number | undefined;
  comments_count?: number | undefined;
}

export interface IGMention {
  id: string;
  caption?: string | undefined;
  media_type: string;
  media_url?: string | undefined;
  permalink: string;
  timestamp: string;
  username: string;
}

export interface IGWebhookEvent {
  id: string;
  event_type: string;
  ig_user_id: string;
  payload: Record<string, unknown>;
  received_at: string;
  processed: boolean;
  processed_at?: string | undefined;
  error?: string | undefined;
}

export interface IGBusinessProfile {
  username: string;
  name: string;
  biography: string;
  followers_count: number;
  media_count: number;
  profile_picture_url: string;
  website?: string | undefined;
}

export interface IGBusinessMedia {
  id: string;
  caption?: string | undefined;
  media_type: string;
  media_url?: string | undefined;
  permalink: string;
  timestamp: string;
  like_count?: number | undefined;
  comments_count?: number | undefined;
}

export interface IGConversation {
  id: string;
  participants: {
    data: Array<{ id: string; username?: string | undefined; name?: string | undefined }>;
  };
  updated_time: string;
}

export interface IGMessage {
  id: string;
  message: string;
  from: { id: string; name?: string | undefined; username?: string | undefined };
  to: { data: Array<{ id: string; name?: string | undefined }> };
  created_time: string;
}

export interface BatchRequest {
  method: "GET" | "POST" | "DELETE";
  relative_url: string;
  body?: string | undefined;
}

export interface BatchResponse {
  code: number;
  headers: Array<{ name: string; value: string }>;
  body: string;
}

export type NotificationPriority = "low" | "medium" | "high" | "urgent";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  read: boolean;
  priority: NotificationPriority;
  createdAt: TimestampLike;
  actionUrl?: string | undefined; // Optional URL to navigate to when clicked
  metadata?: {
            postId?: string | undefined;
            accountId?: string | undefined;
            accountHandle?: string | undefined;
            milestone?: number | undefined;
            teamMemberId?: string | undefined;
            teamMemberName?: string | undefined;
            [key: string]: unknown;
          } | undefined;
}
