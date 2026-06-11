/**
 * Favorites Service
 * Manages favorite posts for quick reuse in content creation
 */

import logger from "@/utils/logger";
import { supabase } from "./supabase";

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session?.user?.id || null;
};

export interface FavoritePost {
	postId: string;
	favoritedAt: Date;
	content: string;
	accountId: string;
	groupId?: string | undefined;
	metrics?: {
        		views?: number | undefined;
        		likes?: number | undefined;
        		replies?: number | undefined;
        	} | undefined;
}

interface FavoriteRow {
	post_id: string;
	created_at: string;
	content: string;
	account_id: string;
	group_id: string | null;
	metrics: {
		views?: number | undefined;
		likes?: number | undefined;
		replies?: number | undefined;
	} | null;
}

/**
 * Add a post to favorites
 */
export const addToFavorites = async (
	postId: string,
	content: string,
	accountId: string,
	groupId?: string,
	metrics?: { views?: number | undefined; likes?: number | undefined; replies?: number | undefined },
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		logger.error("[favoritesService] No user logged in");
		return false;
	}

	try {
		// Add to favorites table
		const { error: favError } = await supabase.from("favorites").insert({
			user_id: userId,
			post_id: postId,
			content,
			account_id: accountId,
			group_id: groupId || null,
			metrics: metrics || null,
		});

		if (favError) throw favError;

		// Update the original post's isFavorite flag
		await supabase
			.from("posts")
			.update({ is_favorite: true } satisfies Record<string, boolean>)
			.eq("id", postId)
			.eq("user_id", userId);

		logger.debug("[favoritesService] Added to favorites:", postId);
		return true;
	} catch (error) {
		logger.error("[favoritesService] Failed to add favorite:", error);
		return false;
	}
};

/**
 * Remove a post from favorites
 */
export const removeFromFavorites = async (postId: string): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		logger.error("[favoritesService] No user logged in");
		return false;
	}

	try {
		// Remove from favorites table
		await supabase
			.from("favorites")
			.delete()
			.eq("post_id", postId)
			.eq("user_id", userId);

		// Update the original post's isFavorite flag
		await supabase
			.from("posts")
			.update({ is_favorite: false } satisfies Record<string, boolean>)
			.eq("id", postId)
			.eq("user_id", userId);

		logger.debug("[favoritesService] Removed from favorites:", postId);
		return true;
	} catch (error) {
		logger.error("[favoritesService] Failed to remove favorite:", error);
		return false;
	}
};

/**
 * Toggle favorite status for a post
 */
export const toggleFavorite = async (
	postId: string,
	currentlyFavorited: boolean,
	content: string,
	accountId: string,
	groupId?: string,
	metrics?: { views?: number | undefined; likes?: number | undefined; replies?: number | undefined },
): Promise<boolean> => {
	if (currentlyFavorited) {
		return await removeFromFavorites(postId);
	} else {
		return await addToFavorites(postId, content, accountId, groupId, metrics);
	}
};

/**
 * Check if a post is favorited
 */
export const isFavorited = async (postId: string): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const { data, error } = await supabase
			.from("favorites")
			.select("id")
			.eq("post_id", postId)
			.eq("user_id", userId)
			.maybeSingle();

		return !!data && !error;
	} catch (error) {
		logger.error("[favoritesService] Failed to check favorite status:", error);
		return false;
	}
};

/**
 * Get all favorited posts (ordered by most recent first)
 */
export const getFavorites = async (): Promise<FavoritePost[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		logger.error("[favoritesService] No user logged in");
		return [];
	}

	try {
		const { data, error } = await supabase
			.from("favorites")
			.select("*")
			.eq("user_id", userId)
			.order("created_at", { ascending: false });

		if (error) throw error;

		return ((data || []) as FavoriteRow[]).map((row) => ({
			postId: row.post_id,
			favoritedAt: new Date(row.created_at),
			content: row.content,
			accountId: row.account_id,
			groupId: row.group_id || undefined,
			metrics: row.metrics || undefined,
		}));
	} catch (error) {
		logger.error("[favoritesService] Failed to get favorites:", error);
		return [];
	}
};

/**
 * Update metrics for a favorited post (call after analytics refresh)
 */
export const updateFavoriteMetrics = async (
	postId: string,
	metrics: { views?: number | undefined; likes?: number | undefined; replies?: number | undefined },
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const { data, error } = await supabase
			.from("favorites")
			.update({ metrics } satisfies Record<string, unknown>)
			.eq("post_id", postId)
			.eq("user_id", userId)
			.select();

		return !!data && data.length > 0 && !error;
	} catch (error) {
		logger.error(
			"[favoritesService] Failed to update favorite metrics:",
			error,
		);
		return false;
	}
};
