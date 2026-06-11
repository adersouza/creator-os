/**
 * Database Types for API Routes
 *
 * These types match the Supabase schema
 */

export interface Account {
	id: string;
	user_id: string;
	threads_user_id: string | null;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	bio: string | null;
	posting_method: string | null;
	threads_access_token_encrypted: string | null;
	token_expires_at: string | null;
	is_active: boolean;
	status: string | null;
	followers_count: number;
	following_count: number;
	posts_count: number;
	baseline_followers_count: number;
	baseline_following_count: number;
	baseline_posts_count: number;
	last_synced_at: string | null;
	created_at: string;
	updated_at: string;
}

export interface Post {
	id: string;
	user_id: string;
	account_id: string;
	account_handle: string | null;
	thread_id: string | null;
	permalink: string | null;
	content: string;
	media: { type: string; url: string }[] | null;
	media_type: string | null;
	thumbnail_url: string | null;
	topics: string[] | null;
	link_url: string | null;
	location_id: string | null;
	quote_post_id: string | null;
	poll_attachment: Record<string, unknown> | null;
	is_spoiler: boolean;
	text_spoilers: Record<string, unknown>[] | null;
	allowlisted_country_codes: string[] | null;
	text_attachment: Record<string, unknown> | null;
	settings: Record<string, unknown> | null;
	status: string;
	error: string | null;
	scheduled_for: string | null;
	published_at: string | null;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
	engagement_rate: number;
	last_fetched_at: string | null;
	imported_from_threads: boolean;
	created_at: string;
	updated_at: string;
}

export interface Reply {
	id: string;
	post_id: string;
	threads_reply_id: string;
	text: string;
	username: string;
	profile_pic_url: string | null;
	timestamp: string;
	like_count: number;
	reply_count: number;
	is_read: boolean;
	created_at: string;
}

export interface SentReply {
	id: string;
	user_id: string;
	account_id: string;
	threads_reply_id: string | null;
	reply_to_id: string;
	reply_to_username: string | null;
	content: string;
	account_handle: string | null;
	like_count: number;
	reply_count: number;
	repost_count: number;
	metrics_updated_at: string | null;
	created_at: string;
}

export interface Mention {
	id: string;
	user_id: string;
	account_id: string;
	threads_mention_id: string;
	text: string;
	username: string;
	timestamp: string;
	media_type: string | null;
	media_url: string | null;
	permalink: string | null;
	is_reply: boolean;
	account_handle: string | null;
	is_read: boolean;
	fetched_at: string;
}

export interface Analytics {
	id: string;
	account_id: string;
	date: string;
	followers_count: number;
	followers_gained: number;
	followers_lost: number;
	followers_delta: number;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
	posts_count: number;
	engagement_rate: number;
	is_backfilled: boolean;
	is_interpolated: boolean;
	created_at: string;
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
