/**
 * Saved Views — client-side service wrapper over /api/saved-views.
 */

import { z } from "zod";
import { apiFetch } from "@/lib/apiFetch";
import { supabase } from "./supabase";
import type { AnalyticsDateRange } from "@/lib/analyticsUrlState";

export interface SavedViewFilters {
	platform?: "all" | "threads" | "ig" | undefined;
	/**
	 * Full date range — current callers write rolling-day presets only.
	 * Older rows may still carry only `timeframe`.
	 */
	dateRange?: AnalyticsDateRange | undefined;
	/** Legacy: collapsed 7/30/90-day enum. Read for back-compat with
	 *  pre-2026-04 saved views; never written by current code. */
	timeframe?: "7" | "30" | "90" | undefined;
	scopedAccount?: {
        		id: string;
        		platform: "threads" | "instagram";
        		handle: string;
        	} | null | undefined;
}

export interface SavedView {
	id: string;
	user_id: string;
	name: string;
	scope: "analytics";
	filters: SavedViewFilters;
	created_at: string;
	updated_at: string;
}

async function requireSession(): Promise<void> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session) throw new Error("Not authenticated");
}

const savedViewSchema = z.object({
	id: z.string(),
	user_id: z.string(),
	name: z.string(),
	scope: z.literal("analytics"),
	filters: z.custom<SavedViewFilters>(),
	created_at: z.string(),
	updated_at: z.string(),
});

const listSavedViewsSchema = z.object({
	success: z.boolean().optional(),
	views: z.array(savedViewSchema).optional().default([]),
});

const createSavedViewSchema = z.object({
	success: z.boolean().optional(),
	view: savedViewSchema,
});

const deleteSavedViewSchema = z.object({
	success: z.boolean().optional(),
	deleted: z.string(),
});

export async function listSavedViews(
	scope: "analytics" = "analytics",
): Promise<SavedView[]> {
	await requireSession();
	const data = await apiFetch(`/api/saved-views?scope=${scope}`, listSavedViewsSchema);
	return data.views;
}

export async function createSavedView(args: {
	name: string;
	filters: SavedViewFilters;
	scope?: "analytics" | undefined;
}): Promise<SavedView> {
	await requireSession();
	const data = await apiFetch("/api/saved-views", createSavedViewSchema, {
		method: "POST",
		json: {
			name: args.name,
			filters: args.filters,
			scope: args.scope ?? "analytics",
		},
	});
	return data.view;
}

export async function deleteSavedView(id: string): Promise<void> {
	await requireSession();
	await apiFetch(
		`/api/saved-views?id=${encodeURIComponent(id)}`,
		deleteSavedViewSchema,
		{ method: "DELETE" },
	);
}
